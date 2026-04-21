param(
    [string]$ProjectId = "dealer-contacts-project",
    [string]$Region = "us-central1",
    [string]$Repository = "dealer-contact-system",
    [string]$ImageName = "dealer-contact-system",
    [string]$JobName = "dealer-contact-worker",
    [string]$ServiceAccountEmail,
    [int]$ValidateBatchSize = 50,
    [int]$EnrichBatchSize = 25,
    [int]$ExtractBatchSize = 25,
    [int]$RetryBlockedBatchSize = 10,
    [int]$TaskTimeoutSeconds = 3600
)

$ErrorActionPreference = "Stop"

if (-not $ServiceAccountEmail) {
    throw "Provide -ServiceAccountEmail for the Cloud Run job."
}

$imageUri = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:latest"
$envVars = @(
    "APP_ENVIRONMENT=cloud",
    "BIGQUERY_PROJECT_ID=$ProjectId",
    "BIGQUERY_DATASET=dealer_data",
    "VALIDATE_WORKER_BATCH_SIZE=$ValidateBatchSize",
    "ENRICH_WORKER_BATCH_SIZE=$EnrichBatchSize",
    "EXTRACT_WORKER_BATCH_SIZE=$ExtractBatchSize",
    "RETRY_BLOCKED_WORKER_BATCH_SIZE=$RetryBlockedBatchSize"
) -join ","

Write-Host "Ensuring Artifact Registry repository exists..."
cmd /c "gcloud artifacts repositories create $Repository --repository-format=docker --location=$Region --description=""Dealer contact system images"" --project=$ProjectId" 2>$null

Write-Host "Building container image..."
cmd /c "gcloud builds submit --tag $imageUri --project=$ProjectId"

Write-Host "Deploying Cloud Run Job..."
cmd /c "gcloud run jobs deploy $JobName --image $imageUri --region $Region --project=$ProjectId --service-account $ServiceAccountEmail --set-env-vars $envVars --max-retries 0 --task-timeout ${TaskTimeoutSeconds}s --args run-queue-cycle,--seed"

Write-Host "Cloud Run Job deployed:"
Write-Host "  Job: $JobName"
Write-Host "  Region: $Region"
Write-Host "  Image: $imageUri"
