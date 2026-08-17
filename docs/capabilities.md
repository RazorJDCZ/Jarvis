# Centro de capacidades local

Jarvis 0.8 amplía el motor existente con capacidades locales y opcionales. No sustituye el flujo
conversacional ni entrega acceso directo al modelo: toda operación sigue pasando por
`ActionEngine`, el catálogo tipado, la validación de argumentos, el nivel de riesgo y, cuando
corresponde, una confirmación vinculada a la sesión.

## Funciones incorporadas

### Actividad y trazas

Cada solicitud crea una traza con identificador propio, duración, resultado y pasos del motor. El
panel **Control Deck > Actividad** permite revisar las últimas ejecuciones sin mostrar texto
sensible. Las trazas se guardan en SQLite, están separadas por sesión y tienen un límite de
retención.

### Skills declarativas

Las skills son recetas JSON de dos a cinco acciones del catálogo. Incluye `diagnostico_rapido` y
`vista_de_trabajo`; los manifiestos personales pueden colocarse en `.data/skills`. Una receta no
puede importar Python, usar scripts, abrir terminales ni anidar otra receta. Compilarla no ejecuta
nada: sus pasos regresan al motor normal para volver a validarse y confirmarse.

Ejemplos: “lista mis skills” y “ejecuta la receta diagnóstico rápido”.

### Tareas y Appa

“Crea una tarea para revisar el informe mañana con prioridad alta”, “lista mis pendientes” y
“completa la tarea…” usan Appa cuando está instalada. Jarvis descubre dinámicamente
`%LOCALAPPDATA%\Appa\jarvis-bridge.json`, por lo que Appa puede iniciarse después de Jarvis. El
puente sigue disponible cuando la ventana de Appa está oculta en la bandeja y se detiene al salir
de Appa.

La integración también permite listar y crear proyectos, consultar y crear eventos, capturar ideas
en el inbox y consultar o iniciar sesiones focus. Ejemplos: “dime mis proyectos de Appa”, “agenda
una reunión mañana a las 9”, “guarda en mi inbox revisar esta idea” e “inicia focus de 25 minutos”.
Las lecturas son de riesgo bajo; toda creación es de riesgo medio y requiere la confirmación normal
del motor, también desde el celular.

El descriptor contiene una URL `http://127.0.0.1:<puerto>/v1` y un token rotatorio. Jarvis exige
loopback exacto, Bearer, versión de contrato compatible, archivo regular y límites estrictos;
desactiva proxies del entorno, no sigue redirecciones, limita respuestas y nunca registra el token.
Las creaciones llevan `Idempotency-Key` y no se reintentan silenciosamente.

El contrato v1 utilizado es:

- `GET /health` con capacidades explícitas.
- `GET/POST /tasks` y `PATCH /tasks/{id}`.
- `GET/POST /projects`.
- `GET/POST /calendar/events`.
- `GET/POST /inbox`.
- `GET/POST /focus`.

Los vencimientos de tareas se convierten a `YYYY-MM-DD`; recordatorios y horas de calendario usan
RFC 3339 con zona. Jarvis nunca envía palabras como “mañana” al backend. Si Appa está instalada
pero su descriptor es inválido o el puente no responde, la operación falla con un mensaje claro:
no cambia silenciosamente al SQLite local. Si ya existen tareas locales, tampoco cambia a Appa
hasta que se defina una migración, evitando repartir pendientes entre dos almacenes.

Cuando Appa no está instalada, las tareas conservan el almacén SQLite privado y gratuito de
Jarvis. El override manual `JARVIS_APPA_URL`/`JARVIS_APPA_TOKEN` queda disponible únicamente para
desarrollo; la integración normal no requiere copiar secretos ni usar una API externa.

### Recordatorios y proactividad acotada

Jarvis programa recordatorios locales únicos o recurrentes y los entrega a la sesión que los creó.
Acepta expresiones como “en 20 minutos”, “mañana a las 9”, “el 12 de agosto a las 9” y “cada
semana a las 18”. El programador usa la zona de Quito, sobrevive reinicios y la PWA consulta las
notificaciones mientras está abierta. El navegador puede mostrar una notificación si el usuario le
concede permiso.

No envía SMS, correos ni mensajes por su cuenta. “Lista mis recordatorios” y “cancela el
recordatorio…” están disponibles por voz, y el Control Deck ofrece creación y cancelación manual.

### Biblioteca privada y adjuntos móviles

La PWA permite adjuntar TXT, Markdown, CSV, JSON, XML, PDF, JPEG, PNG y WebP. Los archivos se
validan por extensión, MIME y firma, se renombran con identificadores aleatorios, quedan aislados
por sesión y caducan por defecto a las 24 horas. Las imágenes solo llegan al modelo visual cuando
el usuario las adjunta expresamente; Jarvis no enciende la cámara en segundo plano y detiene el
stream después de cada captura.

Un documento autorizado puede indexarse con “guarda este adjunto en mi biblioteca”. La búsqueda
local devuelve fragmentos con su fuente. El contenido de un archivo o una imagen se trata siempre
como datos no confiables: instrucciones escritas dentro de ellos no pueden cambiar permisos ni
activar acciones. Para extraer PDF se requiere el extra opcional `pypdf`, incluido en
`jarvis-local[actions]`.

### Permisos recordados

En acciones benignas seleccionadas, el cuadro de confirmación ofrece **Confirmar 30 días**. El
permiso solo se guarda después de que la acción termine correctamente. Nunca se recuerda para
acciones de riesgo alto, apertura de aplicaciones, archivos, escritura, cierres, pruebas, cámara o
acciones financieras/borrado; estas vuelven a preguntar siempre.

Los permisos remotos quedan ligados al dispositivo autenticado que confirmó la acción y no pueden
crearse manualmente desde otro equipo. Pueden consultarse u olvidarse desde la consola local.

### Sistema y portapapeles

“Estado del sistema” consulta CPU, memoria, disco y batería cuando están disponibles. El monitor
mantiene un historial pequeño y genera una sola alerta al entrar en un episodio sostenido de uso
alto. La alerta permanece enclavada hasta observar una recuperación sostenida con margen, momento
en el que informa la normalización; una pestaña nueva nunca reproduce avisos históricos. Jamás
termina procesos ni cambia prioridades.

“Resume/explica/corrige/traduce mi portapapeles” requiere confirmación, lee el texto una sola vez y
lo analiza con Ollama local. El contenido se censura en auditoría y no se incorpora a la memoria.

### Espacios de desarrollo

Jarvis puede listar proyectos autorizados, leer un archivo y buscar texto sin salir de sus raíces.
El repositorio de Jarvis es el único workspace predeterminado; otros se agregan con
`JARVIS_WORKSPACE_ROOTS`, separados por punto y coma.

Las rutas se resuelven debajo de una raíz explícita y se bloquean traversal, enlaces/reparse points,
`.git`, `.env`, credenciales y archivos binarios. “Ejecuta las pruebas del proyecto…” es de riesgo
alto y solo permite comandos exactos predefinidos, sin shell, tuberías, sustituciones ni argumentos
arbitrarios. No existe una herramienta de terminal general.

### Juegos y multimedia

“Lista mis juegos” inspecciona manifiestos de Steam y Epic únicamente después de una solicitud
explícita. “Inicia el juego…” prepara un URI validado y requiere confirmación antes de abrirlo. No
escanea procesos, no lee partidas y no controla anticheat. Los controles de reproducción, volumen,
ventanas y navegador existentes siguen siendo la capa segura para multimedia.

### Cámara

El botón de cámara de la PWA solicita permiso al navegador para una captura explícita. La imagen se
procesa como adjunto efímero y el modelo tiene prohibido inferir identidad o atributos sensibles.
No hay reconocimiento facial, vigilancia continua ni captura automática.

## Datos y configuración

De forma predeterminada todo queda dentro de `.data`:

- `capabilities.sqlite3`: trazas, permisos, recordatorios y biblioteca.
- `tasks.sqlite3`: tareas locales.
- `attachments/`: adjuntos temporales aislados.
- `skills/`: manifiestos declarativos opcionales.

Variables principales:

```dotenv
JARVIS_CAPABILITIES_ENABLED=true
JARVIS_CAPABILITY_DATABASE=.data/capabilities.sqlite3
JARVIS_ATTACHMENT_MAX_BYTES=12582912
JARVIS_ATTACHMENT_RETENTION_HOURS=24
JARVIS_SCHEDULER_POLL_SECONDS=2
JARVIS_SYSTEM_MONITOR_SECONDS=15
JARVIS_APPA_AUTO_DISCOVER=true
JARVIS_APPA_BRIDGE_CONFIG=
JARVIS_APPA_URL=
JARVIS_APPA_TOKEN=
JARVIS_WORKSPACE_ROOTS=
JARVIS_STEAM_ROOTS=
JARVIS_EPIC_MANIFEST_ROOTS=
```

`JARVIS_CAPABILITIES_ENABLED=false` desactiva el paquete completo y conserva el asistente anterior.
Los límites de tamaño, intervalos y rutas se validan al arrancar. Ningún conector de pago es
necesario: SQLite, Ollama, Steam/Epic local y la PWA funcionan sin suscripción.

## Límites deliberados

- Jarvis no ejecuta código arbitrario ni instala paquetes.
- No envía mensajes, correos, publicaciones ni pagos.
- No borra archivos ni controla procesos desde estas capacidades.
- Appa debe permanecer ejecutándose o en la bandeja para que su puente loopback responda.
- Las tareas locales previas requieren una migración explícita antes de activar Appa.
- Las notificaciones móviles dependen de que la PWA esté abierta; todavía no existe un servicio
  push externo en segundo plano.
- El reconocimiento de juegos depende de los manifiestos instalados, no de una búsqueda en línea.
