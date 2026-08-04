$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvironmentFile = Join-Path $ProjectRoot '.env'

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

if (Test-Path -LiteralPath $EnvironmentFile) {
    $Lines = [System.IO.File]::ReadAllLines($EnvironmentFile)
    $Found = $false
    for ($Index = 0; $Index -lt $Lines.Length; $Index += 1) {
        if ($Lines[$Index] -match '^\s*JARVIS_REMOTE_ACCESS_ENABLED\s*=') {
            $Lines[$Index] = 'JARVIS_REMOTE_ACCESS_ENABLED=false'
            $Found = $true
            break
        }
    }
    if (-not $Found) {
        $Lines += 'JARVIS_REMOTE_ACCESS_ENABLED=false'
    }
    [System.IO.File]::WriteAllLines(
        $EnvironmentFile,
        $Lines,
        [System.Text.UTF8Encoding]::new($false)
    )
}

$Tailscale = Find-Tailscale
if ($null -ne $Tailscale) {
    & $Tailscale serve reset
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo restablecer la configuración de Tailscale Serve.'
    }
}

Write-Host 'Acceso móvil desactivado. Reinicia Jarvis para aplicar el cambio.' -ForegroundColor Green
