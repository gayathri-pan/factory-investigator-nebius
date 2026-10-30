$ErrorActionPreference = 'Continue'
Set-Location (Split-Path $PSScriptRoot -Parent)
$project = 'factory-investigator-nebius'
$region = 'asia-south1'
function Invoke-GcloudChecked {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw ('gcloud failed: ' + ($args -join ' ')) }
}
Invoke-GcloudChecked builds submit --config=cloudbuild.nebius-dashboard.yaml --ignore-file=.gcloudignore-nebius-dashboard --project=$project
Invoke-GcloudChecked run jobs deploy nebius-investigate-event --project=$project --region=$region --image="asia-south1-docker.pkg.dev/$project/nebius-investigator/event-worker:v1" --service-account="nebius-investigator@$project.iam.gserviceaccount.com" --cpu=2 --memory=4Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=2400s --set-env-vars="GOOGLE_CLOUD_PROJECT=$project,NEBIUS_BASE_URL=https://api.tokenfactory.us-central1.nebius.com/v1/,NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b" --set-secrets=NEBIUS_API_KEY=nebius-token-key:latest
Invoke-GcloudChecked run jobs add-iam-policy-binding nebius-investigate-event --project=$project --region=$region --member="serviceAccount:nebius-dashboard@$project.iam.gserviceaccount.com" --role=roles/run.jobsExecutorWithOverrides
Invoke-GcloudChecked run deploy nebius-dashboard-api --project=$project --region=$region --image="asia-south1-docker.pkg.dev/$project/nebius-investigator/dashboard:v1" --service-account="nebius-dashboard@$project.iam.gserviceaccount.com" --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=60s --allow-unauthenticated --set-env-vars="GOOGLE_CLOUD_PROJECT=$project,NEBIUS_DAILY_LIMIT=20"
Write-Host 'API deployed. Complete Firebase Google sign-in setup, then deploy hosting using firebase.nebius.json.'
