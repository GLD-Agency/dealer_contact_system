"""Campaign Monitor connection checks and structure helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class CampaignMonitorStructureResult:
    """Summary from one structure sync into Campaign Monitor."""

    status: str
    detail: str
    list_id: str | None
    created_segments: int
    existing_segments: int


class CampaignMonitorService:
    """Run Campaign Monitor health checks and record them in BigQuery."""

    BASE_URL = "https://api.createsend.com/api/v3.3"
    CONNECTION_RECORD_ID = "campaign_monitor_connection"
    MASTER_LIST_RECORD_ID = "campaign_monitor_master_list"
    SEGMENT_CUSTOM_FIELDS = {
        "OEM": "Text",
        "Dealer Name": "Text",
        "City": "Text",
        "State": "Text",
        "Role Family": "Text",
        "Dealer Classification": "Text",
    }

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

    def ensure_master_list_and_segments(
        self,
        dry_run: bool = False,
    ) -> CampaignMonitorStructureResult:
        """Ensure the master list, custom fields, and OEM segments exist."""

        if not self.settings.campaign_monitor_api_key or not self.settings.campaign_monitor_client_id:
            return CampaignMonitorStructureResult(
                status="failed",
                detail="Campaign Monitor credentials are missing.",
                list_id=None,
                created_segments=0,
                existing_segments=0,
            )

        brands = self._get_brand_values()
        if not brands:
            return CampaignMonitorStructureResult(
                status="failed",
                detail="No validated OEM brands were found in BigQuery.",
                list_id=None,
                created_segments=0,
                existing_segments=0,
            )

        lists = self._api_get(f"/clients/{self.settings.campaign_monitor_client_id}/lists.json")
        master_list = next(
            (
                item
                for item in lists
                if str(item.get("Name", "")).strip() == self.settings.campaign_monitor_master_list_name
            ),
            None,
        )

        created_list = False
        if not master_list:
            if dry_run:
                list_id = None
            else:
                payload = {
                    "Title": self.settings.campaign_monitor_master_list_name,
                    "UnsubscribePage": "",
                    "ConfirmedOptIn": False,
                    "ConfirmationSuccessPage": "",
                    "UnsubscribeSetting": "AllClientLists",
                }
                list_id = str(
                    self._api_post(
                        f"/lists/{self.settings.campaign_monitor_client_id}.json",
                        payload,
                    )
                )
                created_list = True
                master_list = {
                    "ListID": list_id,
                    "Name": self.settings.campaign_monitor_master_list_name,
                }
        else:
            list_id = str(master_list["ListID"])

        if dry_run and not master_list:
            return CampaignMonitorStructureResult(
                status="success",
                detail=(
                    f"Would create master list '{self.settings.campaign_monitor_master_list_name}' "
                    f"and {len(brands)} OEM segments."
                ),
                list_id=None,
                created_segments=len(brands),
                existing_segments=0,
            )

        if list_id is None:
            return CampaignMonitorStructureResult(
                status="failed",
                detail="Unable to determine a Campaign Monitor list ID.",
                list_id=None,
                created_segments=0,
                existing_segments=0,
            )

        field_map = self._ensure_custom_fields(list_id, dry_run=dry_run)
        existing_segments = self._api_get(f"/lists/{list_id}/segments.json") if not dry_run else []
        existing_names = {str(item.get("Title", "")).strip() for item in existing_segments}
        created_segments = 0

        oem_key = field_map.get("OEM", "[OEM]")
        for brand in brands:
            segment_name = f"Automation {brand} Subscribers"
            if segment_name in existing_names:
                continue
            created_segments += 1
            if dry_run:
                continue
            payload = {
                "Title": segment_name,
                "RuleGroups": [
                    {
                        "Rules": [
                            {
                                "RuleType": oem_key,
                                "Clause": f"EQUALS {brand}",
                            }
                        ]
                    }
                ],
            }
            self._api_post(f"/segments/{list_id}.json", payload)

        if not dry_run:
            self._record_structure_status(list_id=list_id)

        existing_segment_count = len(existing_names)
        action_bits = []
        if created_list:
            action_bits.append("created the master list")
        if created_segments:
            action_bits.append(f"created {created_segments} OEM segments")
        if not action_bits:
            action_bits.append("found the master list and all OEM segments already in place")

        return CampaignMonitorStructureResult(
            status="success",
            detail=(
                f"Campaign Monitor structure is ready: {', '.join(action_bits)}. "
                f"Current OEM brand count: {len(brands)}."
            ),
            list_id=list_id,
            created_segments=created_segments,
            existing_segments=existing_segment_count,
        )

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

    def _record_structure_status(self, list_id: str) -> None:
        """Upsert the Campaign Monitor master list status into sync_targets."""

        query = f"""
        MERGE `{self.settings.sync_targets_table_fqn}` AS target
        USING (
          SELECT
            'campaign_monitor' AS target_system,
            'subscriber_list' AS target_entity_type,
            '{list_id}' AS target_entity_id,
            'system' AS source_record_type,
            '{self.MASTER_LIST_RECORD_ID}' AS source_record_id,
            'synced' AS sync_status
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

    def _ensure_custom_fields(self, list_id: str, dry_run: bool) -> dict[str, str]:
        """Ensure required custom fields exist on the Campaign Monitor list."""

        existing_fields = self._api_get(f"/lists/{list_id}/customfields.json") if not dry_run else []
        field_map = {
            str(item.get("FieldName", "")).strip(): str(item.get("Key", "")).strip()
            for item in existing_fields
        }
        for field_name, data_type in self.SEGMENT_CUSTOM_FIELDS.items():
            if field_name in field_map:
                continue
            field_map[field_name] = f"[{field_name}]"
            if dry_run:
                continue
            payload = {
                "FieldName": field_name,
                "DataType": data_type,
                "VisibleInPreferenceCenter": True,
            }
            created = self._api_post(f"/lists/{list_id}/customfields.json", payload)
            field_map[field_name] = str(created) if created else field_map[field_name]
        return field_map

    def _get_brand_values(self) -> list[str]:
        """Return validated OEM brands from dealer accounts."""

        query = f"""
        SELECT DISTINCT inferred_brand
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND inferred_brand IS NOT NULL
          AND TRIM(inferred_brand) != ''
        ORDER BY inferred_brand ASC
        """
        rows = self.repository.fetch_all(query)
        return [str(row["inferred_brand"]).strip() for row in rows if row.get("inferred_brand")]

    def _api_get(self, path: str) -> Any:
        """Send a GET request to Campaign Monitor and return the decoded JSON."""

        response = requests.get(
            f"{self.BASE_URL}{path}",
            auth=(self.settings.campaign_monitor_api_key, "x"),
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        if not response.text.strip():
            return None
        return response.json()

    def _api_post(self, path: str, payload: dict[str, Any]) -> Any:
        """Send a POST request to Campaign Monitor and return the decoded response."""

        response = requests.post(
            f"{self.BASE_URL}{path}",
            auth=(self.settings.campaign_monitor_api_key, "x"),
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        if not response.text.strip():
            return None
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text.strip().strip('"')
