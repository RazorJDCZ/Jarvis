param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$JarvisRoot = Split-Path -Parent $PSScriptRoot
$StartupFolder = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupFolder 'Jarvis Assistant.lnk'
if ($Remove) {
    if (Test-Path -LiteralPath $ShortcutPath) { Remove-Item -LiteralPath $ShortcutPath }
    Write-Host 'Inicio automatico desactivado.'
    exit
}
$PythonWindowless = Join-Path $JarvisRoot '.venv\Scripts\pythonw.exe'
$SupervisorScript = Join-Path $PSScriptRoot 'supervise_assistant.py'
$ShellObject = New-Object -ComObject WScript.Shell
$Shortcut = $ShellObject.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonWindowless
$Shortcut.Arguments = '"' + $SupervisorScript + '"'
$Shortcut.WorkingDirectory = $JarvisRoot
$Shortcut.Description = 'Jarvis: inicio y recuperacion automatica al iniciar sesion'
$Shortcut.Save()
Start-Process -FilePath $PythonWindowless -ArgumentList ('"' + $SupervisorScript + '"') -WorkingDirectory $JarvisRoot -WindowStyle Hidden
Write-Host 'Supervisor instalado para este usuario de Windows.'
