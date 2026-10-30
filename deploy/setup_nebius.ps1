$ErrorActionPreference = 'Continue'
Set-Location (Split-Path $PSScriptRoot -Parent)
$project = 'factory-investigator-nebius'
$region = 'asia-south1'
$bucket = 'factory-investigator-nebius-assets-126939332706'
$sa = "nebius-investigator@$project.iam.gserviceaccount.com"
function Invoke-GcloudChecked {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) {
        throw ('gcloud failed: ' + ($args -join ' '))
    }
}
Invoke-GcloudChecked services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com --project=$project
# For a fresh project: if a resource already exists, verify it rather than deleting it.
& gcloud iam service-accounts describe $sa --project=$project *> $null
if ($LASTEXITCODE -ne 0) { Invoke-GcloudChecked iam service-accounts create nebius-investigator --project=$project --display-name='Nebius investigation job' }
& gcloud artifacts repositories describe nebius-investigator --location=$region --project=$project *> $null
if ($LASTEXITCODE -ne 0) { Invoke-GcloudChecked artifacts repositories create nebius-investigator --repository-format=docker --location=$region --project=$project }
& gcloud storage buckets describe "gs://$bucket" --project=$project *> $null
if ($LASTEXITCODE -ne 0) { Invoke-GcloudChecked storage buckets create "gs://$bucket" --location=$region --uniform-bucket-level-access --project=$project }
Invoke-GcloudChecked storage buckets add-iam-policy-binding "gs://$bucket" --member="serviceAccount:$sa" --role=roles/storage.objectUser --project=$project
& gcloud secrets describe nebius-token-key --project=$project *> $null
if ($LASTEXITCODE -ne 0) { Invoke-GcloudChecked secrets create nebius-token-key --replication-policy=automatic --project=$project }
Invoke-GcloudChecked secrets add-iam-policy-binding nebius-token-key --member="serviceAccount:$sa" --role=roles/secretmanager.secretAccessor --project=$project
Write-Host 'Separate-project resources prepared. Next run deploy/set_nebius_secret.ps1.'
