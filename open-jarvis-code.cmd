@echo off
setlocal

set "JARVIS_CODE_EXE=%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
if not exist "%JARVIS_CODE_EXE%" (
  echo No se encontro Visual Studio Code en la ubicacion esperada.
  pause
  exit /b 1
)

start "" "%JARVIS_CODE_EXE%" --new-window ^
  --disable-extension oracle.oracle-java ^
  --disable-extension redhat.java ^
  --disable-extension vscjava.vscode-gradle ^
  --disable-extension vscjava.vscode-java-debug ^
  --disable-extension vscjava.vscode-java-dependency ^
  --disable-extension vscjava.vscode-java-test ^
  --disable-extension vscjava.vscode-maven ^
  "%~dp0"

endlocal
