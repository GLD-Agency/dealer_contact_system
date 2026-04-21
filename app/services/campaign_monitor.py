"""Campaign Monitor connection checks and future sync helpers."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from app.bigquery_repository import BigQueryRepository
from app.config import Settings
from app.logging_utils import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class CampaignMonitorHealthResult:
    """Simple result from one Campaign Monitor health check."""

    status: str
    detail: str


class CampaignMonitorService:
    """Run Campaign Monitor health checks and record them in BigQuery."""

    BASE_URL = "https://api.createsend.com/api/v3.3"
    CONNECTION_RECORD_ID = "campaign_monitor_connection"

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def check_connection(self, dry_run: bool = False) -> CampaignMonitorHealthResult:
        """Check Campaign Monitor connectivity and optionally store the result."""

        if not self.settings.campaign_monitor_api_key or not self.settings.campaign_monitor_client_id:
            result = CampaignMonitorHealthResult(
                status="failed",
                detail="Campaign Monitor credentials are missing.",
            )
            if not dry_run:
                self._record_status(result.status)
            return result

        url = (
            f"{self.BASE_URL}/clients/"
            f"{self.settings.campaign_monitor_client_id}/lists.json"
        )
        try:
            response = requests.get(
                url,
                auth=(self.settings.campaign_monitor_api_key, "x"),
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            list_count = len(payload) if isinstance(payload, list) else 0
            result = CampaignMonitorHealthResult(
                status="success",
                detail=f"Connected successfully. Found {list_count} subscriber lists.",
            )
        except requests.RequestException as error:
            logger.warning("Campaign Monitor connection check failed: %s", error)
            result = CampaignMonitorHealthResult(
                status="failed",
                detail=f"Connection failed: {error}",
            )

        if not dry_run:
            self._record_status(result.status)
        return result

    def _record_status(self, sync_status: str) -> None:
        """Upsert the latest Campaign Monitor connection state into sync_targets."""

        query = f"""
        MERGE `{self.settings.sync_targets_table_fqn}` AS target
        USING (
          SELECT
            'campaign_monitor' AS target_system,
            'system_connection' AS target_entity_type,
            '{self.settings.campaign_monitor_client_id or "missing_client_id"}' AS target_entity_id,
            'system' AS source_record_type,
            '{self.CONNECTION_RECORD_ID}' AS source_record_id,
            '{sync_status}' AS sync_status
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
