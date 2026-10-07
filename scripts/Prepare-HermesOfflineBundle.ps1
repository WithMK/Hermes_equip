[CmdletBinding()]
param(
    [string]$OutputRoot = "",
    [string]$PocRoot = "",
    [string]$HermesRepository = "https://github.com/NousResearch/hermes-agent.git",
    [string]$HermesTag = "v2026.9.7",
    [string]$HermesCommit = "2237be355906fbe6065ce1815711eee52b2d646e",
    [string]$HermesPackageVersion = "0.21.1",
    [string]$PythonVersion = "3.11.9",
    [string]$PortableGitTag = "v2.54.0.windows.1",
    [string]$PortableGitVersion = "2.54.0",
    [switch]$Force
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

function Get-SafeFullPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "Path must not be empty." }
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ValidAuthenticodeSignature([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Downloaded executable has no valid Authenticode signature: $Path ($($signature.Status))"
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
    throw "This bundle must be prepared on an internet-connected Windows x64 PC."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Only Windows x64 is supported by this PoC bundle."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($PocRoot)) {
    $PocRoot = Join-Path $scriptRoot ".."
}
$PocRoot = Get-SafeFullPath $PocRoot
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path (Split-Path -Parent $PocRoot) "HermesEquipmentOfflineBundle"
}
$OutputRoot = Get-SafeFullPath $OutputRoot
$zipPath = "$OutputRoot.zip"

if ((Test-Path -LiteralPath $OutputRoot) -or (Test-Path -LiteralPath $zipPath)) {
    if (-not $Force) {
        throw "Output already exists. Choose another -OutputRoot or explicitly use -Force: $OutputRoot"
    }
    if ($OutputRoot -eq [System.IO.Path]::GetPathRoot($OutputRoot) -or $OutputRoot -eq $PocRoot) {
        throw "Refusing to remove an unsafe output path: $OutputRoot"
    }
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath (Join-Path $PocRoot "pyproject.toml"))) {
    throw "PoC root is invalid: $PocRoot"
}
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    throw "Git for Windows is required on the bundle preparation PC."
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$assets = New-Item -ItemType Directory -Path (Join-Path $OutputRoot "assets") -Force
$wheelhouse = New-Item -ItemType Directory -Path (Join-Path $OutputRoot "wheelhouse") -Force
$integration = New-Item -ItemType Directory -Path (Join-Path $OutputRoot "integration") -Force
$notices = New-Item -ItemType Directory -Path (Join-Path $OutputRoot "notices") -Force
$workRoot = Join-Path $env:TEMP ("hermes-offline-build-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

try {
    $pythonInstallerName = "python-$PythonVersion-amd64.exe"
    $pythonInstaller = Join-Path $assets.FullName $pythonInstallerName
    $pythonUrl = "https://www.python.org/ftp/python/$PythonVersion/$pythonInstallerName"
    Write-Step "Downloading Python $PythonVersion x64"
    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller -UseBasicParsing
    Assert-ValidAuthenticodeSignature $pythonInstaller

    $gitAssetName = "PortableGit-$PortableGitVersion-64-bit.7z.exe"
    $gitAsset = Join-Path $assets.FullName $gitAssetName
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/$PortableGitTag/$gitAssetName"
    Write-Step "Downloading PortableGit $PortableGitVersion x64"
    Invoke-WebRequest -Uri $gitUrl -OutFile $gitAsset -UseBasicParsing
    Assert-ValidAuthenticodeSignature $gitAsset

    Write-Step "Installing a private Python used only to build and validate the bundle"
    $builderPythonRoot = Join-Path $workRoot "python"
    $pythonProcess = Start-Process -FilePath $pythonInstaller -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "TargetDir=$builderPythonRoot", "Include_pip=1",
        "Include_test=0", "Include_launcher=0", "PrependPath=0", "Shortcuts=0"
    ) -Wait -PassThru
    if ($pythonProcess.ExitCode -ne 0) {
        throw "Private Python installation failed with exit code $($pythonProcess.ExitCode)."
    }
    $builderPython = Join-Path $builderPythonRoot "python.exe"
    if (-not (Test-Path -LiteralPath $builderPython)) {
        throw "Private Python executable was not created: $builderPython"
    }

    Write-Step "Checking out the pinned Hermes source"
    $hermesSource = Join-Path $workRoot "hermes-agent"
    & git.exe clone --quiet --no-checkout $HermesRepository $hermesSource
    Assert-LastExitCode "Hermes clone"
    & git.exe -C $hermesSource checkout --quiet $HermesCommit
    Assert-LastExitCode "Hermes checkout"
    $resolvedCommit = (& git.exe -C $hermesSource rev-parse HEAD).Trim()
    Assert-LastExitCode "Hermes revision check"
    if ($resolvedCommit -ne $HermesCommit) {
        throw "Hermes commit mismatch. Expected $HermesCommit, got $resolvedCommit."
    }
    $tagCommit = (& git.exe -C $hermesSource rev-list -n 1 $HermesTag).Trim()
    Assert-LastExitCode "Hermes tag check"
    if ($tagCommit -ne $HermesCommit) {
        throw "Hermes tag $HermesTag does not resolve to the pinned commit."
    }

    Write-Step "Building the Windows CPython 3.11 wheelhouse (Hermes Core + MCP)"
    & $builderPython -m pip install --disable-pip-version-check --upgrade "pip<26" "setuptools==83.0.0" wheel
    Assert-LastExitCode "Build tooling installation"
    $hermesRequirement = "${hermesSource}[mcp]"
    & $builderPython -m pip wheel --disable-pip-version-check --wheel-dir $wheelhouse.FullName --only-binary=:all: $hermesRequirement
    Assert-LastExitCode "Hermes wheelhouse build"
    & $builderPython -m pip wheel --disable-pip-version-check --wheel-dir $wheelhouse.FullName --no-deps $PocRoot
    Assert-LastExitCode "PoC wheel build"

    $nonWheels = Get-ChildItem -LiteralPath $wheelhouse.FullName -File | Where-Object Extension -ne ".whl"
    if ($nonWheels) {
        throw "Wheelhouse contains non-wheel packages: $($nonWheels.Name -join ', ')"
    }

    Write-Step "Validating that installation succeeds with network access disabled"
    $verifyVenv = Join-Path $workRoot "verify-venv"
    & $builderPython -m venv $verifyVenv
    Assert-LastExitCode "Validation venv creation"
    $verifyPython = Join-Path $verifyVenv "Scripts\python.exe"
    & $verifyPython -m pip install --disable-pip-version-check --no-index --find-links $wheelhouse.FullName `
        "hermes-agent[mcp]==$HermesPackageVersion" "hermes-equipment-poc[web]==0.4.0"
    Assert-LastExitCode "Offline validation installation"
    & $verifyPython -c "import hermes_cli, hermes_equipment_poc; print('Offline import validation: OK')"
    Assert-LastExitCode "Offline import validation"
    & $verifyPython -m pip check
    Assert-LastExitCode "Offline dependency validation"

    Write-Step "Copying PoC integration files"
    Copy-Directory (Join-Path $PocRoot "plugin") (Join-Path $integration.FullName "plugin")
    Copy-Directory (Join-Path $PocRoot "skills") (Join-Path $integration.FullName "skills")
    Copy-Directory (Join-Path $PocRoot "config") (Join-Path $integration.FullName "config")
    Copy-Directory (Join-Path $PocRoot "docs") (Join-Path $integration.FullName "docs")
    $testScripts = Join-Path $integration.FullName "scripts"
    New-Item -ItemType Directory -Path $testScripts -Force | Out-Null
    Get-ChildItem -LiteralPath $scriptRoot -Filter "Test-*.ps1" -File | Copy-Item -Destination $testScripts -Force
    Copy-Item -LiteralPath (Join-Path $scriptRoot "Install-HermesOffline.ps1") -Destination $OutputRoot -Force
    Copy-Item -LiteralPath (Join-Path $PocRoot "README.md") -Destination (Join-Path $integration.FullName "README-PoC.md") -Force
    Copy-Item -LiteralPath (Join-Path $hermesSource "LICENSE") -Destination (Join-Path $notices.FullName "HERMES-LICENSE") -Force

    $sourceRef = @"
Hermes upstream: $HermesRepository
Tag: $HermesTag
Commit: $HermesCommit
Python package: hermes-agent==$HermesPackageVersion
Extras included: mcp
Prepared (UTC): $([DateTime]::UtcNow.ToString("o"))
"@
    Set-Content -LiteralPath (Join-Path $notices.FullName "HERMES-SOURCE-REF.txt") -Value $sourceRef -Encoding UTF8

    $readme = @"
# Hermes Equipment Offline Bundle

This bundle installs the pinned Hermes runtime, MCP support, and the Hermes Equipment PoC
integration without accessing the internet. It intentionally excludes browser, unrestricted
terminal, cron, Home Assistant, and other optional integrations.

Run in Windows PowerShell on the closed-network PC:

    Set-ExecutionPolicy -Scope Process Bypass
    .\Install-HermesOffline.ps1

After installation, edit the copied profile templates before starting a profile. See:
`integration\docs\OFFLINE_INSTALL.md`.
"@
    Set-Content -LiteralPath (Join-Path $OutputRoot "README-OFFLINE.md") -Value $readme -Encoding UTF8

    Write-Step "Generating SHA-256 manifest"
    $manifestFiles = @()
    Get-ChildItem -LiteralPath $OutputRoot -File -Recurse | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($OutputRoot.Length).TrimStart('\', '/') -replace '\\', '/'
        $manifestFiles += [ordered]@{
            path = $relative
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $manifest = [ordered]@{
        schema_version = 1
        bundle_name = "HermesEquipmentOfflineBundle"
        created_utc = [DateTime]::UtcNow.ToString("o")
        target = "Windows-x64"
        python_version = $PythonVersion
        hermes = [ordered]@{ tag = $HermesTag; commit = $HermesCommit; package_version = $HermesPackageVersion; extras = @("mcp") }
        equipment_poc_version = "0.4.0"
        files = $manifestFiles
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputRoot "manifest.json") -Encoding UTF8

    Write-Step "Creating transfer ZIP"
    Compress-Archive -Path (Join-Path $OutputRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$zipPath.sha256" -Value "$zipHash  $([System.IO.Path]::GetFileName($zipPath))" -Encoding ASCII
    Write-Host "Bundle directory: $OutputRoot" -ForegroundColor Green
    Write-Host "Transfer ZIP:     $zipPath" -ForegroundColor Green
    Write-Host "Checksum file:    $zipPath.sha256" -ForegroundColor Green
    Write-Host "ZIP SHA-256:      $zipHash" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
