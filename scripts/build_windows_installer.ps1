param(
    [string]$DistDir = "dist\go",
    [string]$OutDir = "dist\windows"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dist = Join-Path $Root $DistDir
$Out = Join-Path $Root $OutDir
$Iss = Join-Path $Root "installer\windows\flashcli-desktop.iss"

$VersionLine = Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $VersionLine) { throw "cannot read version from pyproject.toml" }
$Version = $VersionLine.Matches[0].Groups[1].Value
$CargoLine = Select-String -Path (Join-Path $Root "desktop\Cargo.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $CargoLine) { throw "cannot read version from desktop/Cargo.toml" }
$CargoVersion = $CargoLine.Matches[0].Groups[1].Value
$PyShortVersion = (($Version -split '\.')[0..2] -join '.')
if ($CargoVersion -ne $PyShortVersion) {
    throw "desktop/Cargo.toml version $CargoVersion != pyproject version prefix $PyShortVersion; bump both before packaging"
}

$SetupExe = Join-Path $Dist "flashserver-setup-windows-amd64.exe"
if (-not (Test-Path $SetupExe)) {
    throw "missing $SetupExe; run scripts/build_go.sh first"
}

$Iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if (-not $Iscc) {
    $Candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $Candidates) {
        if (Test-Path $c) { $Iscc = Get-Command $c; break }
    }
}
if (-not $Iscc) {
    throw "Inno Setup 6 (ISCC.exe) not found; install from https://jrsoftware.org/isinfo.php"
}

$Payload = Join-Path $env:TEMP ("flashcli-desktop-installer-payload-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Payload | Out-Null
try {
    Copy-Item $SetupExe (Join-Path $Payload "flashserver-setup-windows-amd64.exe")
    $ClientExe = Join-Path $Root "desktop\target\release\flashcli-desktop.exe"
    if (-not (Test-Path $ClientExe)) {
        throw "missing $ClientExe; run 'cargo build --release' in desktop/ first"
    }
    Copy-Item $ClientExe (Join-Path $Payload "flashcli-desktop.exe")
    # Only amd64 Linux binaries are shipped: the installer is x64-only
    # (ArchitecturesAllowed=x64) and WSL2 on x64 Windows is amd64. Preserve the
    # project build checksums so Setup can verify this bundled payload locally.
    $ChecksumsPath = Join-Path $Dist "sha256sums.txt"
    if (-not (Test-Path -LiteralPath $ChecksumsPath)) {
        throw "missing $ChecksumsPath; build the release assets with scripts/build_go.sh first"
    }
    $ChecksumEntries = @{}
    foreach ($line in Get-Content -LiteralPath $ChecksumsPath) {
        if ($line -match '^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
            $ChecksumEntries[$Matches[2]] = $Matches[1].ToLowerInvariant()
        }
    }
    $PayloadChecksums = @()
    foreach ($name in @(
        "flashcli-linux-amd64",
        "flashserver-linux-amd64"
    )) {
        $src = Join-Path $Dist $name
        if (-not (Test-Path -LiteralPath $src)) { throw "missing Linux payload $src" }
        if (-not $ChecksumEntries.ContainsKey($name)) { throw "$name is missing from $ChecksumsPath" }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $src).Hash.ToLowerInvariant()
        if ($actual -ne $ChecksumEntries[$name]) {
            throw "$name SHA-256 mismatch: got $actual, expected $($ChecksumEntries[$name]) from $ChecksumsPath"
        }
        Copy-Item -LiteralPath $src -Destination (Join-Path $Payload $name)
        $PayloadChecksums += "$actual  $name"
    }
    [IO.File]::WriteAllLines((Join-Path $Payload "sha256sums.txt"), $PayloadChecksums, [Text.Encoding]::ASCII)

    # Bundle the protocol package source so bundle venvs do not need GitHub.
    $BundleSrc = Join-Path $Root "flashcli-bundle"
    if (-not (Test-Path (Join-Path $BundleSrc "pyproject.toml"))) {
        throw "missing $BundleSrc; run from the repository root"
    }
    $BundleStage = Join-Path $Payload "flashcli-bundle"
    New-Item -ItemType Directory -Force -Path $BundleStage | Out-Null
    Copy-Item (Join-Path $BundleSrc "pyproject.toml") $BundleStage
    Copy-Item (Join-Path $BundleSrc "README.md") $BundleStage
    Copy-Item (Join-Path $BundleSrc "src") (Join-Path $BundleStage "src") -Recurse
    Remove-Item (Join-Path $BundleStage "src\flashcli_bundle.egg-info") -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $BundleStage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem $BundleStage -Recurse -File -Filter "*.pyc" | Remove-Item -Force
    $Tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $Tar) { throw "tar.exe not found; Windows 10 1803+ or bsdtar is required to package flashcli-bundle" }
    & $Tar.Source -czf (Join-Path $Payload "flashcli-bundle.tar.gz") -C $Payload "flashcli-bundle"
    if ($LASTEXITCODE -ne 0) { throw "tar.exe failed with exit code $LASTEXITCODE" }
    Remove-Item $BundleStage -Recurse -Force

    New-Item -ItemType Directory -Force -Path $Out | Out-Null
    & $Iscc.Source "/DAppVersion=$Version" "/DPayloadDir=$Payload" $Iss
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
    Get-ChildItem -Path $Out -Filter "flashcli-desktop-setup-windows-amd64-v*.exe" | Select-Object Name, Length
} finally {
    Remove-Item -Recurse -Force $Payload -ErrorAction SilentlyContinue
}
