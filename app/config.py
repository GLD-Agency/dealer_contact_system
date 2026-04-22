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
    external_seed_contacts_table: str
    prospect_leads_table: str
    activation_ready_contacts_view: str
    marketing_ready_contacts_view: str
    sales_ready_leads_view: str
    external_seed_directory: str
    enrichment_batch_size: int
    worker_batch_size: int
    worker_lease_minutes: int
    validate_worker_batch_size: int
    enrich_worker_batch_size: int
    gbp_worker_batch_size: int
    extract_worker_batch_size: int
    retry_blocked_worker_batch_size: int
    campaign_monitor_sync_batch_size: int
    campaign_monitor_sync_enabled: bool
    gbp_enrichment_enabled: bool
    gbp_provider: str
    gbp_search_endpoint: str
    managed_fetch_enabled: bool
    managed_fetch_provider: str
    managed_fetch_api_key: str | None
    managed_fetch_batch_size: int
    managed_fetch_min_blocked_attempts: int
    managed_fetch_cooldown_hours: int
    cloud_run_region: str
    request_timeout_seconds: int
    browser_timeout_seconds: int
    blocked_retry_short_cooldown_hours: int
    blocked_retry_medium_cooldown_hours: int
    blocked_retry_long_cooldown_hours: int
    campaign_monitor_api_key: str | None
    campaign_monitor_client_id: str | None
    campaign_monitor_master_list_name: str
    meta_access_token: str | None
    meta_ad_account_id: str | None
    google_ads_developer_token: str | None
    google_ads_customer_id: str | None
    google_application_credentials: str | None
    gld_accountability_project_id: str
    client_dim_dataset: str
    client_dim_table: str
    client_dim_enabled: bool
    client_dim_client_id_column: str
    client_dim_account_owner_column: str
    client_dim_account_key_column: str
    client_dim_domain_column: str
    client_dim_name_column: str
    client_dim_city_column: str
    client_dim_state_column: str
    client_dim_email_domain_column: str
    client_dim_email_column: str
    client_dim_current_client_flag_column: str

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

    @property
    def external_seed_contacts_table_fqn(self) -> str:
        """Return the fully qualified external seed contacts table name."""

        return self.table_fqn(self.external_seed_contacts_table)

    @property
    def prospect_leads_table_fqn(self) -> str:
        """Return the fully qualified prospect leads table name."""

        return self.table_fqn(self.prospect_leads_table)

    @property
    def activation_ready_contacts_view_fqn(self) -> str:
        """Return the fully qualified activation-ready contacts view name."""

        return self.table_fqn(self.activation_ready_contacts_view)

    @property
    def marketing_ready_contacts_view_fqn(self) -> str:
        """Return the fully qualified marketing-ready contacts view name."""

        return self.table_fqn(self.marketing_ready_contacts_view)

    @property
    def sales_ready_leads_view_fqn(self) -> str:
        """Return the fully qualified sales-ready leads view name."""

        return self.table_fqn(self.sales_ready_leads_view)

    @property
    def client_dim_table_fqn(self) -> str | None:
        """Return the fully qualified client DIM table name when configured."""

        if not self.client_dim_dataset or not self.client_dim_table:
            return None
        return f"{self.gld_accountability_project_id}.{self.client_dim_dataset}.{self.client_dim_table}"

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
        external_seed_contacts_table=os.getenv("EXTERNAL_SEED_CONTACTS_TABLE", "external_seed_contacts"),
        prospect_leads_table=os.getenv("PROSPECT_LEADS_TABLE", "prospect_leads"),
        activation_ready_contacts_view=os.getenv("ACTIVATION_READY_CONTACTS_VIEW", "activation_ready_contacts"),
        marketing_ready_contacts_view=os.getenv("MARKETING_READY_CONTACTS_VIEW", "marketing_ready_contacts"),
        sales_ready_leads_view=os.getenv("SALES_READY_LEADS_VIEW", "sales_ready_leads"),
        external_seed_directory=os.getenv(
            "EXTERNAL_SEED_DIRECTORY",
            str(Path.home() / "Downloads"),
        ),
        enrichment_batch_size=int(os.getenv("ENRICHMENT_BATCH_SIZE", "25")),
        worker_batch_size=int(os.getenv("WORKER_BATCH_SIZE", "50")),
        worker_lease_minutes=int(os.getenv("WORKER_LEASE_MINUTES", "30")),
        validate_worker_batch_size=int(os.getenv("VALIDATE_WORKER_BATCH_SIZE", "50")),
        enrich_worker_batch_size=int(os.getenv("ENRICH_WORKER_BATCH_SIZE", "25")),
        gbp_worker_batch_size=int(os.getenv("GBP_WORKER_BATCH_SIZE", "25")),
        extract_worker_batch_size=int(os.getenv("EXTRACT_WORKER_BATCH_SIZE", "25")),
        retry_blocked_worker_batch_size=int(os.getenv("RETRY_BLOCKED_WORKER_BATCH_SIZE", "10")),
        campaign_monitor_sync_batch_size=int(os.getenv("CAMPAIGN_MONITOR_SYNC_BATCH_SIZE", "100")),
        campaign_monitor_sync_enabled=os.getenv("CAMPAIGN_MONITOR_SYNC_ENABLED", "false").lower() == "true",
        gbp_enrichment_enabled=os.getenv("GBP_ENRICHMENT_ENABLED", "true").lower() == "true",
        gbp_provider=os.getenv("GBP_PROVIDER", "duckduckgo_search_fallback"),
        gbp_search_endpoint=os.getenv("GBP_SEARCH_ENDPOINT", "https://html.duckduckgo.com/html/"),
        managed_fetch_enabled=os.getenv("MANAGED_FETCH_ENABLED", "false").lower() == "true",
        managed_fetch_provider=os.getenv("MANAGED_FETCH_PROVIDER", "none"),
        managed_fetch_api_key=os.getenv("MANAGED_FETCH_API_KEY"),
        managed_fetch_batch_size=int(os.getenv("MANAGED_FETCH_BATCH_SIZE", "25")),
        managed_fetch_min_blocked_attempts=int(os.getenv("MANAGED_FETCH_MIN_BLOCKED_ATTEMPTS", "3")),
        managed_fetch_cooldown_hours=int(os.getenv("MANAGED_FETCH_COOLDOWN_HOURS", "72")),
        cloud_run_region=os.getenv("CLOUD_RUN_REGION", "us-central1"),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "12")),
        browser_timeout_seconds=int(os.getenv("BROWSER_TIMEOUT_SECONDS", "30")),
        blocked_retry_short_cooldown_hours=int(os.getenv("BLOCKED_RETRY_SHORT_COOLDOWN_HOURS", "6")),
        blocked_retry_medium_cooldown_hours=int(os.getenv("BLOCKED_RETRY_MEDIUM_COOLDOWN_HOURS", "24")),
        blocked_retry_long_cooldown_hours=int(os.getenv("BLOCKED_RETRY_LONG_COOLDOWN_HOURS", "72")),
        campaign_monitor_api_key=os.getenv("CAMPAIGN_MONITOR_API_KEY"),
        campaign_monitor_client_id=os.getenv("CAMPAIGN_MONITOR_CLIENT_ID"),
        campaign_monitor_master_list_name=os.getenv(
            "CAMPAIGN_MONITOR_MASTER_LIST_NAME",
            "Automation All Subscribers",
        ),
        meta_access_token=os.getenv("META_ACCESS_TOKEN"),
        meta_ad_account_id=os.getenv("META_AD_ACCOUNT_ID"),
        google_ads_developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        google_ads_customer_id=os.getenv("GOOGLE_ADS_CUSTOMER_ID"),
        google_application_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        gld_accountability_project_id=os.getenv("GLD_ACCOUNTABILITY_PROJECT_ID", "productivity-project-491503"),
        client_dim_dataset=os.getenv("CLIENT_DIM_DATASET", "accountability_v1"),
        client_dim_table=os.getenv("CLIENT_DIM_TABLE", "dim_clients"),
        client_dim_enabled=os.getenv("CLIENT_DIM_ENABLED", "false").lower() == "true",
        client_dim_client_id_column=os.getenv("CLIENT_DIM_CLIENT_ID_COLUMN", "client_key"),
        client_dim_account_owner_column=os.getenv("CLIENT_DIM_ACCOUNT_OWNER_COLUMN", ""),
        client_dim_account_key_column=os.getenv("CLIENT_DIM_ACCOUNT_KEY_COLUMN", "account_key"),
        client_dim_domain_column=os.getenv("CLIENT_DIM_DOMAIN_COLUMN", ""),
        client_dim_name_column=os.getenv("CLIENT_DIM_NAME_COLUMN", "normalized_client_name"),
        client_dim_city_column=os.getenv("CLIENT_DIM_CITY_COLUMN", ""),
        client_dim_state_column=os.getenv("CLIENT_DIM_STATE_COLUMN", ""),
        client_dim_email_domain_column=os.getenv("CLIENT_DIM_EMAIL_DOMAIN_COLUMN", ""),
        client_dim_email_column=os.getenv("CLIENT_DIM_EMAIL_COLUMN", ""),
        client_dim_current_client_flag_column=os.getenv("CLIENT_DIM_CURRENT_CLIENT_FLAG_COLUMN", "active_flag"),
    )
