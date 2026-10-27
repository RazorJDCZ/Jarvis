param(
    [switch]$SkipChecks,
    [switch]$NoDeploy
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TauriRoot = Join-Path $ProjectRoot 'desktop\src-tauri'
$BuiltExecutable = Join-Path $TauriRoot 'target\release\jarvis-desktop.exe'
$DesktopExecutable = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis.exe'

Push-Location $TauriRoot
try {
    if (-not $SkipChecks) {
        cargo fmt --check
        if ($LASTEXITCODE -ne 0) { throw 'cargo fmt detectó errores.' }
        cargo clippy --release -- -D warnings
        if ($LASTEXITCODE -ne 0) { throw 'cargo clippy detectó errores.' }
        cargo test
        if ($LASTEXITCODE -ne 0) { throw 'Las pruebas Rust fallaron.' }
    }
    cargo build --release
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo compilar Jarvis Desktop.' }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $BuiltExecutable)) {
    throw "No se generó el ejecutable esperado: $BuiltExecutable"
}

if (-not $NoDeploy) {
    if (Test-Path -LiteralPath $DesktopExecutable) {
        $BackupRoot = Join-Path $ProjectRoot '.data\desktop-backups'
        New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
        $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item -LiteralPath $DesktopExecutable -Destination (Join-Path $BackupRoot "Jarvis-$Stamp.exe")
    }
    Copy-Item -LiteralPath $BuiltExecutable -Destination $DesktopExecutable -Force
}

$Hash = Get-FileHash -LiteralPath $BuiltExecutable -Algorithm SHA256
[pscustomobject]@{
    BuiltExecutable = $BuiltExecutable
    DesktopExecutable = if ($NoDeploy) { $null } else { $DesktopExecutable }
    Sha256 = $Hash.Hash
    SizeBytes = (Get-Item -LiteralPath $BuiltExecutable).Length
} | ConvertTo-Json -Compress
