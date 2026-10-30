$ErrorActionPreference = 'Stop'
$secret = Read-Host 'Paste Nebius API key (hidden)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
$tempPath = [IO.Path]::GetTempFileName()
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    [IO.File]::WriteAllText($tempPath, $plain, [Text.UTF8Encoding]::new($false))
    & gcloud secrets versions add nebius-token-key --data-file=$tempPath --project=factory-investigator-nebius
    if ($LASTEXITCODE -ne 0) { throw 'Secret upload failed.' }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $plain = $null
    Remove-Item $tempPath -Force
}
