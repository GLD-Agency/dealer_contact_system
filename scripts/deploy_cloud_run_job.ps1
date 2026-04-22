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
    [int]$CampaignMonitorSyncBatchSize = 100,
    [bool]$CampaignMonitorSyncEnabled = $true,
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
    "RETRY_BLOCKED_WORKER_BATCH_SIZE=$RetryBlockedBatchSize",
    "CAMPAIGN_MONITOR_SYNC_BATCH_SIZE=$CampaignMonitorSyncBatchSize",
    "CAMPAIGN_MONITOR_SYNC_ENABLED=$($CampaignMonitorSyncEnabled.ToString().ToLower())"
) -join ","

if ($env:CAMPAIGN_MONITOR_API_KEY) {
    $envVars = "$envVars,CAMPAIGN_MONITOR_API_KEY=$($env:CAMPAIGN_MONITOR_API_KEY)"
}
if ($env:CAMPAIGN_MONITOR_CLIENT_ID) {
    $envVars = "$envVars,CAMPAIGN_MONITOR_CLIENT_ID=$($env:CAMPAIGN_MONITOR_CLIENT_ID)"
}
if ($env:CAMPAIGN_MONITOR_MASTER_LIST_NAME) {
    $envVars = "$envVars,CAMPAIGN_MONITOR_MASTER_LIST_NAME=$($env:CAMPAIGN_MONITOR_MASTER_LIST_NAME)"
}
if ($env:MANAGED_FETCH_ENABLED) {
    $envVars = "$envVars,MANAGED_FETCH_ENABLED=$($env:MANAGED_FETCH_ENABLED)"
}
if ($env:MANAGED_FETCH_PROVIDER) {
    $envVars = "$envVars,MANAGED_FETCH_PROVIDER=$($env:MANAGED_FETCH_PROVIDER)"
}
if ($env:MANAGED_FETCH_API_KEY) {
    $envVars = "$envVars,MANAGED_FETCH_API_KEY=$($env:MANAGED_FETCH_API_KEY)"
}
if ($env:CLIENT_DIM_ENABLED) {
    $envVars = "$envVars,CLIENT_DIM_ENABLED=$($env:CLIENT_DIM_ENABLED)"
}
if ($env:GLD_ACCOUNTABILITY_PROJECT_ID) {
    $envVars = "$envVars,GLD_ACCOUNTABILITY_PROJECT_ID=$($env:GLD_ACCOUNTABILITY_PROJECT_ID)"
}
if ($env:CLIENT_DIM_DATASET) {
    $envVars = "$envVars,CLIENT_DIM_DATASET=$($env:CLIENT_DIM_DATASET)"
}
if ($env:CLIENT_DIM_TABLE) {
    $envVars = "$envVars,CLIENT_DIM_TABLE=$($env:CLIENT_DIM_TABLE)"
}

Write-Host "Ensuring Artifact Registry repository exists..."
cmd /c "gcloud artifacts repositories describe $Repository --location=$Region --project=$ProjectId >nul 2>nul"
if ($LASTEXITCODE -ne 0) {
    cmd /c "gcloud artifacts repositories create $Repository --repository-format=docker --location=$Region --description=""Dealer contact system images"" --project=$ProjectId"
}

Write-Host "Building container image..."
cmd /c "gcloud builds submit --tag $imageUri --project=$ProjectId"

Write-Host "Deploying Cloud Run Job..."
cmd /c "gcloud run jobs deploy $JobName --image $imageUri --region $Region --project=$ProjectId --service-account $ServiceAccountEmail --set-env-vars $envVars --max-retries 0 --task-timeout ${TaskTimeoutSeconds}s --args run-queue-cycle,--seed"

Write-Host "Cloud Run Job deployed:"
Write-Host "  Job: $JobName"
Write-Host "  Region: $Region"
Write-Host "  Image: $imageUri"
