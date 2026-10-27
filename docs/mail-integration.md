# Correos Pendientes: Gmail, universidad y Appa

Jarvis descarga mensajes mediante Gmail API y Microsoft Graph, prepara resúmenes con
`gpt-5.6-luna` mediante la sesión de Codex y guarda el resultado en `.data/mail.sqlite3`. La
sección **Correos Pendientes** de Appa consulta
ese registro local. La configuración se abre desde **Conectar o administrar cuentas** en Appa,
o desde [Correos de Jarvis](http://127.0.0.1:8765/mail), en la PC.

## Activar tus cuentas

Los proveedores requieren registrar una aplicación OAuth antes de mostrar su pantalla de inicio
de sesión. La instalación no incluye un cliente compartido ni utiliza tus contraseñas de correo.
Este paso y el consentimiento de cada cuenta requieren tu sesión de Google/Microsoft.

### Gmail personal

1. En [Google Cloud](https://console.cloud.google.com/), crea o selecciona un proyecto y habilita
   **Gmail API**.
2. Configura **Google Auth Platform / Pantalla de consentimiento OAuth** para tu aplicación
   personal. Jarvis solicita `https://www.googleapis.com/auth/gmail.readonly` y
   `https://www.googleapis.com/auth/gmail.send`. El segundo permiso solo habilita las respuestas
   que autorices explícitamente; no permite borrar ni modificar mensajes.
3. Si la aplicación está en modo de pruebas, añade tu Gmail a los usuarios de prueba.
4. Crea un cliente OAuth de tipo **Aplicación de escritorio** y descarga su JSON.
5. En la página local de Jarvis, abre **Configurar la conexión por primera vez**, importa el JSON
   y pulsa **Guardar conexión de Gmail**. Después pulsa **Conectar Gmail** y autoriza la cuenta
   en Google.

Si Gmail ya estaba conectado antes de incorporar respuestas, desconecta y vuelve a conectar cada
cuenta una vez para conceder `gmail.send`. Appa muestra **Reconecta Gmail** mientras falte.

Google limita la duración de autorizaciones de aplicaciones externas en modo de pruebas. Si el
permiso deja de renovarse, Jarvis muestra el error de cuenta y permite volver a conectarla;
publicar una aplicación con acceso a Gmail puede requerir verificación del proveedor.
Consulta [OAuth para escritorio](https://developers.google.com/identity/protocols/oauth2/native-app)
y [permisos de Gmail](https://developers.google.com/workspace/gmail/api/auth/scopes).

### Universidad en Outlook / Microsoft 365

1. En [Microsoft Entra](https://entra.microsoft.com/), registra una aplicación compatible con
   cuentas organizativas y cuentas Microsoft personales.
2. En **Autenticación → Agregar plataforma → Aplicaciones móviles y de escritorio**, registra
   `http://localhost/callback`. Jarvis utiliza un puerto local libre para cada inicio de sesión.
3. Añade permisos **delegados** de Microsoft Graph: `Mail.Read` y `User.Read`. Jarvis solicita
   también `offline_access` para renovar la sesión. No añadas permisos de aplicación, escritura
   ni envío, y no crees un secreto de cliente para Microsoft.
4. Copia el **ID de aplicación (cliente)** al formulario local de Microsoft en Jarvis, guarda
   y pulsa **Conectar universidad · Microsoft 365**.
5. Inicia sesión con tu cuenta universitaria. Si la universidad exige consentimiento administrativo
   o impide registrar aplicaciones, su administrador debe habilitar esta integración. Jarvis
   no puede concederse ese acceso.

Referencias: [OAuth con PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
y [permisos delegados](https://learn.microsoft.com/en-us/graph/permissions-reference).

## Uso

- Cada conversación muestra cuenta, remitente, asunto, fecha, extracto o resumen, prioridad
  sugerida, cita que la justifica y fecha límite textual si existe.
- Estados: **Por revisar**, **Por responder**, **Esperando respuesta**, **Resuelto**. También
  puedes posponer 24 horas y ver los elementos pospuestos por separado.
- Un nuevo mensaje en un hilo vuelve a abrirlo para revisión. La sincronización repetida de un
  mismo mensaje conserva tus estados, posposición y borrador.
- **Crear tarea** muestra una confirmación y usa el puente autenticado existente de Appa.
  La tarea incluye resumen y enlace; no se inventa una fecha de vencimiento. Una clave persistente
  evita duplicados si se repite la solicitud o se pierde una respuesta del puente.
- **Buscar** consulta asunto, remitente, resumen de Luna y contenido en la copia SQLite; no exige
  que todas las palabras coincidan. Expande temas comunes, pondera prioridad y recencia, y permite
  pedir “más recientes” o “más importantes”. No vuelve a descargar el buzón ni añade todo el correo
  al contexto de Codex.
- **Preparar borrador** usa `gpt-5.6-luna`. Puedes editarlo, guardarlo y copiarlo.
- **Revisar y autorizar envío** está disponible solo para Gmail. Appa muestra cuenta,
  destinatario y texto completo, liga una autorización de dos minutos al correo, versión y texto
  exactos, y exige un segundo clic en **Enviar ahora**. Cambiar el texto, recibir otro mensaje o
  reutilizar la autorización detiene el envío.
- Por voz o chat puedes pedir **«Responde al correo de profesor diciendo …»**. Jarvis resuelve un
  único hilo y repite destinatario, asunto y texto antes de pedir la confirmación de riesgo alto.
  Outlook permanece en modo lectura.
- Puedes decir o escribir **«Resume mis correos pendientes»** o **«¿Qué correos tengo pendientes?»**.
  El resumen diario de Jarvis también incorpora los correos conectados.

La primera revisión incluye la bandeja de entrada de los últimos 30 días. Gmail se descarga en
grupos de 20 conversaciones, a un ritmo aproximado de una conversación por segundo y con una
pausa entre grupos. El token de página y el avance se guardan en SQLite, de modo que un reinicio
continúa el recorrido en vez de comenzar de nuevo. Si Gmail devuelve un límite temporal, Jarvis
aplica espera exponencial y conserva el avance. Los errores de cuota se distinguen de los errores
reales de autorización.

Después se revisan mensajes nuevos cada cinco minutos, con cinco minutos de solapamiento para
evitar huecos. La vista muestra hasta 500 conversaciones.
Se guarda el último mensaje recibido de cada conversación, no un archivo completo del buzón.
En Gmail, los mensajes enviados y los borradores propios no reabren el pendiente.
Los adjuntos y recursos remotos de HTML no se descargan. Archivar o borrar un correo en el
proveedor no elimina automáticamente un pendiente de Appa: márcalo resuelto cuando corresponda.

## Rendimiento y datos

La consulta desde el teléfono lee la copia ya preparada; no espera una revisión del proveedor.
El modelo resume de uno en uno tras 45 segundos sin peticiones de conversación. Una petición de
texto o voz interrumpe ese análisis en segundo plano para dar paso al usuario. Si Codex falla queda
un extracto identificado como tal
y se vuelve a intentar el resumen tras un intervalo de diez minutos.
El borrador se genera solo cuando lo pides.

Los tokens OAuth y las configuraciones de clientes se cifran con Windows DPAPI para el usuario
actual. El contenido del correo y sus resúmenes se guardan en SQLite local, sin cifrado adicional;
el directorio `.data` está excluido de Git. El asunto, remitente, fecha y hasta 10 000 caracteres
del mensaje se envían a OpenAI para resumir o redactar. El modelo no recibe tokens ni herramientas.
Los correos
se tratan como contenido no confiable: sus instrucciones no autorizan acciones.
Las fechas y justificaciones citadas se validan como texto presente en el mensaje. Los resúmenes
siguen siendo generados por IA y deben contrastarse con el original cuando importen los detalles.

El envío no se reintenta automáticamente si Gmail recibe el mensaje pero se pierde la respuesta
de red, para evitar duplicados. En ese caso Jarvis pide revisar **Enviados** antes de intentarlo de
nuevo. Cada versión entrante admite como máximo una respuesta desde Jarvis; un mensaje nuevo en el
hilo vuelve a habilitarla.

Appa hace solicitudes nativas únicamente a `127.0.0.1:8765/api/mail` mediante operaciones
permitidas; nunca recibe tokens de Google/Microsoft. Requiere Jarvis encendido en el puerto
predeterminado. El teléfono conserva la autenticación existente de Tailscale y passkey; conectar
cuentas y modificar pendientes requiere la consola local.

**Desconectar** borra credenciales, contenido y resúmenes de esa cuenta del registro local.
No borra las tareas creadas en Appa ni revoca automáticamente el permiso en el proveedor;
puedes revocarlo desde la administración de aplicaciones de Google o Microsoft.

## Verificación y despliegue

Pruebas nuevas: aislamiento de cuentas, duplicados, reapertura por mensaje nuevo, cifrado DPAPI,
HTML sin ejecución, paginación gradual y continuación tras reiniciar, espera ante cuotas,
distinción de permisos y límites, rechazo de enlaces de paginación ajenos al proveedor,
OAuth con estado/PKCE y callback local, renovación de tokens, errores de sincronización,
validación de citas, prioridad de conversación y tareas idempotentes.
También se prueban búsqueda literal, permiso `gmail.send`, destinatario verificado, autorización
de dos pasos ligada al contenido, bloqueo de versiones antiguas y ausencia de reintentos de envío.

`scripts/smoke_mail_ui.py` comprueba Appa compilada y la API de Jarvis con datos sintéticos:
crear tarea, editar/guardar borrador, posponer/reactivar, resolver, recargar y guardar configuración.
`scripts/verify_mail_model.py` comprueba el modelo real con correos sintéticos.
La conexión real a tus dos buzones requiere completar el registro y consentimiento descritos arriba.

La copia del código anterior de Appa está en `appa/backups/mail-integration-20260915`.
El ejecutable anterior del escritorio se respalda antes de instalar la compilación nueva.

Validación final del 15 de septiembre de 2026: **844 pruebas Python aprobadas, 3 omitidas**,
**22 pruebas Rust aprobadas**, comprobaciones de formato/TypeScript y compilación de producción
de Appa completadas. La interfaz de correo pasó la prueba automatizada sin errores JavaScript.
Se comprobó también el ejecutable instalado, su comunicación nativa con Jarvis y la pantalla
de cuentas vacías. Aquella validación histórica usó el modelo local anterior; la implementación
actual prueba Luna con mensajes sintéticos e instrucciones maliciosas sin acceder a correos reales.

Ejecutable actualizado: `%USERPROFILE%\Desktop\Appa Jarvis.exe`. Respaldo anterior:
`D:\Verano_2026\appa\backups\mail-integration-20260915\Appa Jarvis.before-mail.exe`.
