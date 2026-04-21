"""Browser-backed retry lane for blocked dealer sites."""

from __future__ import annotations

from dataclasses import dataclass

from app.bigquery_repository import BigQueryRepository
from app.browser_fetcher import BrowserFetcher
from app.config import Settings
from app.fetch_tracker import FetchStatusTracker, FetchTrackingUpdate
from app.logging_utils import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class BrowserRetryPreview:
    """Summary of accounts currently queued for browser-backed retry."""

    blocked_accounts: int


class BrowserRetryService:
    """Retry blocked dealer websites with a real browser session."""

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.browser_fetcher = BrowserFetcher(timeout_seconds=settings.browser_timeout_seconds)
        self.fetch_tracker = FetchStatusTracker(repository, settings)

    def preview(self) -> BrowserRetryPreview:
        """Return the size of the blocked-site queue."""

        query = f"""
        SELECT COUNT(*) AS blocked_accounts
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND fetch_status = 'blocked'
        """
        row = self.repository.fetch_one(query)
        return BrowserRetryPreview(blocked_accounts=int(row.get("blocked_accounts", 0)))

    def retry(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        account_keys: list[str] | None = None,
    ) -> None:
        """Run browser retries for blocked dealer accounts."""

        preview = self.preview()
        logger.info(
            "Browser retry preview | blocked_accounts=%s | dry_run=%s",
            preview.blocked_accounts,
            dry_run,
        )

        accounts = self._load_accounts(limit=limit, account_keys=account_keys)
        logger.info("Loaded browser retry batch | accounts=%s", len(accounts))

        if dry_run:
            return

        for account in accounts:
            self._retry_account(account)

    def _load_accounts(self, limit: int | None, account_keys: list[str] | None) -> list[dict[str, str]]:
        """Load blocked accounts ready for browser-backed fetch attempts."""

        row_limit = limit or self.settings.enrichment_batch_size
        account_filter = ""
        if account_keys:
            quoted = ", ".join("'" + account_key.lower().replace("'", "''") + "'" for account_key in account_keys)
            account_filter = f" AND account_key IN ({quoted})"

        query = f"""
        SELECT
          dealer_account_id,
          account_key,
          website_url
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND fetch_status = 'blocked'
          {account_filter}
        ORDER BY
          IFNULL(last_fetch_attempt_at, TIMESTAMP('1970-01-01')) ASC,
          account_key ASC
        LIMIT {row_limit}
        """
        return [dict(row.items()) for row in self.repository.run_query(query)]

    def _retry_account(self, account: dict[str, str]) -> None:
        """Retry one blocked website in a browser context."""

        try:
            target_url = self._target_url(account)
            result = self.browser_fetcher.fetch(target_url)
        except RuntimeError as exc:
            logger.warning("Browser retry unavailable | account_key=%s | error=%s", account["account_key"], exc)
            return

        logger.info(
            "Browser retry result | account_key=%s | status=%s | final_url=%s | blocked_reason=%s",
            account["account_key"],
            result.status,
            result.final_url,
            result.blocked_reason or "",
        )

        self.fetch_tracker.record(
            FetchTrackingUpdate(
                dealer_account_id=account["dealer_account_id"],
                fetch_status=result.status,
                fetch_method="browser_http",
                blocked_reason=result.blocked_reason,
            )
        )

        if result.final_url and result.final_url != account["website_url"]:
            self._update_website_url(account["dealer_account_id"], result.final_url)

    def _target_url(self, account: dict[str, str]) -> str:
        """Return the best available URL for a blocked-site browser retry."""

        website_url = account.get("website_url")
        if isinstance(website_url, str) and website_url.strip():
            return website_url.strip()
        return f"https://{account['account_key']}"

    def _update_website_url(self, dealer_account_id: str, website_url: str) -> None:
        """Store the final browser-resolved URL when it changes."""

        escaped_url = website_url.replace("\\", "\\\\").replace("'", "\\'")
        query = f"""
        UPDATE `{self.settings.dealer_accounts_table_fqn}`
        SET
          website_url = '{escaped_url}',
          website_source_url = '{escaped_url}',
          updated_at = CURRENT_TIMESTAMP()
        WHERE dealer_account_id = '{dealer_account_id}'
        """
        self.repository.execute_statement(query)
