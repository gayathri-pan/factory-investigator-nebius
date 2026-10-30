$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$project = 'factory-investigator-nebius'
$bucket = 'factory-investigator-nebius-assets-126939332706'
function Invoke-GcloudChecked {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) {
        throw ('gcloud failed: ' + ($args -join ' '))
    }
}
$files = @(
 'data/nebius/cases.json',
 'data/yearly_experiment_v3/raw/sensors.csv',
 'data/yearly_experiment_v3/raw/maintenance_history.csv',
 'data/yearly_experiment_v3/raw/machine_logs.csv',
 'artifacts/rag/v1/manifest.json',
 'artifacts/rag/v1/manual_points.jsonl.gz',
 'artifacts/rag/v1/embedding_model.tar.gz'
)
foreach ($file in $files) { if (!(Test-Path $file)) { throw "Missing input: $file" } }
# Stop before deployment unless all five input windows pass locally.
& uv run python scripts/run_all_machines.py --cases data/nebius/cases.json
if ($LASTEXITCODE -ne 0) { throw 'Five-machine preflight failed. Inspect execution.log files.' }
foreach ($file in $files) { Invoke-GcloudChecked storage cp $file "gs://$bucket/inputs/$file" --project=$project }
Invoke-GcloudChecked builds submit --config=cloudbuild.nebius.yaml --ignore-file=.gcloudignore-nebius --project=$project
Invoke-GcloudChecked run jobs deploy nebius-investigate-five --project=$project --region=asia-south1 --image="asia-south1-docker.pkg.dev/$project/nebius-investigator/worker:v1" --service-account="nebius-investigator@$project.iam.gserviceaccount.com" --cpu=2 --memory=4Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=10800s --set-env-vars="GOOGLE_CLOUD_PROJECT=$project,NEBIUS_BASE_URL=https://api.tokenfactory.us-central1.nebius.com/v1/,NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b" --set-secrets=NEBIUS_API_KEY=nebius-token-key:latest
Write-Host 'Deployed. Execution is manual; no paid investigation was started by this deployment script.'
