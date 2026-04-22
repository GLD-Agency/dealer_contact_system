"""Dashboard data queries for the one-page system status UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.bigquery_repository import BigQueryRepository
from app.config import Settings


@dataclass(frozen=True)
class DashboardConnectionStatus:
    """Simple health row for one important system dependency."""

    name: str
    status: str
    detail: str


class DashboardService:
    """Read one-page dashboard metrics from BigQuery."""

    def __init__(self, repository: BigQueryRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def get_dashboard_data(self) -> dict[str, Any]:
        """Return all dashboard data needed by the UI."""

        overview = self._get_overview()
        latest_snapshot = self._get_latest_snapshot()
        previous_snapshot = self._get_previous_snapshot()
        trend_rows = self._get_recent_snapshots()
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            "environment": self.settings.environment,
            "project_id": self.settings.bigquery_project_id,
            "dataset": self.settings.bigquery_dataset,
            "overview": overview,
            "snapshot_summary": self._build_snapshot_summary(latest_snapshot, previous_snapshot),
            "trend_rows": trend_rows,
            "trend_cards": self._build_trend_cards(trend_rows),
            "connections": self._get_connections(overview),
            "classification_counts": self._get_classification_counts(),
            "fetch_status_counts": self._get_fetch_status_counts(),
            "brand_counts": self._get_brand_counts(),
            "role_family_counts": self._get_role_family_counts(),
            "queue_rows": self._get_queue_rows(),
            "recent_runs": self._get_recent_runs(),
            "blocked_accounts": self._get_blocked_accounts(),
            "integration_connections": self._get_integration_connections(),
        }

    def capture_snapshot(self) -> None:
        """Store one point-in-time dashboard snapshot for trend reporting."""

        query = f"""
        INSERT INTO `{self.settings.dashboard_snapshots_table_fqn}` (
          snapshot_id,
          snapshot_at,
          source_contacts,
          dealer_accounts,
          validated_dealers,
          validated_dealer_groups,
          accounts_with_phone,
          accounts_with_website_phone,
          accounts_with_gbp_phone,
          activation_ready_accounts,
          marketing_ready_contacts,
          sales_ready_leads,
          validated_websites,
          enriched_websites,
          prospect_contacts,
          prospect_leads,
          activation_ready_contacts,
          current_client_contacts,
          canada_contacts,
          dim_matched_leads,
          dim_suppressed_leads,
          website_extracted_contacts,
          blocked_fetch_accounts,
          managed_fetch_eligible_accounts,
          queued_validate,
          queued_enrich,
          queued_extract,
          queued_retry_blocked,
          created_at
        )
        SELECT
          GENERATE_UUID(),
          CURRENT_TIMESTAMP(),
          (SELECT COUNT(*) FROM `{self.settings.source_contact_table_fqn}`),
          (SELECT COUNT(*) FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(dealer_classification = 'dealer') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(dealer_classification = 'dealer_group') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(account_phone IS NOT NULL AND TRIM(account_phone) != '') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(website_phone IS NOT NULL AND TRIM(website_phone) != '') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(gbp_phone IS NOT NULL AND TRIM(gbp_phone) != '') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(activation_status = 'activation_ready') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNT(*) FROM `{self.settings.marketing_ready_contacts_view_fqn}`),
          (SELECT COUNT(*) FROM `{self.settings.sales_ready_leads_view_fqn}`),
          (SELECT COUNTIF(website_url IS NOT NULL AND TRIM(website_url) != '' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(website_url IS NOT NULL AND TRIM(website_url) != '') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNT(*) FROM `{self.settings.prospect_contacts_table_fqn}`),
          (SELECT COUNT(*) FROM `{self.settings.prospect_leads_table_fqn}`),
          (SELECT COUNT(*) FROM `{self.settings.activation_ready_contacts_view_fqn}`),
          (SELECT COUNTIF(audience_type = 'current_client') FROM `{self.settings.prospect_contacts_table_fqn}`),
          (SELECT COUNTIF(country = 'Canada') FROM `{self.settings.prospect_contacts_table_fqn}`),
          (SELECT COUNTIF(dim_client_match_flag) FROM `{self.settings.prospect_leads_table_fqn}`),
          (SELECT COUNTIF(NOT prospecting_allowed_flag) FROM `{self.settings.prospect_leads_table_fqn}`),
          (SELECT COUNTIF(source_type = 'website_contact_extraction') FROM `{self.settings.prospect_contacts_table_fqn}`),
          (SELECT COUNTIF(fetch_status = 'blocked' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(managed_fetch_status = 'eligible') FROM `{self.settings.dealer_accounts_table_fqn}`),
          (SELECT COUNTIF(task_type = 'validate' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`),
          (SELECT COUNTIF(task_type = 'enrich' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`),
          (SELECT COUNTIF(task_type = 'extract_contacts' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`),
          (SELECT COUNTIF(task_type = 'retry_blocked' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`),
          CURRENT_TIMESTAMP()
        """
        self.repository.execute_statement(query)

    def _get_overview(self) -> dict[str, Any]:
        """Return the top-line counts shown in summary cards."""

        query = f"""
        SELECT
          (SELECT COUNT(*) FROM `{self.settings.source_contact_table_fqn}`) AS source_contacts,
          (SELECT COUNT(*) FROM `{self.settings.dealer_accounts_table_fqn}`) AS dealer_accounts,
          (SELECT COUNTIF(dealer_classification = 'dealer') FROM `{self.settings.dealer_accounts_table_fqn}`) AS validated_dealers,
          (SELECT COUNTIF(dealer_classification = 'dealer_group') FROM `{self.settings.dealer_accounts_table_fqn}`) AS validated_dealer_groups,
          (SELECT COUNTIF(account_phone IS NOT NULL AND TRIM(account_phone) != '') FROM `{self.settings.dealer_accounts_table_fqn}`) AS accounts_with_phone,
          (SELECT COUNTIF(website_phone IS NOT NULL AND TRIM(website_phone) != '') FROM `{self.settings.dealer_accounts_table_fqn}`) AS accounts_with_website_phone,
          (SELECT COUNTIF(gbp_phone IS NOT NULL AND TRIM(gbp_phone) != '') FROM `{self.settings.dealer_accounts_table_fqn}`) AS accounts_with_gbp_phone,
          (SELECT COUNTIF(activation_status = 'activation_ready') FROM `{self.settings.dealer_accounts_table_fqn}`) AS activation_ready_accounts,
          (SELECT COUNT(*) FROM `{self.settings.marketing_ready_contacts_view_fqn}`) AS marketing_ready_contacts,
          (SELECT COUNT(*) FROM `{self.settings.sales_ready_leads_view_fqn}`) AS sales_ready_leads,
          (SELECT COUNTIF(website_url IS NOT NULL AND TRIM(website_url) != '') FROM `{self.settings.dealer_accounts_table_fqn}`) AS enriched_websites,
          (SELECT COUNTIF(website_url IS NOT NULL AND TRIM(website_url) != '' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{self.settings.dealer_accounts_table_fqn}`) AS validated_websites,
          (SELECT COUNT(*) FROM `{self.settings.prospect_contacts_table_fqn}`) AS prospect_contacts,
          (SELECT COUNT(*) FROM `{self.settings.prospect_leads_table_fqn}`) AS prospect_leads,
          (SELECT COUNT(*) FROM `{self.settings.activation_ready_contacts_view_fqn}`) AS activation_ready_contacts,
          (SELECT COUNTIF(audience_type = 'current_client') FROM `{self.settings.prospect_contacts_table_fqn}`) AS current_client_contacts,
          (SELECT COUNTIF(country = 'Canada') FROM `{self.settings.prospect_contacts_table_fqn}`) AS canada_contacts,
          (SELECT COUNTIF(dim_client_match_flag) FROM `{self.settings.prospect_leads_table_fqn}`) AS dim_matched_leads,
          (SELECT COUNTIF(NOT prospecting_allowed_flag) FROM `{self.settings.prospect_leads_table_fqn}`) AS dim_suppressed_leads,
          (SELECT COUNTIF(source_type = 'website_contact_extraction') FROM `{self.settings.prospect_contacts_table_fqn}`) AS website_extracted_contacts,
          (SELECT COUNT(*) FROM `{self.settings.pipeline_runs_table_fqn}`) AS pipeline_runs,
          (SELECT COUNTIF(task_type = 'validate' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`) AS queued_validate,
          (SELECT COUNTIF(task_type = 'enrich' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`) AS queued_enrich,
          (SELECT COUNTIF(task_type = 'extract_contacts' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`) AS queued_extract,
          (SELECT COUNTIF(task_type = 'retry_blocked' AND status IN ('pending', 'retry')) FROM `{self.settings.account_work_queue_table_fqn}`) AS queued_retry_blocked,
          (SELECT COUNTIF(status = 'in_progress') FROM `{self.settings.account_work_queue_table_fqn}`) AS queue_in_progress,
          (SELECT COUNTIF(fetch_status = 'blocked' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{self.settings.dealer_accounts_table_fqn}`) AS blocked_fetch_accounts,
          (SELECT COUNTIF(managed_fetch_status = 'eligible') FROM `{self.settings.dealer_accounts_table_fqn}`) AS managed_fetch_eligible_accounts
        """
        return self.repository.fetch_one(query)

    def _get_latest_snapshot(self) -> dict[str, Any]:
        """Return the newest stored dashboard snapshot."""

        query = f"""
        SELECT
          snapshot_at,
          source_contacts,
          dealer_accounts,
          validated_dealers,
          validated_dealer_groups,
          accounts_with_phone,
          accounts_with_website_phone,
          accounts_with_gbp_phone,
          activation_ready_accounts,
          marketing_ready_contacts,
          sales_ready_leads,
          validated_websites,
          enriched_websites,
          prospect_contacts,
          prospect_leads,
          activation_ready_contacts,
          current_client_contacts,
          canada_contacts,
          dim_matched_leads,
          dim_suppressed_leads,
          website_extracted_contacts,
          blocked_fetch_accounts,
          managed_fetch_eligible_accounts,
          queued_validate,
          queued_enrich,
          queued_extract,
          queued_retry_blocked
        FROM `{self.settings.dashboard_snapshots_table_fqn}`
        ORDER BY snapshot_at DESC
        LIMIT 1
        """
        return self.repository.fetch_one(query)

    def _get_previous_snapshot(self) -> dict[str, Any]:
        """Return the prior dashboard snapshot for before/after comparisons."""

        query = f"""
        SELECT
          snapshot_at,
          source_contacts,
          dealer_accounts,
          validated_dealers,
          validated_dealer_groups,
          accounts_with_phone,
          accounts_with_website_phone,
          accounts_with_gbp_phone,
          activation_ready_accounts,
          marketing_ready_contacts,
          sales_ready_leads,
          validated_websites,
          enriched_websites,
          prospect_contacts,
          prospect_leads,
          activation_ready_contacts,
          current_client_contacts,
          canada_contacts,
          dim_matched_leads,
          dim_suppressed_leads,
          website_extracted_contacts,
          blocked_fetch_accounts,
          managed_fetch_eligible_accounts,
          queued_validate,
          queued_enrich,
          queued_extract,
          queued_retry_blocked
        FROM `{self.settings.dashboard_snapshots_table_fqn}`
        ORDER BY snapshot_at DESC
        LIMIT 1
        OFFSET 1
        """
        return self.repository.fetch_one(query)

    def _get_recent_snapshots(self) -> list[dict[str, Any]]:
        """Return recent snapshots for trend rows on the dashboard."""

        query = f"""
        SELECT
          snapshot_at,
          validated_dealers,
          validated_dealer_groups,
          accounts_with_phone,
          accounts_with_website_phone,
          accounts_with_gbp_phone,
          activation_ready_accounts,
          marketing_ready_contacts,
          sales_ready_leads,
          validated_websites,
          enriched_websites,
          prospect_leads,
          activation_ready_contacts,
          current_client_contacts,
          canada_contacts,
          dim_matched_leads,
          dim_suppressed_leads,
          website_extracted_contacts,
          blocked_fetch_accounts,
          managed_fetch_eligible_accounts
        FROM `{self.settings.dashboard_snapshots_table_fqn}`
        ORDER BY snapshot_at DESC
        LIMIT 10
        """
        return self.repository.fetch_all(query)

    def _build_snapshot_summary(
        self,
        latest_snapshot: dict[str, Any],
        previous_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return dashboard cards showing before/after changes."""

        labels = {
            "validated_dealers": "Validated Dealers",
            "validated_dealer_groups": "Dealer Groups",
            "accounts_with_phone": "Accounts With Phone",
            "accounts_with_website_phone": "Accounts With Website Phone",
            "accounts_with_gbp_phone": "Accounts With GBP Phone",
            "activation_ready_accounts": "Activation-Ready Accounts",
            "prospect_leads": "Prospect Leads",
            "marketing_ready_contacts": "Marketing-Ready Contacts",
            "sales_ready_leads": "Sales-Ready Leads",
            "validated_websites": "Website-Ready Dealers",
            "enriched_websites": "Resolved Websites",
            "activation_ready_contacts": "Activation-Ready Contacts",
            "current_client_contacts": "Current Clients",
            "canada_contacts": "Canada Contacts",
            "dim_matched_leads": "DIM Matched Leads",
            "dim_suppressed_leads": "Suppressed Leads",
            "website_extracted_contacts": "Website Contacts",
            "blocked_fetch_accounts": "Blocked Dealer Sites",
            "managed_fetch_eligible_accounts": "Managed Fetch Eligible",
        }
        if not latest_snapshot:
            return {
                "available": False,
                "latest_snapshot_at": None,
                "previous_snapshot_at": None,
                "cards": [],
            }

        cards: list[dict[str, Any]] = []
        for key, label in labels.items():
            latest_value = int(latest_snapshot.get(key, 0) or 0)
            previous_value = int(previous_snapshot.get(key, 0) or 0)
            delta = latest_value - previous_value
            cards.append(
                {
                    "label": label,
                    "value": latest_value,
                    "delta": delta,
                    "direction": self._delta_direction(delta),
                }
            )

        return {
            "available": True,
            "latest_snapshot_at": latest_snapshot.get("snapshot_at"),
            "previous_snapshot_at": previous_snapshot.get("snapshot_at"),
            "cards": cards,
        }

    def _build_trend_cards(self, trend_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build compact sparkline cards from recent snapshot rows."""

        metrics = [
            ("validated_dealers", "Validated Dealers"),
            ("validated_websites", "Website-Ready Dealers"),
            ("accounts_with_phone", "Accounts With Phone"),
            ("accounts_with_website_phone", "Website Phone Coverage"),
            ("accounts_with_gbp_phone", "GBP Phone Coverage"),
            ("marketing_ready_contacts", "Marketing-Ready Contacts"),
            ("sales_ready_leads", "Sales-Ready Leads"),
            ("prospect_leads", "Prospect Leads"),
            ("activation_ready_contacts", "Activation-Ready Contacts"),
            ("current_client_contacts", "Current Clients"),
            ("canada_contacts", "Canada Contacts"),
            ("dim_matched_leads", "DIM Matched Leads"),
            ("dim_suppressed_leads", "Suppressed Leads"),
            ("website_extracted_contacts", "Website Contacts"),
            ("blocked_fetch_accounts", "Blocked Dealer Sites"),
            ("managed_fetch_eligible_accounts", "Managed Fetch Eligible"),
        ]
        if not trend_rows:
            return []

        ordered_rows = list(reversed(trend_rows))
        cards: list[dict[str, Any]] = []
        for key, label in metrics:
            values = [int(row.get(key, 0) or 0) for row in ordered_rows]
            cards.append(
                {
                    "label": label,
                    "current_value": values[-1] if values else 0,
                    "delta": (values[-1] - values[0]) if len(values) > 1 else 0,
                    "direction": self._delta_direction((values[-1] - values[0]) if len(values) > 1 else 0),
                    "sparkline_points": self._build_sparkline_points(values),
                }
            )
        return cards

    @staticmethod
    def _delta_direction(delta: int) -> str:
        """Return a CSS-friendly delta direction."""

        if delta > 0:
            return "up"
        if delta < 0:
            return "down"
        return "flat"

    @staticmethod
    def _build_sparkline_points(values: list[int]) -> str:
        """Convert metric values into a compact SVG polyline string."""

        if not values:
            return ""
        if len(values) == 1:
            return "0,30 100,30"

        min_value = min(values)
        max_value = max(values)
        spread = max(max_value - min_value, 1)
        x_step = 100 / (len(values) - 1)
        points: list[str] = []
        for index, value in enumerate(values):
            x = round(index * x_step, 2)
            normalized = (value - min_value) / spread
            y = round(30 - (normalized * 24), 2)
            points.append(f"{x},{y}")
        return " ".join(points)

    def _get_connections(self, overview: dict[str, Any]) -> list[DashboardConnectionStatus]:
        """Create human-readable system health rows."""

        system_statuses = self._get_named_system_statuses(("client_dim", "managed_fetch"))
        return [
            DashboardConnectionStatus(
                name="BigQuery",
                status="healthy",
                detail=f"Connected to {self.settings.bigquery_project_id}.{self.settings.bigquery_dataset}",
            ),
            DashboardConnectionStatus(
                name="Source Table",
                status="healthy" if int(overview.get("source_contacts", 0)) > 0 else "warning",
                detail=f"{int(overview.get('source_contacts', 0)):,} source contacts available",
            ),
            DashboardConnectionStatus(
                name="Worker Queue",
                status="healthy" if int(overview.get("pipeline_runs", 0)) > 0 else "warning",
                detail=f"{int(overview.get('queue_in_progress', 0)):,} items in progress across queue workers",
            ),
            DashboardConnectionStatus(
                name="Blocked-Site Retry",
                status="warning" if int(overview.get("blocked_fetch_accounts", 0)) > 0 else "healthy",
                detail=f"{int(overview.get('blocked_fetch_accounts', 0)):,} dealer sites still blocked or challenged",
            ),
            self._system_status_row(
                name="Client DIM",
                sync_row=system_statuses.get("client_dim"),
                fallback_status="warning",
                fallback_detail=(
                    "Configured for future client-suppression matching."
                    if self.settings.client_dim_enabled
                    else "Client DIM integration is not configured yet."
                ),
            ),
            self._system_status_row(
                name="Managed Fetch",
                sync_row=system_statuses.get("managed_fetch"),
                fallback_status="warning" if int(overview.get("managed_fetch_eligible_accounts", 0)) > 0 else "healthy",
                fallback_detail=(
                    f"{int(overview.get('managed_fetch_eligible_accounts', 0)):,} hard blocked sites are eligible for escalation."
                ),
            ),
        ]

    def _get_integration_connections(self) -> list[DashboardConnectionStatus]:
        """Return status rows for downstream platform integrations."""

        latest_syncs = self._get_latest_sync_statuses()

        return [
            self._build_integration_status(
                name="Campaign Monitor",
                configured=bool(
                    self.settings.campaign_monitor_api_key
                    and self.settings.campaign_monitor_client_id
                ),
                sync_row=latest_syncs.get("campaign_monitor"),
                missing_detail="Missing API key or client ID.",
            ),
            self._build_integration_status(
                name="Meta",
                configured=bool(
                    self.settings.meta_access_token
                    and self.settings.meta_ad_account_id
                ),
                sync_row=latest_syncs.get("meta"),
                missing_detail="Missing access token or ad account ID.",
            ),
            self._build_integration_status(
                name="Google Ads",
                configured=bool(
                    self.settings.google_ads_developer_token
                    and self.settings.google_ads_customer_id
                ),
                sync_row=latest_syncs.get("google_ads"),
                missing_detail="Missing developer token or customer ID.",
            ),
        ]

    def _build_integration_status(
        self,
        name: str,
        configured: bool,
        sync_row: dict[str, Any] | None,
        missing_detail: str,
    ) -> DashboardConnectionStatus:
        """Map configuration and sync history into one dashboard status row."""

        if not configured:
            return DashboardConnectionStatus(
                name=name,
                status="error",
                detail=f"Not connected. {missing_detail}",
            )

        if not sync_row:
            return DashboardConnectionStatus(
                name=name,
                status="warning",
                detail="Configured, but no sync attempts have been recorded yet.",
            )

        sync_status = (sync_row.get("sync_status") or "unknown").lower()
        last_synced_at = sync_row.get("last_synced_at")
        detail = f"Latest sync status: {sync_status}"
        if last_synced_at:
            detail += f" at {last_synced_at}"

        if sync_status in {"synced", "success", "completed"}:
            status = "healthy"
        elif sync_status in {"failed", "error"}:
            status = "error"
        else:
            status = "warning"

        return DashboardConnectionStatus(
            name=name,
            status=status,
            detail=detail,
        )

    def _get_latest_sync_statuses(self) -> dict[str, dict[str, Any]]:
        """Return the latest sync row for each target system."""

        query = f"""
        SELECT
          target_system,
          sync_status,
          last_synced_at
        FROM (
          SELECT
            target_system,
            sync_status,
            last_synced_at,
            ROW_NUMBER() OVER (
              PARTITION BY target_system
              ORDER BY last_synced_at DESC NULLS LAST, updated_at DESC NULLS LAST, created_at DESC
            ) AS row_number
          FROM `{self.settings.sync_targets_table_fqn}`
          WHERE target_system IN ('campaign_monitor', 'meta', 'google_ads')
        )
        WHERE row_number = 1
        """
        rows = self.repository.fetch_all(query)
        return {str(row["target_system"]): row for row in rows}

    def _get_named_system_statuses(self, systems: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        """Return the latest sync row for each requested system."""

        if not systems:
            return {}
        systems_sql = ", ".join(f"'{system}'" for system in systems)
        query = f"""
        SELECT
          target_system,
          sync_status,
          last_synced_at
        FROM (
          SELECT
            target_system,
            sync_status,
            last_synced_at,
            ROW_NUMBER() OVER (
              PARTITION BY target_system
              ORDER BY last_synced_at DESC NULLS LAST, updated_at DESC NULLS LAST, created_at DESC
            ) AS row_number
          FROM `{self.settings.sync_targets_table_fqn}`
          WHERE target_system IN ({systems_sql})
        )
        WHERE row_number = 1
        """
        rows = self.repository.fetch_all(query)
        return {str(row["target_system"]): row for row in rows}

    def _system_status_row(
        self,
        name: str,
        sync_row: dict[str, Any] | None,
        fallback_status: str,
        fallback_detail: str,
    ) -> DashboardConnectionStatus:
        """Convert one latest-system-status row into a dashboard connection row."""

        if not sync_row:
            return DashboardConnectionStatus(name=name, status=fallback_status, detail=fallback_detail)

        sync_status = str(sync_row.get("sync_status") or "unknown").lower()
        last_synced_at = sync_row.get("last_synced_at")
        detail = f"Latest status: {sync_status}"
        if last_synced_at:
            detail += f" at {last_synced_at}"
        if sync_status in {"synced", "success", "completed", "configured"}:
            status = "healthy"
        elif sync_status in {"failed", "error"}:
            status = "error"
        elif sync_status in {"warning"}:
            status = "warning"
        else:
            status = fallback_status
        return DashboardConnectionStatus(name=name, status=status, detail=detail)

    def _get_classification_counts(self) -> list[dict[str, Any]]:
        """Return account counts by dealer classification."""

        query = f"""
        SELECT
          COALESCE(dealer_classification, 'unclassified') AS label,
          COUNT(*) AS total_accounts
        FROM `{self.settings.dealer_accounts_table_fqn}`
        GROUP BY label
        ORDER BY total_accounts DESC, label ASC
        """
        return self.repository.fetch_all(query)

    def _get_fetch_status_counts(self) -> list[dict[str, Any]]:
        """Return fetch counts for dealer and dealer_group websites."""

        query = f"""
        SELECT
          COALESCE(fetch_status, 'not_attempted') AS label,
          COUNT(*) AS total_accounts
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
        GROUP BY label
        ORDER BY total_accounts DESC, label ASC
        """
        return self.repository.fetch_all(query)

    def _get_brand_counts(self) -> list[dict[str, Any]]:
        """Return the leading validated brands for dashboard charts."""

        query = f"""
        SELECT
          inferred_brand AS label,
          COUNT(*) AS total_accounts
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND inferred_brand IS NOT NULL
          AND TRIM(inferred_brand) != ''
        GROUP BY inferred_brand
        ORDER BY total_accounts DESC, label ASC
        LIMIT 15
        """
        return self.repository.fetch_all(query)

    def _get_role_family_counts(self) -> list[dict[str, Any]]:
        """Return extracted contact counts by role family."""

        query = f"""
        SELECT
          COALESCE(role_family, 'unclassified') AS label,
          COUNT(*) AS total_contacts
        FROM `{self.settings.prospect_contacts_table_fqn}`
        WHERE source_type = 'website_contact_extraction'
        GROUP BY label
        ORDER BY total_contacts DESC, label ASC
        LIMIT 12
        """
        return self.repository.fetch_all(query)

    def _get_queue_rows(self) -> list[dict[str, Any]]:
        """Return queue status counts for each worker type."""

        query = f"""
        SELECT
          task_type,
          COUNTIF(status IN ('pending', 'retry')) AS queued_count,
          COUNTIF(status = 'in_progress') AS in_progress_count,
          COUNTIF(status = 'completed') AS completed_count,
          COUNTIF(status = 'failed') AS failed_count
        FROM `{self.settings.account_work_queue_table_fqn}`
        GROUP BY task_type
        ORDER BY task_type ASC
        """
        return self.repository.fetch_all(query)

    def _get_recent_runs(self) -> list[dict[str, Any]]:
        """Return the most recent worker runs."""

        query = f"""
        SELECT
          task_type,
          run_status,
          requested_batch_size,
          claimed_count,
          succeeded_count,
          failed_count,
          worker_id,
          started_at,
          completed_at,
          run_notes
        FROM `{self.settings.pipeline_runs_table_fqn}`
        ORDER BY started_at DESC
        LIMIT 12
        """
        return self.repository.fetch_all(query)

    def _get_blocked_accounts(self) -> list[dict[str, Any]]:
        """Return a small list of blocked dealer sites for operational review."""

        query = f"""
        SELECT
          account_key,
          website_url,
          inferred_brand,
          blocked_reason,
          blocked_attempt_count,
          managed_fetch_status,
          last_fetch_attempt_at
        FROM `{self.settings.dealer_accounts_table_fqn}`
        WHERE dealer_classification IN ('dealer', 'dealer_group')
          AND fetch_status = 'blocked'
        ORDER BY blocked_attempt_count DESC, last_fetch_attempt_at DESC
        LIMIT 12
        """
        return self.repository.fetch_all(query)
