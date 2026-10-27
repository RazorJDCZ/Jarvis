# Jarvis Mobile para Pixel 8

La aplicación Android es una carcasa nativa y privada para la misma interfaz de Jarvis. Conserva
el tema Spider Core, las conversaciones, Calendar, adjuntos, notificaciones y las confirmaciones de
seguridad. Además ofrece voz ambiental aun cuando la pantalla de Jarvis no está en primer plano.

Desde la versión 1.3.1, la barra nativa refleja si el enlace está autenticado, bloqueado o sin
conexión. **Mantener pulsado** espera la confirmación real del micrófono antes de aceptar la
soltada, y las sesiones verificadas sobreviven los reinicios normales del núcleo hasta su fecha de
caducidad. Si la sesión vence, la voz se bloquea y pide biometría en lugar de perder la petición.

La passkey usa Credential Manager a través de Android WebView y comprueba la asociación publicada
en `/.well-known/assetlinks.json`. Si se cambia la clave de firma del APK, actualiza
`JARVIS_ANDROID_CERTIFICATE_SHA256` antes de reiniciar Jarvis y distribuir la nueva versión.

## Seguridad del modo ambiental

- Solo se inicia al pulsar **AMBIENTE** mientras la aplicación está visible.
- Android muestra una notificación permanente mientras el micrófono está activo.
- La notificación siempre ofrece **Detener**.
- El audio se envía únicamente al origen HTTPS de Tailscale configurado y reutiliza la sesión
  autenticada de la aplicación.
- El servicio no se inicia después de reiniciar el teléfono y no se publica en Internet.

## Compilar e instalar

Con Android SDK y JDK 17 o 21 instalados, desde PowerShell en la raíz de Jarvis:

```powershell
.\scripts\build_android_app.ps1
```

El APK queda en
`mobile\android\app\build\outputs\apk\debug\app-debug.apk`. Para instalarlo directamente en un
único teléfono conectado y autorizado por depuración USB:

```powershell
.\scripts\build_android_app.ps1 -Install
```

Al abrirla por primera vez, introduce la URL HTTPS que muestra **ACCESO MÓVIL** en Jarvis. Inicia
sesión con la passkey del Pixel igual que en el navegador. Después puedes pulsar **AMBIENTE** y
conceder micrófono y notificaciones.

La aplicación usa `minSdk 29`, `compileSdk 36` y `targetSdk 36`; el Pixel 8 está cubierto.
