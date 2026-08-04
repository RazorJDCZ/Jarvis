param(
    [int]$Port = 0
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvironmentFile = Join-Path $ProjectRoot '.env'
$EnvironmentExample = Join-Path $ProjectRoot '.env.example'

function Find-Tailscale {
    $Command = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($null -ne $Command) {
        return $Command.Source
    }
    $Candidates = @(
        (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\tailscale.exe')
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    return $null
}

function Set-EnvironmentValue {
    param(
        [string]$Name,
        [string]$Value
    )
    $Lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $EnvironmentFile) {
        foreach ($Line in [System.IO.File]::ReadAllLines($EnvironmentFile)) {
            $Lines.Add($Line)
        }
    }
    $Replacement = "$Name=$Value"
    $Found = $false
    for ($Index = 0; $Index -lt $Lines.Count; $Index += 1) {
        if ($Lines[$Index] -match ('^\s*' + [regex]::Escape($Name) + '\s*=')) {
            $Lines[$Index] = $Replacement
            $Found = $true
            break
        }
    }
    if (-not $Found) {
        $Lines.Add($Replacement)
    }
    [System.IO.File]::WriteAllLines($EnvironmentFile, $Lines, [System.Text.UTF8Encoding]::new($false))
}

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    Copy-Item -LiteralPath $EnvironmentExample -Destination $EnvironmentFile
}

$Tailscale = Find-Tailscale
if ($null -eq $Tailscale) {
    throw @'
Tailscale no está instalado. Instálalo desde https://tailscale.com/download/windows,
inicia sesión y vuelve a ejecutar scripts\setup_remote_access.cmd.
'@
}

$StatusText = & $Tailscale status --json
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($StatusText)) {
    throw 'No se pudo consultar Tailscale. Abre Tailscale e inicia sesión.'
}
$Status = $StatusText | ConvertFrom-Json
if ($Status.BackendState -ne 'Running') {
    throw "Tailscale no está conectado (estado: $($Status.BackendState)). Inicia sesión primero."
}

$DnsName = [string]$Status.Self.DNSName
$DnsName = $DnsName.Trim().TrimEnd('.')
if ([string]::IsNullOrWhiteSpace($DnsName)) {
    throw 'Tailscale no entregó un nombre MagicDNS para este equipo.'
}

$LoginName = ''
$UserId = [string]$Status.Self.UserID
if ($null -ne $Status.User) {
    $UserProperty = $Status.User.PSObject.Properties |
        Where-Object { $_.Name -eq $UserId } |
        Select-Object -First 1
    if ($null -ne $UserProperty) {
        $LoginName = [string]$UserProperty.Value.LoginName
    }
}
if ([string]::IsNullOrWhiteSpace($LoginName)) {
    throw 'No se pudo determinar el usuario propietario de Tailscale de forma segura.'
}

if ($Port -le 0) {
    $ConfiguredPort = Get-Content -LiteralPath $EnvironmentFile |
        Where-Object { $_ -match '^\s*JARVIS_PORT\s*=' } |
        Select-Object -Last 1
    if ($ConfiguredPort -match '=\s*(\d+)\s*$') {
        $Port = [int]$Matches[1]
    } else {
        $Port = 8765
    }
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw 'El puerto de Jarvis no es válido.'
}

$RemoteOrigin = "https://$DnsName"
$Backend = "http://127.0.0.1:$Port"

Write-Host 'Configurando enlace HTTPS privado de Tailscale...' -ForegroundColor Cyan
& $Tailscale serve --bg $Backend
if ($LASTEXITCODE -ne 0) {
    throw 'Tailscale Serve no pudo publicar el servicio privado.'
}

Set-EnvironmentValue -Name 'JARVIS_HOST' -Value '127.0.0.1'
Set-EnvironmentValue -Name 'JARVIS_PORT' -Value ([string]$Port)
Set-EnvironmentValue -Name 'JARVIS_REMOTE_ORIGIN' -Value $RemoteOrigin
Set-EnvironmentValue -Name 'JARVIS_REMOTE_ALLOWED_LOGIN' -Value $LoginName
Set-EnvironmentValue -Name 'JARVIS_REMOTE_ACCESS_ENABLED' -Value 'true'

Write-Host ''
Write-Host 'Acceso móvil configurado.' -ForegroundColor Green
Write-Host "URL privada: $RemoteOrigin" -ForegroundColor Cyan
Write-Host "Identidad autorizada: $LoginName" -ForegroundColor DarkCyan
Write-Host 'Reinicia Jarvis con start.cmd para aplicar la configuración.' -ForegroundColor Yellow
Write-Host 'Después abre ACCESO MÓVIL en la PC para generar el código del teléfono.'
