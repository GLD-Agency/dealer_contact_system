"""Create and verify BigQuery tables used by the pipeline."""

from __future__ import annotations

from app.bigquery_repository import BigQueryRepository
from app.config import Settings
from app.logging_utils import get_logger


logger = get_logger(__name__)


class SchemaManager:
    """Ensure required canonical tables exist in BigQuery."""

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def ensure_tables(self) -> None:
        """Create canonical tables if they are missing."""

        statements = {
            self.settings.dealer_accounts_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.dealer_accounts_table_fqn}` (
              dealer_account_id STRING NOT NULL,
              account_key STRING NOT NULL,
              email_domain STRING,
              account_name STRING,
              inferred_brand STRING,
              dealer_classification STRING,
              account_city STRING,
              account_state STRING,
              website_url STRING,
              account_type STRING,
              account_status STRING,
              enrichment_stage STRING,
              activation_status STRING,
              confidence_score FLOAT64,
              dealer_classification_confidence_score FLOAT64,
              website_confidence_score FLOAT64,
              account_name_confidence_score FLOAT64,
              brand_confidence_score FLOAT64,
              location_confidence_score FLOAT64,
              source_type STRING,
              source_table STRING,
              website_source_url STRING,
              account_name_source_url STRING,
              brand_source_url STRING,
              dealer_classification_source_url STRING,
              dealer_validation_checked_at TIMESTAMP,
              location_source_url STRING,
              fetch_status STRING,
              fetch_method STRING,
              blocked_reason STRING,
              blocked_attempt_count INT64,
              last_fetch_attempt_at TIMESTAMP,
              last_fetch_success_at TIMESTAMP,
              is_personal_domain BOOL,
              last_verified_at TIMESTAMP,
              first_seen_at TIMESTAMP,
              last_seen_at TIMESTAMP,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """,
            self.settings.prospect_contacts_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.prospect_contacts_table_fqn}` (
              prospect_contact_id STRING NOT NULL,
              source_contact_id STRING,
              full_name STRING,
              first_name STRING,
              last_name STRING,
              email STRING NOT NULL,
              email_domain STRING,
              is_personal_email BOOL,
              domain_type STRING,
              role_type STRING,
              role_title STRING,
              role_family STRING,
              contact_status STRING,
              enrichment_stage STRING,
              activation_status STRING,
              confidence_score FLOAT64,
              source_type STRING,
              source_table STRING,
              source_file_name STRING,
              audience_type STRING,
              market STRING,
              country STRING,
              source_url STRING,
              first_seen_at TIMESTAMP,
              last_seen_at TIMESTAMP,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """,
            self.settings.account_relationships_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.account_relationships_table_fqn}` (
              relationship_id STRING NOT NULL,
              dealer_account_id STRING NOT NULL,
              prospect_contact_id STRING NOT NULL,
              relationship_type STRING,
              is_primary BOOL,
              relationship_status STRING,
              confidence_score FLOAT64,
              source_type STRING,
              source_table STRING,
              source_url STRING,
              first_seen_at TIMESTAMP,
              last_seen_at TIMESTAMP,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """,
            self.settings.sync_targets_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.sync_targets_table_fqn}` (
              sync_target_id STRING NOT NULL,
              target_system STRING NOT NULL,
              target_entity_type STRING NOT NULL,
              target_entity_id STRING,
              source_record_type STRING NOT NULL,
              source_record_id STRING NOT NULL,
              sync_status STRING,
              last_synced_at TIMESTAMP,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """,
            self.settings.account_work_queue_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.account_work_queue_table_fqn}` (
              work_item_id STRING NOT NULL,
              task_type STRING NOT NULL,
              account_key STRING NOT NULL,
              status STRING NOT NULL,
              priority INT64,
              attempt_count INT64,
              lease_owner STRING,
              lease_expires_at TIMESTAMP,
              last_attempt_at TIMESTAMP,
              next_attempt_at TIMESTAMP,
              completed_at TIMESTAMP,
              last_error STRING,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """,
            self.settings.pipeline_runs_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.pipeline_runs_table_fqn}` (
              pipeline_run_id STRING NOT NULL,
              task_type STRING NOT NULL,
              run_status STRING NOT NULL,
              worker_id STRING,
              requested_batch_size INT64,
              claimed_count INT64,
              succeeded_count INT64,
              failed_count INT64,
              run_notes STRING,
              started_at TIMESTAMP,
              completed_at TIMESTAMP,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """,
            self.settings.dashboard_snapshots_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.dashboard_snapshots_table_fqn}` (
              snapshot_id STRING NOT NULL,
              snapshot_at TIMESTAMP NOT NULL,
              source_contacts INT64,
              dealer_accounts INT64,
              validated_dealers INT64,
              validated_dealer_groups INT64,
              activation_ready_accounts INT64,
              validated_websites INT64,
              enriched_websites INT64,
              prospect_contacts INT64,
              activation_ready_contacts INT64,
              current_client_contacts INT64,
              canada_contacts INT64,
              website_extracted_contacts INT64,
              blocked_fetch_accounts INT64,
              queued_validate INT64,
              queued_enrich INT64,
              queued_extract INT64,
              queued_retry_blocked INT64,
              created_at TIMESTAMP
            )
            """,
            self.settings.external_seed_contacts_table_fqn: f"""
            CREATE TABLE IF NOT EXISTS `{self.settings.external_seed_contacts_table_fqn}` (
              external_seed_contact_id STRING NOT NULL,
              import_batch_id STRING NOT NULL,
              source_file_name STRING NOT NULL,
              source_path STRING,
              source_group STRING,
              audience_type STRING,
              market STRING,
              country STRING,
              inferred_brand_from_source STRING,
              row_number INT64,
              raw_name STRING,
              raw_email STRING,
              normalized_full_name STRING,
              first_name STRING,
              last_name STRING,
              normalized_email STRING,
              email_domain STRING,
              account_key STRING,
              is_personal_email BOOL,
              import_notes STRING,
              imported_at TIMESTAMP,
              created_at TIMESTAMP
            )
            """,
        }

        for table_name, statement in statements.items():
            logger.info("Ensuring table exists: %s", table_name)
            self.repository.execute_statement(statement)

        self._ensure_optional_columns()

    def _ensure_optional_columns(self) -> None:
        """Add newly introduced columns without rewriting any tables."""

        alter_statements = [
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS account_city STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS account_state STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS dealer_classification STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS enrichment_stage STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS activation_status STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS dealer_classification_confidence_score FLOAT64",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS website_confidence_score FLOAT64",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS account_name_confidence_score FLOAT64",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS brand_confidence_score FLOAT64",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS location_confidence_score FLOAT64",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS website_source_url STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS account_name_source_url STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS brand_source_url STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS dealer_classification_source_url STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS dealer_validation_checked_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS location_source_url STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS fetch_status STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS fetch_method STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS blocked_reason STRING",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS blocked_attempt_count INT64",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS last_fetch_attempt_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS last_fetch_success_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.dealer_accounts_table_fqn}` ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS role_family STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS enrichment_stage STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS activation_status STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS source_file_name STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS audience_type STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS market STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS country STRING",
            f"ALTER TABLE `{self.settings.prospect_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS source_url STRING",
            f"ALTER TABLE `{self.settings.account_relationships_table_fqn}` ADD COLUMN IF NOT EXISTS source_url STRING",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS priority INT64",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS attempt_count INT64",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS lease_owner STRING",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.account_work_queue_table_fqn}` ADD COLUMN IF NOT EXISTS last_error STRING",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS worker_id STRING",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS requested_batch_size INT64",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS claimed_count INT64",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS succeeded_count INT64",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS failed_count INT64",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS run_notes STRING",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.pipeline_runs_table_fqn}` ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.dashboard_snapshots_table_fqn}` ADD COLUMN IF NOT EXISTS activation_ready_accounts INT64",
            f"ALTER TABLE `{self.settings.dashboard_snapshots_table_fqn}` ADD COLUMN IF NOT EXISTS activation_ready_contacts INT64",
            f"ALTER TABLE `{self.settings.dashboard_snapshots_table_fqn}` ADD COLUMN IF NOT EXISTS current_client_contacts INT64",
            f"ALTER TABLE `{self.settings.dashboard_snapshots_table_fqn}` ADD COLUMN IF NOT EXISTS canada_contacts INT64",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS source_path STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS source_group STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS audience_type STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS market STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS country STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS inferred_brand_from_source STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS row_number INT64",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS raw_name STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS raw_email STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS normalized_full_name STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS first_name STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS last_name STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS normalized_email STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS email_domain STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS account_key STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS is_personal_email BOOL",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS import_notes STRING",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS imported_at TIMESTAMP",
            f"ALTER TABLE `{self.settings.external_seed_contacts_table_fqn}` ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        ]

        for statement in alter_statements:
            self.repository.execute_statement(statement)
