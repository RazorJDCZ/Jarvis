@echo off
setlocal
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0disable_remote_access.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo desactivar el acceso movil.
  pause
  exit /b 1
)
echo.
pause
