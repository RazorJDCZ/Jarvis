[CmdletBinding()]
param(
    [switch]$Install
)

$ErrorActionPreference = 'Stop'
$JarvisProject = Split-Path -Parent $PSScriptRoot
$AndroidProject = Join-Path $JarvisProject 'mobile\android'
$SdkRoot = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$Gradle = Join-Path $AndroidProject 'gradlew.bat'
$Apk = Join-Path $AndroidProject 'app\build\outputs\apk\debug\app-debug.apk'
$LocalProperties = Join-Path $AndroidProject 'local.properties'

if (-not (Test-Path -LiteralPath $SdkRoot -PathType Container)) {
    throw 'No se encontró Android SDK. Instálalo desde Android Studio antes de compilar.'
}
if (-not (Test-Path -LiteralPath $LocalProperties -PathType Leaf)) {
    $EscapedSdk = $SdkRoot.Replace('\', '\\').Replace(':', '\:')
    Set-Content -LiteralPath $LocalProperties -Value "sdk.dir=$EscapedSdk" -Encoding Ascii
}

Push-Location $AndroidProject
try {
    & $Gradle ':app:lintDebug' ':app:testDebugUnitTest' ':app:assembleDebug' '--no-daemon'
    if ($LASTEXITCODE -ne 0) { throw 'La compilación Android no terminó correctamente.' }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $Apk -PathType Leaf)) {
    throw 'Gradle terminó sin producir el APK esperado.'
}

Write-Host "APK listo: $Apk" -ForegroundColor Green
if (-not $Install) { return }

$Adb = Join-Path $SdkRoot 'platform-tools\adb.exe'
$Devices = @(& $Adb devices | Select-String "`tdevice$")
if ($Devices.Count -ne 1) {
    throw 'Conecta exactamente un Android con depuración USB autorizada para usar -Install.'
}
& $Adb install -r $Apk
if ($LASTEXITCODE -ne 0) { throw 'ADB no pudo instalar Jarvis en el teléfono.' }
Write-Host 'Jarvis Mobile instalado correctamente.' -ForegroundColor Green
