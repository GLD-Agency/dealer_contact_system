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
if ($env:MANAGED_FETCH_ENABLED) {
  $envVars += "MANAGED_FETCH_ENABLED=$($env:MANAGED_FETCH_ENABLED)"
}
if ($env:GBP_ENRICHMENT_ENABLED) {
  $envVars += "GBP_ENRICHMENT_ENABLED=$($env:GBP_ENRICHMENT_ENABLED)"
}
if ($env:GBP_PROVIDER) {
  $envVars += "GBP_PROVIDER=$($env:GBP_PROVIDER)"
}
if ($env:MANAGED_FETCH_PROVIDER) {
  $envVars += "MANAGED_FETCH_PROVIDER=$($env:MANAGED_FETCH_PROVIDER)"
}
if ($env:CLIENT_DIM_ENABLED) {
  $envVars += "CLIENT_DIM_ENABLED=$($env:CLIENT_DIM_ENABLED)"
}
if ($env:GLD_ACCOUNTABILITY_PROJECT_ID) {
  $envVars += "GLD_ACCOUNTABILITY_PROJECT_ID=$($env:GLD_ACCOUNTABILITY_PROJECT_ID)"
}
if ($env:CLIENT_DIM_DATASET) {
  $envVars += "CLIENT_DIM_DATASET=$($env:CLIENT_DIM_DATASET)"
}
if ($env:CLIENT_DIM_TABLE) {
  $envVars += "CLIENT_DIM_TABLE=$($env:CLIENT_DIM_TABLE)"
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
