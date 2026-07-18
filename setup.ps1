param(
    [switch]$SkipVoice,
    [switch]$SkipPiperModel,
    [switch]$SkipWhisperModel
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$VoiceDirectory = Join-Path $ProjectRoot 'models\piper'
$VoiceModel = Join-Path $VoiceDirectory 'es_ES-sharvard-medium.onnx'
$VoiceConfig = Join-Path $VoiceDirectory 'es_ES-sharvard-medium.onnx.json'
$VoiceModelPartial = "$VoiceModel.part"
$VoiceConfigPartial = "$VoiceConfig.part"
$WhisperDirectory = Join-Path $ProjectRoot 'models\whisper\small'
$WhisperModel = Join-Path $WhisperDirectory 'model.bin'

Set-Location -LiteralPath $ProjectRoot

Write-Host '[1/4] Preparando entorno virtual de Python 3.12...' -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & py -3.12 -m venv (Join-Path $ProjectRoot '.venv')
}

Write-Host '[2/4] Instalando dependencias dentro de .venv...' -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
if ($SkipVoice) {
    & $VenvPython -m pip install -e '.[actions,dev]'
} else {
    & $VenvPython -m pip install -e '.[voice,actions,dev]'
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot '.env.example') -Destination (Join-Path $ProjectRoot '.env')
}

Write-Host '[3/4] Comprobando voz Piper...' -ForegroundColor Cyan
if (-not $SkipVoice -and -not $SkipPiperModel) {
    New-Item -ItemType Directory -Force -Path $VoiceDirectory | Out-Null
    if (-not (Test-Path -LiteralPath $VoiceModel)) {
        Write-Host 'Descargando modelo de voz es_ES-sharvard-medium (aprox. 77 MB)...'
        Invoke-WebRequest `
            -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx?download=true' `
            -OutFile $VoiceModelPartial
        Move-Item -LiteralPath $VoiceModelPartial -Destination $VoiceModel
    }
    if (-not (Test-Path -LiteralPath $VoiceConfig)) {
        Invoke-WebRequest `
            -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx.json?download=true' `
            -OutFile $VoiceConfigPartial
        Move-Item -LiteralPath $VoiceConfigPartial -Destination $VoiceConfig
    }
} else {
    Write-Host 'Piper omitido. Jarvis usara una voz instalada en Windows.' -ForegroundColor Yellow
}

if (-not $SkipVoice -and -not $SkipWhisperModel -and -not (Test-Path -LiteralPath $WhisperModel)) {
    Write-Host 'Descargando Faster Whisper small dentro del proyecto (aprox. 464 MB)...'
    New-Item -ItemType Directory -Force -Path $WhisperDirectory | Out-Null
    & $VenvPython -c "from faster_whisper.utils import download_model; download_model('small', output_dir=r'$WhisperDirectory')"
}

Write-Host '[4/4] Comprobando Ollama...' -ForegroundColor Cyan
if ((Get-Command ollama -ErrorAction SilentlyContinue) -or (Test-Path -LiteralPath (Join-Path $ProjectRoot '.tools\ollama\ollama.exe'))) {
    Write-Host 'Ollama detectado.' -ForegroundColor Green
} else {
    Write-Host 'Ollama no esta instalado. La interfaz funcionara con el nucleo de respaldo.' -ForegroundColor Yellow
    Write-Host 'Para conversacion completa ejecuta: scripts\install_ollama.cmd'
}

Write-Host ''
Write-Host 'Entorno listo. Ejecuta start.cmd para iniciar Jarvis.' -ForegroundColor Green
