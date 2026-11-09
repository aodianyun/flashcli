param(
    [string]$DistDir = "dist\go",
    [string]$OutDir = "dist\windows"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dist = Join-Path $Root $DistDir
$Out = Join-Path $Root $OutDir
$Iss = Join-Path $Root "installer\windows\flashserver.iss"

$VersionLine = Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $VersionLine) { throw "cannot read version from pyproject.toml" }
$Version = $VersionLine.Matches[0].Groups[1].Value

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

$Payload = Join-Path $env:TEMP ("flashserver-installer-payload-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Payload | Out-Null
try {
    Copy-Item $SetupExe (Join-Path $Payload "flashserver-setup-windows-amd64.exe")
    $ClientExe = Join-Path $Root "desktop\target\release\FlashServer.exe"
    if (-not (Test-Path $ClientExe)) {
        throw "missing $ClientExe; run 'cargo build --release' in desktop/ first"
    }
    Copy-Item $ClientExe (Join-Path $Payload "FlashServer.exe")
    foreach ($name in @(
        "flashcli-linux-amd64",
        "flashserver-linux-amd64",
        "flashcli-linux-arm64",
        "flashserver-linux-arm64",
        "sha256sums.txt"
    )) {
        $src = Join-Path $Dist $name
        if (Test-Path $src) { Copy-Item $src (Join-Path $Payload $name) }
    }

    New-Item -ItemType Directory -Force -Path $Out | Out-Null
    & $Iscc.Source "/DAppVersion=$Version" "/DPayloadDir=$Payload" $Iss
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
    Get-ChildItem -Path $Out -Filter "FlashServer-Setup-*.exe" | Select-Object Name, Length
} finally {
    Remove-Item -Recurse -Force $Payload -ErrorAction SilentlyContinue
}
