param(
    [switch]$SkipClient,
    [switch]$SkipGo,
    [string]$OutDir = "dist\windows",
    [string]$GoBin = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GoDist = Join-Path $Root "dist\go"
$Installer = Join-Path $Root "scripts\build_windows_installer.ps1"
$ClientExe = Join-Path $Root "desktop\target\release\FlashServer.exe"

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
$LdFlags = "-s -w -X github.com/aodianyun/flashcli/go/internal/version.Version=$Version"

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "missing '$Name' on PATH; $Hint"
    }
}

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) { $env:PATH = "$cargoBin;$env:PATH" }

if ($GoBin) {
    if (-not (Test-Path (Join-Path $GoBin "go.exe"))) { throw "go.exe not found in -GoBin $GoBin" }
    $env:PATH = "$GoBin;$env:PATH"
}
if (-not (Get-Command "go" -ErrorAction SilentlyContinue)) {
    $goCandidates = @(
        (Join-Path $env:ProgramFiles "Go\bin"),
        (Join-Path $env:LOCALAPPDATA "Programs\Go\bin"),
        "C:\Go\bin",
        (Join-Path $env:USERPROFILE "scoop\apps\go\current\bin")
    )
    foreach ($dir in $goCandidates) {
        if ($dir -and (Test-Path (Join-Path $dir "go.exe"))) {
            $env:PATH = "$dir;$env:PATH"
            break
        }
    }
}

Write-Host "flashcli Windows package $Version"

if (-not $SkipClient) {
    Require-Command "cargo" "install the Rust MSVC toolchain (rustup default stable-x86_64-pc-windows-msvc)"
    Write-Host "[1/3] desktop client ..."
    $runningClient = Get-Process FlashServer -ErrorAction SilentlyContinue
    if ($runningClient) {
        Write-Host "stopping running FlashServer client ..."
        $runningClient | Stop-Process -Force
        Start-Sleep -Milliseconds 400
    }
    Push-Location (Join-Path $Root "desktop")
    try {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & cargo build --release
            $code = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previous
        }
        if ($code -ne 0) { throw "cargo build --release failed (exit $code)" }
    }
    finally {
        Pop-Location
    }
}
if (-not (Test-Path $ClientExe)) {
    throw "missing $ClientExe; run without -SkipClient"
}
$bytes = [System.IO.File]::ReadAllBytes($ClientExe)
$peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
$subsystem = [BitConverter]::ToUInt16($bytes, $peOffset + 24 + 68)
if ($subsystem -ne 2) {
    throw "desktop client subsystem is $subsystem; expected 2 (Windows GUI). Rebuild the release client."
}

if (-not $SkipGo) {
    Require-Command "go" "install Go >= 1.24"
    Write-Host "[2/3] Go assets ..."
    New-Item -ItemType Directory -Force -Path $GoDist | Out-Null

    function Build-Go([string]$GOOS, [string]$GOARCH, [string]$Cmd, [string]$OutName) {
        $prev = @{ GOOS = $env:GOOS; GOARCH = $env:GOARCH; CGO_ENABLED = $env:CGO_ENABLED }
        try {
            $env:CGO_ENABLED = "0"
            $env:GOOS = $GOOS
            $env:GOARCH = $GOARCH
            Push-Location (Join-Path $Root "go")
            try {
                $previous = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                try {
                    & go build -trimpath -ldflags $LdFlags -o (Join-Path $GoDist $OutName) ".\cmd\$Cmd"
                    $code = $LASTEXITCODE
                }
                finally {
                    $ErrorActionPreference = $previous
                }
                if ($code -ne 0) { throw "go build $Cmd ($GOOS/$GOARCH) failed (exit $code)" }
            }
            finally {
                Pop-Location
            }
        }
        finally {
            $env:GOOS = $prev.GOOS
            $env:GOARCH = $prev.GOARCH
            $env:CGO_ENABLED = $prev.CGO_ENABLED
        }
    }

    foreach ($arch in @("amd64", "arm64")) {
        Build-Go "linux" $arch "flashcli" "flashcli-linux-$arch"
        Build-Go "linux" $arch "flashserver" "flashserver-linux-$arch"
        Build-Go "linux" $arch "flashserver-setup" "flashserver-setup-linux-$arch"
    }
    Build-Go "windows" "amd64" "flashserver-setup" "flashserver-setup-windows-amd64.exe"

    $assets = @(
        "flashcli-linux-amd64",
        "flashcli-linux-arm64",
        "flashserver-linux-amd64",
        "flashserver-linux-arm64",
        "flashserver-setup-linux-amd64",
        "flashserver-setup-linux-arm64",
        "flashserver-setup-windows-amd64.exe"
    )
    $lines = foreach ($name in $assets) {
        $path = Join-Path $GoDist $name
        if (-not (Test-Path $path)) { throw "missing build output $path" }
        $hash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
        "$hash  $name"
    }
    [System.IO.File]::WriteAllText((Join-Path $GoDist "sha256sums.txt"), ($lines -join "`n") + "`n")
}
else {
    Write-Host "[2/3] Go assets skipped"
}

if (-not (Test-Path $Installer)) { throw "missing $Installer" }
Write-Host "[3/3] Windows installer ..."
& $Installer -DistDir "dist\go" -OutDir $OutDir

$setup = Get-ChildItem (Join-Path $Root $OutDir) -Filter "FlashServer-Setup-$Version.exe" -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "installer output not found in $OutDir" }

$hash = (Get-FileHash $setup.FullName -Algorithm SHA256).Hash
Write-Host ""
Write-Host "Package: $($setup.FullName)"
Write-Host "Size:    $($setup.Length) bytes"
Write-Host "SHA256:  $hash"
exit 0
