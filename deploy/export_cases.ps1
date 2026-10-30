$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force data/nebius | Out-Null
$sql = ((Get-Content deploy/select_test_cases.sql) |
    Where-Object { $_ -notmatch '^\s*--' }) -join "`n"
$sql = $sql.Trim()
$rows = $sql | & bq --project_id=factory-investigator-nebius --location=asia-south1 --format=json query --use_legacy_sql=false --max_rows=5
if ($LASTEXITCODE -ne 0) {
    $rows | Out-Host
    throw 'BigQuery export failed; no cases were saved.'
}
$joined = $rows -join "`n"
$parsed = ConvertFrom-Json $joined
if (@($parsed).Count -ne 5) { throw 'Expected five flagged windows; inspect the query result.' }
[IO.File]::WriteAllText((Join-Path $PWD 'data/nebius/cases.json'), $joined, [Text.UTF8Encoding]::new($false))
Write-Host 'Saved data/nebius/cases.json (read-only source query).'
