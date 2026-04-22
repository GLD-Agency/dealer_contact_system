"""Integrate a client DIM table as suppression and ownership authority."""

from __future__ import annotations

from dataclasses import dataclass

from google.api_core.exceptions import BadRequest, Forbidden, NotFound

from app.bigquery_repository import BigQueryRepository
from app.config import Settings
from app.logging_utils import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class ClientDimRefreshResult:
    """Summary from one client DIM refresh attempt."""

    status: str
    detail: str
    matched_leads: int
    suppressed_leads: int


class ClientDimService:
    """Refresh client DIM matches into the prospect lead table."""

    CONNECTION_RECORD_ID = "client_dim_connection"

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def refresh(self, dry_run: bool = False) -> ClientDimRefreshResult:
        """Refresh client DIM mappings into the prospect lead table."""

        if not self.settings.client_dim_enabled:
            detail = "Client DIM integration is disabled. Prospect leads keep default suppression values."
            if not dry_run:
                self._record_status("warning", detail)
            return ClientDimRefreshResult("warning", detail, 0, 0)

        client_dim_table = self.settings.client_dim_table_fqn
        if not client_dim_table:
            detail = "Client DIM integration is enabled, but dataset/table configuration is incomplete."
            if not dry_run:
                self._record_status("failed", detail)
            return ClientDimRefreshResult("failed", detail, 0, 0)

        try:
            self.repository.fetch_one(f"SELECT COUNT(*) AS total_rows FROM `{client_dim_table}` LIMIT 1")
        except (BadRequest, Forbidden, NotFound) as error:
            detail = f"Client DIM table is not accessible yet: {error}"
            logger.warning(detail)
            if not dry_run:
                self._record_status("failed", detail)
            return ClientDimRefreshResult("failed", detail, 0, 0)

        preview_query = self._build_match_preview_query(client_dim_table)
        preview = self.repository.fetch_one(preview_query)
        matched_leads = int(preview.get("matched_leads", 0))
        suppressed_leads = int(preview.get("suppressed_leads", 0))

        if dry_run:
            detail = (
              "Would refresh client DIM matches. "
              f"Matched leads: {matched_leads:,}. Suppressed leads: {suppressed_leads:,}."
            )
            return ClientDimRefreshResult("preview", detail, matched_leads, suppressed_leads)

        reset_query = f"""
        UPDATE `{self.settings.prospect_leads_table_fqn}`
        SET
          dim_client_match_flag = FALSE,
          dim_client_id = NULL,
          dim_account_owner = NULL,
          prospecting_allowed_flag = TRUE,
          suppression_reason = NULL,
          current_client_override_flag = FALSE,
          updated_at = CURRENT_TIMESTAMP()
        WHERE TRUE
        """
        self.repository.execute_statement(reset_query)

        merge_query = self._build_match_merge_query(client_dim_table)
        self.repository.execute_statement(merge_query)
        detail = (
            f"Refreshed client DIM matches. Matched leads: {matched_leads:,}. "
            f"Suppressed leads: {suppressed_leads:,}."
        )
        self._record_status("synced", detail)
        logger.info(detail)
        return ClientDimRefreshResult("success", detail, matched_leads, suppressed_leads)

    def _build_match_preview_query(self, client_dim_table: str) -> str:
        """Return a count query for lead/DIM matches."""

        return f"""
        WITH client_dim AS (
          SELECT
            LOWER(TRIM(CAST({self.settings.client_dim_client_id_column} AS STRING))) AS dim_client_id,
            NULLIF(TRIM(CAST({self.settings.client_dim_account_owner_column} AS STRING)), '') AS dim_account_owner,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_account_key_column} AS STRING))), '') AS dim_account_key,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_domain_column} AS STRING))), '') AS dim_domain,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_name_column} AS STRING))), '') AS dim_name,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_city_column} AS STRING))), '') AS dim_city,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_state_column} AS STRING))), '') AS dim_state,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_email_domain_column} AS STRING))), '') AS dim_email_domain,
            NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_email_column} AS STRING))), '') AS dim_email,
            CASE
              WHEN LOWER(TRIM(CAST({self.settings.client_dim_current_client_flag_column} AS STRING))) IN ('true', '1', 'yes', 'y') THEN TRUE
              WHEN LOWER(TRIM(CAST({self.settings.client_dim_current_client_flag_column} AS STRING))) IN ('false', '0', 'no', 'n') THEN FALSE
              ELSE TRUE
            END AS current_client_flag
          FROM `{client_dim_table}`
        ),
        ranked_matches AS (
          SELECT
            pl.prospect_lead_id,
            ROW_NUMBER() OVER (
              PARTITION BY pl.prospect_lead_id
              ORDER BY
                CASE
                  WHEN cd.dim_account_key IS NOT NULL AND cd.dim_account_key = LOWER(pl.account_key) THEN 1
                  WHEN cd.dim_domain IS NOT NULL AND cd.dim_domain = LOWER(pl.account_key) THEN 1
                  WHEN cd.dim_name IS NOT NULL
                       AND cd.dim_name = LOWER(pl.dealer_name)
                       AND COALESCE(cd.dim_city, '') = COALESCE(LOWER(pl.city), '')
                       AND COALESCE(cd.dim_state, '') = COALESCE(LOWER(pl.state), '') THEN 2
                  WHEN cd.dim_email_domain IS NOT NULL AND cd.dim_email_domain = LOWER(pl.email_domain) THEN 3
                  WHEN cd.dim_email IS NOT NULL AND cd.dim_email = LOWER(pl.email) THEN 4
                  ELSE 9
                END,
                cd.dim_client_id
            ) AS row_number,
            cd.current_client_flag
          FROM `{self.settings.prospect_leads_table_fqn}` AS pl
          JOIN client_dim AS cd
            ON (
              (cd.dim_account_key IS NOT NULL AND cd.dim_account_key = LOWER(pl.account_key))
              OR (cd.dim_domain IS NOT NULL AND cd.dim_domain = LOWER(pl.account_key))
              OR (
                cd.dim_name IS NOT NULL
                AND cd.dim_name = LOWER(pl.dealer_name)
                AND COALESCE(cd.dim_city, '') = COALESCE(LOWER(pl.city), '')
                AND COALESCE(cd.dim_state, '') = COALESCE(LOWER(pl.state), '')
              )
              OR (cd.dim_email_domain IS NOT NULL AND cd.dim_email_domain = LOWER(pl.email_domain))
              OR (cd.dim_email IS NOT NULL AND cd.dim_email = LOWER(pl.email))
            )
        )
        SELECT
          COUNTIF(row_number = 1) AS matched_leads,
          COUNTIF(row_number = 1 AND current_client_flag) AS suppressed_leads
        FROM ranked_matches
        """

    def _build_match_merge_query(self, client_dim_table: str) -> str:
        """Return the merge query for client DIM mappings."""

        return f"""
        MERGE `{self.settings.prospect_leads_table_fqn}` AS target
        USING (
          WITH client_dim AS (
            SELECT
              LOWER(TRIM(CAST({self.settings.client_dim_client_id_column} AS STRING))) AS dim_client_id,
              NULLIF(TRIM(CAST({self.settings.client_dim_account_owner_column} AS STRING)), '') AS dim_account_owner,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_account_key_column} AS STRING))), '') AS dim_account_key,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_domain_column} AS STRING))), '') AS dim_domain,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_name_column} AS STRING))), '') AS dim_name,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_city_column} AS STRING))), '') AS dim_city,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_state_column} AS STRING))), '') AS dim_state,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_email_domain_column} AS STRING))), '') AS dim_email_domain,
              NULLIF(LOWER(TRIM(CAST({self.settings.client_dim_email_column} AS STRING))), '') AS dim_email,
              CASE
                WHEN LOWER(TRIM(CAST({self.settings.client_dim_current_client_flag_column} AS STRING))) IN ('true', '1', 'yes', 'y') THEN TRUE
                WHEN LOWER(TRIM(CAST({self.settings.client_dim_current_client_flag_column} AS STRING))) IN ('false', '0', 'no', 'n') THEN FALSE
                ELSE TRUE
              END AS current_client_flag
            FROM `{client_dim_table}`
          ),
          ranked_matches AS (
            SELECT
              pl.prospect_lead_id,
              cd.dim_client_id,
              cd.dim_account_owner,
              cd.current_client_flag,
              ROW_NUMBER() OVER (
                PARTITION BY pl.prospect_lead_id
                ORDER BY
                  CASE
                    WHEN cd.dim_account_key IS NOT NULL AND cd.dim_account_key = LOWER(pl.account_key) THEN 1
                    WHEN cd.dim_domain IS NOT NULL AND cd.dim_domain = LOWER(pl.account_key) THEN 1
                    WHEN cd.dim_name IS NOT NULL
                         AND cd.dim_name = LOWER(pl.dealer_name)
                         AND COALESCE(cd.dim_city, '') = COALESCE(LOWER(pl.city), '')
                         AND COALESCE(cd.dim_state, '') = COALESCE(LOWER(pl.state), '') THEN 2
                    WHEN cd.dim_email_domain IS NOT NULL AND cd.dim_email_domain = LOWER(pl.email_domain) THEN 3
                    WHEN cd.dim_email IS NOT NULL AND cd.dim_email = LOWER(pl.email) THEN 4
                    ELSE 9
                  END,
                  cd.dim_client_id
              ) AS row_number
            FROM `{self.settings.prospect_leads_table_fqn}` AS pl
            JOIN client_dim AS cd
              ON (
                (cd.dim_account_key IS NOT NULL AND cd.dim_account_key = LOWER(pl.account_key))
                OR (cd.dim_domain IS NOT NULL AND cd.dim_domain = LOWER(pl.account_key))
                OR (
                  cd.dim_name IS NOT NULL
                  AND cd.dim_name = LOWER(pl.dealer_name)
                  AND COALESCE(cd.dim_city, '') = COALESCE(LOWER(pl.city), '')
                  AND COALESCE(cd.dim_state, '') = COALESCE(LOWER(pl.state), '')
                )
                OR (cd.dim_email_domain IS NOT NULL AND cd.dim_email_domain = LOWER(pl.email_domain))
                OR (cd.dim_email IS NOT NULL AND cd.dim_email = LOWER(pl.email))
              )
          )
          SELECT
            prospect_lead_id,
            dim_client_id,
            dim_account_owner,
            current_client_flag
          FROM ranked_matches
          WHERE row_number = 1
        ) AS source
        ON target.prospect_lead_id = source.prospect_lead_id
        WHEN MATCHED THEN
          UPDATE SET
            dim_client_match_flag = TRUE,
            dim_client_id = source.dim_client_id,
            dim_account_owner = source.dim_account_owner,
            prospecting_allowed_flag = FALSE,
            suppression_reason = 'client_dim_match',
            current_client_override_flag = source.current_client_flag,
            updated_at = CURRENT_TIMESTAMP()
        """

    def _record_status(self, sync_status: str, detail: str) -> None:
        """Upsert the latest client DIM integration state into sync_targets."""

        safe_detail = (
            detail.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
        )
        query = f"""
        MERGE `{self.settings.sync_targets_table_fqn}` AS target
        USING (
          SELECT
            'client_dim' AS target_system,
            'system_connection' AS target_entity_type,
            '{self.settings.client_dim_table_fqn or "not_configured"}' AS target_entity_id,
            'system' AS source_record_type,
            '{self.CONNECTION_RECORD_ID}' AS source_record_id,
            '{sync_status}' AS sync_status,
            '{safe_detail}' AS sync_detail
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
