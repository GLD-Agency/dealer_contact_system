"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# Load variables from a local .env file if one exists.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Simple container for runtime configuration."""

    environment: str
    bigquery_project_id: str
    bigquery_dataset: str
    source_contact_table: str
    dealer_accounts_table: str
    prospect_contacts_table: str
    account_relationships_table: str
    sync_targets_table: str
    account_work_queue_table: str
    pipeline_runs_table: str
    dashboard_snapshots_table: str
    enrichment_batch_size: int
    worker_batch_size: int
    worker_lease_minutes: int
    validate_worker_batch_size: int
    enrich_worker_batch_size: int
    extract_worker_batch_size: int
    retry_blocked_worker_batch_size: int
    cloud_run_region: str
    request_timeout_seconds: int
    browser_timeout_seconds: int
    blocked_retry_short_cooldown_hours: int
    blocked_retry_medium_cooldown_hours: int
    blocked_retry_long_cooldown_hours: int
    campaign_monitor_api_key: str | None
    campaign_monitor_client_id: str | None
    meta_access_token: str | None
    meta_ad_account_id: str | None
    google_ads_developer_token: str | None
    google_ads_customer_id: str | None
    google_application_credentials: str | None

    @property
    def source_contact_table_fqn(self) -> str:
        """Return the fully qualified source table name."""

        return self.table_fqn(self.source_contact_table)

    @property
    def dealer_accounts_table_fqn(self) -> str:
        """Return the fully qualified dealer accounts table name."""

        return self.table_fqn(self.dealer_accounts_table)

    @property
    def prospect_contacts_table_fqn(self) -> str:
        """Return the fully qualified prospect contacts table name."""

        return self.table_fqn(self.prospect_contacts_table)

    @property
    def account_relationships_table_fqn(self) -> str:
        """Return the fully qualified account relationships table name."""

        return self.table_fqn(self.account_relationships_table)

    @property
    def sync_targets_table_fqn(self) -> str:
        """Return the fully qualified sync targets table name."""

        return self.table_fqn(self.sync_targets_table)

    @property
    def account_work_queue_table_fqn(self) -> str:
        """Return the fully qualified account work queue table name."""

        return self.table_fqn(self.account_work_queue_table)

    @property
    def pipeline_runs_table_fqn(self) -> str:
        """Return the fully qualified pipeline runs table name."""

        return self.table_fqn(self.pipeline_runs_table)

    @property
    def dashboard_snapshots_table_fqn(self) -> str:
        """Return the fully qualified dashboard snapshots table name."""

        return self.table_fqn(self.dashboard_snapshots_table)

    def table_fqn(self, table_name: str) -> str:
        """Build a fully qualified BigQuery table name."""

        return f"{self.bigquery_project_id}.{self.bigquery_dataset}.{table_name}"


def get_settings() -> Settings:
    """Read settings from environment variables with safe defaults."""

    return Settings(
        environment=os.getenv("APP_ENVIRONMENT", "local"),
        bigquery_project_id=os.getenv("BIGQUERY_PROJECT_ID", "dealer-contacts-project"),
        bigquery_dataset=os.getenv("BIGQUERY_DATASET", "dealer_data"),
        source_contact_table=os.getenv("SOURCE_CONTACT_TABLE", "contact_master"),
        dealer_accounts_table=os.getenv("DEALER_ACCOUNTS_TABLE", "dealer_accounts"),
        prospect_contacts_table=os.getenv("PROSPECT_CONTACTS_TABLE", "prospect_contacts"),
        account_relationships_table=os.getenv(
            "ACCOUNT_RELATIONSHIPS_TABLE",
            "account_relationships",
        ),
        sync_targets_table=os.getenv("SYNC_TARGETS_TABLE", "sync_targets"),
        account_work_queue_table=os.getenv("ACCOUNT_WORK_QUEUE_TABLE", "account_work_queue"),
        pipeline_runs_table=os.getenv("PIPELINE_RUNS_TABLE", "pipeline_runs"),
        dashboard_snapshots_table=os.getenv("DASHBOARD_SNAPSHOTS_TABLE", "dashboard_snapshots"),
        enrichment_batch_size=int(os.getenv("ENRICHMENT_BATCH_SIZE", "25")),
        worker_batch_size=int(os.getenv("WORKER_BATCH_SIZE", "50")),
        worker_lease_minutes=int(os.getenv("WORKER_LEASE_MINUTES", "30")),
        validate_worker_batch_size=int(os.getenv("VALIDATE_WORKER_BATCH_SIZE", "50")),
        enrich_worker_batch_size=int(os.getenv("ENRICH_WORKER_BATCH_SIZE", "25")),
        extract_worker_batch_size=int(os.getenv("EXTRACT_WORKER_BATCH_SIZE", "25")),
        retry_blocked_worker_batch_size=int(os.getenv("RETRY_BLOCKED_WORKER_BATCH_SIZE", "10")),
        cloud_run_region=os.getenv("CLOUD_RUN_REGION", "us-central1"),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "12")),
        browser_timeout_seconds=int(os.getenv("BROWSER_TIMEOUT_SECONDS", "30")),
        blocked_retry_short_cooldown_hours=int(os.getenv("BLOCKED_RETRY_SHORT_COOLDOWN_HOURS", "6")),
        blocked_retry_medium_cooldown_hours=int(os.getenv("BLOCKED_RETRY_MEDIUM_COOLDOWN_HOURS", "24")),
        blocked_retry_long_cooldown_hours=int(os.getenv("BLOCKED_RETRY_LONG_COOLDOWN_HOURS", "72")),
        campaign_monitor_api_key=os.getenv("CAMPAIGN_MONITOR_API_KEY"),
        campaign_monitor_client_id=os.getenv("CAMPAIGN_MONITOR_CLIENT_ID"),
        meta_access_token=os.getenv("META_ACCESS_TOKEN"),
        meta_ad_account_id=os.getenv("META_AD_ACCOUNT_ID"),
        google_ads_developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        google_ads_customer_id=os.getenv("GOOGLE_ADS_CUSTOMER_ID"),
        google_application_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    )
