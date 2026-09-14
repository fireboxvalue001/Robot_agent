$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceEnv = Join-Path $projectRoot "..\..\asr_app\backend\.env"
$targetEnv = Join-Path $projectRoot "backend\.env"
$allowedNames = @(
    "TENCENTCLOUD_SECRET_ID",
    "TENCENTCLOUD_SECRET_KEY",
    "TENCENT_ASR_ENGINE",
    "TENCENTCLOUD_REGION"
)

if (-not (Test-Path -LiteralPath $sourceEnv)) {
    throw "Reference ASR environment file was not found."
}
if (Test-Path -LiteralPath $targetEnv) {
    Write-Output "backend/.env already exists; no credentials were overwritten."
    exit 0
}

$allowedPattern = "^\s*(" + (($allowedNames | ForEach-Object { [regex]::Escape($_) }) -join "|") + ")\s*="
$selectedLines = Get-Content -LiteralPath $sourceEnv |
    Where-Object { $_ -match $allowedPattern }

if (-not ($selectedLines | Where-Object { $_ -match "^\s*TENCENTCLOUD_SECRET_ID\s*=" }) -or
    -not ($selectedLines | Where-Object { $_ -match "^\s*TENCENTCLOUD_SECRET_KEY\s*=" })) {
    throw "Tencent Cloud credentials were not found in the reference .env file."
}

[System.IO.File]::WriteAllLines(
    $targetEnv,
    [string[]]$selectedLines,
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "Tencent ASR settings were migrated to backend/.env without printing their values."
