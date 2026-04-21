"""Command line interface for the dealer contact system pipeline."""

from __future__ import annotations

import argparse

from app.bigquery_client import get_bigquery_client
from app.bigquery_repository import BigQueryRepository
from app.config import Settings, get_settings
from app.dashboard_service import DashboardService
from app.dashboard_web import run_dashboard
from app.logging_utils import configure_logging, get_logger
from app.schema_manager import SchemaManager
from app.services.account_enrichment import AccountEnrichmentService
from app.services.browser_retry import BrowserRetryService
from app.services.campaign_monitor import CampaignMonitorService
from app.services.contact_extraction import ContactExtractionService
from app.services.dealer_validation import DealerValidationService
from app.services.normalization import NormalizationService
from app.services.work_queue import TASK_TYPES, WorkQueueService


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""

    parser = argparse.ArgumentParser(
        description="Dealer Contact System pipeline CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "setup",
        help="Create or verify canonical BigQuery tables.",
    )

    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Normalize contact_master into canonical BigQuery tables.",
    )
    normalize_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the normalization inputs without writing to BigQuery.",
    )

    enrich_parser = subparsers.add_parser(
        "enrich-accounts",
        help="Confirm dealer websites and enrich dealer account fields from public pages.",
    )
    enrich_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the account enrichment batch without writing to BigQuery.",
    )
    enrich_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override the default enrichment batch size for a single run.",
    )
    enrich_parser.add_argument(
        "--account-key",
        action="append",
        default=None,
        help="Re-enrich one or more specific account_key values.",
    )

    extract_parser = subparsers.add_parser(
        "extract-contacts",
        help="Extract manager, operations, and executive contacts from confirmed dealer websites.",
    )
    extract_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the contact extraction batch without writing to BigQuery.",
    )
    extract_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override the default extraction batch size for a single run.",
    )
    extract_parser.add_argument(
        "--account-key",
        action="append",
        default=None,
        help="Extract contacts for one or more specific account_key values.",
    )

    validate_parser = subparsers.add_parser(
        "validate-dealers",
        help="Classify accounts as dealers, dealer groups, vendors, OEMs, non-dealers, or unknown.",
    )
    validate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the dealer validation batch without writing to BigQuery.",
    )
    validate_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override the default validation batch size for a single run.",
    )
    validate_parser.add_argument(
        "--account-key",
        action="append",
        default=None,
        help="Validate one or more specific account_key values.",
    )

    browser_retry_parser = subparsers.add_parser(
        "retry-blocked-sites",
        help="Retry blocked dealer websites with a browser-backed fetch lane.",
    )
    browser_retry_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the blocked-site browser retry queue without writing to BigQuery.",
    )
    browser_retry_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override the default blocked-site retry batch size for a single run.",
    )
    browser_retry_parser.add_argument(
        "--account-key",
        action="append",
        default=None,
        help="Retry one or more specific blocked account_key values.",
    )

    seed_queue_parser = subparsers.add_parser(
        "seed-work-queue",
        help="Seed queue rows for one task or all worker task types.",
    )
    seed_queue_parser.add_argument(
        "--task-type",
        choices=TASK_TYPES + ["all"],
        default="all",
        help="Which queue to seed. Defaults to all worker task types.",
    )

    worker_parser = subparsers.add_parser(
        "run-worker",
        help="Claim a batch from the BigQuery work queue and process it.",
    )
    worker_parser.add_argument(
        "--task-type",
        required=True,
        choices=TASK_TYPES,
        help="Which queue-backed worker to run.",
    )
    worker_parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override the default queue worker batch size for this run.",
    )
    worker_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview queue counts without claiming or processing work.",
    )

    cycle_parser = subparsers.add_parser(
        "run-queue-cycle",
        help="Run one full queue-driven worker cycle for scheduled Cloud Run jobs.",
    )
    cycle_parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed all queue task types before running the cycle.",
    )
    cycle_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the cycle without processing queue items.",
    )

    subparsers.add_parser(
        "report",
        help="Print source and canonical BigQuery table counts.",
    )

    subparsers.add_parser(
        "serve-dashboard",
        help="Run the one-page dashboard UI locally.",
    )

    subparsers.add_parser(
        "capture-dashboard-snapshot",
        help="Store one dashboard metrics snapshot for before/after reporting.",
    )

    campaign_monitor_parser = subparsers.add_parser(
        "check-campaign-monitor",
        help="Check Campaign Monitor API connectivity and record the latest status.",
    )
    campaign_monitor_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test the connection logic without writing the result to BigQuery.",
    )

    campaign_monitor_structure_parser = subparsers.add_parser(
        "ensure-campaign-monitor-structure",
        help="Create the master Campaign Monitor list, required custom fields, and OEM segments.",
    )
    campaign_monitor_structure_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the Campaign Monitor structure changes without creating anything.",
    )

    campaign_monitor_sync_parser = subparsers.add_parser(
        "sync-campaign-monitor",
        help="Sync a deduped batch of subscribers into the Campaign Monitor master list.",
    )
    campaign_monitor_sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the Campaign Monitor subscriber sync without sending data.",
    )
    campaign_monitor_sync_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of subscribers to sync in one batch.",
    )

    return parser


def main() -> None:
    """Run the requested CLI command."""

    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    settings = get_settings()
    repository = BigQueryRepository(get_bigquery_client())
    schema_manager = SchemaManager(repository, settings)
    normalization_service = NormalizationService(repository, settings)
    account_enrichment_service = AccountEnrichmentService(repository, settings)
    contact_extraction_service = ContactExtractionService(repository, settings)
    dealer_validation_service = DealerValidationService(repository, settings)
    browser_retry_service = BrowserRetryService(repository, settings)
    work_queue_service = WorkQueueService(repository, settings)
    dashboard_service = DashboardService(repository, settings)
    campaign_monitor_service = CampaignMonitorService(repository, settings)

    logger.info(
        "Starting command | environment=%s | project=%s | dataset=%s | command=%s",
        settings.environment,
        settings.bigquery_project_id,
        settings.bigquery_dataset,
        args.command,
    )

    if args.command == "setup":
        schema_manager.ensure_tables()
        logger.info("Schema setup complete.")
        return

    if args.command == "normalize":
        schema_manager.ensure_tables()
        normalization_service.normalize(dry_run=args.dry_run)
        logger.info("Normalization command complete.")
        return

    if args.command == "enrich-accounts":
        schema_manager.ensure_tables()
        account_enrichment_service.enrich(
            dry_run=args.dry_run,
            limit=args.limit,
            account_keys=args.account_key,
        )
        logger.info("Account enrichment command complete.")
        return

    if args.command == "extract-contacts":
        schema_manager.ensure_tables()
        contact_extraction_service.extract(
            dry_run=args.dry_run,
            limit=args.limit,
            account_keys=args.account_key,
        )
        logger.info("Contact extraction command complete.")
        return

    if args.command == "validate-dealers":
        schema_manager.ensure_tables()
        dealer_validation_service.validate(
            dry_run=args.dry_run,
            limit=args.limit,
            account_keys=args.account_key,
        )
        logger.info("Dealer validation command complete.")
        return

    if args.command == "retry-blocked-sites":
        schema_manager.ensure_tables()
        browser_retry_service.retry(
            dry_run=args.dry_run,
            limit=args.limit,
            account_keys=args.account_key,
        )
        logger.info("Browser retry command complete.")
        return

    if args.command == "seed-work-queue":
        schema_manager.ensure_tables()
        work_queue_service.seed(task_type=args.task_type)
        logger.info("Work queue seed command complete.")
        return

    if args.command == "run-worker":
        schema_manager.ensure_tables()
        work_queue_service.run_worker(
            task_type=args.task_type,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        logger.info("Queue worker command complete.")
        return

    if args.command == "run-queue-cycle":
        schema_manager.ensure_tables()
        if args.seed:
            work_queue_service.seed(task_type="all")
        work_queue_service.run_worker(
            task_type="validate",
            batch_size=settings.validate_worker_batch_size,
            dry_run=args.dry_run,
        )
        work_queue_service.run_worker(
            task_type="enrich",
            batch_size=settings.enrich_worker_batch_size,
            dry_run=args.dry_run,
        )
        work_queue_service.run_worker(
            task_type="extract_contacts",
            batch_size=settings.extract_worker_batch_size,
            dry_run=args.dry_run,
        )
        work_queue_service.run_worker(
            task_type="retry_blocked",
            batch_size=settings.retry_blocked_worker_batch_size,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            dashboard_service.capture_snapshot()
            campaign_monitor_service.check_connection(dry_run=False)
        logger.info("Queue cycle command complete.")
        return

    if args.command == "report":
        print_report(repository, settings)
        return

    if args.command == "serve-dashboard":
        run_dashboard()
        return

    if args.command == "capture-dashboard-snapshot":
        schema_manager.ensure_tables()
        dashboard_service.capture_snapshot()
        logger.info("Dashboard snapshot capture complete.")
        return

    if args.command == "check-campaign-monitor":
        schema_manager.ensure_tables()
        result = campaign_monitor_service.check_connection(dry_run=args.dry_run)
        logger.info("Campaign Monitor check complete | status=%s | detail=%s", result.status, result.detail)
        print(f"Campaign Monitor status: {result.status}")
        print(result.detail)
        return

    if args.command == "ensure-campaign-monitor-structure":
        schema_manager.ensure_tables()
        result = campaign_monitor_service.ensure_master_list_and_segments(dry_run=args.dry_run)
        logger.info(
            "Campaign Monitor structure check complete | status=%s | list_id=%s | created_segments=%s | existing_segments=%s",
            result.status,
            result.list_id,
            result.created_segments,
            result.existing_segments,
        )
        print(f"Campaign Monitor structure status: {result.status}")
        print(result.detail)
        if result.list_id:
            print(f"Master list ID: {result.list_id}")
        print(f"Created segments: {result.created_segments}")
        print(f"Existing segments: {result.existing_segments}")
        return

    if args.command == "sync-campaign-monitor":
        schema_manager.ensure_tables()
        result = campaign_monitor_service.sync_subscribers(
            dry_run=args.dry_run,
            limit=args.limit,
        )
        logger.info(
            "Campaign Monitor subscriber sync complete | status=%s | list_id=%s | submitted=%s | new=%s | existing=%s | failed=%s",
            result.status,
            result.list_id,
            result.submitted_count,
            result.new_subscribers,
            result.existing_subscribers,
            result.failed_count,
        )
        print(f"Campaign Monitor subscriber sync status: {result.status}")
        print(result.detail)
        if result.list_id:
            print(f"Master list ID: {result.list_id}")
        print(f"Submitted: {result.submitted_count}")
        print(f"New subscribers: {result.new_subscribers}")
        print(f"Existing subscribers updated: {result.existing_subscribers}")
        print(f"Failures: {result.failed_count}")
        return


def print_report(repository: BigQueryRepository, settings: Settings) -> None:
    """Print health checks for the source and canonical tables."""

    query = f"""
    SELECT
      (SELECT COUNT(*) FROM `{settings.source_contact_table_fqn}`) AS source_contacts,
      (SELECT COUNT(DISTINCT account_key) FROM `{settings.source_contact_table_fqn}`) AS source_distinct_accounts,
      (SELECT COUNTIF(is_personal_email) FROM `{settings.source_contact_table_fqn}`) AS source_personal_emails,
      (SELECT COUNT(*) FROM `{settings.dealer_accounts_table_fqn}`) AS dealer_accounts,
      (SELECT COUNTIF(website_url IS NOT NULL AND TRIM(website_url) != '') FROM `{settings.dealer_accounts_table_fqn}`) AS enriched_websites,
      (SELECT COUNTIF(website_url IS NOT NULL AND TRIM(website_url) != '' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{settings.dealer_accounts_table_fqn}`) AS validated_websites,
      (SELECT COUNTIF(source_type = 'website_resolution') FROM `{settings.dealer_accounts_table_fqn}`) AS resolution_only_websites,
      (SELECT COUNTIF(fetch_status = 'success' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{settings.dealer_accounts_table_fqn}`) AS successful_fetch_accounts,
      (SELECT COUNTIF(fetch_status = 'blocked' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{settings.dealer_accounts_table_fqn}`) AS blocked_fetch_accounts,
      (SELECT COUNTIF(fetch_status = 'unavailable' AND dealer_classification IN ('dealer', 'dealer_group')) FROM `{settings.dealer_accounts_table_fqn}`) AS unavailable_fetch_accounts,
      (SELECT COUNTIF(
        website_url IS NOT NULL
        AND TRIM(website_url) != ''
        AND dealer_classification IN ('dealer', 'dealer_group')
        AND source_type = 'website_resolution'
        AND IFNULL(account_name, '') = ''
        AND IFNULL(inferred_brand, '') = ''
        AND (IFNULL(account_city, '') = '' OR IFNULL(account_state, '') = '')
      ) FROM `{settings.dealer_accounts_table_fqn}`) AS blocked_or_unparsed_websites,
      (SELECT COUNTIF(account_name IS NOT NULL AND TRIM(account_name) != '') FROM `{settings.dealer_accounts_table_fqn}`) AS enriched_names,
      (SELECT COUNTIF(inferred_brand IS NOT NULL AND TRIM(inferred_brand) != '') FROM `{settings.dealer_accounts_table_fqn}`) AS enriched_brands,
      (SELECT COUNTIF(account_city IS NOT NULL AND account_state IS NOT NULL) FROM `{settings.dealer_accounts_table_fqn}`) AS enriched_locations,
      (SELECT COUNTIF(dealer_classification = 'dealer') FROM `{settings.dealer_accounts_table_fqn}`) AS validated_dealers,
      (SELECT COUNTIF(dealer_classification = 'dealer_group') FROM `{settings.dealer_accounts_table_fqn}`) AS validated_dealer_groups,
      (SELECT COUNTIF(dealer_classification = 'vendor') FROM `{settings.dealer_accounts_table_fqn}`) AS validated_vendors,
      (SELECT COUNTIF(dealer_classification = 'non_dealer') FROM `{settings.dealer_accounts_table_fqn}`) AS validated_non_dealers,
      (SELECT COUNTIF(dealer_classification = 'oem') FROM `{settings.dealer_accounts_table_fqn}`) AS validated_oems,
      (SELECT COUNTIF(dealer_classification = 'unknown') FROM `{settings.dealer_accounts_table_fqn}`) AS validated_unknowns,
      (SELECT COUNT(*) FROM `{settings.prospect_contacts_table_fqn}`) AS prospect_contacts,
      (SELECT COUNTIF(source_type = 'website_contact_extraction') FROM `{settings.prospect_contacts_table_fqn}`) AS website_extracted_contacts,
      (SELECT COUNT(*) FROM `{settings.account_relationships_table_fqn}`) AS account_relationships,
      (SELECT COUNT(*) FROM `{settings.sync_targets_table_fqn}`) AS sync_targets,
      (SELECT COUNTIF(task_type = 'validate' AND status IN ('pending', 'retry')) FROM `{settings.account_work_queue_table_fqn}`) AS queued_validate,
      (SELECT COUNTIF(task_type = 'enrich' AND status IN ('pending', 'retry')) FROM `{settings.account_work_queue_table_fqn}`) AS queued_enrich,
      (SELECT COUNTIF(task_type = 'extract_contacts' AND status IN ('pending', 'retry')) FROM `{settings.account_work_queue_table_fqn}`) AS queued_extract_contacts,
      (SELECT COUNTIF(task_type = 'retry_blocked' AND status IN ('pending', 'retry')) FROM `{settings.account_work_queue_table_fqn}`) AS queued_retry_blocked,
      (SELECT COUNTIF(status = 'in_progress') FROM `{settings.account_work_queue_table_fqn}`) AS queue_in_progress,
      (SELECT COUNT(*) FROM `{settings.pipeline_runs_table_fqn}`) AS pipeline_runs
    """
    report = repository.fetch_one(query)
    logger.info("Read-only report | source=%s", settings.source_contact_table_fqn)
    print("Dealer Contact System Report")
    print(f"Source contacts: {report.get('source_contacts', 0)}")
    print(f"Source distinct account keys: {report.get('source_distinct_accounts', 0)}")
    print(f"Source personal emails: {report.get('source_personal_emails', 0)}")
    print(f"Dealer accounts: {report.get('dealer_accounts', 0)}")
    print(f"Enriched websites: {report.get('enriched_websites', 0)}")
    print(f"Validated dealer/group websites: {report.get('validated_websites', 0)}")
    print(f"Resolution-only websites: {report.get('resolution_only_websites', 0)}")
    print(f"Successful dealer/group fetches: {report.get('successful_fetch_accounts', 0)}")
    print(f"Blocked dealer/group fetches: {report.get('blocked_fetch_accounts', 0)}")
    print(f"Unavailable dealer/group fetches: {report.get('unavailable_fetch_accounts', 0)}")
    print(f"Blocked or unparsed dealer websites: {report.get('blocked_or_unparsed_websites', 0)}")
    print(f"Enriched account names: {report.get('enriched_names', 0)}")
    print(f"Enriched brands: {report.get('enriched_brands', 0)}")
    print(f"Enriched locations: {report.get('enriched_locations', 0)}")
    print(f"Validated dealers: {report.get('validated_dealers', 0)}")
    print(f"Validated dealer groups: {report.get('validated_dealer_groups', 0)}")
    print(f"Validated vendors: {report.get('validated_vendors', 0)}")
    print(f"Validated non-dealers: {report.get('validated_non_dealers', 0)}")
    print(f"Validated OEMs: {report.get('validated_oems', 0)}")
    print(f"Validated unknowns: {report.get('validated_unknowns', 0)}")
    print(f"Prospect contacts: {report.get('prospect_contacts', 0)}")
    print(f"Website-extracted contacts: {report.get('website_extracted_contacts', 0)}")
    print(f"Account relationships: {report.get('account_relationships', 0)}")
    print(f"Sync targets: {report.get('sync_targets', 0)}")
    print(f"Queued validate tasks: {report.get('queued_validate', 0)}")
    print(f"Queued enrich tasks: {report.get('queued_enrich', 0)}")
    print(f"Queued extract tasks: {report.get('queued_extract_contacts', 0)}")
    print(f"Queued blocked-site retry tasks: {report.get('queued_retry_blocked', 0)}")
    print(f"Queue items in progress: {report.get('queue_in_progress', 0)}")
    print(f"Pipeline runs logged: {report.get('pipeline_runs', 0)}")


if __name__ == "__main__":
    main()
