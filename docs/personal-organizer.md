# Hoy, Calendar y continuidad

La pantalla **Hoy** aparece después de Dashboard en Appa. También está disponible en
`/organizer` desde Jarvis, con el acceso privado habitual del teléfono.

## Funciones

- **Google Calendar:** autorización independiente de Gmail, una cuenta de destino y un
  calendario secundario llamado Jarvis. Se consulta la agenda accesible de los próximos
  90 días y el día anterior, cada cinco minutos. La Agenda de Appa muestra también los
  eventos de Google. No se migran automáticamente eventos manuales de Appa a Google.
- **Correo a evento:** las fechas citadas en correos de Gmail o Microsoft 365 producen
  propuestas editables. Las fechas relativas, numéricas ambiguas o sin año quedan sin
  completar. Las horas se proponen en America/Guayaquil; la duración de una hora es una
  sugerencia, no un dato extraído. El usuario revisa y guarda desde la PC.
- **Cambios y duplicados:** un hilo conserva el identificador del evento. Un nuevo correo
  con fecha produce una propuesta de actualización. Los reintentos conservan el mismo
  identificador y los datos pendientes; los cambios externos en Google se detectan con
  ETag y se pide revisarlos antes de sobrescribir. No se infieren cancelaciones automáticamente.
- **Edición desde Appa y Jarvis:** los eventos publicados en el calendario secundario **Jarvis**
  muestran **Editar** en Hoy. Se pueden cambiar título, descripción, horario, modalidad de día
  completo y avisos. Antes de guardar se comprueba el ETag; si Google cambió el evento en otro
  dispositivo, se rechaza la edición y se pide actualizar. Los calendarios compartidos o creados
  fuera de Jarvis se muestran, pero no se editan desde esta función. Por voz o chat, una edición
  también requiere confirmación.
- **Hoy:** prioridades sugeridas a partir de tareas pendientes, correos por responder y
  agenda próxima. El contenido se lee de la copia local; no requiere esperar a un modelo.
  Se señala cuando Appa o Google no se han podido sincronizar.
- **Finanzas 2.0:** extrae localmente importes, fecha, comercio y tipo de movimiento de
  notificaciones reconocidas de Produbanco y Banco Pichincha. El panel separa compras,
  transferencias, retiros e ingresos, muestra categorías y permite excluir o recategorizar cada
  registro. Las promociones, claves temporales e inicios de sesión no cuentan como gastos. Gmail
  puede agrupar mensajes con el mismo asunto; Jarvis conserva cada mensaje individual para no
  subcontarlos. Permite definir un presupuesto total o por categoría, ingreso y meta de ahorro;
  muestra proyección de cierre, seis meses de tendencia, posibles pagos recurrentes y compras
  claramente inusuales frente al historial. Se puede corregir un comercio y reutilizar ese alias,
  además de exportar el mes como CSV. Solo guarda estas preferencias en Jarvis y enlaza el correo
  original. Appa consume la misma fuente mediante su módulo **Finanzas**: no duplica correos ni
  credenciales bancarias.
- **Seguimiento:** por defecto, avisos tras tres días en «Por responder» o «Esperando
  respuesta», como máximo uno cada 24 horas. Los intervalos se ajustan en la página Hoy.
  Los correos resueltos o pospuestos no generan estos avisos. No se envían respuestas.
- **Estudio:** sesiones distribuidas entre días antes de una fecha límite, con duración y
  horario configurables. Se evitan bloques ocupados y otras propuestas, con diez minutos
  de margen posterior. Se informa de sesiones que no caben. La interfaz propone lunes a
  viernes; la API admite elegir días. Cada sesión se revisa antes de guardarla en Calendar.
- **Captura:** notas inmediatas, recordatorio opcional y dictado. En la página móvil,
  primero se guarda la solicitud en el navegador; un identificador persistente impide
  duplicarla al reconectar. El dictado se transcribe localmente y se revisa antes de guardar.
  También funciona «Anota esta idea: ...» en el chat de texto o voz. Appa muestra las
  capturas de todos tus dispositivos; cada teléfono consulta las suyas.

El cálculo financiero se puede consultar también por chat o voz, por ejemplo «¿cuánto he gastado
este mes?», «¿cuánto transferí?» o «¿cuánto gasté esta semana?». Es una estimación basada en los
correos disponibles: una operación sin notificación, un formato bancario nuevo o una reversión
pueden requerir revisión. Los estados de cuenta siguen siendo la fuente oficial.

## Conectar Google Calendar

1. En el proyecto de Google Cloud que usarás para Gmail, habilita **Google Calendar API**.
2. Conserva el cliente OAuth de tipo **Aplicación de escritorio** y configura su JSON en
   la página Correos de Jarvis. No necesitas una contraseña ni un segundo cliente.
3. En **Hoy → Conectar Calendar y configurar avisos**, pulsa **Conectar Google Calendar**.
4. Autoriza consultar la agenda y administrar los calendarios creados por Jarvis.
   En modo de pruebas, añade tu cuenta a los usuarios de prueba del proyecto.

Permisos: `calendar.readonly`, `calendar.app.created` y `userinfo.email`. Los permisos de
Calendar se guardan separados de los de Gmail y no conceden acceso al correo universitario.
La cuenta de Outlook puede aportar un correo cuya fecha guardes en tu calendario Google.
Al desconectar se eliminan el token y la copia local de la agenda; los eventos en Google
se conservan. La revocación definitiva se hace en las aplicaciones autorizadas de Google.

## Activar avisos en el teléfono

1. Abre Jarvis mediante su enlace HTTPS privado e inicia sesión con tu passkey.
2. Abre **Hoy → Avisos en este dispositivo → Activar avisos** y acepta el permiso del navegador.
3. Usa **Enviar prueba**. La entrega respeta el horario de silencio de Asistente.
4. En iPhone/iPad, abre primero la aplicación añadida a la pantalla de inicio.

Los avisos funcionan con la página cerrada en navegadores compatibles. Requieren que la
PC y Jarvis estén activos y tengan Internet; no despiertan una PC apagada. El navegador y
el sistema operativo pueden retrasar su entrega. Los datos se cifran mediante Web Push;
Google, Mozilla o Apple transportan el aviso. La pantalla bloqueada muestra solo un texto
genérico. Los detalles se consultan con la autenticación existente de Jarvis.

Los recordatorios creados en el chat del mismo dispositivo también se entregan por push.
Revocar el dispositivo impide nuevos envíos. Una suscripción caducada se elimina; fallos
temporales se reintentan con espera creciente. La etiqueta del aviso evita apilar duplicados
si una respuesta del proveedor se pierde. La aceptación del proveedor no certifica que el
teléfono haya mostrado la notificación.

Cuando Appa está instalada, Jarvis registra además un canal de escritorio persistente. Los
avisos de agenda, capturas, seguimiento de correo y resumen diario se entregan al sistema de
notificaciones de Windows mediante el puente autenticado de Appa. Una entrega fallida queda
en cola y se reintenta; Appa conserva la clave de idempotencia para no repetirla. El resumen
diario usa texto genérico y no muestra asuntos de correo en la pantalla bloqueada.

## Arranque, respaldo y restauración

`scripts/install_supervisor.ps1` instala un acceso directo de inicio para el usuario actual.
El supervisor arranca Jarvis al iniciar sesión, comprueba su salud y recupera el proceso
que él mismo inició tras fallos consecutivos. Recupera también Ollama local si el puerto
está libre. No detiene procesos ajenos, ni cambia la suspensión o el bloqueo de Windows.
Si detecta una instalación de Appa, también la inicia oculta cuando su puente no está activo;
no termina instancias ajenas ni intenta abrirla sobre un puerto ocupado.
El estado está en `.data/supervisor.json`; los registros del servidor se rotan a 5 MB.
Abrir `start.cmd` cuando Jarvis ya está activo reutiliza ese servidor y abre su interfaz.

Cada día se prepara un respaldo cifrado con Windows DPAPI en `.data/backups`. Se conservan
14 copias. Cada copia se descifra de nuevo inmediatamente, comprueba su manifiesto y hashes y
ejecuta `PRAGMA quick_check` sobre cada SQLite antes de declararse válida. Incluye las bases SQLite
de Jarvis, `.env`, preferencias y el perfil local
predeterminado. SQLite usa su API de backup para incluir escrituras del diario WAL.
No incluye modelos, adjuntos, fuentes de documentos ni la base propia de Appa; para esta
última utiliza los respaldos existentes de Appa. Un respaldo en el mismo disco sirve para
recuperar errores de software; no protege frente a la pérdida del disco.

En **Mi día → Confiabilidad y recuperación** se puede comprobar el estado de Gmail, Calendar,
Appa, el programador, las bases locales, el espacio disponible y la copia más reciente. También
permite verificar otra vez la última copia y escoger actividad normal (cada minuto) o modo ahorro
(cada tres minutos). El diagnóstico detallado y la creación/verificación de respaldos solo están
disponibles desde la PC principal; el teléfono no puede ejecutar operaciones de recuperación.

La restauración requiere el mismo usuario de Windows y el material DPAPI de ese perfil:

```powershell
# Pausar recuperación y esperar a que Jarvis se detenga.
New-Item -ItemType File -Force .data\supervisor.pause
# Si Jarvis se abrió manualmente, ciérralo también.
.\.venv\Scripts\python.exe scripts\restore_assistant.py jarvis-NOMBRE.jbackup
# Tras revisar el resultado, reanudar.
Remove-Item -LiteralPath .data\supervisor.pause
```

La herramienta rechaza la restauración con Jarvis escuchando, valida rutas y hashes y
crea un respaldo previo antes de reemplazar archivos. Al restaurar se recuperan también
credenciales y estado de dispositivos del respaldo; revisa los permisos y vuelve a revocar
dispositivos que hubieras retirado después de esa copia.

Para desactivar futuros arranques: `scripts/install_supervisor.ps1 -Remove`; para pausar el
supervisor actual utiliza el archivo `supervisor.pause`.

## Pruebas reproducibles

`tests/test_organizer.py` comprueba fechas ambiguas, husos horarios, OAuth separado,
duplicados y pérdida de respuestas, edición de eventos administrados, ETags, conflictos con
ediciones externas, paginación,
conservación de caché, capturas tras reinicio, permisos remotos, horarios de estudio,
notificaciones cifradas y firmadas con la librería real, reintentos, revocación y restauración.
`tests/test_finance.py` cubre promociones, formatos reales anonimizados de ambos bancos,
deduplicación, conversaciones agrupadas, totales mensuales, categorías, exclusiones y consultas
por chat.

`scripts/smoke_organizer_ui.py` prueba Appa compilada y la página móvil con datos ficticios:
revisión de evento, estudio, capturas, funcionamiento sin conexión, sincronización sin
duplicados, ruta de dictado y errores JavaScript. Las llamadas de Google y la transcripción
de esa prueba se simulan. Los datos personales y los resultados de prueba quedan fuera de Git.

La autorización real de correo/Calendar y el permiso de avisos del teléfono requieren tu
participación. Ninguna prueba sintética equivale a comprobar entrega en tu teléfono físico.

Verificación final: **996 pruebas Python aprobadas, 4 omitidas** y **23 pruebas Rust
aprobadas**; formato, TypeScript y compilación de producción completados. Las pruebas
de navegador pasaron sin errores JavaScript. Se verificó el ejecutable instalado de Appa
y su comunicación nativa con Jarvis. El supervisor recuperó el servidor después de una
terminación controlada. En la PC, ocho consultas a Hoy dieron una mediana de **11,5 ms**;
«Dime la hora» respondió en **57,1 ms**. Estas cifras no incluyen la red del teléfono.
Los detalles de esta comprobación están en `.data/organizer-live-verification.json`.

Referencias: [permisos de Calendar](https://developers.google.com/workspace/calendar/api/auth),
[eventos](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[Web Push](https://github.com/web-push-libs/pywebpush),
[Web Push en iOS](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).
