# Acceso móvil privado

Jarvis 0.6.0 expone su PWA únicamente dentro de la red privada de Tailscale. El proceso de Python
continúa escuchando en `127.0.0.1`; no se abre un puerto del router, no se activa Tailscale Funnel y
no existe un listener en la LAN.

Para uso personal, [el plan Personal de Tailscale](https://tailscale.com/pricing) es gratuito y
admite dispositivos de usuario ilimitados; Jarvis no necesita ninguna API de pago.

## Arquitectura de confianza

Una solicitud remota debe superar las dos capas:

1. **Tailscale Serve** termina HTTPS y aporta la identidad autenticada del usuario mediante
   cabeceras que elimina y vuelve a crear en el proxy local.
2. **Passkey de Jarvis** comprueba el teléfono con WebAuthn y verificación de usuario obligatoria
   (rostro, huella o PIN administrado por el sistema operativo).

Jarvis fija la primera identidad autorizada en SQLite, o usa
`JARVIS_REMOTE_ALLOWED_LOGIN` cuando el script puede obtenerla. Las cookies de sesión son
`HttpOnly`, `Secure` y `SameSite=Strict`; su contenido es aleatorio y solo se conserva un hash en
memoria. Al reiniciar Jarvis hay que volver a usar la passkey, pero no repetir el emparejamiento.
Las claves privadas nunca llegan a Jarvis.

Referencias técnicas:

- [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve)
- [Cabeceras de identidad de Tailscale](https://tailscale.com/kb/1312/serve)
- [Web Authentication API y passkeys](https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API)

## Activación

Requisitos:

- Tailscale instalado, conectado y con MagicDNS disponible.
- El mismo tailnet accesible desde la PC y el teléfono.
- Chrome, Edge o Safari moderno en el teléfono.

Con Jarvis detenido, ejecuta:

```text
scripts\setup_remote_access.cmd
```

El script:

- detecta el ejecutable y el usuario de Tailscale;
- publica `http://127.0.0.1:8765` mediante HTTPS privado con Tailscale Serve;
- conserva `JARVIS_HOST=127.0.0.1`;
- escribe el origen HTTPS y la identidad permitida en `.env`.

Después inicia `start.cmd`, abre **ACCESO MÓVIL** en la interfaz local y pulsa **GENERAR CÓDIGO DE
EMPAREJAMIENTO**. El código dura cinco minutos, admite como máximo cinco intentos fallidos y se
invalida al crear la passkey.

En el teléfono abre la URL `https://<equipo>.<tailnet>.ts.net`, escribe un nombre identificable y
el código. Confirma la passkey con el mecanismo que ofrezca el teléfono. En visitas posteriores,
el botón **DESBLOQUEAR CON BIOMETRÍA** renueva la sesión sin usar otro código.

## Política de acciones remotas

- Consultar el volumen, estado del sistema, monitores, ventanas, pestañas o texto visible mantiene
  riesgo de lectura.
- Abrir una aplicación, navegar, escribir, hacer clic o modificar el PC se eleva al menos a riesgo
  medio y exige confirmación explícita desde el teléfono.
- Las acciones ya clasificadas como altas o bloqueadas conservan su nivel.
- Cada teléfono recibe un espacio de sesión distinto aunque reutilice el mismo identificador del
  navegador.
- Las órdenes remotas guardan únicamente tipo de acción y resultado en
  `.data/remote-access.sqlite3`; no se registra la frase dictada.
- `/api/actions/audit` solo está disponible desde la consola local.

El botón rojo **DETENER JARVIS** interrumpe el audio del navegador, desactiva manos libres y cancela
confirmaciones, flujos o diálogos pendientes de esa sesión. Una acción corta que el sistema
operativo ya terminó no puede deshacerse; por eso toda mutación remota se confirma antes.

## Revocación y apagado

En la PC, abre **ACCESO MÓVIL** y pulsa **REVOCAR** junto al teléfono. Su passkey queda inutilizable
de inmediato y las sesiones activas dejan de autenticar.

Para desactivar el canal completo:

```text
scripts\disable_remote_access.cmd
```

Esto ejecuta `tailscale serve reset` y cambia `JARVIS_REMOTE_ACCESS_ENABLED=false`. Reinicia Jarvis
para aplicar el cambio. La base de dispositivos queda local para auditoría; eliminarla no es
necesario para cerrar el acceso.

## Diagnóstico

- **Tailscale no está instalado:** usa el instalador oficial de Windows, inicia sesión y vuelve a
  ejecutar el script.
- **La URL no abre en el teléfono:** comprueba que Tailscale esté conectado en ambos equipos y que
  pertenezcan al mismo tailnet.
- **La sesión expiró:** pulsa **DESBLOQUEAR CON BIOMETRÍA**. Es normal después de reiniciar Jarvis.
- **El dispositivo fue revocado o cambió de navegador:** genera un código nuevo desde la PC.
- **Jarvis está apagado:** Tailscale puede conservar la URL, pero el proxy responderá sin backend;
  `start.cmd` debe estar ejecutándose para realizar acciones.
