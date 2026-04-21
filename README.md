# dealer_contact_system

Phase 2 foundation for a dealer contact pipeline that uses BigQuery as the source of truth for contact and account data.

## What This Project Includes

- App config for environment-driven BigQuery settings
- A reusable BigQuery repository layer
- Python-managed schema setup for canonical tables
- A normalization pipeline that reads `contact_master`
- An account enrichment pipeline that confirms dealer websites and writes best current account values
- A leadership contact extraction pipeline that uses confirmed dealer sites
- A dealer validation pipeline that classifies true dealers vs non-dealers and other business types
- Fetch-status tracking for blocked, successful, and unavailable dealer website attempts
- A browser-backed retry lane for blocked dealer websites
- A BigQuery-backed account work queue for queue-driven workers
- A pipeline run log for resumable worker execution and future scheduling
- CLI commands for setup, normalize, and report
- Helper scripts for connection checks and operational entry points

This version does not add crawling, multi-agent orchestration, Campaign Monitor sync, or Airtable sync yet.

## Current Data Flow

1. Read from `dealer_data.contact_master`
2. Normalize accounts into `dealer_accounts`
3. Normalize contacts into `prospect_contacts`
4. Create links in `account_relationships`
5. Enrich `dealer_accounts` from public website signals
6. Validate whether an account is actually a dealer
7. Enrich and extract from validated `dealer` and `dealer_group` accounts only
8. Track fetch outcomes so blocked sites can move into a future browser-backed retry lane
9. Retry blocked dealer websites with a browser-backed fetch lane when basic HTTP fails
10. Use queue-backed workers to claim small account batches and checkpoint progress
11. Leave `sync_targets` ready for later downstream sync work

Important guardrails:

- `contact_master` is never modified
- No tables are dropped
- Existing higher-confidence canonical rows are not downgraded by lower-confidence source rows
- Personal emails are preserved and flagged instead of being silently removed

## Project Structure

```text
dealer_contact_system/
  app/
    __init__.py
    __main__.py
    bigquery_client.py
    bigquery_repository.py
    browser_fetcher.py
    cli.py
    config.py
    fetch_tracker.py
    logging_utils.py
    schema_manager.py
    web_fetcher.py
    services/
      account_enrichment.py
      browser_retry.py
      contact_extraction.py
      dealer_validation.py
      __init__.py
      normalization.py
      work_queue.py
  scripts/
    test_bigquery_connection.py
    check_contact_count.py
    check_domain_count.py
    setup_bigquery_tables.py
    run_normalization.py
    enrich_accounts.py
    extract_contacts.py
    validate_dealers.py
    report_pipeline_status.py
  requirements.txt
  .env.example
  README.md
```

## Setup

1. Create or activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env`.
4. Update `.env` with your project and table settings if you want to override the defaults.
5. Authenticate with Google Cloud.
6. If you plan to use the browser-backed blocked-site retry lane, install the Chromium runtime for Playwright:

```bash
playwright install chromium
```

You can use either:

- Application Default Credentials:

```bash
gcloud auth application-default login
```

- Or a service account key via `GOOGLE_APPLICATION_CREDENTIALS`

## Environment Variables

- `APP_ENVIRONMENT`: Runtime label such as `local`
- `BIGQUERY_PROJECT_ID`: BigQuery project ID
- `BIGQUERY_DATASET`: BigQuery dataset name
- `SOURCE_CONTACT_TABLE`: Source table for raw contacts
- `DEALER_ACCOUNTS_TABLE`: Canonical account table
- `PROSPECT_CONTACTS_TABLE`: Canonical contact table
- `ACCOUNT_RELATIONSHIPS_TABLE`: Account-to-contact link table
- `SYNC_TARGETS_TABLE`: Placeholder downstream sync table
- `ACCOUNT_WORK_QUEUE_TABLE`: BigQuery work queue table for brute-force workers
- `PIPELINE_RUNS_TABLE`: BigQuery run log for worker execution
- `WORKER_BATCH_SIZE`: Default account batch size for queue-driven workers
- `WORKER_LEASE_MINUTES`: How long a worker lease remains valid before another worker can retry it
- `VALIDATE_WORKER_BATCH_SIZE`: Batch size for one queue-cycle validation step
- `ENRICH_WORKER_BATCH_SIZE`: Batch size for one queue-cycle enrichment step
- `EXTRACT_WORKER_BATCH_SIZE`: Batch size for one queue-cycle contact extraction step
- `RETRY_BLOCKED_WORKER_BATCH_SIZE`: Batch size for one queue-cycle blocked-site retry step
- `CLOUD_RUN_REGION`: Target region for Cloud Run jobs
- `BROWSER_TIMEOUT_SECONDS`: Timeout for browser-backed blocked-site retries
- `GOOGLE_APPLICATION_CREDENTIALS`: Optional service account key path

Defaults target:

- project: `dealer-contacts-project`
- dataset: `dealer_data`
- source table: `contact_master`

## CLI Commands

Run the CLI directly:

```bash
python -m app setup
python -m app normalize --dry-run
python -m app normalize
python -m app enrich-accounts --dry-run --limit 10
python -m app enrich-accounts --limit 25
python -m app enrich-accounts --account-key 1ststatechevy.com
python -m app validate-dealers --dry-run --limit 10
python -m app validate-dealers --account-key 1ststatechevy.com
python -m app extract-contacts --dry-run --limit 10
python -m app extract-contacts --account-key 1ststatechevy.com
python -m app retry-blocked-sites --dry-run --limit 10
python -m app retry-blocked-sites --limit 10
python -m app seed-work-queue --task-type all
python -m app run-worker --task-type validate --dry-run
python -m app run-worker --task-type validate --batch-size 50
python -m app run-worker --task-type enrich --batch-size 25
python -m app run-worker --task-type extract_contacts --batch-size 25
python -m app run-worker --task-type retry_blocked --batch-size 10
python -m app run-queue-cycle --seed --dry-run
python -m app run-queue-cycle --seed
python -m app report
```

Or use `main.py`:

```bash
python main.py setup
python main.py normalize --dry-run
python main.py normalize
python main.py enrich-accounts --dry-run --limit 10
python main.py enrich-accounts --limit 25
python main.py enrich-accounts --account-key 1ststatechevy.com
python main.py validate-dealers --dry-run --limit 10
python main.py validate-dealers --account-key 1ststatechevy.com
python main.py extract-contacts --dry-run --limit 10
python main.py extract-contacts --account-key 1ststatechevy.com
python main.py retry-blocked-sites --dry-run --limit 10
python main.py retry-blocked-sites --limit 10
python main.py seed-work-queue --task-type all
python main.py run-worker --task-type validate --dry-run
python main.py run-worker --task-type validate --batch-size 50
python main.py run-worker --task-type enrich --batch-size 25
python main.py run-worker --task-type extract_contacts --batch-size 25
python main.py run-worker --task-type retry_blocked --batch-size 10
python main.py run-queue-cycle --seed --dry-run
python main.py run-queue-cycle --seed
python main.py report
```

## Helper Scripts

Test the BigQuery connection:

```bash
python scripts/test_bigquery_connection.py
```

Check total contacts in the configured source table:

```bash
python scripts/check_contact_count.py
```

Check total unique domains in the configured source table:

```bash
python scripts/check_domain_count.py
```

Create or verify canonical tables:

```bash
python scripts/setup_bigquery_tables.py
```

Run the normalization pipeline:

```bash
python scripts/run_normalization.py normalize --dry-run
python scripts/run_normalization.py normalize
```

Run account enrichment:

```bash
python scripts/enrich_accounts.py enrich-accounts --dry-run --limit 10
python scripts/enrich_accounts.py enrich-accounts --limit 25
python scripts/enrich_accounts.py enrich-accounts --account-key 1ststatechevy.com
```

Run leadership contact extraction:

```bash
python scripts/extract_contacts.py extract-contacts --dry-run --limit 10
python scripts/extract_contacts.py extract-contacts --account-key 1ststatechevy.com
```

Run dealer validation:

```bash
python scripts/validate_dealers.py validate-dealers --dry-run --limit 10
python scripts/validate_dealers.py validate-dealers --account-key 1ststatechevy.com
```

Run blocked-site browser retries:

```bash
python scripts/retry_blocked_sites.py retry-blocked-sites --dry-run --limit 10
python scripts/retry_blocked_sites.py retry-blocked-sites --limit 10
```

Deploy the Cloud Run job:

```powershell
.\scripts\deploy_cloud_run_job.ps1 -ServiceAccountEmail YOUR_SERVICE_ACCOUNT@dealer-contacts-project.iam.gserviceaccount.com
```

Deploy the Cloud Scheduler trigger:

```powershell
.\scripts\deploy_cloud_scheduler_job.ps1 -InvokerServiceAccountEmail YOUR_SERVICE_ACCOUNT@dealer-contacts-project.iam.gserviceaccount.com
```

Print a read-only pipeline report:

```bash
python scripts/report_pipeline_status.py
```

## Queue-Driven Workers

The system can now brute-force the backlog through BigQuery queue rows instead of relying on long Codex sessions.

Queue task types:

- `validate`
- `enrich`
- `extract_contacts`
- `retry_blocked`

Recommended flow:

1. Seed the queue:

```bash
python main.py seed-work-queue --task-type all
```

2. Run small checkpointed worker batches:

```bash
python main.py run-worker --task-type validate --batch-size 50
python main.py run-worker --task-type enrich --batch-size 25
python main.py run-worker --task-type extract_contacts --batch-size 25
python main.py run-worker --task-type retry_blocked --batch-size 10
python main.py report
```

This worker model is designed so Cloud Run jobs can eventually do the brute-force work automatically:

- claim a lease on a small batch of `account_key` rows
- run one pipeline stage
- mark queue items complete or retry
- log the batch in `pipeline_runs`

You can also run one full worker cycle locally:

```bash
python main.py run-queue-cycle --seed
```

That command runs:

1. `validate`
2. `enrich`
3. `extract_contacts`
4. `retry_blocked`

using the environment-configured worker batch sizes.

## Cloud Run Jobs

The project now includes a `Dockerfile` that is ready for Cloud Run Jobs and supports the Playwright browser retry lane.

Build and push the image:

```bash
gcloud builds submit --tag us-central1-docker.pkg.dev/dealer-contacts-project/dealer-contact-system/dealer-contact-system:latest
```

Deploy one queue-cycle job:

```bash
gcloud run jobs deploy dealer-contact-worker ^
  --image us-central1-docker.pkg.dev/dealer-contacts-project/dealer-contact-system/dealer-contact-system:latest ^
  --region us-central1 ^
  --service-account YOUR_SERVICE_ACCOUNT@dealer-contacts-project.iam.gserviceaccount.com ^
  --set-env-vars APP_ENVIRONMENT=cloud,BIGQUERY_PROJECT_ID=dealer-contacts-project,BIGQUERY_DATASET=dealer_data,VALIDATE_WORKER_BATCH_SIZE=50,ENRICH_WORKER_BATCH_SIZE=25,EXTRACT_WORKER_BATCH_SIZE=25,RETRY_BLOCKED_WORKER_BATCH_SIZE=10 ^
  --max-retries 0 ^
  --task-timeout 3600 ^
  --args run-queue-cycle,--seed
```

Run the job manually:

```bash
gcloud run jobs execute dealer-contact-worker --region us-central1
```

Recommended production pattern:

- one Cloud Run Job that runs `run-queue-cycle --seed`
- Cloud Scheduler triggers it every 15 to 30 minutes
- queue workers claim only small batches, so interrupted runs do not lose much progress
- BigQuery remains the checkpointed source of truth for queue state and run logs

Included deployment helpers:

- [scripts/deploy_cloud_run_job.ps1](/C:/Users/brent/OneDrive/Desktop/dealer_contact_system/scripts/deploy_cloud_run_job.ps1)
- [scripts/deploy_cloud_scheduler_job.ps1](/C:/Users/brent/OneDrive/Desktop/dealer_contact_system/scripts/deploy_cloud_scheduler_job.ps1)

## GitHub Migration

To move the project fully off a laptop-centered workflow:

1. Create a GitHub repository for this project.
2. Push this folder as the initial source repository.
3. Add the GitHub secret `GCP_SA_KEY` containing a deployment service-account JSON key.
4. Use the included workflow at `.github/workflows/deploy-cloud-run-job.yml` so pushes to `main` can rebuild and redeploy the Cloud Run Job automatically.

Once that is in place:

- GitHub becomes the source-code home
- Cloud Build / GitHub Actions become the deployment path
- Cloud Run + Scheduler keep the worker running
- your laptop is only a development environment, not the production control plane

## Canonical Tables

The setup command creates:

- `dealer_accounts`
- `prospect_contacts`
- `account_relationships`
- `sync_targets`
- `account_work_queue`
- `pipeline_runs`

The normalization pipeline uses stable SHA256-based IDs to support safe reruns:

- account IDs from normalized `account_key`
- contact IDs from normalized `email`
- relationship IDs from `account_key + email`

The account enrichment pipeline writes best current values directly into validated `dealer` and `dealer_group` rows in `dealer_accounts`, including:

- `website_url`
- `account_name`
- `inferred_brand`
- `account_city`
- `account_state`
- field-level confidence scores
- field-level source URLs
- `last_verified_at`

The fetch tracking layer also records website access outcomes directly into `dealer_accounts`, including:

- `fetch_status`
- `fetch_method`
- `blocked_reason`
- `blocked_attempt_count`
- `last_fetch_attempt_at`
- `last_fetch_success_at`

The dealer validation pipeline writes best current account classifications directly into `dealer_accounts`, including:

- `dealer_classification`
- `dealer_classification_confidence_score`
- `dealer_classification_source_url`

The contact extraction pipeline writes website-derived leadership contacts for validated `dealer` and `dealer_group` accounts into `prospect_contacts` and links them back through `account_relationships`, including:

- `full_name`
- `email`
- `role_type`
- `role_family`
- `role_title`
- `source_url`
- confidence score

## Notes

- SQL is executed in BigQuery using `MERGE` so reruns stay idempotent.
- Website enrichment checks public pages only and does not log in or interact with forms.
- Account enrichment and contact extraction are now scoped to validated `dealer` and `dealer_group` accounts by default.
- When a validated dealer site blocks page reads, the system still keeps the resolved website URL and reports those resolution-only accounts separately.
- Basic HTTP fetch attempts are now tracked so blocked sites can move into a future browser-backed retry queue without using your local IP.
- Browser retries are a separate command so they can later run from cloud infrastructure without using your local IP.
- Contact extraction currently only promotes contacts when a public email, nearby person name, and recognizable leadership title are all present.
- Dealer validation is intentionally conservative and is meant to tighten before broad-scale sync and activation.
- The normalization pipeline is local CLI-first, but organized so it can later move to Cloud Run jobs.
- Crawling, role extraction, validation, Campaign Monitor sync, Airtable sync, and multi-agent orchestration are intentionally deferred.
