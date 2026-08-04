param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$PortableOllama = Join-Path $ProjectRoot '.tools\ollama\ollama.exe'
$OllamaModels = Join-Path $ProjectRoot 'models\ollama'
$PortableOllamaRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PortableOllama))
$StartedOllama = $null

function Test-PortableOllamaProcess {
    param($Process)
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace($Process.ExecutablePath)) {
        return $false
    }
    try {
        $ExecutablePath = [IO.Path]::GetFullPath([string]$Process.ExecutablePath)
    } catch {
        return $false
    }
    return $ExecutablePath.Equals($PortableOllama, [StringComparison]::OrdinalIgnoreCase) -or
        $ExecutablePath.StartsWith(
            $PortableOllamaRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
}

function Stop-StalePortableOllamaRunners {
    $Processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $ProcessIds = @{}
    foreach ($Process in $Processes) {
        $ProcessIds[[int]$Process.ProcessId] = $true
    }
    foreach ($Process in $Processes) {
        if (
            $Process.Name -eq 'llama-server.exe' -and
            (Test-PortableOllamaProcess $Process) -and
            -not $ProcessIds.ContainsKey([int]$Process.ParentProcessId)
        ) {
            Stop-Process -Id $Process.ProcessId -ErrorAction SilentlyContinue
        }
    }
}

function Stop-PortableOllamaTree {
    param([int]$RootProcessId)
    $Processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $Descendants = @()
    $Parents = @($RootProcessId)
    while ($Parents.Count -gt 0) {
        $Children = @(
            $Processes | Where-Object {
                $_.ParentProcessId -in $Parents -and (Test-PortableOllamaProcess $_)
            }
        )
        if ($Children.Count -eq 0) {
            break
        }
        $Descendants += $Children
        $Parents = @($Children | ForEach-Object { [int]$_.ProcessId })
    }
    [array]::Reverse($Descendants)
    foreach ($Process in $Descendants) {
        Stop-Process -Id $Process.ProcessId -ErrorAction SilentlyContinue
    }
    $Root = Get-CimInstance Win32_Process -Filter "ProcessId = $RootProcessId" `
        -ErrorAction SilentlyContinue
    if (Test-PortableOllamaProcess $Root) {
        Stop-Process -Id $RootProcessId -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 350
    Stop-StalePortableOllamaRunners
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw 'El entorno no existe. Ejecuta setup.cmd primero.'
}
Set-Location -LiteralPath $ProjectRoot
$ConfigReader = @'
import json
from jarvis.config import Settings
s = Settings()
host = f'[{s.host}]' if ':' in s.host else s.host
print(json.dumps({
    'jarvis_url': f'http://{host}:{s.port}',
    'ollama_url': s.ollama_url,
    'remote_enabled': s.remote_access_enabled,
    'remote_origin': s.remote_origin,
}))
'@
$RuntimeConfigJson = & $VenvPython -c $ConfigReader
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($RuntimeConfigJson)) {
    throw 'No se pudo leer la configuracion de Jarvis.'
}
$RuntimeConfig = $RuntimeConfigJson | ConvertFrom-Json
$JarvisUrl = $RuntimeConfig.jarvis_url
$OllamaUrl = $RuntimeConfig.ollama_url
$RemoteEnabled = [bool]$RuntimeConfig.remote_enabled
$RemoteOrigin = [string]$RuntimeConfig.remote_origin
$PortableOllamaAllowed = $OllamaUrl -in @('http://127.0.0.1:11434', 'http://localhost:11434')
$OllamaReady = $false
try {
    Invoke-WebRequest -Uri "$OllamaUrl/api/tags" -UseBasicParsing -TimeoutSec 1 | Out-Null
    $OllamaReady = $true
} catch {
    $OllamaReady = $false
}

if (-not $OllamaReady -and $PortableOllamaAllowed -and (Test-Path -LiteralPath $PortableOllama)) {
    Stop-StalePortableOllamaRunners
    New-Item -ItemType Directory -Force -Path $OllamaModels | Out-Null
    $env:OLLAMA_MODELS = $OllamaModels
    $StartedOllama = Start-Process `
        -FilePath $PortableOllama `
        -ArgumentList 'serve' `
        -WorkingDirectory (Split-Path -Parent $PortableOllama) `
        -WindowStyle Hidden `
        -PassThru
}

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($Url)
        $Ready = $false
        foreach ($Attempt in 1..40) {
            try {
                Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1 | Out-Null
                $Ready = $true
                break
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
        if ($Ready) {
            Start-Process $Url
        }
    } -ArgumentList $JarvisUrl | Out-Null
}

Write-Host "JARVIS Local Core iniciando en $JarvisUrl" -ForegroundColor Cyan
if ($RemoteEnabled) {
    Write-Host "Enlace móvil privado: $RemoteOrigin" -ForegroundColor DarkCyan
}
Write-Host 'Usa Ctrl+C para detenerlo.' -ForegroundColor DarkGray
try {
    & $VenvPython -m jarvis.main
} finally {
    if ($null -ne $StartedOllama) {
        Stop-PortableOllamaTree -RootProcessId $StartedOllama.Id
    }
}
