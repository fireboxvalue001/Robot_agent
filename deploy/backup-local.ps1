param(
    [string]$DestinationRoot = ""
)

$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path (Split-Path $Project -Parent) "deployment-backups"
}
$DestinationRoot = [IO.Path]::GetFullPath($DestinationRoot)
if ($DestinationRoot.StartsWith($Project + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $DestinationRoot -eq $Project) {
    throw "Keep the backup outside the project repository."
}
$SafeDirectory = "safe.directory=" + $Project.Replace("\", "/")
$Files = @(& git -c $SafeDirectory -C $Project -c core.quotepath=false ls-files --cached --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw "Cannot enumerate project files." }
$Revision = & git -c $SafeDirectory -C $Project rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Cannot identify the source revision." }
$Backup = Join-Path $DestinationRoot ((Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $Backup | Out-Null

# The backup can contain credentials; only its owner and local administrators may read it.
$Acl = Get-Acl -LiteralPath $Backup
$Acl.SetAccessRuleProtection($true, $false)
$CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$Inheritance = [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
$Propagation = [Security.AccessControl.PropagationFlags]::None
foreach ($Sid in @($CurrentSid, [Security.Principal.SecurityIdentifier]::new("S-1-5-18"), [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544"))) {
    $Rule = [Security.AccessControl.FileSystemAccessRule]::new($Sid, "FullControl", $Inheritance, $Propagation, "Allow")
    $Acl.AddAccessRule($Rule)
}
Set-Acl -LiteralPath $Backup -AclObject $Acl

$PrivateFiles = @(".env", "backend/.env")
$History = Join-Path $Project "data/mqtt_history"
if (Test-Path -LiteralPath $History) {
    $PrivateFiles += @(Get-ChildItem -LiteralPath $History -File -Filter "*.jsonl" | ForEach-Object { "data/mqtt_history/" + $_.Name })
}
$Manifest = @()
foreach ($Relative in @($Files + $PrivateFiles | Sort-Object -Unique)) {
    $Source = [IO.Path]::GetFullPath((Join-Path $Project $Relative))
    if (-not $Source.StartsWith($Project + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Source path escaped the repository."
    }
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { continue }
    $Target = Join-Path (Join-Path $Backup "snapshot") $Relative
    New-Item -ItemType Directory -Path (Split-Path $Target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Target
    $SourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
    $BackupHash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
    if ($SourceHash -ne $BackupHash) { throw "Backup verification failed; do not treat this backup as complete." }
    $Manifest += [pscustomobject]@{ path = $Relative; sha256 = $BackupHash }
}
$Record = [pscustomobject]@{
    createdAt = (Get-Date).ToString("o")
    revision = $Revision
    complete = $true
    note = "Source/config/history only. No virtual environment. Files were verified individually; not a transactional snapshot of a live writer."
    files = $Manifest
}
$Record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Backup "manifest.json") -Encoding UTF8
Write-Output "Verified backup: $Backup"
Write-Output "Files verified: $($Manifest.Count)"
Write-Output "Private config included only when present; do not upload this backup."
