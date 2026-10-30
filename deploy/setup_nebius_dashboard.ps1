$ErrorActionPreference = 'Continue'
Set-Location (Split-Path $PSScriptRoot -Parent)
$project = 'factory-investigator-nebius'
$apiSA = "nebius-dashboard@$project.iam.gserviceaccount.com"
$workerSA = "nebius-investigator@$project.iam.gserviceaccount.com"
function Invoke-GcloudChecked {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw ('gcloud failed: ' + ($args -join ' ')) }
}
Invoke-GcloudChecked services enable firestore.googleapis.com identitytoolkit.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com bigquery.googleapis.com --project=$project
& gcloud iam service-accounts describe $apiSA --project=$project *> $null
if ($LASTEXITCODE -ne 0) { Invoke-GcloudChecked iam service-accounts create nebius-dashboard --project=$project --display-name='Nebius dashboard API' }
& gcloud firestore databases describe '--database=(default)' --project=$project *> $null
if ($LASTEXITCODE -ne 0) { Invoke-GcloudChecked firestore databases create '--database=(default)' --location=asia-south1 --type=firestore-native --project=$project }
Invoke-GcloudChecked projects add-iam-policy-binding $project --member="serviceAccount:$apiSA" --role=roles/datastore.user
Invoke-GcloudChecked projects add-iam-policy-binding $project --member="serviceAccount:$workerSA" --role=roles/datastore.user
Invoke-GcloudChecked projects add-iam-policy-binding $project --member="serviceAccount:$apiSA" --role=roles/bigquery.jobUser
Invoke-GcloudChecked storage buckets add-iam-policy-binding gs://factory-investigator-nebius-assets-126939332706 --member="serviceAccount:$apiSA" --role=roles/storage.objectViewer --project=$project
Write-Host 'API identity and Firestore prepared. Copy historical tables next using your local ADC credentials.'
