param([string]$DestinationRoot = "")

$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path (Split-Path $Project -Parent) "deployment-releases"
}
$DestinationRoot = [IO.Path]::GetFullPath($DestinationRoot)
if ($DestinationRoot -eq $Project -or $DestinationRoot.StartsWith($Project + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release artifacts must be outside the source repository."
}
$Name = "vd10-server-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
$Release = Join-Path $DestinationRoot $Name
$Snapshot = Join-Path $Release "source"
New-Item -ItemType Directory -Path $Snapshot | Out-Null
$Files = @()
$Files += @(Get-ChildItem -LiteralPath $Project -File | Where-Object { $_.Extension -in @(".html", ".js", ".css") })
$Files += Get-Item -LiteralPath (Join-Path $Project ".dockerignore")
$Files += Get-Item -LiteralPath (Join-Path $Project "backend/requirements.txt")
$Files += @(Get-ChildItem -LiteralPath (Join-Path $Project "backend") -Recurse -File -Filter "*.py")
$Files += @(Get-ChildItem -LiteralPath (Join-Path $Project "data") -File -Filter "*.json")
foreach ($Directory in @("knowledge", "schemas")) {
    $Files += @(Get-ChildItem -LiteralPath (Join-Path $Project $Directory) -Recurse -File -Filter "*.json")
}
foreach ($File in @("Dockerfile", "requirements.lock", "compose.json", "compose.https.json", "Caddyfile", "access.caddy.example", "server.env.example", "probe.py", "README.md")) {
    $Files += Get-Item -LiteralPath (Join-Path $PSScriptRoot $File)
}
$Manifest = @()
foreach ($File in @($Files | Sort-Object FullName -Unique)) {
    if ($File.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Do not package links." }
    $Relative = $File.FullName.Substring($Project.Length + 1).Replace("\", "/")
    if ($Relative -match '(^|/)(\.env|server\.env|access\.caddy|\.venv|__pycache__|mqtt_history)(/|$)') {
        throw "Private or runtime path selected: $Relative"
    }
    $Target = Join-Path $Snapshot $Relative
    New-Item -ItemType Directory -Path (Split-Path $Target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Target
    $SourceHash = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
    if ($SourceHash -ne (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash) { throw "Source snapshot changed during packaging." }
    $Manifest += [pscustomobject]@{ path = $Relative; sha256 = $SourceHash }
}
$SafeDirectory = "safe.directory=" + $Project.Replace("\", "/")
$Revision = & git -c $SafeDirectory -C $Project rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Cannot identify source revision." }
$Status = @(& git -c $SafeDirectory -C $Project status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Cannot inspect source state." }
$Record = [pscustomobject]@{
    release = $Name
    createdAt = (Get-Date).ToString("o")
    baseRevision = $Revision
    workingTreeDirty = ($Status.Count -gt 0)
    purpose = "Internal staging candidate. MQTT disabled; no real credentials included. Not an approved production release."
    files = $Manifest
}
$Utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $Snapshot "release-manifest.json"), ($Record | ConvertTo-Json -Depth 5), $Utf8)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = Join-Path $Release ($Name + ".zip")
[IO.Compression.ZipFile]::CreateFromDirectory($Snapshot, $Archive)
$Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
try {
    $Names = @($Zip.Entries | ForEach-Object { $_.FullName })
    if ($Names.Count -ne ($Manifest.Count + 1)) { throw "Unexpected archive entry count." }
    if ($Names -notcontains ".dockerignore" -or $Names -notcontains "deploy/compose.json") { throw "Archive is incomplete." }
    foreach ($Path in $Names) {
        if ($Path.Contains("\") -or $Path.StartsWith("/") -or $Path.Split("/") -contains "..") { throw "Nonportable archive path." }
        if ($Path -match '(^|/)(\.env|server\.env|access\.caddy|\.venv|__pycache__|mqtt_history)(/|$)') { throw "Private archive entry detected." }
    }
} finally { $Zip.Dispose() }
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($Archive + ".sha256"), "$Hash  $Name.zip`n", $Utf8)
Write-Output "Release archive: $Archive"
Write-Output "SHA256: $Hash"
Write-Output "Verified source files: $($Manifest.Count)"
Write-Output "Source is a working-tree candidate, not a committed production release."
