param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$PortableOllama = Join-Path $ProjectRoot '.tools\ollama\ollama.exe'
$OllamaModels = Join-Path $ProjectRoot 'models\ollama'
$StartedOllama = $null

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw 'El entorno no existe. Ejecuta setup.cmd primero.'
}
Set-Location -LiteralPath $ProjectRoot
$ConfigReader = @'
import json
from jarvis.config import Settings
s = Settings()
host = f'[{s.host}]' if ':' in s.host else s.host
print(json.dumps({'jarvis_url': f'http://{host}:{s.port}', 'ollama_url': s.ollama_url}))
'@
$RuntimeConfigJson = & $VenvPython -c $ConfigReader
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($RuntimeConfigJson)) {
    throw 'No se pudo leer la configuracion de Jarvis.'
}
$RuntimeConfig = $RuntimeConfigJson | ConvertFrom-Json
$JarvisUrl = $RuntimeConfig.jarvis_url
$OllamaUrl = $RuntimeConfig.ollama_url
$PortableOllamaAllowed = $OllamaUrl -in @('http://127.0.0.1:11434', 'http://localhost:11434')
$OllamaReady = $false
try {
    Invoke-WebRequest -Uri "$OllamaUrl/api/tags" -UseBasicParsing -TimeoutSec 1 | Out-Null
    $OllamaReady = $true
} catch {
    $OllamaReady = $false
}

if (-not $OllamaReady -and $PortableOllamaAllowed -and (Test-Path -LiteralPath $PortableOllama)) {
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
Write-Host 'Usa Ctrl+C para detenerlo.' -ForegroundColor DarkGray
try {
    & $VenvPython -m jarvis.main
} finally {
    if ($null -ne $StartedOllama -and -not $StartedOllama.HasExited) {
        Stop-Process -Id $StartedOllama.Id
    }
}
