"""Provider-neutral AI retrieval lane for protected or low-information dealer sites."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Protocol
import uuid
from urllib.parse import urlparse

import requests

from app.bigquery_repository import BigQueryRepository
from app.config import Settings
from app.logging_utils import get_logger


logger = get_logger(__name__)


ACCOUNT_FACTS_INTENT = "account_facts"
CONNECTION_RECORD_ID = "ai_retrieval_lane"


@dataclass(frozen=True)
class AiRetrievalAccountCandidate:
    """Subset of dealer account data used to prompt AI providers."""

    dealer_account_id: str
    account_key: str
    account_name: str | None
    inferred_brand: str | None
    website_url: str | None
    account_city: str | None
    account_state: str | None
    best_phone: str | None
    best_phone_source: str | None
    gbp_phone: str | None
    gbp_phone_confidence_score: float
    gbp_address_line: str | None
    gbp_city: str | None
    gbp_state_or_province: str | None
    gbp_postal_code: str | None
    gbp_country: str | None
    fetch_status: str | None
    blocked_reason: str | None
    managed_fetch_status: str | None


@dataclass(frozen=True)
class AiProviderResult:
    """Normalized provider output for one AI retrieval attempt."""

    provider: str
    status: str
    facts: dict[str, Any]
    citations: list[str]
    confidence: float
    detail: str
    request_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AiRetrievalRefreshResult:
    """Summary from one AI account-facts refresh."""

    status: str
    detail: str
    processed_accounts: int
    enriched_accounts: int


class AiRetrievalProvider(Protocol):
    """Interface for one AI retrieval provider."""

    name: str

    def is_available(self) -> bool:
        """Return True when the provider is configured and enabled."""

    def retrieve_account_facts(
        self,
        account: AiRetrievalAccountCandidate,
        prompt_style: str,
    ) -> AiProviderResult:
        """Return structured account facts for one account candidate."""


class GeminiRetrievalProvider:
    """Gemini-backed AI retrieval for protected site account facts."""

    name = "gemini"
    API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.trust_env = False

    def is_available(self) -> bool:
        return self.settings.gemini_enabled and bool(self.settings.gemini_api_key)

    def retrieve_account_facts(
        self,
        account: AiRetrievalAccountCandidate,
        prompt_style: str,
    ) -> AiProviderResult:
        if not self.is_available():
            return AiProviderResult(
                provider=self.name,
                status="unconfigured",
                facts={},
                citations=[],
                confidence=0.0,
                detail="Gemini provider is not configured.",
            )

        prompt = build_account_facts_prompt(account, prompt_style)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}, {"urlContext": {}}],
            "generationConfig": {
                "temperature": 0.1,
            },
        }
        try:
            response = self.session.post(
                self.API_URL_TEMPLATE.format(model=self.settings.gemini_model),
                params={"key": self.settings.gemini_api_key},
                json=payload,
                timeout=self.settings.request_timeout_seconds * 3,
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                detail = "Gemini account-facts request hit provider rate limits."
                if retry_after:
                    detail = f"{detail} Retry-After={retry_after}."
                return AiProviderResult(
                    provider=self.name,
                    status="rate_limited",
                    facts={},
                    citations=[],
                    confidence=0.0,
                    detail=detail,
                    error_message=response.text[:1000] or None,
                )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            return AiProviderResult(
                provider=self.name,
                status="failed",
                facts={},
                citations=[],
                confidence=0.0,
                detail="Gemini account-facts request failed.",
                error_message=str(exc),
            )

        facts = parse_json_text(self._extract_text(body))
        citations = self._extract_citations(body)
        if not citations and isinstance(facts.get("citations"), list):
            citations = [str(value).strip() for value in facts.get("citations", []) if str(value).strip()]
        confidence = clamp_confidence(facts.get("confidence"))
        detail = str(facts.get("detail") or "Gemini account-facts retrieval completed.")
        return AiProviderResult(
            provider=self.name,
            status="success" if has_account_facts(facts) else "empty",
            facts=facts,
            citations=citations,
            confidence=confidence,
            detail=detail,
            request_id=body.get("responseId"),
        )

    def _extract_text(self, body: dict[str, Any]) -> str:
        candidates = body.get("candidates") or []
        if not candidates:
            return ""
        content = (candidates[0] or {}).get("content") or {}
        parts = content.get("parts") or []
        fallback_text = ""
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text = str(part["text"])
                stripped = text.strip()
                if stripped.startswith("```json") or stripped.startswith("{"):
                    return text
                if not fallback_text:
                    fallback_text = text
        return fallback_text

    def _extract_citations(self, body: dict[str, Any]) -> list[str]:
        citations: list[str] = []
        candidates = body.get("candidates") or []
        if not candidates:
            return citations
        grounding = (candidates[0] or {}).get("groundingMetadata") or {}
        for chunk in grounding.get("groundingChunks") or []:
            web = (chunk or {}).get("web") or {}
            uri = web.get("uri")
            if uri:
                citations.append(str(uri))
        url_context_metadata = body.get("urlContextMetadata") or {}
        for metadata in url_context_metadata.get("urlMetadata") or []:
            retrieved_url = (metadata or {}).get("retrievedUrl")
            if retrieved_url:
                citations.append(str(retrieved_url))
        return dedupe_urls(citations)


class OpenAIRetrievalProvider:
    """OpenAI Responses API retrieval with web search as a fallback provider."""

    name = "openai"
    API_URL = "https://api.openai.com/v1/responses"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.trust_env = False

    def is_available(self) -> bool:
        return self.settings.openai_enabled and bool(self.settings.openai_api_key)

    def retrieve_account_facts(
        self,
        account: AiRetrievalAccountCandidate,
        prompt_style: str,
    ) -> AiProviderResult:
        if not self.is_available():
            return AiProviderResult(
                provider=self.name,
                status="unconfigured",
                facts={},
                citations=[],
                confidence=0.0,
                detail="OpenAI provider is not configured.",
            )

        prompt = build_account_facts_prompt(account, prompt_style)
        payload = {
            "model": self.settings.openai_model,
            "input": prompt,
            "tools": [{"type": "web_search_preview"}],
        }
        try:
            response = self.session.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.request_timeout_seconds * 3,
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                detail = "OpenAI account-facts request hit provider rate limits."
                if retry_after:
                    detail = f"{detail} Retry-After={retry_after}."
                return AiProviderResult(
                    provider=self.name,
                    status="rate_limited",
                    facts={},
                    citations=[],
                    confidence=0.0,
                    detail=detail,
                    error_message=response.text[:1000] or None,
                )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            return AiProviderResult(
                provider=self.name,
                status="failed",
                facts={},
                citations=[],
                confidence=0.0,
                detail="OpenAI account-facts request failed.",
                error_message=str(exc),
            )

        facts = parse_json_text(self._extract_text(body))
        citations = dedupe_urls(self._extract_citations(body) + [str(value).strip() for value in facts.get("citations", []) if str(value).strip()])
        confidence = clamp_confidence(facts.get("confidence"))
        detail = str(facts.get("detail") or "OpenAI account-facts retrieval completed.")
        return AiProviderResult(
            provider=self.name,
            status="success" if has_account_facts(facts) else "empty",
            facts=facts,
            citations=citations,
            confidence=confidence,
            detail=detail,
            request_id=body.get("id"),
        )

    def _extract_text(self, body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        for item in body.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    return str(content["text"])
        return ""

    def _extract_citations(self, body: dict[str, Any]) -> list[str]:
        citations: list[str] = []
        for item in body.get("output") or []:
            for content in item.get("content") or []:
                for annotation in content.get("annotations") or []:
                    url = annotation.get("url") or annotation.get("source_url")
                    if url:
                        citations.append(str(url))
        return citations


class AiRetrievalService:
    """Fetch structured account facts through configured AI providers."""

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.providers: dict[str, AiRetrievalProvider] = {
            "gemini": GeminiRetrievalProvider(settings),
            "openai": OpenAIRetrievalProvider(settings),
        }

    def preview(self) -> dict[str, int]:
        """Return counts for accounts eligible for AI account-facts retrieval."""

        query = f"""
        SELECT
          COUNT(*) AS candidate_accounts
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND (
            fetch_status = 'blocked'
            OR managed_fetch_status = 'eligible'
            OR website_url IS NULL
            OR TRIM(website_url) = ''
            OR best_phone IS NULL
            OR TRIM(best_phone) = ''
            OR account_city IS NULL
            OR account_state IS NULL
          )
          AND (
            next_ai_retrieval_at IS NULL
            OR next_ai_retrieval_at <= CURRENT_TIMESTAMP()
          )
        """
        row = self.repository.fetch_one(query)
        return {"candidate_accounts": int(row.get("candidate_accounts", 0))}

    def refresh_account_facts(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        account_keys: list[str] | None = None,
        prompt_style: str | None = None,
    ) -> AiRetrievalRefreshResult:
        """Retrieve structured account facts for eligible dealer accounts."""

        candidates = self._load_accounts(limit=limit, account_keys=account_keys)
        configured_providers = self._configured_providers()
        if dry_run:
            detail = (
                f"Would run AI account-facts retrieval for {len(candidates):,} eligible account(s) "
                f"using providers: {', '.join(provider.name for provider in configured_providers) or 'none'}."
            )
            return AiRetrievalRefreshResult("preview", detail, len(candidates), 0)

        if not self.settings.ai_retrieval_enabled:
            detail = "AI retrieval is disabled."
            self._record_status("warning", detail)
            return AiRetrievalRefreshResult("warning", detail, 0, 0)

        if not configured_providers:
            detail = "AI retrieval is enabled, but no AI providers are configured."
            self._record_status("warning", detail)
            return AiRetrievalRefreshResult("warning", detail, len(candidates), 0)

        resolved_prompt_style = self._resolve_prompt_style(prompt_style)
        processed_accounts = 0
        enriched_accounts = 0
        rate_limited = False
        for account in candidates:
            if processed_accounts > 0 and self.settings.ai_retrieval_request_delay_seconds > 0:
                time.sleep(self.settings.ai_retrieval_request_delay_seconds)
            processed_accounts += 1
            provider_results: list[AiProviderResult] = []
            winning_result: AiProviderResult | None = None
            for provider in configured_providers:
                result = provider.retrieve_account_facts(account, resolved_prompt_style)
                provider_results.append(result)
                if result.status == "rate_limited":
                    rate_limited = True
                    break
                if result.status == "success" and self._qualifies_for_canonical_update(result):
                    winning_result = result
                    break

            self._record_results(account, provider_results)
            if winning_result:
                self._apply_account_update(account, winning_result)
                enriched_accounts += 1
            else:
                self._mark_attempt_without_update(account, provider_results)
            if rate_limited:
                logger.warning(
                    "AI retrieval hit provider rate limit; stopping batch early | account=%s | prompt_style=%s",
                    account.account_key,
                    resolved_prompt_style,
                )
                break

        detail = (
            f"AI account-facts retrieval processed {processed_accounts:,} account(s) "
            f"and enriched {enriched_accounts:,} using {', '.join(provider.name for provider in configured_providers)} "
            f"with prompt_style={resolved_prompt_style}."
        )
        if rate_limited:
            detail = f"{detail} Processing stopped early because the provider rate-limited the batch."
        self._record_status("healthy" if enriched_accounts > 0 else "warning", detail)
        return AiRetrievalRefreshResult(
            status="success",
            detail=detail,
            processed_accounts=processed_accounts,
            enriched_accounts=enriched_accounts,
        )

    def _resolve_prompt_style(self, prompt_style: str | None) -> str:
        """Return one supported prompt style."""

        resolved = (prompt_style or self.settings.ai_retrieval_prompt_style or "structured").strip().lower()
        if resolved not in {"structured", "simple_staff"}:
            return "structured"
        return resolved

    def _configured_providers(self) -> list[AiRetrievalProvider]:
        """Return configured providers in preferred order."""

        ordered_names = [
            value.strip().lower()
            for value in self.settings.ai_retrieval_provider_order.split(",")
            if value.strip()
        ]
        providers: list[AiRetrievalProvider] = []
        for name in ordered_names:
            provider = self.providers.get(name)
            if provider and provider.is_available():
                providers.append(provider)
        return providers

    def _load_accounts(
        self,
        limit: int | None,
        account_keys: list[str] | None,
    ) -> list[AiRetrievalAccountCandidate]:
        """Load dealer accounts that should enter the AI account-facts lane."""

        row_limit = limit or self.settings.ai_retrieval_batch_size
        account_filter = ""
        if account_keys:
            quoted = ", ".join(f"'{self._escape_sql(key.lower())}'" for key in account_keys)
            account_filter = f" AND account_key IN ({quoted})"
        query = f"""
        SELECT
          dealer_account_id,
          account_key,
          account_name,
          inferred_brand,
          website_url,
          account_city,
          account_state,
          best_phone,
          best_phone_source,
          gbp_phone,
          IFNULL(gbp_phone_confidence_score, 0.0) AS gbp_phone_confidence_score,
          gbp_address_line,
          gbp_city,
          gbp_state_or_province,
          gbp_postal_code,
          gbp_country,
          fetch_status,
          blocked_reason,
          managed_fetch_status
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND (
            fetch_status = 'blocked'
            OR managed_fetch_status = 'eligible'
            OR website_url IS NULL
            OR TRIM(website_url) = ''
            OR best_phone IS NULL
            OR TRIM(best_phone) = ''
            OR account_city IS NULL
            OR account_state IS NULL
          )
          AND (
            next_ai_retrieval_at IS NULL
            OR next_ai_retrieval_at <= CURRENT_TIMESTAMP()
          )
          {account_filter}
        ORDER BY
          CASE WHEN fetch_status = 'blocked' THEN 0 ELSE 1 END,
          CASE WHEN managed_fetch_status = 'eligible' THEN 0 ELSE 1 END,
          CASE WHEN best_phone IS NULL OR TRIM(best_phone) = '' THEN 0 ELSE 1 END,
          IFNULL(last_fetch_attempt_at, TIMESTAMP('1970-01-01')) DESC,
          account_key ASC
        LIMIT {row_limit}
        """
        rows = self.repository.fetch_all(query)
        return [
            AiRetrievalAccountCandidate(
                dealer_account_id=row["dealer_account_id"],
                account_key=row["account_key"],
                account_name=row.get("account_name"),
                inferred_brand=row.get("inferred_brand"),
                website_url=row.get("website_url"),
                account_city=row.get("account_city"),
                account_state=row.get("account_state"),
                best_phone=row.get("best_phone"),
                best_phone_source=row.get("best_phone_source"),
                gbp_phone=row.get("gbp_phone"),
                gbp_phone_confidence_score=float(row.get("gbp_phone_confidence_score", 0.0) or 0.0),
                gbp_address_line=row.get("gbp_address_line"),
                gbp_city=row.get("gbp_city"),
                gbp_state_or_province=row.get("gbp_state_or_province"),
                gbp_postal_code=row.get("gbp_postal_code"),
                gbp_country=row.get("gbp_country"),
                fetch_status=row.get("fetch_status"),
                blocked_reason=row.get("blocked_reason"),
                managed_fetch_status=row.get("managed_fetch_status"),
            )
            for row in rows
        ]

    def _qualifies_for_canonical_update(self, result: AiProviderResult) -> bool:
        """Return True when structured AI facts are safe to promote."""

        return (
            result.confidence >= 0.65
            and bool(result.citations)
            and has_account_facts(result.facts)
        )

    def _record_results(
        self,
        account: AiRetrievalAccountCandidate,
        provider_results: list[AiProviderResult],
    ) -> None:
        """Write AI provider results into the provenance table."""

        rows: list[dict[str, Any]] = []
        retrieved_at = datetime.now(timezone.utc).isoformat()
        for result in provider_results:
            rows.append(
                {
                    "ai_retrieval_result_id": str(uuid.uuid4()),
                    "dealer_account_id": account.dealer_account_id,
                    "account_key": account.account_key,
                    "retrieval_intent": ACCOUNT_FACTS_INTENT,
                    "provider": result.provider,
                    "provider_status": result.status,
                    "request_id": result.request_id,
                    "facts_json": json.dumps(result.facts or {}, ensure_ascii=True),
                    "citations_json": json.dumps(result.citations or [], ensure_ascii=True),
                    "confidence_score": float(result.confidence or 0.0),
                    "detail": result.detail,
                    "error_message": result.error_message,
                    "retrieved_at": retrieved_at,
                    "created_at": retrieved_at,
                    "updated_at": retrieved_at,
                }
            )
        if rows:
            errors = self.repository.insert_rows_json(self.settings.ai_retrieval_results_table_fqn, rows)
            if errors:
                logger.warning("AI retrieval provenance insert returned errors | account=%s | errors=%s", account.account_key, errors)

    def _apply_account_update(
        self,
        account: AiRetrievalAccountCandidate,
        result: AiProviderResult,
    ) -> None:
        """Write validated AI facts into canonical dealer account fields."""

        facts = result.facts
        ai_phone = normalize_phone(facts.get("ai_phone") or facts.get("phone"))
        staff_hints = normalize_staff_hints(facts.get("staff_hints"))
        staff_page_url = str(facts.get("staff_page_url") or "").strip() or None
        assignments = [
            f"ai_retrieval_status = 'success'",
            f"ai_retrieval_last_error = NULL",
            "ai_retrieval_last_attempt_at = CURRENT_TIMESTAMP()",
            f"ai_request_id = {self._sql_literal(result.request_id)}",
            f"ai_display_name = {self._sql_literal(facts.get('ai_display_name') or facts.get('display_name'))}",
            f"ai_phone = {self._sql_literal(ai_phone)}",
            f"ai_address_line = {self._sql_literal(facts.get('ai_address_line') or facts.get('address_line'))}",
            f"ai_city = {self._sql_literal(facts.get('ai_city') or facts.get('city'))}",
            f"ai_state_or_province = {self._sql_literal(facts.get('ai_state_or_province') or facts.get('state_or_province'))}",
            f"ai_postal_code = {self._sql_literal(facts.get('ai_postal_code') or facts.get('postal_code'))}",
            f"ai_country = {self._sql_literal(normalize_country(facts.get('ai_country') or facts.get('country')))}",
            f"ai_website_url = {self._sql_literal(facts.get('ai_website_url') or facts.get('website_url'))}",
            f"ai_staff_page_url = {self._sql_literal(staff_page_url)}",
            f"ai_staff_hints_json = {self._sql_literal(json.dumps(staff_hints, ensure_ascii=True) if staff_hints else None)}",
            f"ai_staff_hint_count = {len(staff_hints)}",
            f"ai_source_provider = {self._sql_literal(result.provider)}",
            f"ai_source_url = {self._sql_literal((result.citations or [None])[0])}",
            f"ai_confidence_score = {float(result.confidence or 0.0)}",
            "ai_last_verified_at = CURRENT_TIMESTAMP()",
            f"next_ai_retrieval_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {self.settings.ai_retrieval_cooldown_hours} HOUR)",
        ]
        if ai_phone and (
            not account.best_phone
            or not account.best_phone_source
            or account.best_phone_source == "gbp" and result.confidence >= (account.gbp_phone_confidence_score + 0.05)
        ):
            assignments.extend(
                [
                    f"best_phone = {self._sql_literal(ai_phone)}",
                    "best_phone_source = 'ai'",
                    f"best_phone_source_url = {self._sql_literal((result.citations or [None])[0])}",
                    f"best_phone_confidence_score = {float(result.confidence or 0.0)}",
                ]
            )

        if facts.get("ai_address_line") or facts.get("address_line") or facts.get("ai_city") or facts.get("city"):
            assignments.append(
                "best_location_source = CASE "
                "WHEN account_city IS NOT NULL AND TRIM(account_city) != '' OR account_state IS NOT NULL AND TRIM(account_state) != '' THEN 'website' "
                "ELSE 'ai' END"
            )

        query = f"""
        UPDATE `{self.settings.dealer_accounts_table_fqn}`
        SET
          {", ".join(assignments)},
          updated_at = CURRENT_TIMESTAMP()
        WHERE dealer_account_id = '{self._escape_sql(account.dealer_account_id)}'
        """
        self.repository.execute_statement(query)

    def _mark_attempt_without_update(
        self,
        account: AiRetrievalAccountCandidate,
        provider_results: list[AiProviderResult],
    ) -> None:
        """Record a completed AI attempt even when no canonical update was made."""

        status = "empty"
        error_message = None
        cooldown_expression = f"TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {self.settings.ai_retrieval_cooldown_hours} HOUR)"
        for result in provider_results:
            if result.status == "rate_limited":
                status = "rate_limited"
                error_message = result.error_message or result.detail
                cooldown_expression = (
                    f"TIMESTAMP_ADD(CURRENT_TIMESTAMP(), "
                    f"INTERVAL {self.settings.ai_retrieval_rate_limit_cooldown_minutes} MINUTE)"
                )
                break
            if result.status == "failed":
                status = "failed"
                error_message = result.error_message or result.detail
                break
            if result.status == "empty":
                status = "empty"
        query = f"""
        UPDATE `{self.settings.dealer_accounts_table_fqn}`
        SET
          ai_retrieval_status = '{status}',
          ai_retrieval_last_error = {self._sql_literal(error_message)},
          ai_retrieval_last_attempt_at = CURRENT_TIMESTAMP(),
          next_ai_retrieval_at = {cooldown_expression},
          updated_at = CURRENT_TIMESTAMP()
        WHERE dealer_account_id = '{self._escape_sql(account.dealer_account_id)}'
        """
        self.repository.execute_statement(query)

    def _record_status(self, sync_status: str, detail: str) -> None:
        """Upsert the AI retrieval lane status into sync_targets."""

        query = f"""
        MERGE `{self.settings.sync_targets_table_fqn}` AS target
        USING (
          SELECT
            'ai_retrieval' AS target_system,
            'ai_account_facts' AS target_entity_type,
            '{self._escape_sql(self.settings.ai_retrieval_provider_order)}' AS target_entity_id,
            'system' AS source_record_type,
            '{CONNECTION_RECORD_ID}' AS source_record_id,
            '{self._escape_sql(sync_status)}' AS sync_status
        ) AS source
        ON target.target_system = source.target_system
           AND target.source_record_type = source.source_record_type
           AND target.source_record_id = source.source_record_id
        WHEN MATCHED THEN
          UPDATE SET
            target_entity_type = source.target_entity_type,
            target_entity_id = source.target_entity_id,
            sync_status = source.sync_status,
            last_synced_at = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
          INSERT (
            sync_target_id,
            target_system,
            target_entity_type,
            target_entity_id,
            source_record_type,
            source_record_id,
            sync_status,
            last_synced_at,
            created_at,
            updated_at
          )
          VALUES (
            GENERATE_UUID(),
            source.target_system,
            source.target_entity_type,
            source.target_entity_id,
            source.source_record_type,
            source.source_record_id,
            source.sync_status,
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP()
          )
        """
        self.repository.execute_statement(query)

    def _sql_literal(self, value: Any) -> str:
        """Convert one Python value into a BigQuery SQL literal."""

        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        return f"'{self._escape_sql(str(value))}'"

    def _escape_sql(self, value: str) -> str:
        """Escape one string for a BigQuery SQL literal."""

        return (
            value.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
        )


def build_account_facts_prompt(account: AiRetrievalAccountCandidate, prompt_style: str = "structured") -> str:
    """Build a structured prompt for account-facts retrieval."""

    if prompt_style == "simple_staff":
        return build_simple_staff_prompt(account)

    known_context = {
        "account_key": account.account_key,
        "account_name": account.account_name,
        "inferred_brand": account.inferred_brand,
        "website_url": account.website_url,
        "known_city": account.account_city,
        "known_state": account.account_state,
        "known_best_phone": account.best_phone,
        "known_best_phone_source": account.best_phone_source,
        "known_gbp_phone": account.gbp_phone,
        "known_gbp_address": account.gbp_address_line,
        "fetch_status": account.fetch_status,
        "blocked_reason": account.blocked_reason,
        "managed_fetch_status": account.managed_fetch_status,
    }
    return (
        "You are retrieving public dealership account facts for a CRM enrichment system.\n"
        "Return only valid JSON with this shape:\n"
        "{\n"
        '  "display_name": string|null,\n'
        '  "phone": string|null,\n'
        '  "address_line": string|null,\n'
        '  "city": string|null,\n'
        '  "state_or_province": string|null,\n'
        '  "postal_code": string|null,\n'
        '  "country": string|null,\n'
        '  "website_url": string|null,\n'
        '  "staff_page_url": string|null,\n'
        '  "staff_directory_detected": boolean,\n'
        '  "staff_hints": [{"full_name": string|null, "role_title": string|null, "role_family": string|null, "phone": string|null, "citation_url": string|null}],\n'
        '  "citations": string[],\n'
        '  "confidence": number,\n'
        '  "detail": string\n'
        "}\n"
        "Requirements:\n"
        "- Prefer the real dealer rooftop/store facts, not vendor or OEM facts.\n"
        "- Use public web sources only.\n"
        "- Include citation URLs for every fact source you relied on.\n"
        "- If you find a staff directory or team page, include staff_page_url and any staff_hints you can extract even when email is missing.\n"
        "- Staff hints should focus on employee names, role titles, role families, and phone numbers when visible.\n"
        "- If you are unsure, leave the field null.\n"
        "- Confidence must be between 0 and 1.\n"
        "- If a known website URL is provided, prioritize it and pages under that domain first.\n"
        f"Known account context: {json.dumps(known_context, ensure_ascii=True)}\n"
    )


def build_simple_staff_prompt(account: AiRetrievalAccountCandidate) -> str:
    """Build a simpler natural-language prompt for dealer and staff fact finding."""

    dealer_name = account.account_name or account.account_key
    brand_prefix = f"{account.inferred_brand} " if account.inferred_brand and account.inferred_brand.lower() not in str(dealer_name).lower() else ""
    place_parts = [part for part in [account.account_city, account.account_state] if part]
    location_hint = f" in {', '.join(place_parts)}" if place_parts else ""
    known_website = f" Known website: {account.website_url}." if account.website_url else ""
    known_phone = f" Known phone: {account.best_phone}." if account.best_phone else ""
    known_address = ""
    if account.gbp_address_line or account.gbp_city or account.gbp_state_or_province:
        known_address = (
            " Known address hint: "
            f"{', '.join(part for part in [account.gbp_address_line, account.gbp_city, account.gbp_state_or_province, account.gbp_postal_code, account.gbp_country] if part)}."
        )
    return (
        f"{brand_prefix}{dealer_name}{location_hint}: can you get me the dealership address, phone number, website, "
        "and any staff page you can find? Also get the names, roles, phone numbers, and strongly inferred email patterns "
        "for visible staff when possible.\n"
        f"{known_website}{known_phone}{known_address}\n"
        "Return only valid JSON with this shape:\n"
        "{\n"
        '  "display_name": string|null,\n'
        '  "phone": string|null,\n'
        '  "address_line": string|null,\n'
        '  "city": string|null,\n'
        '  "state_or_province": string|null,\n'
        '  "postal_code": string|null,\n'
        '  "country": string|null,\n'
        '  "website_url": string|null,\n'
        '  "staff_page_url": string|null,\n'
        '  "staff_directory_detected": boolean,\n'
        '  "staff_hints": [{"full_name": string|null, "role_title": string|null, "role_family": string|null, "phone": string|null, "citation_url": string|null, "inferred_email": string|null}],\n'
        '  "citations": string[],\n'
        '  "confidence": number,\n'
        '  "detail": string\n'
        "}\n"
        "Rules:\n"
        "- Prefer the actual dealer rooftop, not OEM or vendor facts.\n"
        "- Use public web sources only.\n"
        "- Include citation URLs.\n"
        "- If an email is not visible, inferred_email may be included only when the pattern is strongly supported by public evidence; otherwise leave it null.\n"
        "- If unsure, leave fields null.\n"
        "- Confidence must be between 0 and 1.\n"
    )


def parse_json_text(text: str) -> dict[str, Any]:
    """Parse model text into a JSON object, stripping light markdown wrappers."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dedupe_urls(values: list[str]) -> list[str]:
    """Return normalized distinct URLs preserving order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def clamp_confidence(value: Any) -> float:
    """Clamp provider confidence into a safe 0-1 range."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def has_account_facts(facts: dict[str, Any]) -> bool:
    """Return True when an account-facts payload includes usable dealer data."""

    return bool(
        normalize_phone(facts.get("ai_phone") or facts.get("phone"))
        or str(facts.get("ai_address_line") or facts.get("address_line") or "").strip()
        or str(facts.get("ai_city") or facts.get("city") or "").strip()
        or str(facts.get("website_url") or facts.get("ai_website_url") or "").strip()
        or str(facts.get("staff_page_url") or "").strip()
        or normalize_staff_hints(facts.get("staff_hints"))
    )


def normalize_staff_hints(value: Any) -> list[dict[str, str]]:
    """Normalize partial AI-discovered staff hints into a stable structured list."""

    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "").strip()
        role_title = str(item.get("role_title") or "").strip()
        role_family = str(item.get("role_family") or "").strip()
        phone = normalize_phone(item.get("phone"))
        citation_url = str(item.get("citation_url") or "").strip()
        inferred_email = str(item.get("inferred_email") or "").strip().lower()
        if not (full_name or role_title or role_family or phone):
            continue
        normalized.append(
            {
                "full_name": full_name,
                "role_title": role_title,
                "role_family": role_family,
                "phone": phone or "",
                "citation_url": citation_url,
                "inferred_email": inferred_email,
            }
        )
    return normalized


def normalize_phone(value: Any) -> str | None:
    """Normalize a North American phone into a consistent format."""

    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def normalize_country(value: Any) -> str | None:
    """Normalize common country variants."""

    if not isinstance(value, str) or not value.strip():
        return None
    lowered = value.strip().lower()
    if lowered in {"ca", "canada"}:
        return "Canada"
    if lowered in {"us", "usa", "united states", "united states of america"}:
        return "United States"
    return value.strip()
