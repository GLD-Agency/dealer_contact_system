param(
  [string]$ProjectId = "dealer-contacts-project",
  [string]$Region = "us-central1",
  [string]$Repository = "dealer-contact-system",
  [string]$ImageName = "dealer-contact-dashboard",
  [string]$ServiceName = "dealer-contact-dashboard",
  [Parameter(Mandatory = $true)]
  [string]$ServiceAccountEmail
)

$imageUri = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:latest"
$envVars = @(
  "APP_ENVIRONMENT=cloud"
  "BIGQUERY_PROJECT_ID=$ProjectId"
  "BIGQUERY_DATASET=dealer_data"
)

if ($env:CAMPAIGN_MONITOR_API_KEY) {
  $envVars += "CAMPAIGN_MONITOR_API_KEY=$($env:CAMPAIGN_MONITOR_API_KEY)"
}
if ($env:CAMPAIGN_MONITOR_CLIENT_ID) {
  $envVars += "CAMPAIGN_MONITOR_CLIENT_ID=$($env:CAMPAIGN_MONITOR_CLIENT_ID)"
}
if ($env:META_ACCESS_TOKEN) {
  $envVars += "META_ACCESS_TOKEN=$($env:META_ACCESS_TOKEN)"
}
if ($env:META_AD_ACCOUNT_ID) {
  $envVars += "META_AD_ACCOUNT_ID=$($env:META_AD_ACCOUNT_ID)"
}
if ($env:GOOGLE_ADS_DEVELOPER_TOKEN) {
  $envVars += "GOOGLE_ADS_DEVELOPER_TOKEN=$($env:GOOGLE_ADS_DEVELOPER_TOKEN)"
}
if ($env:GOOGLE_ADS_CUSTOMER_ID) {
  $envVars += "GOOGLE_ADS_CUSTOMER_ID=$($env:GOOGLE_ADS_CUSTOMER_ID)"
}

gcloud builds submit `
  --project $ProjectId `
  --config cloudbuild.dashboard.yaml

gcloud run deploy $ServiceName `
  --image $imageUri `
  --region $Region `
  --project $ProjectId `
  --service-account $ServiceAccountEmail `
  --allow-unauthenticated `
  --port 8080 `
  --set-env-vars ($envVars -join ",")
