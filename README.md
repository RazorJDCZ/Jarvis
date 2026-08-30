# JARVIS Local Core

Asistente de voz privado y local para Windows. El proyecto está dividido en cinco etapas:

1. MVP de voz — completado.
2. Motor de acciones — completado.
3. Acceso móvil — implementado (`0.7.0`).
4. Memoria y personalidad — implementada.
5. Visión y proactividad — la percepción visual multimonitor y contextual está implementada;
   recordatorios y alertas aportan proactividad local acotada, sin autonomía continua.

## Qué hace esta versión

- Conversa por texto o voz con Qwen mediante Ollama, sin pagar por cada solicitud.
- Transcribe localmente con Faster Whisper y habla con la voz masculina `em_alex` de Kokoro 82M;
  Piper y las voces de Windows quedan como respaldos automáticos.
- Ofrece modo pulsar-para-hablar y manos libres con la frase “Jarvis”.
- Ejecuta 78 acciones tipadas sobre Windows, aplicaciones, pantalla, navegadores y capacidades
  locales controladas.
- Usa una vía determinista rápida para acciones evidentes y un núcleo semántico local para entender
  metas expresadas con contexto, cortesía, motivación, pronombres o lenguaje indirecto; no exige una
  frase exacta ni que el usuario reformule su intención como “comando”.
- Puede preparar hasta cinco acciones y resolver metas dependientes mediante un ciclo acotado de
  planificar, ejecutar, verificar, observar y volver a planear. Nunca decide con una observación que
  todavía no existe y cada cambio sensible conserva su confirmación.
- Si falta un dato esencial o las herramientas no pueden materializar la meta, hace una sola
  pregunta concreta y conserva la solicitud original para entender la respuesta breve.
- Enumera monitores y permite describir, consultar o localizar elementos en uno específico mediante
  el modelo visual local de Ollama; las capturas transitorias se mantienen en memoria.
- Conserva durante cinco minutos el foco visual de cada conversación para entender continuaciones
  como “¿qué dice ese error?”, pero siempre vuelve a capturar la pantalla antes de responder.
- Muestra confirmaciones de seguridad en la interfaz y también acepta “confirma” o “cancela”.
- Registra una auditoría local con los argumentos y resultados sensibles censurados.
- Mantiene historial temporal por sesión y permite borrarlo.
- Verifica clima y temperatura con Open-Meteo y aporta evidencia de Wikipedia a las preguntas
  factuales antes de responder; si una fuente falla, no inventa el dato.
- Conserva el contexto personal confirmado por el usuario en `.data/user_profile.json`, un archivo
  local excluido de Git. Las preguntas personales no salen del equipo.
- Aprende selectivamente preferencias, relaciones, estudios, proyectos y objetivos en una base
  SQLite local. Recupera solo los recuerdos relevantes y conserva una ventana limitada de diálogo
  reciente para continuar después de reiniciar.
- Funciona como PWA tanto en la PC como en el teléfono. El servidor siempre permanece limitado a
  `127.0.0.1`; Tailscale Serve proporciona el único enlace HTTPS privado hacia el celular.
- Añade un Control Deck para trazas, recordatorios, adjuntos y métricas; integra tareas locales o
  Appa, biblioteca privada, skills declarativas, permisos temporales, workspaces y juegos sin
  entregar al modelo una terminal ni acceso irrestricto al equipo.

El modo manos libres detecta la frase de activación después de transcribir localmente cada
intervención. Una etapa posterior podrá incorporar openWakeWord para reducir el consumo continuo.

## Instalación

Desde el Explorador de Windows, ejecuta:

```text
setup.cmd
```

El instalador crea `.venv`, instala las dependencias dentro del proyecto, descarga Kokoro 82M y su
catálogo de voces (aproximadamente 338 MB), una voz Piper de respaldo (aproximadamente 77 MB) y
Whisper `small` (aproximadamente 464 MB). Todo el audio se genera localmente y sin costo. No cambia
la política de ejecución de PowerShell. Si ya instalaste una versión anterior, vuelve a ejecutar
`setup.cmd` para incorporar las dependencias nuevas.

Después inicia la aplicación con:

```text
start.cmd
```

Se abrirá `http://127.0.0.1:8765`. La primera transcripción puede tardar mientras Whisper termina de
cargar el modelo.

### Acceso móvil privado

El teléfono no se conecta mediante un puerto público. Jarvis combina dos barreras: la identidad
privada de Tailscale y una passkey propia del dispositivo, protegida por la biometría o PIN del
teléfono.

1. Instala Tailscale en la PC y en el teléfono e inicia sesión con la misma cuenta.
2. En la PC ejecuta `scripts\setup_remote_access.cmd`.
3. Reinicia Jarvis con `start.cmd`.
4. En la interfaz local abre **ACCESO MÓVIL** y genera un código de un solo uso.
5. Abre en el teléfono la URL privada que muestra Jarvis, escribe el código y crea la passkey.
6. En el navegador móvil usa **Añadir a pantalla de inicio** para instalar la PWA.

En el celular, toda acción que cambie el equipo pide confirmación aunque normalmente fuese de
riesgo bajo. Las consultas de estado y lectura conservan ejecución directa. El botón rojo
**DETENER JARVIS** corta la voz y cancela acciones o diálogos pendientes. Desde la PC puedes
revocar teléfonos en cualquier momento; `scripts\disable_remote_access.cmd` elimina la publicación
privada completa. La guía operativa y el modelo de seguridad están en
[docs/mobile-access.md](docs/mobile-access.md).

### Modelo conversacional

La interfaz arranca sin Ollama usando un núcleo limitado. Para instalar la edición portátil dentro
del proyecto y descargar el modelo recomendado, ejecuta:

```text
scripts\install_ollama.cmd
```

Jarvis iniciará ese Ollama automáticamente y lo apagará al cerrar `start.cmd`. También puede usar
una instalación que ya responda en `http://127.0.0.1:11434`. En equipos de 16 GB, Qwen se carga
solo cuando una conversación o una acción visual realmente lo necesita y se descarga al terminar;
los comandos deterministas no lo cargan. Esta política evita competir por memoria con Whisper,
Kokoro, juegos y navegadores. Se controla mediante `JARVIS_OLLAMA_KEEP_ALIVE=0s` y
`JARVIS_OLLAMA_WARMUP_ENABLED=false`. La precarga puede habilitarse manualmente, pero Jarvis la
omite si la memoria libre está por debajo de `JARVIS_OLLAMA_WARMUP_MIN_FREE_GB`.

Durante una consulta visual multimonitor, Qwen permanece cargado únicamente entre las capturas de
esa consulta (`JARVIS_VISION_KEEP_ALIVE`) y se libera inmediatamente al finalizar. Antes de cada
transcripción, Jarvis también solicita la descarga de cualquier Qwen residente para que Whisper
tenga prioridad. Al cerrar `start.cmd`, se detienen de forma validada el servidor portátil y todos
sus runners; el siguiente arranque elimina runners huérfanos de la carpeta del proyecto.

## Uso

- Mantén presionado el núcleo central o la barra espaciadora mientras hablas.
- Activa **Manos libres**, guarda silencio durante la calibración y di “Jarvis”.
- Pulsa **Respuesta de voz** para silenciar o reactivar las respuestas.
- Usa la consola derecha si prefieres escribir.
- Cuando aparezca **SECURITY GATE**, revisa la acción y pulsa **CONFIRMAR** o **CANCELAR**. También
  puedes responder por voz “sí, hazlo” o “no lo hagas”. La autorización expira a los 90 segundos.
- Si una aplicación abre un diálogo después de la acción, Jarvis lee sus opciones y vuelve a
  preguntar. Debes elegir algo concreto, como “guardar”, “no guardes” o “cancelar”; Jarvis no
  supone una respuesta.
- Para interrumpir una respuesta larga di “Jarvis, es suficiente”, “Jarvis, detente” o “Jarvis,
  deja de hablar”. Al detectar tu voz, Jarvis pausa el audio mientras valida localmente la frase;
  si no era una interrupción, continúa donde iba. Funciona en manos libres y después de usar el
  micrófono manualmente. Con pulsar el micrófono también detienes la voz de inmediato.

## Acciones disponibles

### Aplicaciones y ventanas

- “Abre la calculadora”, “abre el bloc de notas”, “abre Paint”, “abre Configuración”.
- “Abre Spotify”, “abre Discord”, “abre Word” o “abre Visual Studio Code”. Jarvis consulta el
  catálogo de aplicaciones de Windows, incluidos programas clásicos y aplicaciones empaquetadas.
- “¿Qué aplicaciones puedes abrir?” muestra el inventario seguro disponible en este equipo.
- “¿Qué aplicaciones están abiertas en mi PC?” consulta las ventanas directamente mediante
  Windows; funciona aunque los monitores estén apagados y no necesita una captura.
- Las aplicaciones descubiertas dinámicamente requieren confirmación y vuelven a validarse contra
  el catálogo de Windows justo antes de abrirse. Si un nombre es ambiguo, Jarvis pide el nombre
  completo.
- “Lista las ventanas”, “cuál es la ventana actual”, “cambia a la ventana de Spotify”.
- “Minimiza la ventana”, “maximiza la ventana de Edge”, “restaura la ventana”.
- “Cierra la ventana de Paint” requiere confirmación.

Si el cierre muestra un aviso de cambios sin guardar, el flujo queda pausado hasta que elijas uno
de los botones accesibles del diálogo. La elección se valida de nuevo contra la misma ventana antes
de activarse.

Jarvis espera y verifica la aparición de la ventana al iniciar una aplicación. Si ya estaba abierta,
la trae al frente en lugar de crear copias innecesarias.

### Navegador controlado

- “Abre github.com”, “abre YouTube”, “busca en Google clima en Quito”.
- “Abre YouTube en Chrome”, “visita GitHub usando Microsoft Edge” o “busca restaurantes en Brave”.
- Si no indicas navegador, Jarvis usa el navegador predeterminado de Windows cuando sea Chrome,
  Edge o Brave.
- “Atrás”, “página siguiente”, “recarga la página”.
- “Abre una nueva pestaña”, “lista las pestañas”, “cambia a la pestaña GitHub”.
- “Lee la página”.
- “Escribe Juandi en el campo Nombre” llena el campo, pero nunca lo envía automáticamente.
- En el perfil personal, pide el enlace por su nombre visible en vez de por número.
- “Haz clic en Aceptar” y “cierra la pestaña” requieren confirmación.

Por defecto Jarvis abre una ventana normal de Chrome, Edge o Brave reutilizando el último perfil
personal del navegador (`Default` en esta PC), por lo que conserva la cuenta, las sesiones y las
cookies habituales. No usa incógnito, invitado, un `user-data-dir` separado ni depuración remota.
La navegación básica y los controles con nombre accesible se manejan mediante UI Automation y
atajos fijos de Windows. Al apagarse, Jarvis nunca cierra las ventanas personales.

Si se configura `JARVIS_BROWSER_PERSONAL_PROFILE=false`, vuelve al perfil persistente aislado en
`.data`: ese modo permite control DOM más preciso, pero no comparte las cuentas personales.

### Información verificada y perfil personal

- “¿Qué temperatura hace en Quito?” y “¿Cómo estará el clima mañana en Vancouver?” consultan
  Open-Meteo directamente y mencionan la hora o fecha del dato.
- Las preguntas factuales generales reciben extractos de Wikipedia delimitados como evidencia no
  confiable antes de llegar a Qwen. El modelo debe citar la fuente brevemente y no rellenar vacíos.
- Noticias, precios, marcadores y otros datos en vivo no compatibles se rechazan con honestidad.
- El perfil privado se encuentra en `.data/user_profile.json`; puede editarse sin tocar el código y
  nunca se envía a Open-Meteo ni Wikipedia. Admite identidad, estudios, trabajo, objetivos,
  proyectos, rutina, herramientas, preferencias de asistencia, personas importantes, fechas,
  gustos y planes de futuro.
- En cada conversación se inyecta un núcleo personal compacto y solo las secciones relacionadas
  con el tema actual. Mencionar a una persona concreta recupera sus datos sin cargar todo el grupo;
  hablar de juegos, música, comida, viajes o proyectos recupera únicamente esa categoría.
- Las descripciones de personas funcionan como apuntes privados. Una pregunta factual como
  “¿quién es?” responde desde los datos estructurados para impedir alucinaciones; “¿qué sabes de?”,
  “¿cómo es?” o “analiza a…” usa una composición local fundamentada cuando se refiere a una sola
  persona conocida. Así responde en milisegundos, separa hechos de impresiones y reconoce lo que
  no puede inferir. Comparaciones complejas conservan el modelo, pero aíslan la solicitud actual
  para que una conversación anterior no cambie el tema.
- Las preguntas sobre Juan Diego distinguen identidad, memoria y reflexión. “¿Quién soy?” devuelve
  un resumen factual; “¿qué recuerdas de mí?” enumera memoria local; y “¿qué sabes de mí?”,
  “¿cómo me ves?” o “analízame” activan un análisis propio. Este último conecta únicamente hechos
  compatibles del perfil mediante una composición local fundamentada, porque permitir inferencias
  libres al modelo pequeño producía rasgos psicológicos y relaciones causales no confirmadas.
- Jarvis evita preguntas genéricas al final de cada respuesta y solo pregunta cuando necesita una
  aclaración real para continuar.

### Memoria y personalidad

La memoria se guarda en `.data/memory.sqlite3`, excluida de Git. Usa SQLite con WAL, índices,
deduplicación por clave, límites de tamaño y borrado seguro. No guarda preguntas, órdenes,
estados pasajeros ni mensajes que parezcan contener contraseñas, tokens, códigos o datos bancarios.
Los recuerdos se recuperan por relevancia y las conversaciones recientes solo se inyectan al abrir
una sesión nueva, evitando llenar innecesariamente el contexto de Qwen.

Comandos de voz útiles:

- “Recuerda que mi color favorito es azul”.
- “¿Qué recuerdas de mí?” o “¿Cuántos recuerdos tienes?”.
- “Olvida que mi color favorito es azul”.
- “¿De qué hablábamos?” para retomar una conversación reciente.
- “Borra toda tu memoria” requiere una segunda frase explícita de confirmación. El perfil base de
  `.data/user_profile.json` se conserva.

Jarvis también aprende frases claras como “me gusta tocar el ukelele”, “vivo en Quito”, “estudio
Ingeniería…” o “estoy desarrollando mi propio Jarvis”. La personalidad está orientada a voz:
gentil, servicial, serena y ligeramente ingeniosa, con una sola pregunta puntual únicamente cuando
la conversación realmente la amerita. Las consultas de opinión o análisis reciben normalmente de
tres a seis oraciones sustantivas. Si el tema permite un desarrollo mucho mayor, Jarvis ofrece el
modo de análisis profundo: “sí, profundiza” retoma la pregunta original con una respuesta extensa y
“no, dame la versión normal” conserva el formato habitual. Pedir “analízalo a fondo” activa el modo
directamente. La confirmación caduca después de 180 segundos y puede deshabilitarse con
`JARVIS_DEEP_ANALYSIS_CONFIRMATION_ENABLED=false`. El modo profundo baja la variabilidad y amplía
el presupuesto de la respuesta final dentro de un límite estricto; no mantiene otro modelo cargado
ni reserva RAM adicional. Las respuestas naturales o imperfectas como “sí, quiero que profundices”
y “no, dame la version nomal” se interpretan dentro de la elección pendiente en vez de enviarse
solas al historial conversacional.
El análisis del propio Juan Diego usa una ruta fundamentada separada: la versión normal sintetiza
su situación en tres bloques y la profunda desarrolla seis perspectivas, siempre distinguiendo
hechos, conexiones permitidas, riesgos prácticos y límites de lo que el perfil puede demostrar.

### Audio, multimedia y escritorio

- “Pon el volumen al 42 por ciento”, “súbele el volumen”, “silencia el sonido”, “dime el volumen
  actual” o “¿en cuánto está el volumen del sistema?”. Las consultas leen Windows directamente y
  nunca permiten que el modelo conversacional invente el valor.
- “Pausa”, “siguiente canción”, “pista anterior”, “detén la música”.
- “Muestra los controles”, “haz clic en el control Guardar”.
- `escribe "Texto con acentos"`, “guarda”, “deshaz”, “presiona intro”.
- “Haz scroll abajo 8”, “muestra el escritorio”.
- “Haz clic en 400, 250” es una acción de riesgo alto y exige confirmación.
- “Captura la pantalla” requiere confirmación y guarda la imagen solo dentro de `.data`.

### Pantalla y flujos encadenados

- “¿Qué monitores están conectados?” enumera las pantallas activas y señala la principal.
- “¿Qué hay en cada monitor?” captura y analiza cada pantalla por separado; la respuesta identifica
  `Monitor 1`/`Monitor 2`, dispositivo `DISPLAY`, posición física, resolución y evidencia de una
  captura nueva. Jarvis no comprime ambos escritorios dentro de una sola imagen panorámica.
- Puedes decir “describe el monitor 2”, “mira la pantalla principal”, “¿qué hay en el monitor de la
  derecha?” o “encuentra Aceptar en la pantalla de la izquierda”.
- “Describe lo que ves”, “¿qué aparece en la pantalla?” y “encuentra el botón Continuar” usan
  visión local y requieren confirmación porque la pantalla puede contener información privada.
- Después de una observación, preguntas breves como “¿qué dice ese error?” continúan en el mismo
  monitor. El foco está aislado por sesión, expira y nunca reutiliza coordenadas de una captura vieja.
- “Haz clic visualmente en Continuar” intenta primero usar el árbol accesible de Windows. Si el
  control no está disponible, la visión solo coloca el cursor y solicita una segunda confirmación
  antes del clic real. Puedes revisar la posición o cancelar; mover el cursor invalida el clic.
- “Abre el bloc de notas y después escribe «hola»” prepara los pasos en orden y pide una sola
  confirmación de riesgo medio. Se admiten hasta cinco acciones y el flujo se detiene si un paso
  falla.
- Metas como “busca cursos de Python, compara los resultados y abre el mejor” se dividen en rondas:
  primero busca y lee; solo después usa lo observado para decidir. El agente está limitado a tres
  rondas y cinco acciones totales, y devuelve el resultado verificado del último paso.
- También se aceptan formas naturales como “¿me abres YouTube?”, “búscame restaurantes cerca”,
  “quiero que abras la calculadora” o “deja el sonido aproximadamente a la mitad”.

La visión funciona únicamente contra Ollama en `127.0.0.1` o `localhost`. El texto visible se trata
como datos no confiables: una instrucción escrita dentro de una página o imagen nunca puede ampliar
los permisos del motor.

### Sistema, portapapeles y archivos

- “Estado del sistema” informa CPU, memoria, disco y batería cuando están disponibles.
- “Lee el portapapeles” y `copia "Texto" al portapapeles` requieren confirmación.
- “Resume mi portapapeles”, “explícalo”, “corrígelo” o “tradúcelo al inglés” lo analiza de forma
  efímera con Ollama local sin incorporarlo a memoria.
- “Abre la carpeta Descargas”.
- `abre el archivo "D:\Datos\reporte.pdf"` requiere confirmación. Solo se permiten formatos
  comunes de documentos sin macros, texto, imagen, audio, video y archivos ZIP.
- “Dime la hora”, “dime la fecha”, “qué versión eres”, “ayuda”.
- “Olvida esta conversación”.

### Control Deck y capacidades locales

- **Actividad** muestra trazas censuradas de cada solicitud y sus pasos, aisladas por sesión.
- **Agenda** crea, lista y cancela recordatorios locales; acepta “recuérdame entregar el informe
  mañana a las 9” y recurrencias diarias, semanales o mensuales.
- **Archivos** adjunta documentos o imágenes desde PC y celular. “Guarda este adjunto en mi
  biblioteca” lo indexa y “busca … en mi biblioteca” devuelve resultados con su fuente.
- **Sistema** muestra métricas sin administrar ni cerrar procesos.
- “Crea una tarea para…”, “lista mis pendientes” y “completa la tarea…” usan SQLite local o
  descubren automáticamente el puente privado de Appa. Jarvis entiende fechas naturales,
  prioridad, categoría y proyecto sin enviar texto ambiguo al backend.
- Appa también aporta proyectos, calendario, inbox y sesiones focus por voz. Las creaciones se
  confirman y todo permanece en loopback, incluso cuando Appa está oculta en la bandeja.
- “Lista mis skills” y “ejecuta la receta diagnóstico rápido” usan recetas declarativas que vuelven
  a pasar por el catálogo y las confirmaciones normales.
- “Lista los proyectos autorizados”, “busca … en el proyecto Jarvis” y “ejecuta las pruebas del
  proyecto Jarvis” trabajan dentro de raíces explícitas; las pruebas son de riesgo alto.
- “Lista mis juegos” e “inicia el juego…” detectan manifiestos locales de Steam/Epic y confirman
  antes de abrir.
- El botón de cámara solicita permiso para una única captura, detiene el stream y envía la imagen
  como adjunto efímero; Jarvis nunca enciende la cámara de fondo.
- Algunas confirmaciones benignas pueden recordarse durante 30 días desde el mismo dispositivo.
  Las acciones de riesgo alto y las que manejan datos sensibles siempre vuelven a preguntar.

La referencia completa de acciones, riesgos y límites está en
[docs/action-engine.md](docs/action-engine.md). La guía del nuevo centro local, Appa, adjuntos,
workspaces y sus límites está en [docs/capabilities.md](docs/capabilities.md).

## Agente local 1.0

La toma de decisiones combina llamadas nativas a herramientas, selección semántica del catálogo,
estado verificable con caducidad y metas persistentes. Qwen 4B atiende lo cotidiano y Qwen 9B se
activa sólo para razonamiento complejo. Appa aporta en una sola lectura el contexto real de tareas,
proyectos, agenda, inbox y focus. Consulta [docs/agent-architecture.md](docs/agent-architecture.md).

## Seguridad

- No existe ninguna acción de PowerShell, CMD, terminal ni comandos arbitrarios.
- El modelo nunca recibe acceso directo a Windows: únicamente propone nombres y argumentos del
  catálogo cerrado. El motor vuelve a validar tipos, rangos, permisos, riesgo y estado real.
- Apagar, reiniciar, borrar, formatear, comprar, pagar o transferir están bloqueados.
- Los controles cuyo nombre indica compra, transferencia o eliminación tampoco se activan.
- Los clics visuales estimados por píxeles nunca se realizan en el mismo paso que la detección: se
  mueve el cursor y se exige una confirmación adicional.
- Cada acción pertenece a un catálogo cerrado y valida tipo, longitud, rango y formato de sus
  argumentos antes de ejecutarse.
- Las mutaciones sugeridas por el modelo local se elevan automáticamente a confirmación aunque la
  acción normalmente sea de riesgo bajo.
- Las confirmaciones están vinculadas a la sesión, tienen identificadores impredecibles, expiran y
  no pueden reutilizarse desde otra sesión. Una solicitud nueva cancela la confirmación anterior,
  evitando que un “sí” tardío autorice una acción de otro tema.
- Los diálogos se vinculan al identificador nativo de la ventana y solo aceptan una de las opciones
  que continúen visibles. Si el aviso cambió o desapareció, la elección se rechaza.
- Las frases de interrupción requieren la palabra de activación y una orden cerrada; el audio se
  transcribe localmente y no se incorpora al historial de conversación.
- URLs limitadas a HTTP/HTTPS y sin credenciales incrustadas. En modo personal solo se ejecutan el
  navegador instalado, un perfil existente validado y la URL; no se usa shell.
- Aplicaciones fijas usan comandos conocidos sin shell. Las demás se resuelven desde `AppsFolder`,
  el catálogo publicado por Windows, y se rechazan si son documentos, desinstaladores, terminales,
  intérpretes o accesos modificados después de la confirmación.
- La apertura de archivos usa una lista positiva de extensiones; ejecutables, scripts, macros y
  páginas activas quedan fuera.
- El acceso móvil usa exclusivamente Tailscale Serve privado; no activa Funnel. Además de la
  identidad del tailnet exige una passkey con verificación biométrica o PIN.
- Una orden remota que pueda modificar el equipo se eleva como mínimo a riesgo medio y se confirma
  en el teléfono. Las sesiones y confirmaciones se aíslan por dispositivo.
- El servidor acepta únicamente loopback, rechaza orígenes ajenos y aplica CSP, Permissions Policy
  y límites de tamaño.
- Los audios temporales se eliminan al terminar la transcripción. `.env`, modelos, temporales,
  auditoría y el entorno virtual están excluidos de Git.
- El análisis visual rechaza servidores externos y no guarda su captura transitoria en disco.
- Los adjuntos se validan por tamaño, extensión, MIME y firma, se renombran y aíslan por sesión;
  caducan automáticamente y nunca pueden convertirse en instrucciones para el agente.
- Las herramientas de desarrollo permanecen dentro de workspaces autorizados, bloquean secretos,
  enlaces y rutas internas de Git, y no aceptan comandos ni argumentos libres.
- Un permiso solo se recuerda después de una ejecución exitosa, nunca para riesgo alto y, desde el
  teléfono, queda ligado a ese dispositivo autenticado.

El registro se guarda en `.data/action-audit.jsonl` y se rota automáticamente. También puede verse
localmente en `/api/actions/audit`; texto escrito, portapapeles y contenido visible se censuran.

## Configuración

`setup.cmd` crea `.env` a partir de `.env.example`. Las opciones principales son:

```dotenv
JARVIS_OLLAMA_MODEL=qwen3.5:4b
JARVIS_STT_MODEL=small
JARVIS_STT_DEVICE=cpu
JARVIS_STT_COMPUTE_TYPE=int8
JARVIS_WAKE_WORD=jarvis
JARVIS_REMOTE_ACCESS_ENABLED=false
JARVIS_REMOTE_SESSION_HOURS=12
JARVIS_SAFE_ACTIONS_ENABLED=true
JARVIS_ACTION_MODEL_PLANNING=true
JARVIS_ACTION_CONFIRMATION_SECONDS=90
JARVIS_VISION_ACTIONS_ENABLED=true
JARVIS_VISION_TIMEOUT=180
JARVIS_BROWSER_SEARCH_URL=https://www.google.com/search?q={query}
JARVIS_CAPABILITIES_ENABLED=true
JARVIS_ATTACHMENT_RETENTION_HOURS=24
JARVIS_APPA_AUTO_DISCOVER=true
JARVIS_APPA_BRIDGE_CONFIG=
JARVIS_APPA_URL=
JARVIS_WORKSPACE_ROOTS=
```

`JARVIS_BROWSER_SEARCH_URL` debe ser HTTP/HTTPS y contener exactamente `{query}`. Puedes apagar todo
el motor con `JARVIS_SAFE_ACTIONS_ENABLED=false`, desactivar solo la interpretación flexible con
`JARVIS_ACTION_MODEL_PLANNING=false` o apagar la percepción visual con
`JARVIS_VISION_ACTIONS_ENABLED=false`.
El paquete de capacidades también puede desactivarse de una vez con
`JARVIS_CAPABILITIES_ENABLED=false`; sus almacenes permanecen en `.data` y no se eliminan.

## Desarrollo y pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
node --check src\jarvis\web\app.js
```

La suite cubre parser, catálogo, niveles de riesgo, confirmaciones y permisos recordados,
auditoría, flujos encadenados, visión, controlador de Windows, navegador personal, verificación de
información, perfil privado, API, voz, trazas, adjuntos hostiles, recordatorios, contrato Appa
simulado y aislado (tareas, proyectos, calendario, inbox y focus),
workspaces, skills, juegos, cámara simulada y regresiones de la etapa 1. El smoke test remoto crea y
verifica una passkey WebAuthn real mediante un autenticador virtual de Chrome. El esquema OpenAPI
está disponible localmente en `http://127.0.0.1:8765/api/openapi.json`.

## Solución rápida de problemas

- **No abre una aplicación:** vuelve a ejecutar `setup.cmd`; Jarvis espera hasta cinco segundos por
  la ventana y reporta si pudo verificarla.
- **No cambia el volumen:** comprueba que Windows tenga un dispositivo de salida predeterminado.
- **ACTIONS aparece limitado:** instala Microsoft Edge y verifica
  `JARVIS_SAFE_ACTIONS_ENABLED=true`.
- **El micrófono no abre:** permite el acceso a `127.0.0.1` en Edge o Chrome.
- **CORE aparece limitado:** instala/inicia Ollama y ejecuta `ollama pull qwen3.5:4b`.
- **VISION aparece limitado:** confirma que Ollama sea local y que el modelo publicado por
  `/api/show` incluya la capacidad `vision`. En equipos sin GPU, una consulta visual puede tardar.
- **Kokoro o Piper no aparecen disponibles:** repite `setup.cmd`; las voces de Windows seguirán
  disponibles como último respaldo.
- **Manos libres se activa solo:** desactívalo, reduce el ruido y vuelve a activarlo para recalibrar.
- **No reconoce una interrupción:** usa una frase completa como “Jarvis, es suficiente” y concede
  permiso de micrófono activando manos libres o usándolo una vez de forma manual. La reproducción
  se pausa al detectar tu voz mientras Whisper valida la frase; pulsar el micrófono la cancela de
  inmediato.
- **Un aviso no aparece en Jarvis:** algunos diálogos protegidos, incluido el escritorio seguro de
  UAC, no exponen controles accesibles y permanecen deliberadamente fuera del motor.
- **La URL móvil no abre:** confirma que Tailscale esté conectado en la PC y el teléfono, reinicia
  Jarvis y revisa `scripts\setup_remote_access.cmd`.
- **La passkey dejó de funcionar:** revoca el teléfono desde **ACCESO MÓVIL** y empareja uno nuevo
  con otro código de un solo uso.
