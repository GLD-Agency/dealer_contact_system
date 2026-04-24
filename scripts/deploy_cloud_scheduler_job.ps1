param(
    [string]$ProjectId = "dealer-contacts-project",
    [string]$Region = "us-central1",
    [string]$JobName = "dealer-contact-worker",
    [string]$SchedulerName = "dealer-contact-worker-schedule",
    [string]$Schedule = "*/30 * * * *",
    [string]$InvokerServiceAccountEmail
)

$ErrorActionPreference = "Stop"

if (-not $InvokerServiceAccountEmail) {
    throw "Provide -InvokerServiceAccountEmail for Cloud Scheduler OAuth."
}

$uri = "https://run.googleapis.com/v2/projects/$ProjectId/locations/$Region/jobs/${JobName}:run"

Write-Host "Deploying Cloud Scheduler trigger..."
$existingJob = cmd /c "gcloud scheduler jobs describe $SchedulerName --location $Region --project=$ProjectId" 2>$null

if ($LASTEXITCODE -eq 0 -and $existingJob) {
    cmd /c "gcloud scheduler jobs update http $SchedulerName --location $Region --project=$ProjectId --schedule ""$Schedule"" --http-method POST --uri $uri --oauth-service-account-email $InvokerServiceAccountEmail --oauth-token-scope https://www.googleapis.com/auth/cloud-platform"
} else {
    cmd /c "gcloud scheduler jobs create http $SchedulerName --location $Region --project=$ProjectId --schedule ""$Schedule"" --http-method POST --uri $uri --oauth-service-account-email $InvokerServiceAccountEmail --oauth-token-scope https://www.googleapis.com/auth/cloud-platform"
}
