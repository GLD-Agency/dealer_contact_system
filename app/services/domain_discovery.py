"""Separate discovery worker for new dealer domain candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import parse_qs, urlparse
import uuid

from bs4 import BeautifulSoup
import requests

from app.bigquery_repository import BigQueryRepository
from app.config import Settings
from app.logging_utils import get_logger
from app.web_fetcher import DEFAULT_HEADERS


logger = get_logger(__name__)

DEALER_WORDS = (
    "dealer",
    "dealership",
    "motors",
    "auto",
    "automotive",
    "autoplex",
    "cars",
    "truck",
)
DIRECTORY_HOST_HINTS = {
    "cars.com",
    "cargurus.com",
    "carfax.com",
    "autotrader.com",
    "edmunds.com",
    "dealerrater.com",
    "yelp.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "mapquest.com",
    "yellowpages.com",
    "rocketreach.co",
    "zoominfo.com",
    "dealerinspire.com",
    "dealeron.com",
    "dealerspike.com",
    "dealer.com",
    "wikipedia.org",
    "chamberofcommerce.com",
    "loc8nearme.com",
    "cardealerships.com",
    "autostoday.com",
    "alabamalive.net",
}
OEM_HOST_HINTS = {
    "acura.com",
    "audi.com",
    "bmwusa.com",
    "ford.com",
    "gmc.com",
    "honda.com",
    "hyundaiusa.com",
    "kia.com",
    "lexus.com",
    "mazdausa.com",
    "nissanusa.com",
    "porsche.com",
    "subaru.com",
    "toyota.com",
    "vw.com",
    "volkswagen.com",
}
CANADA_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


@dataclass(frozen=True)
class DiscoverySeedTask:
    """One search term that should be run by the discovery worker."""

    dedupe_key: str
    search_term: str
    brand_hint: str
    market: str
    country: str
    state_or_province: str | None
    city: str | None
    priority: int


@dataclass(frozen=True)
class DiscoveryQueueItem:
    """Claimed discovery queue row."""

    work_item_id: str
    dedupe_key: str
    search_term: str
    brand_hint: str
    market: str
    country: str
    state_or_province: str | None
    city: str | None


@dataclass(frozen=True)
class DiscoverySearchResult:
    """One raw search engine result."""

    title: str
    snippet: str
    url: str


@dataclass(frozen=True)
class DomainDiscoveryResult:
    """Summary from one discovery worker run or promotion pass."""

    status: str
    detail: str
    processed_tasks: int = 0
    candidates_written: int = 0
    promoted_candidates: int = 0


class DomainDiscoveryRunLogger:
    """Track discovery-only runs in a separate BigQuery table."""

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def start_run(self, run_type: str, worker_id: str, requested_batch_size: int) -> str:
        run_id = str(uuid.uuid4())
        query = f"""
        INSERT INTO `{self.settings.domain_discovery_runs_table_fqn}` (
          discovery_run_id,
          run_type,
          run_status,
          worker_id,
          requested_batch_size,
          claimed_count,
          succeeded_count,
          failed_count,
          run_notes,
          started_at,
          completed_at,
          created_at,
          updated_at
        )
        VALUES (
          '{run_id}',
          '{self._escape(run_type)}',
          'running',
          '{self._escape(worker_id)}',
          {requested_batch_size},
          0,
          0,
          0,
          NULL,
          CURRENT_TIMESTAMP(),
          NULL,
          CURRENT_TIMESTAMP(),
          CURRENT_TIMESTAMP()
        )
        """
        self.repository.execute_statement(query)
        return run_id

    def finish_run(
        self,
        run_id: str,
        run_status: str,
        claimed_count: int,
        succeeded_count: int,
        failed_count: int,
        run_notes: str | None = None,
    ) -> None:
        notes_sql = "NULL"
        if run_notes:
            notes_sql = f"'{self._escape(run_notes)}'"
        query = f"""
        UPDATE `{self.settings.domain_discovery_runs_table_fqn}`
        SET
          run_status = '{self._escape(run_status)}',
          claimed_count = {claimed_count},
          succeeded_count = {succeeded_count},
          failed_count = {failed_count},
          run_notes = {notes_sql},
          completed_at = CURRENT_TIMESTAMP(),
          updated_at = CURRENT_TIMESTAMP()
        WHERE discovery_run_id = '{self._escape(run_id)}'
        """
        self.repository.execute_statement(query)

    def _escape(self, value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
        )


class DomainDiscoveryService:
    """Find and promote new dealer domain candidates on a separate queue."""

    SOURCE_ENGINE = "duckduckgo_html"
    PROMOTION_CONFIDENCE_THRESHOLD = 0.52

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.run_logger = DomainDiscoveryRunLogger(repository, settings)
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(DEFAULT_HEADERS)

    def seed_queue(self, dry_run: bool = False) -> int:
        """Seed discovery search terms from existing brand and geography coverage."""

        tasks = self._build_seed_tasks()
        if dry_run:
            return len(tasks)
        if not tasks:
            return 0
        self._merge_seed_tasks(tasks)
        return len(tasks)

    def run_worker(self, dry_run: bool = False, batch_size: int | None = None) -> DomainDiscoveryResult:
        """Process one claimed batch of discovery search terms."""

        if not self.settings.domain_discovery_enabled:
            return DomainDiscoveryResult("skipped", "Domain discovery is disabled.")

        effective_batch_size = batch_size or self.settings.domain_discovery_batch_size
        worker_id = f"discovery-{uuid.uuid4()}"
        run_id = self.run_logger.start_run("search", worker_id, effective_batch_size)

        try:
            claimed = self._claim_batch(effective_batch_size, worker_id)
            if dry_run:
                self.run_logger.finish_run(
                    run_id,
                    run_status="preview",
                    claimed_count=len(claimed),
                    succeeded_count=0,
                    failed_count=0,
                    run_notes=f"Previewed {len(claimed):,} discovery task(s).",
                )
                return DomainDiscoveryResult(
                    "preview",
                    f"Would process {len(claimed):,} discovery task(s).",
                    processed_tasks=len(claimed),
                )

            if not claimed:
                self.run_logger.finish_run(
                    run_id,
                    run_status="completed",
                    claimed_count=0,
                    succeeded_count=0,
                    failed_count=0,
                    run_notes="No queued discovery tasks were ready.",
                )
                return DomainDiscoveryResult("success", "No queued discovery tasks were ready.")

            candidates_written = 0
            succeeded = 0
            failed = 0
            for item in claimed:
                try:
                    candidates = self._discover_candidates_for_task(item)
                    if candidates:
                        self._upsert_candidates(candidates)
                        candidates_written += len(candidates)
                    self._mark_completed(item.work_item_id)
                    succeeded += 1
                except Exception as exc:  # pragma: no cover - operational safety
                    logger.exception("Discovery task failed | search_term=%s", item.search_term)
                    self._mark_failed(item.work_item_id, str(exc))
                    failed += 1

            detail = (
                f"Processed {len(claimed):,} discovery task(s) and wrote "
                f"{candidates_written:,} candidate row(s)."
            )
            self.run_logger.finish_run(
                run_id,
                run_status="completed" if failed == 0 else "partial_failure",
                claimed_count=len(claimed),
                succeeded_count=succeeded,
                failed_count=failed,
                run_notes=detail,
            )
            return DomainDiscoveryResult(
                "success" if failed == 0 else "partial_failure",
                detail,
                processed_tasks=len(claimed),
                candidates_written=candidates_written,
            )
        except Exception as exc:  # pragma: no cover - operational safety
            self.run_logger.finish_run(
                run_id,
                run_status="failed",
                claimed_count=0,
                succeeded_count=0,
                failed_count=1,
                run_notes=str(exc),
            )
            raise

    def promote_candidates(self, dry_run: bool = False, limit: int | None = None) -> DomainDiscoveryResult:
        """Promote truly new discovery candidates into dealer_accounts."""

        candidates = self._load_promotable_candidates(limit)
        if dry_run:
            return DomainDiscoveryResult(
                "preview",
                f"Would review {len(candidates):,} candidate(s) for promotion.",
                promoted_candidates=0,
            )

        promoted = 0
        reviewed = 0
        for candidate in candidates:
            reviewed += 1
            candidate_id = str(candidate["candidate_id"])
            domain = self._normalize_domain(candidate.get("candidate_domain"))
            website_url = self._normalize_url(candidate.get("candidate_website_url"))
            account_name = str(candidate.get("candidate_account_name") or "").strip()
            city = str(candidate.get("city") or "").strip() or None
            state = str(candidate.get("state_or_province") or "").strip() or None
            country = str(candidate.get("country") or "").strip() or None
            confidence = float(candidate.get("confidence_score") or 0.0)
            if not domain:
                self._update_candidate_status(candidate_id, "rejected_low_confidence", "missing_domain")
                continue
            if confidence < self.PROMOTION_CONFIDENCE_THRESHOLD:
                self._update_candidate_status(candidate_id, "rejected_low_confidence", "confidence_below_threshold")
                continue
            if not self._looks_like_rooftop_candidate(domain, account_name, str(candidate.get("brand_hint") or ""), city, state):
                self._update_candidate_status(candidate_id, "rejected_non_dealer", "domain_failed_rooftop_heuristic")
                continue
            if self._candidate_matches_existing(domain, website_url, account_name, city, state):
                self._update_candidate_status(candidate_id, "duplicate_existing", "matched_existing_account")
                continue

            self._promote_candidate_to_accounts(
                candidate_id=candidate_id,
                domain=domain,
                website_url=website_url,
                account_name=account_name or domain,
                brand_hint=str(candidate.get("brand_hint") or "").strip() or None,
                city=city,
                state=state,
                country=country,
                market=str(candidate.get("market") or "").strip() or None,
                source_url=str(candidate.get("source_url") or "").strip() or None,
            )
            promoted += 1

        detail = f"Reviewed {reviewed:,} candidate(s) and promoted {promoted:,} into dealer_accounts."
        return DomainDiscoveryResult(
            "success",
            detail,
            processed_tasks=reviewed,
            promoted_candidates=promoted,
        )

    def run_cycle(self, seed: bool = False, dry_run: bool = False) -> DomainDiscoveryResult:
        """Run one full discovery-only cycle."""

        seeded = 0
        if seed:
            seeded = self.seed_queue(dry_run=dry_run)
        worker_result = self.run_worker(dry_run=dry_run)
        promoted_result = DomainDiscoveryResult("skipped", "Promotion disabled.")
        if self.settings.domain_discovery_promotion_enabled:
            promoted_result = self.promote_candidates(dry_run=dry_run)
        detail = (
            f"Discovery cycle seeded {seeded:,} task(s), processed {worker_result.processed_tasks:,}, "
            f"wrote {worker_result.candidates_written:,} candidate row(s), and promoted "
            f"{promoted_result.promoted_candidates:,} candidate(s)."
        )
        return DomainDiscoveryResult(
            "preview" if dry_run else "success",
            detail,
            processed_tasks=worker_result.processed_tasks,
            candidates_written=worker_result.candidates_written,
            promoted_candidates=promoted_result.promoted_candidates,
        )

    def report(self) -> dict[str, int]:
        """Return simple counts for operational reporting."""

        query = f"""
        SELECT
          (SELECT COUNTIF(status IN ('pending', 'retry')) FROM `{self.settings.domain_discovery_queue_table_fqn}`) AS queued_tasks,
          (SELECT COUNT(*) FROM `{self.settings.discovered_domain_candidates_table_fqn}`) AS total_candidates,
          (SELECT COUNTIF(promotion_status = 'new') FROM `{self.settings.discovered_domain_candidates_table_fqn}`) AS new_candidates,
          (SELECT COUNTIF(promotion_status = 'duplicate_existing') FROM `{self.settings.discovered_domain_candidates_table_fqn}`) AS duplicate_existing_candidates,
          (SELECT COUNTIF(promotion_status = 'promoted_to_main_pipeline') FROM `{self.settings.discovered_domain_candidates_table_fqn}`) AS promoted_candidates,
          (SELECT COUNTIF(STARTS_WITH(promotion_status, 'rejected')) FROM `{self.settings.discovered_domain_candidates_table_fqn}`) AS rejected_candidates
        """
        row = self.repository.fetch_one(query)
        return {key: int(row.get(key, 0) or 0) for key in row.keys()}

    def _build_seed_tasks(self) -> list[DiscoverySeedTask]:
        """Generate search tasks from known brands and geographies."""

        source_query = f"""
        SELECT DISTINCT
          inferred_brand AS brand_hint,
          account_city AS city,
          account_state AS state_or_province,
          CASE
            WHEN COALESCE(NULLIF(TRIM(ai_country), ''), NULLIF(TRIM(gbp_country), '')) = 'Canada'
                 OR account_state IN ({", ".join(f"'{province}'" for province in sorted(CANADA_PROVINCES))})
              THEN 'Canada'
            ELSE 'United States'
          END AS country,
          CASE
            WHEN COALESCE(NULLIF(TRIM(ai_country), ''), NULLIF(TRIM(gbp_country), '')) = 'Canada'
                 OR account_state IN ({", ".join(f"'{province}'" for province in sorted(CANADA_PROVINCES))})
              THEN 'Canada'
            ELSE 'US'
          END AS market
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND inferred_brand IS NOT NULL
          AND TRIM(inferred_brand) != ''
          AND account_state IS NOT NULL
          AND TRIM(account_state) != ''
        ORDER BY brand_hint, state_or_province, city
        LIMIT {max(self.settings.domain_discovery_query_batch_size * 4, 100)}
        """
        rows = self.repository.fetch_all(source_query)
        tasks: list[DiscoverySeedTask] = []
        seen: set[str] = set()
        expansions = ("dealer", "dealership", "motors")
        for row in rows:
            brand = str(row.get("brand_hint") or "").strip()
            if not brand:
                continue
            city = str(row.get("city") or "").strip() or None
            state = str(row.get("state_or_province") or "").strip() or None
            country = str(row.get("country") or "United States").strip() or "United States"
            market = str(row.get("market") or ("Canada" if country == "Canada" else "US")).strip()
            location_parts = [part for part in [city, state, country] if part]
            for expansion in expansions:
                search_term = " ".join([brand, expansion, *location_parts]).strip()
                dedupe_key = self._normalize_key(search_term)
                if not search_term or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                priority = 100 if city and state else 80
                tasks.append(
                    DiscoverySeedTask(
                        dedupe_key=dedupe_key,
                        search_term=search_term,
                        brand_hint=brand,
                        market=market,
                        country=country,
                        state_or_province=state,
                        city=city,
                        priority=priority,
                    )
                )
                if len(tasks) >= self.settings.domain_discovery_query_batch_size:
                    return tasks
        return tasks

    def _merge_seed_tasks(self, tasks: list[DiscoverySeedTask]) -> None:
        """Insert missing queue tasks or reopen cooled-down ones."""

        rows = []
        for task in tasks:
            rows.append(
                "SELECT "
                f"'{self._escape(task.dedupe_key)}' AS dedupe_key, "
                f"'{self._escape(task.search_term)}' AS search_term, "
                f"'{self._escape(task.brand_hint)}' AS brand_hint, "
                f"'{self._escape(task.market)}' AS market, "
                f"'{self._escape(task.country)}' AS country, "
                f"{self._sql_string(task.state_or_province)} AS state_or_province, "
                f"{self._sql_string(task.city)} AS city, "
                f"{task.priority} AS priority"
            )
        source_sql = "\nUNION ALL\n".join(rows)
        query = f"""
        MERGE `{self.settings.domain_discovery_queue_table_fqn}` AS target
        USING (
          {source_sql}
        ) AS source
        ON target.dedupe_key = source.dedupe_key
        WHEN MATCHED AND target.status IN ('completed', 'failed') AND (target.next_attempt_at IS NULL OR target.next_attempt_at <= CURRENT_TIMESTAMP()) THEN
          UPDATE SET
            status = 'pending',
            search_term = source.search_term,
            brand_hint = source.brand_hint,
            market = source.market,
            country = source.country,
            state_or_province = source.state_or_province,
            city = source.city,
            priority = source.priority,
            lease_owner = NULL,
            lease_expires_at = NULL,
            completed_at = NULL,
            last_error = NULL,
            updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
          INSERT (
            work_item_id,
            dedupe_key,
            search_term,
            brand_hint,
            market,
            country,
            state_or_province,
            city,
            status,
            priority,
            attempt_count,
            lease_owner,
            lease_expires_at,
            last_attempt_at,
            next_attempt_at,
            completed_at,
            last_error,
            created_at,
            updated_at
          )
          VALUES (
            GENERATE_UUID(),
            source.dedupe_key,
            source.search_term,
            source.brand_hint,
            source.market,
            source.country,
            source.state_or_province,
            source.city,
            'pending',
            source.priority,
            0,
            NULL,
            NULL,
            NULL,
            CURRENT_TIMESTAMP(),
            NULL,
            NULL,
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP()
          )
        """
        self.repository.execute_statement(query)

    def _claim_batch(self, batch_size: int, worker_id: str) -> list[DiscoveryQueueItem]:
        """Lease a batch of discovery tasks for this worker."""

        update_query = f"""
        UPDATE `{self.settings.domain_discovery_queue_table_fqn}`
        SET
          status = 'in_progress',
          lease_owner = '{self._escape(worker_id)}',
          lease_expires_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE),
          last_attempt_at = CURRENT_TIMESTAMP(),
          attempt_count = IFNULL(attempt_count, 0) + 1,
          updated_at = CURRENT_TIMESTAMP()
        WHERE work_item_id IN (
          SELECT work_item_id
          FROM `{self.settings.domain_discovery_queue_table_fqn}`
          WHERE status IN ('pending', 'retry')
            AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP())
            AND (lease_expires_at IS NULL OR lease_expires_at <= CURRENT_TIMESTAMP())
          ORDER BY priority DESC, created_at ASC
          LIMIT {batch_size}
        )
        """
        self.repository.execute_statement(update_query)

        fetch_query = f"""
        SELECT
          work_item_id,
          dedupe_key,
          search_term,
          brand_hint,
          market,
          country,
          state_or_province,
          city
        FROM `{self.settings.domain_discovery_queue_table_fqn}`
        WHERE status = 'in_progress'
          AND lease_owner = '{self._escape(worker_id)}'
        ORDER BY priority DESC, created_at ASC
        """
        rows = self.repository.fetch_all(fetch_query)
        return [
            DiscoveryQueueItem(
                work_item_id=str(row["work_item_id"]),
                dedupe_key=str(row["dedupe_key"]),
                search_term=str(row["search_term"]),
                brand_hint=str(row.get("brand_hint") or ""),
                market=str(row.get("market") or ""),
                country=str(row.get("country") or ""),
                state_or_province=str(row.get("state_or_province") or "").strip() or None,
                city=str(row.get("city") or "").strip() or None,
            )
            for row in rows
        ]

    def _discover_candidates_for_task(self, item: DiscoveryQueueItem) -> list[dict[str, Any]]:
        """Search the web for candidate dealer domains for one search term."""

        response = self.session.get(
            self.settings.domain_discovery_search_endpoint,
            params={"q": item.search_term},
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        search_results = self._parse_search_results(response.text)
        existing_domains = self._load_existing_domains()
        candidates: list[dict[str, Any]] = []
        seen_domains: set[str] = set()
        for result in search_results:
            candidate_url = self._normalize_result_url(result.url)
            candidate_domain = self._normalize_domain(candidate_url)
            if not candidate_domain or candidate_domain in seen_domains:
                continue
            seen_domains.add(candidate_domain)
            if self._is_directory_or_marketplace(candidate_domain):
                continue
            confidence = self._score_candidate(item, candidate_domain, result)
            if confidence < 0.30:
                continue
            promotion_status = "new"
            promotion_reason = "candidate_discovered"
            if confidence < self.PROMOTION_CONFIDENCE_THRESHOLD:
                promotion_status = "rejected_low_confidence"
                promotion_reason = "confidence_below_threshold"
            elif candidate_domain in existing_domains:
                promotion_status = "duplicate_existing"
                promotion_reason = "matched_existing_domain"
            account_name = self._clean_candidate_name(result.title)
            dedupe_key = candidate_domain
            candidates.append(
                {
                    "candidate_id": str(uuid.uuid4()),
                    "search_term": item.search_term,
                    "brand_hint": item.brand_hint,
                    "market": item.market,
                    "country": item.country,
                    "state_or_province": item.state_or_province,
                    "city": item.city,
                    "candidate_domain": candidate_domain,
                    "candidate_website_url": candidate_url,
                    "candidate_account_name": account_name or candidate_domain,
                    "source_engine": self.SOURCE_ENGINE,
                    "source_url": candidate_url,
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "confidence_score": round(confidence, 3),
                    "dedupe_key": dedupe_key,
                    "promotion_status": promotion_status,
                    "promotion_reason": promotion_reason,
                    "promoted_account_key": None,
                }
            )
        logger.info(
            "Discovery search complete | search_term=%s | results=%s | candidates=%s",
            item.search_term,
            len(search_results),
            len(candidates),
        )
        return candidates

    def _parse_search_results(self, html: str) -> list[DiscoverySearchResult]:
        """Parse DuckDuckGo HTML result rows into simple objects."""

        soup = BeautifulSoup(html, "html.parser")
        results: list[DiscoverySearchResult] = []
        for result_node in soup.select(".result"):
            link = result_node.select_one("a.result__a")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href", "").strip()
            snippet_node = result_node.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            if title and url:
                results.append(DiscoverySearchResult(title=title, snippet=snippet, url=url))
        return results

    def _upsert_candidates(self, candidates: list[dict[str, Any]]) -> None:
        """Merge discovered candidates into the candidate table by domain."""

        rows = []
        for candidate in candidates:
            rows.append(
                "SELECT "
                f"'{self._escape(candidate['candidate_id'])}' AS candidate_id, "
                f"'{self._escape(candidate['search_term'])}' AS search_term, "
                f"'{self._escape(candidate['brand_hint'])}' AS brand_hint, "
                f"'{self._escape(candidate['market'])}' AS market, "
                f"'{self._escape(candidate['country'])}' AS country, "
                f"{self._sql_string(candidate.get('state_or_province'))} AS state_or_province, "
                f"{self._sql_string(candidate.get('city'))} AS city, "
                f"'{self._escape(candidate['candidate_domain'])}' AS candidate_domain, "
                f"'{self._escape(candidate['candidate_website_url'])}' AS candidate_website_url, "
                f"'{self._escape(candidate['candidate_account_name'])}' AS candidate_account_name, "
                f"'{self._escape(candidate['source_engine'])}' AS source_engine, "
                f"'{self._escape(candidate['source_url'])}' AS source_url, "
                f"TIMESTAMP('{self._escape(candidate['discovered_at'])}') AS discovered_at, "
                f"{float(candidate['confidence_score'])} AS confidence_score, "
                f"'{self._escape(candidate['dedupe_key'])}' AS dedupe_key, "
                f"'{self._escape(candidate['promotion_status'])}' AS promotion_status, "
                f"'{self._escape(candidate['promotion_reason'])}' AS promotion_reason, "
                f"NULL AS promoted_account_key"
            )
        source_sql = "\nUNION ALL\n".join(rows)
        query = f"""
        MERGE `{self.settings.discovered_domain_candidates_table_fqn}` AS target
        USING (
          {source_sql}
        ) AS source
        ON target.dedupe_key = source.dedupe_key
        WHEN MATCHED THEN
          UPDATE SET
            search_term = source.search_term,
            brand_hint = source.brand_hint,
            market = source.market,
            country = source.country,
            state_or_province = source.state_or_province,
            city = source.city,
            candidate_website_url = source.candidate_website_url,
            candidate_account_name = source.candidate_account_name,
            source_engine = source.source_engine,
            source_url = source.source_url,
            confidence_score = GREATEST(IFNULL(target.confidence_score, 0), source.confidence_score),
            promotion_status = CASE
              WHEN target.promotion_status = 'promoted_to_main_pipeline' THEN target.promotion_status
              WHEN target.promotion_status = 'duplicate_existing' THEN target.promotion_status
              ELSE source.promotion_status
            END,
            promotion_reason = CASE
              WHEN target.promotion_status = 'promoted_to_main_pipeline' THEN target.promotion_reason
              ELSE source.promotion_reason
            END,
            last_seen_at = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
          INSERT (
            candidate_id,
            search_term,
            brand_hint,
            market,
            country,
            state_or_province,
            city,
            candidate_domain,
            candidate_website_url,
            candidate_account_name,
            source_engine,
            source_url,
            discovered_at,
            confidence_score,
            dedupe_key,
            promotion_status,
            promotion_reason,
            promoted_account_key,
            created_at,
            updated_at,
            last_seen_at
          )
          VALUES (
            source.candidate_id,
            source.search_term,
            source.brand_hint,
            source.market,
            source.country,
            source.state_or_province,
            source.city,
            source.candidate_domain,
            source.candidate_website_url,
            source.candidate_account_name,
            source.source_engine,
            source.source_url,
            source.discovered_at,
            source.confidence_score,
            source.dedupe_key,
            source.promotion_status,
            source.promotion_reason,
            NULL,
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP()
          )
        """
        self.repository.execute_statement(query)

    def _load_existing_domains(self) -> set[str]:
        """Load current canonical account domains to avoid overlapping promotions."""

        query = f"""
        SELECT DISTINCT
          account_key,
          website_url
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE account_key IS NOT NULL
           OR website_url IS NOT NULL
        """
        domains: set[str] = set()
        for row in self.repository.fetch_all(query):
            domain = self._normalize_domain(row.get("account_key"))
            if domain:
                domains.add(domain)
            website_domain = self._normalize_domain(row.get("website_url"))
            if website_domain:
                domains.add(website_domain)
        return domains

    def _load_promotable_candidates(self, limit: int | None) -> list[dict[str, Any]]:
        """Load candidates awaiting review for promotion into canonical intake."""

        row_limit = limit or self.settings.domain_discovery_batch_size
        query = f"""
        SELECT
          candidate_id,
          candidate_domain,
          candidate_website_url,
          candidate_account_name,
          brand_hint,
          city,
          state_or_province,
          country,
          market,
          confidence_score,
          source_url
        FROM `{self.settings.discovered_domain_candidates_table_fqn}`
        WHERE promotion_status = 'new'
        ORDER BY confidence_score DESC, discovered_at ASC
        LIMIT {row_limit}
        """
        return self.repository.fetch_all(query)

    def _candidate_matches_existing(
        self,
        domain: str,
        website_url: str | None,
        account_name: str,
        city: str | None,
        state: str | None,
    ) -> bool:
        """Check whether a candidate overlaps an existing canonical account."""

        website_domain = self._normalize_domain(website_url)
        name_sql = self._escape(self._normalize_key(account_name))
        city_sql = self._escape(self._normalize_key(city or ""))
        state_sql = self._escape((state or "").strip().upper())
        domains = [domain]
        if website_domain and website_domain != domain:
            domains.append(website_domain)
        domain_sql = ", ".join(f"'{self._escape(value)}'" for value in domains)
        query = f"""
        SELECT COUNT(*) AS matched_rows
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE account_key IN ({domain_sql})
           OR REGEXP_REPLACE(LOWER(COALESCE(website_url, '')), r'^https?://(www\\.)?', '') IN ({domain_sql})
           OR (
             REGEXP_REPLACE(LOWER(COALESCE(account_name, '')), r'[^a-z0-9]+', '') = '{name_sql}'
             AND REGEXP_REPLACE(LOWER(COALESCE(account_city, '')), r'[^a-z0-9]+', '') = '{city_sql}'
             AND UPPER(COALESCE(account_state, '')) = '{state_sql}'
           )
        """
        return int(self.repository.fetch_one(query).get("matched_rows", 0)) > 0

    def _promote_candidate_to_accounts(
        self,
        candidate_id: str,
        domain: str,
        website_url: str | None,
        account_name: str,
        brand_hint: str | None,
        city: str | None,
        state: str | None,
        country: str | None,
        market: str | None,
        source_url: str | None,
    ) -> None:
        """Insert a lightweight discovery seed into dealer_accounts."""

        query = f"""
        MERGE `{self.settings.dealer_accounts_table_fqn}` AS target
        USING (
          SELECT
            '{self._escape(domain)}' AS account_key,
            {self._sql_string(domain)} AS email_domain,
            {self._sql_string(account_name)} AS account_name,
            {self._sql_string(brand_hint)} AS inferred_brand,
            {self._sql_string(city)} AS account_city,
            {self._sql_string(state)} AS account_state,
            {self._sql_string(website_url)} AS website_url,
            {self._sql_string(source_url)} AS website_source_url,
            {self._sql_string(market)} AS source_market,
            {self._sql_string(country)} AS source_country
        ) AS source
        ON target.account_key = source.account_key
        WHEN NOT MATCHED THEN
          INSERT (
            dealer_account_id,
            account_key,
            email_domain,
            account_name,
            inferred_brand,
            dealer_classification,
            account_city,
            account_state,
            website_url,
            account_status,
            enrichment_stage,
            activation_status,
            confidence_score,
            source_type,
            source_table,
            website_source_url,
            first_seen_at,
            last_seen_at,
            created_at,
            updated_at
          )
          VALUES (
            GENERATE_UUID(),
            source.account_key,
            source.email_domain,
            source.account_name,
            source.inferred_brand,
            'unknown',
            source.account_city,
            source.account_state,
            source.website_url,
            'active',
            'discovery_seed',
            'enrichment_needed',
            0.45,
            'domain_discovery',
            '{self.settings.discovered_domain_candidates_table}',
            source.website_source_url,
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP(),
            CURRENT_TIMESTAMP()
          )
        WHEN MATCHED THEN
          UPDATE SET
            account_name = COALESCE(NULLIF(target.account_name, ''), source.account_name),
            inferred_brand = COALESCE(NULLIF(target.inferred_brand, ''), source.inferred_brand),
            account_city = COALESCE(NULLIF(target.account_city, ''), source.account_city),
            account_state = COALESCE(NULLIF(target.account_state, ''), source.account_state),
            website_url = COALESCE(NULLIF(target.website_url, ''), source.website_url),
            source_type = COALESCE(NULLIF(target.source_type, ''), 'domain_discovery'),
            source_table = COALESCE(NULLIF(target.source_table, ''), '{self.settings.discovered_domain_candidates_table}'),
            last_seen_at = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        """
        self.repository.execute_statement(query)
        self._update_candidate_status(candidate_id, "promoted_to_main_pipeline", "inserted_discovery_seed", promoted_account_key=domain)

    def _update_candidate_status(
        self,
        candidate_id: str,
        status: str,
        reason: str,
        promoted_account_key: str | None = None,
    ) -> None:
        """Update the promotion outcome for one candidate row."""

        promoted_account_sql = self._sql_string(promoted_account_key)
        query = f"""
        UPDATE `{self.settings.discovered_domain_candidates_table_fqn}`
        SET
          promotion_status = '{self._escape(status)}',
          promotion_reason = '{self._escape(reason)}',
          promoted_account_key = {promoted_account_sql},
          updated_at = CURRENT_TIMESTAMP(),
          last_seen_at = CURRENT_TIMESTAMP()
        WHERE candidate_id = '{self._escape(candidate_id)}'
        """
        self.repository.execute_statement(query)

    def _mark_completed(self, work_item_id: str) -> None:
        """Complete a discovery task and push its next search into cooldown."""

        query = f"""
        UPDATE `{self.settings.domain_discovery_queue_table_fqn}`
        SET
          status = 'completed',
          lease_owner = NULL,
          lease_expires_at = NULL,
          completed_at = CURRENT_TIMESTAMP(),
          next_attempt_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {self.settings.domain_discovery_cooldown_hours} HOUR),
          last_error = NULL,
          updated_at = CURRENT_TIMESTAMP()
        WHERE work_item_id = '{self._escape(work_item_id)}'
        """
        self.repository.execute_statement(query)

    def _mark_failed(self, work_item_id: str, error_message: str) -> None:
        """Record a failed discovery task and cool it down."""

        query = f"""
        UPDATE `{self.settings.domain_discovery_queue_table_fqn}`
        SET
          status = 'failed',
          lease_owner = NULL,
          lease_expires_at = NULL,
          completed_at = CURRENT_TIMESTAMP(),
          next_attempt_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {self.settings.domain_discovery_cooldown_hours} HOUR),
          last_error = '{self._escape(error_message)}',
          updated_at = CURRENT_TIMESTAMP()
        WHERE work_item_id = '{self._escape(work_item_id)}'
        """
        self.repository.execute_statement(query)

    def _normalize_result_url(self, value: str) -> str:
        """Resolve DuckDuckGo redirect URLs into the destination target."""

        parsed = urlparse(value)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            query = parse_qs(parsed.query)
            target = query.get("uddg", [""])[0]
            if target:
                return target
        return value

    def _normalize_domain(self, value: Any) -> str | None:
        """Normalize a URL or domain string into a root domain key."""

        if not value:
            return None
        raw = str(value).strip().lower()
        if not raw:
            return None
        if "://" not in raw:
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        host = (parsed.netloc or parsed.path).split("@")[-1].strip().lower()
        host = host.split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        host = host.rstrip(".")
        if not host or "." not in host:
            return None
        return host

    def _normalize_url(self, value: Any) -> str | None:
        """Normalize a candidate website URL into a browser-friendly form."""

        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        if "://" not in raw:
            raw = f"https://{raw}"
        return raw.rstrip("/")

    def _normalize_key(self, value: str) -> str:
        """Build a lowercase alphanumeric dedupe key."""

        return re.sub(r"[^a-z0-9]+", "", value.lower()).strip()

    def _is_directory_or_marketplace(self, domain: str) -> bool:
        """Return whether a result domain is clearly not a rooftop site."""

        return (
            any(domain == hint or domain.endswith(f".{hint}") for hint in DIRECTORY_HOST_HINTS)
            or any(domain == hint or domain.endswith(f".{hint}") for hint in OEM_HOST_HINTS)
        )

    def _looks_like_rooftop_candidate(
        self,
        domain: str,
        account_name: str,
        brand_hint: str,
        city: str | None,
        state: str | None,
    ) -> bool:
        """Require a reasonable domain/name/brand match before promotion."""

        if self._is_directory_or_marketplace(domain):
            return False
        root_label = domain.split(".", 1)[0]
        compact_root = re.sub(r"[^a-z0-9]+", "", root_label.lower())
        brand_token = re.sub(r"[^a-z0-9]+", "", brand_hint.lower())
        if brand_token and brand_token in compact_root:
            return True

        meaningful_tokens = [
            re.sub(r"[^a-z0-9]+", "", token.lower())
            for token in re.split(r"\s+", account_name or "")
            if len(re.sub(r"[^a-z0-9]+", "", token.lower())) >= 4
        ]
        for token in meaningful_tokens:
            if token and token in compact_root:
                return True

        city_token = re.sub(r"[^a-z0-9]+", "", (city or "").lower())
        if city_token and len(city_token) >= 4 and city_token in compact_root:
            return True

        state_token = re.sub(r"[^a-z0-9]+", "", (state or "").lower())
        if state_token and len(state_token) >= 4 and state_token in compact_root:
            return True

        return False

    def _score_candidate(
        self,
        item: DiscoveryQueueItem,
        domain: str,
        result: DiscoverySearchResult,
    ) -> float:
        """Score whether a search result looks like a dealer rooftop candidate."""

        score = 0.25
        haystack = " ".join(
            [
                item.brand_hint,
                item.city or "",
                item.state_or_province or "",
                domain,
                result.title,
                result.snippet,
            ]
        ).lower()
        if item.brand_hint and item.brand_hint.lower() in haystack:
            score += 0.3
        if any(word in haystack for word in DEALER_WORDS):
            score += 0.2
        if item.city and item.city.lower() in haystack:
            score += 0.1
        if item.state_or_province and item.state_or_province.lower() in haystack:
            score += 0.1
        if item.country == "Canada" and (
            "canada" in haystack or (item.state_or_province or "").upper() in CANADA_PROVINCES
        ):
            score += 0.1
        if item.country != "Canada" and (item.state_or_province or "").upper() in US_STATES:
            score += 0.05
        return min(score, 0.99)

    def _clean_candidate_name(self, title: str) -> str:
        """Trim common search title separators from candidate account names."""

        name = title.split("|", 1)[0].split(" - ", 1)[0].strip()
        return re.sub(r"\s+", " ", name)

    def _sql_string(self, value: Any) -> str:
        """Render one SQL string literal or NULL."""

        if value is None:
            return "NULL"
        text = str(value).strip()
        if not text:
            return "NULL"
        return f"'{self._escape(text)}'"

    def _escape(self, value: str) -> str:
        """Escape a string for direct SQL literal interpolation."""

        return (
            value.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
        )
