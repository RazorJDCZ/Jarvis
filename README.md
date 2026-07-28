# JARVIS Local Core

Asistente de voz privado y local para Windows. El proyecto está dividido en cinco etapas:

1. MVP de voz — completado.
2. Motor de acciones — completado en esta versión (`0.2.0`).
3. Acceso móvil.
4. Memoria y personalidad — implementada en esta versión.
5. Visión y proactividad — la percepción visual multimonitor y contextual ya está implementada;
   la proactividad sigue pendiente.

## Qué hace esta versión

- Conversa por texto o voz con Qwen mediante Ollama, sin pagar por cada solicitud.
- Transcribe localmente con Faster Whisper y habla con la voz masculina `em_alex` de Kokoro 82M;
  Piper y las voces de Windows quedan como respaldos automáticos.
- Ofrece modo pulsar-para-hablar y manos libres con la frase “Jarvis”.
- Ejecuta 49 acciones tipadas sobre Windows, aplicaciones, pantalla y navegadores controlados.
- Interpreta primero órdenes deterministas y usa el modelo local como traductor restringido cuando
  una orden directa no coincide exactamente.
- Entiende variantes coloquiales y puede preparar flujos explícitos de dos o tres pasos con una
  confirmación calculada según el riesgo más alto.
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
- Funciona como PWA, aunque durante las etapas 1 y 2 el servidor escucha únicamente en
  `127.0.0.1`.

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

### Modelo conversacional

La interfaz arranca sin Ollama usando un núcleo limitado. Para instalar la edición portátil dentro
del proyecto y descargar el modelo recomendado, ejecuta:

```text
scripts\install_ollama.cmd
```

Jarvis iniciará ese Ollama automáticamente y lo apagará al cerrar `start.cmd`. También puede usar
una instalación que ya responda en `http://127.0.0.1:11434`.

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
  nunca se envía a Open-Meteo ni Wikipedia.
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
la conversación realmente la amerita.

### Audio, multimedia y escritorio

- “Pon el volumen al 42 por ciento”, “súbele el volumen”, “silencia el sonido”, “dime el volumen”.
- “Pausa”, “siguiente canción”, “pista anterior”, “detén la música”.
- “Muestra los controles”, “haz clic en el control Guardar”.
- `escribe "Texto con acentos"`, “guarda”, “deshaz”, “presiona intro”.
- “Haz scroll abajo 8”, “muestra el escritorio”.
- “Haz clic en 400, 250” es una acción de riesgo alto y exige confirmación.
- “Captura la pantalla” requiere confirmación y guarda la imagen solo dentro de `.data`.

### Pantalla y flujos encadenados

- “¿Qué monitores están conectados?” enumera las pantallas activas y señala la principal.
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
  confirmación de riesgo medio. Se admiten hasta tres acciones explícitas y el flujo se detiene si
  un paso falla.
- También se aceptan formas naturales como “¿me abres YouTube?”, “búscame restaurantes cerca”,
  “quiero que abras la calculadora” o “deja el sonido aproximadamente a la mitad”.

La visión funciona únicamente contra Ollama en `127.0.0.1` o `localhost`. El texto visible se trata
como datos no confiables: una instrucción escrita dentro de una página o imagen nunca puede ampliar
los permisos del motor.

### Sistema, portapapeles y archivos

- “Estado del sistema” informa CPU, memoria y batería cuando está disponible.
- “Lee el portapapeles” y `copia "Texto" al portapapeles` requieren confirmación.
- “Abre la carpeta Descargas”.
- `abre el archivo "D:\Datos\reporte.pdf"` requiere confirmación. Solo se permiten formatos
  comunes de documentos sin macros, texto, imagen, audio, video y archivos ZIP.
- “Dime la hora”, “dime la fecha”, “qué versión eres”, “ayuda”.
- “Olvida esta conversación”.

La referencia completa de acciones, riesgos y límites está en
[docs/action-engine.md](docs/action-engine.md).

## Seguridad

- No existe ninguna acción de PowerShell, CMD, terminal ni comandos arbitrarios.
- Apagar, reiniciar, borrar, formatear, comprar, pagar o transferir están bloqueados.
- Los controles cuyo nombre indica compra, transferencia o eliminación tampoco se activan.
- Los clics visuales estimados por píxeles nunca se realizan en el mismo paso que la detección: se
  mueve el cursor y se exige una confirmación adicional.
- Cada acción pertenece a un catálogo cerrado y valida tipo, longitud, rango y formato de sus
  argumentos antes de ejecutarse.
- Las mutaciones sugeridas por el modelo local se elevan automáticamente a confirmación aunque la
  acción normalmente sea de riesgo bajo.
- Las confirmaciones están vinculadas a la sesión, tienen identificadores impredecibles, expiran y
  no pueden reutilizarse desde otra sesión.
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
- El servidor acepta únicamente loopback, rechaza orígenes ajenos y aplica CSP, Permissions Policy
  y límites de tamaño.
- Los audios temporales se eliminan al terminar la transcripción. `.env`, modelos, temporales,
  auditoría y el entorno virtual están excluidos de Git.
- El análisis visual rechaza servidores externos y no guarda su captura transitoria en disco.

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
JARVIS_SAFE_ACTIONS_ENABLED=true
JARVIS_ACTION_MODEL_PLANNING=true
JARVIS_ACTION_CONFIRMATION_SECONDS=90
JARVIS_VISION_ACTIONS_ENABLED=true
JARVIS_VISION_TIMEOUT=180
JARVIS_BROWSER_SEARCH_URL=https://www.google.com/search?q={query}
```

`JARVIS_BROWSER_SEARCH_URL` debe ser HTTP/HTTPS y contener exactamente `{query}`. Puedes apagar todo
el motor con `JARVIS_SAFE_ACTIONS_ENABLED=false`, desactivar solo la interpretación flexible con
`JARVIS_ACTION_MODEL_PLANNING=false` o apagar la percepción visual con
`JARVIS_VISION_ACTIONS_ENABLED=false`.

## Desarrollo y pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
node --check src\jarvis\web\app.js
```

La suite cubre parser, catálogo, niveles de riesgo, confirmaciones, aislamiento por sesión,
auditoría, flujos encadenados, visión, controlador de Windows, navegador personal, verificación de
información, perfil privado, API, voz y regresiones de la etapa 1. El esquema
OpenAPI está disponible localmente en `http://127.0.0.1:8765/api/openapi.json`.

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
