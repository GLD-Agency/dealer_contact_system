param(
    [string]$ProjectId = "dealer-contacts-project",
    [string]$Region = "us-central1",
    [string]$Repository = "dealer-contact-system",
    [string]$ImageName = "dealer-contact-system",
    [string]$JobName = "dealer-process-watchdog",
    [string]$ServiceAccountEmail,
    [int]$MainStaleHours = 6,
    [int]$DiscoveryStaleHours = 6,
    [int]$ProspectLeadsStaleHours = 6,
    [int]$SnapshotStaleHours = 8,
    [int]$CampaignMonitorStaleHours = 8,
    [int]$RunningGraceMinutes = 90,
    [bool]$CampaignMonitorSyncEnabled = $true,
    [bool]$ClientDimEnabled = $true,
    [string]$GldAccountabilityProjectId = "productivity-project-491503",
    [string]$ClientDimDataset = "accountability_v1",
    [string]$ClientDimTable = "dim_clients",
    [int]$TaskTimeoutSeconds = 900
)

$ErrorActionPreference = "Stop"

if (-not $ServiceAccountEmail) {
    throw "Provide -ServiceAccountEmail for the process watchdog Cloud Run job."
}

$imageUri = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:latest"
$envVars = @(
    "APP_ENVIRONMENT=cloud",
    "BIGQUERY_PROJECT_ID=$ProjectId",
    "BIGQUERY_DATASET=dealer_data",
    "CLOUD_RUN_JOB_NAME=dealer-contact-worker",
    "DOMAIN_DISCOVERY_JOB_NAME=dealer-domain-discovery-worker",
    "PROCESS_WATCHDOG_ENABLED=true",
    "PROCESS_WATCHDOG_MAIN_STALE_HOURS=$MainStaleHours",
    "PROCESS_WATCHDOG_DISCOVERY_STALE_HOURS=$DiscoveryStaleHours",
    "PROCESS_WATCHDOG_PROSPECT_LEADS_STALE_HOURS=$ProspectLeadsStaleHours",
    "PROCESS_WATCHDOG_SNAPSHOT_STALE_HOURS=$SnapshotStaleHours",
    "PROCESS_WATCHDOG_CAMPAIGN_MONITOR_STALE_HOURS=$CampaignMonitorStaleHours",
    "PROCESS_WATCHDOG_RUNNING_GRACE_MINUTES=$RunningGraceMinutes",
    "CAMPAIGN_MONITOR_SYNC_ENABLED=$($CampaignMonitorSyncEnabled.ToString().ToLower())",
    "CLIENT_DIM_ENABLED=$($ClientDimEnabled.ToString().ToLower())",
    "GLD_ACCOUNTABILITY_PROJECT_ID=$GldAccountabilityProjectId",
    "CLIENT_DIM_DATASET=$ClientDimDataset",
    "CLIENT_DIM_TABLE=$ClientDimTable"
)

$envVarMap = @{}
foreach ($entry in $envVars) {
    if (-not $entry) {
        continue
    }
    $parts = $entry -split "=", 2
    if ($parts.Length -eq 2) {
        $envVarMap[$parts[0]] = $parts[1]
    }
}

$envFile = Join-Path $env:TEMP "dealer-process-watchdog-env.yaml"
$envVarMap.GetEnumerator() |
    Sort-Object Name |
    ForEach-Object {
        $value = [string]$_.Value
        $escaped = $value.Replace("'", "''")
        "$($_.Name): '$escaped'"
    } | Set-Content -Path $envFile -Encoding UTF8

Write-Host "Ensuring Artifact Registry repository exists..."
cmd /c "gcloud artifacts repositories describe $Repository --location=$Region --project=$ProjectId >nul 2>nul"
if ($LASTEXITCODE -ne 0) {
    cmd /c "gcloud artifacts repositories create $Repository --repository-format=docker --location=$Region --description=""Dealer contact system images"" --project=$ProjectId"
}

Write-Host "Building container image..."
cmd /c "gcloud builds submit --tag $imageUri --project=$ProjectId"

Write-Host "Deploying process watchdog Cloud Run job..."
cmd /c "gcloud run jobs deploy $JobName --image $imageUri --region $Region --project=$ProjectId --service-account $ServiceAccountEmail --env-vars-file $envFile --max-retries 0 --task-timeout ${TaskTimeoutSeconds}s --args run-process-watchdog"

Remove-Item -Path $envFile -ErrorAction SilentlyContinue

Write-Host "Process watchdog Cloud Run job deployed:"
Write-Host "  Job: $JobName"
Write-Host "  Region: $Region"
Write-Host "  Image: $imageUri"
