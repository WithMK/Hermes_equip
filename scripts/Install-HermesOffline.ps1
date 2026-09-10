[CmdletBinding()]
param(
    [string]$BundleRoot = "",
    [string]$InstallRoot = "",
    [switch]$Force,
    [switch]$AddToUserPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Assert-LastExitCode([string]$Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

function Copy-Directory([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Required directory is missing: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Destination -Recurse -Force
}

if ($env:OS -ne "Windows_NT") {
    throw "This installer supports Windows only."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "This bundle targets Windows x64 only."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($BundleRoot)) { $BundleRoot = $scriptRoot }
$BundleRoot = [System.IO.Path]::GetFullPath($BundleRoot)
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path $env:LOCALAPPDATA "HermesEquipment"
}
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)

$manifestPath = Join-Path $BundleRoot "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "manifest.json is missing. Extract the complete bundle before installation."
}

Write-Step "Verifying every bundled file against the SHA-256 manifest"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.target -ne "Windows-x64") {
    throw "Unsupported bundle manifest or target: schema=$($manifest.schema_version), target=$($manifest.target)"
}
$safePrefix = $BundleRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$manifestPaths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in $manifest.files) {
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $BundleRoot $entry.path))
    if (-not $candidate.StartsWith($safePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest contains an unsafe path: $($entry.path)"
    }
    [void]$manifestPaths.Add(($entry.path -replace '\\', '/'))
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Bundle file is missing: $($entry.path)"
    }
    $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) {
        throw "SHA-256 mismatch: $($entry.path)"
    }
}
$unexpected = @()
Get-ChildItem -LiteralPath $BundleRoot -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($BundleRoot.Length).TrimStart('\', '/') -replace '\\', '/'
    if ($relative -ne "manifest.json" -and -not $manifestPaths.Contains($relative)) {
        $unexpected += $relative
    }
}
if ($unexpected.Count -gt 0) {
    throw "Bundle contains files not covered by the manifest: $($unexpected -join ', ')"
}

if (Test-Path -LiteralPath $InstallRoot) {
    if (-not $Force) {
        throw "Install root already exists. Use a new -InstallRoot or explicitly use -Force: $InstallRoot"
    }
    if ($InstallRoot -eq [System.IO.Path]::GetPathRoot($InstallRoot) -or $InstallRoot -eq $BundleRoot) {
        throw "Refusing to replace an unsafe install path: $InstallRoot"
    }
    $backup = "$InstallRoot.backup-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
    Move-Item -LiteralPath $InstallRoot -Destination $backup
    Write-Host "Previous installation moved to: $backup" -ForegroundColor Yellow
}
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null

$pythonVersion = [string]$manifest.python_version
$pythonInstaller = Join-Path $BundleRoot "assets\python-$pythonVersion-amd64.exe"
$pythonRoot = Join-Path $InstallRoot "python"
Write-Step "Installing private Python $pythonVersion under the application directory"
$pythonProcess = Start-Process -FilePath $pythonInstaller -ArgumentList @(
    "/quiet", "InstallAllUsers=0", "TargetDir=$pythonRoot", "Include_pip=1",
    "Include_test=0", "Include_launcher=0", "PrependPath=0", "Shortcuts=0"
) -Wait -PassThru
if ($pythonProcess.ExitCode -ne 0) {
    throw "Python installation failed with exit code $($pythonProcess.ExitCode)."
}
$basePython = Join-Path $pythonRoot "python.exe"
if (-not (Test-Path -LiteralPath $basePython)) { throw "Python executable was not installed." }

$gitInstaller = Get-ChildItem -LiteralPath (Join-Path $BundleRoot "assets") -Filter "PortableGit-*-64-bit.7z.exe" -File
if ($gitInstaller.Count -ne 1) { throw "Exactly one PortableGit x64 package is required." }
$gitRoot = Join-Path $InstallRoot "git"
Write-Step "Extracting private PortableGit"
$gitProcess = Start-Process -FilePath $gitInstaller.FullName -ArgumentList @("-o`"$gitRoot`"", "-y") -Wait -PassThru
if ($gitProcess.ExitCode -ne 0) {
    throw "PortableGit extraction failed with exit code $($gitProcess.ExitCode)."
}
$gitExe = Join-Path $gitRoot "cmd\git.exe"
if (-not (Test-Path -LiteralPath $gitExe)) { throw "PortableGit executable was not extracted." }

Write-Step "Creating the Hermes virtual environment"
$venvRoot = Join-Path $InstallRoot "venv"
& $basePython -m venv $venvRoot
Assert-LastExitCode "Virtual environment creation"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$wheelhouse = Join-Path $BundleRoot "wheelhouse"
$hermesVersion = [string]$manifest.hermes.package_version
$pocVersion = [string]$manifest.equipment_poc_version

Write-Step "Installing Hermes and the PoC strictly from the local wheelhouse"
$oldNoIndex = $env:PIP_NO_INDEX
$oldFindLinks = $env:PIP_FIND_LINKS
try {
    $env:PIP_NO_INDEX = "1"
    $env:PIP_FIND_LINKS = $wheelhouse
    & $venvPython -m pip install --disable-pip-version-check --no-index --find-links $wheelhouse `
        "hermes-agent[mcp]==$hermesVersion" "hermes-equipment-poc==$pocVersion"
    Assert-LastExitCode "Offline package installation"
}
finally {
    $env:PIP_NO_INDEX = $oldNoIndex
    $env:PIP_FIND_LINKS = $oldFindLinks
}

Write-Step "Installing the least-privilege plugin, shared skills, and profile templates"
$integration = Join-Path $BundleRoot "integration"
Copy-Directory (Join-Path $integration "plugin\hermes-equipment-platform") `
    (Join-Path $InstallRoot "plugins\hermes-equipment-platform")
Copy-Directory (Join-Path $integration "skills") (Join-Path $InstallRoot "skills")
Copy-Directory (Join-Path $integration "config") (Join-Path $InstallRoot "profile-templates")
Copy-Directory (Join-Path $integration "config\profiles") (Join-Path $InstallRoot "profiles")
Copy-Directory (Join-Path $integration "docs") (Join-Path $InstallRoot "docs")
Copy-Directory (Join-Path $integration "scripts") (Join-Path $InstallRoot "scripts")
Get-ChildItem -LiteralPath (Join-Path $InstallRoot "profiles") -Directory | ForEach-Object {
    Copy-Directory (Join-Path $integration "plugin\hermes-equipment-platform") `
        (Join-Path $_.FullName "plugins\hermes-equipment-platform")
    Copy-Directory (Join-Path $integration "skills") (Join-Path $_.FullName "skills")
    Copy-Item -LiteralPath (Join-Path $integration "config\profile.env.example") `
        -Destination (Join-Path $_.FullName ".env.example") -Force
}
New-Item -ItemType Directory -Path (Join-Path $InstallRoot "approvals") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $InstallRoot "audit") -Force | Out-Null

$binRoot = New-Item -ItemType Directory -Path (Join-Path $InstallRoot "bin") -Force
$launcher = @"
@echo off
set "HERMES_HOME=$InstallRoot"
set "PATH=$gitRoot\cmd;$gitRoot\bin;%PATH%"
"$venvRoot\Scripts\hermes.exe" %*
"@
Set-Content -LiteralPath (Join-Path $binRoot.FullName "hermes-equipment.cmd") -Value $launcher -Encoding ASCII

$shell = @"
`$env:HERMES_HOME = "$InstallRoot"
`$env:PATH = "$gitRoot\cmd;$gitRoot\bin;`$env:PATH"
Write-Host "Hermes Equipment environment is active." -ForegroundColor Green
Write-Host "Launcher: $($binRoot.FullName)\hermes-equipment.cmd"
"@
Set-Content -LiteralPath (Join-Path $binRoot.FullName "Enter-HermesEquipment.ps1") -Value $shell -Encoding UTF8

if ($AddToUserPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($userPath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($parts -notcontains $binRoot.FullName) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $binRoot.FullName) -join ';'), "User")
    }
}

Write-Step "Running offline smoke tests"
$env:HERMES_HOME = $InstallRoot
$env:PATH = "$gitRoot\cmd;$gitRoot\bin;$env:PATH"
& $venvPython -c "import hermes_cli, hermes_equipment_poc; print('Hermes and Equipment PoC imports: OK')"
Assert-LastExitCode "Python import smoke test"
& $venvPython -m pip check
Assert-LastExitCode "Installed dependency check"
& $gitExe --version
Assert-LastExitCode "PortableGit smoke test"

$installation = [ordered]@{
    installed_utc = [DateTime]::UtcNow.ToString("o")
    install_root = $InstallRoot
    hermes_version = $hermesVersion
    hermes_commit = [string]$manifest.hermes.commit
    poc_version = $pocVersion
    python_version = $pythonVersion
    bundle_manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$installation | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $InstallRoot "installation.json") -Encoding UTF8

Write-Host "`nInstallation completed: $InstallRoot" -ForegroundColor Green
Write-Host "1. Edit active profiles under: $InstallRoot\profiles" -ForegroundColor Yellow
Write-Host "2. Set the llama.cpp/GLM, RAG, ContextManager, workspace, audit, and approval paths." -ForegroundColor Yellow
Write-Host "3. Start with: $($binRoot.FullName)\hermes-equipment.cmd -p document-agent" -ForegroundColor Yellow
if (-not $AddToUserPath) {
    Write-Host "The user PATH was not changed. Use -AddToUserPath only if desired." -ForegroundColor DarkGray
}
