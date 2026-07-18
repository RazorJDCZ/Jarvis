$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$OllamaDirectory = Join-Path $ProjectRoot '.tools\ollama'
$OllamaExe = Join-Path $OllamaDirectory 'ollama.exe'
$DownloadsDirectory = Join-Path $ProjectRoot '.data\downloads'
$ArchivePath = Join-Path $DownloadsDirectory 'ollama-windows-amd64.zip'
$ModelsDirectory = Join-Path $ProjectRoot 'models\ollama'
$OllamaProcess = $null

New-Item -ItemType Directory -Force -Path $DownloadsDirectory, $OllamaDirectory, $ModelsDirectory | Out-Null

if (-not (Test-Path -LiteralPath $OllamaExe)) {
    Write-Host 'Descargando Ollama portable oficial para Windows...' -ForegroundColor Cyan
    & curl.exe `
        --fail `
        --location `
        --retry 3 `
        --output $ArchivePath `
        'https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip'
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo descargar Ollama.'
    }
    Write-Host 'Extrayendo Ollama dentro de .tools...' -ForegroundColor Cyan
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $OllamaDirectory -Force
    Remove-Item -LiteralPath $ArchivePath -Force
}
if (-not (Test-Path -LiteralPath $OllamaExe)) {
    throw "No se encontro ollama.exe despues de extraer el paquete: $OllamaExe"
}

$env:OLLAMA_MODELS = $ModelsDirectory
$ServerReady = $false
try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 1 | Out-Null
    $ServerReady = $true
} catch {
    $ServerReady = $false
}

if (-not $ServerReady) {
    $OllamaProcess = Start-Process `
        -FilePath $OllamaExe `
        -ArgumentList 'serve' `
        -WorkingDirectory $OllamaDirectory `
        -WindowStyle Hidden `
        -PassThru
    foreach ($Attempt in 1..60) {
        try {
            Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 1 | Out-Null
            $ServerReady = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
}

if (-not $ServerReady) {
    if ($null -ne $OllamaProcess -and -not $OllamaProcess.HasExited) {
        Stop-Process -Id $OllamaProcess.Id
    }
    throw 'Ollama no inicio correctamente.'
}

try {
    Write-Host 'Descargando Qwen 3.5 4B (aprox. 3.4 GB)...' -ForegroundColor Cyan
    & $OllamaExe pull 'qwen3.5:4b'
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo descargar qwen3.5:4b.'
    }
    Write-Host 'Ollama y Qwen estan listos dentro del proyecto.' -ForegroundColor Green
} finally {
    if ($null -ne $OllamaProcess -and -not $OllamaProcess.HasExited) {
        Stop-Process -Id $OllamaProcess.Id
    }
}
