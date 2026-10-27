# Jarvis Desktop

Jarvis Desktop es una envoltura Tauri/WebView2 para la interfaz local existente. No contiene ni
copia credenciales, tokens, memoria, correo o calendario. La fuente de verdad sigue siendo el
servicio de Jarvis en `127.0.0.1:8765`, por lo que el navegador, la aplicación de Windows y el
cliente Android comparten exactamente los mismos conectores y datos.

Al abrir `Jarvis.exe`, la pantalla nativa comprueba `/api/health`. Si el núcleo no responde, inicia
`scripts/supervise_assistant.py` con el Python de `.venv` y espera hasta tres minutos. El supervisor
mantiene el servicio vivo aunque la ventana se oculte o se cierre. El acceso de inicio de Windows
continúa siendo `Jarvis Assistant.lnk` en la carpeta Startup.

La ventana permite únicamente navegación interna hacia `http://127.0.0.1:8765` o
`http://localhost:8765`. Las ventanas nuevas y enlaces externos se entregan al navegador
predeterminado; esto permite completar OAuth sin alojar páginas externas dentro de Jarvis. El IPC
de Tauri sólo está habilitado en la pantalla empaquetada de arranque, no en la página HTTP.

## Construcción

```powershell
.\scripts\build_desktop_app.ps1
```

El script ejecuta formato, Clippy, pruebas Rust y compilación release. Después copia el resultado a
`%USERPROFILE%\Desktop\Jarvis.exe`. Si ya existe uno, guarda primero una copia en
`.data\desktop-backups`.

## Cierre y uso de recursos

La X no decide el cierre automáticamente. Muestra una confirmación con tres resultados seguros:

- **No** cierra la interfaz y el WebView, pero conserva el núcleo en segundo plano. Gmail,
  automatizaciones y el acceso desde el celular continúan funcionando con un consumo menor que la
  interfaz abierta.
- **Sí** solicita un cierre ordenado del servidor, espera a que terminen sus servicios y cierra
  también el supervisor. El celular queda desconectado hasta volver a abrir `Jarvis.exe` o iniciar
  una nueva sesión de Windows.
- **Cancelar** vuelve a la aplicación sin cambiar ningún proceso.

El menú de la bandeja conserva además una opción para ocultar solamente la ventana. Ninguna de
estas opciones detiene Tailscale ni modifica cuentas, credenciales o datos personales.
