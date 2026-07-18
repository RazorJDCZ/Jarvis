# JARVIS Local Core

Asistente de voz privado y local para Windows. El proyecto está dividido en cinco etapas:

1. MVP de voz — completado.
2. Motor de acciones — completado en esta versión (`0.2.0`).
3. Acceso móvil.
4. Memoria y personalidad.
5. Visión y proactividad — la percepción visual básica se adelantó a la etapa 2; la proactividad
   sigue pendiente.

## Qué hace esta versión

- Conversa por texto o voz con Qwen mediante Ollama, sin pagar por cada solicitud.
- Transcribe localmente con Faster Whisper y habla con Piper o las voces de Windows.
- Ofrece modo pulsar-para-hablar y manos libres con la frase “Jarvis”.
- Ejecuta 47 acciones tipadas sobre Windows, aplicaciones, pantalla y un navegador controlado.
- Interpreta primero órdenes deterministas y usa el modelo local como traductor restringido cuando
  una orden directa no coincide exactamente.
- Entiende variantes coloquiales y puede preparar flujos explícitos de dos o tres pasos con una
  confirmación calculada según el riesgo más alto.
- Describe, consulta y localiza elementos en la pantalla mediante el modelo visual local de Ollama;
  las capturas transitorias se mantienen en memoria.
- Muestra confirmaciones de seguridad en la interfaz y también acepta “confirma” o “cancela”.
- Registra una auditoría local con los argumentos y resultados sensibles censurados.
- Mantiene historial temporal por sesión y permite borrarlo.
- Funciona como PWA, aunque durante las etapas 1 y 2 el servidor escucha únicamente en
  `127.0.0.1`.

El modo manos libres detecta la frase de activación después de transcribir localmente cada
intervención. Una etapa posterior podrá incorporar openWakeWord para reducir el consumo continuo.

## Instalación

Desde el Explorador de Windows, ejecuta:

```text
setup.cmd
```

El instalador crea `.venv`, instala las dependencias dentro del proyecto, descarga una voz Piper de
aproximadamente 77 MB y Whisper `small` (aproximadamente 464 MB). No cambia la política de ejecución
de PowerShell. Si ya instalaste la etapa 1, vuelve a ejecutar `setup.cmd` para agregar Playwright,
PyWinAuto, PyCAW y los demás componentes del motor de acciones.

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

## Acciones disponibles

### Aplicaciones y ventanas

- “Abre la calculadora”, “abre el bloc de notas”, “abre Paint”, “abre Configuración”.
- “Abre Spotify”. Las aplicaciones encontradas en accesos directos confiables del menú Inicio
  requieren confirmación.
- “Lista las ventanas”, “cuál es la ventana actual”, “cambia a la ventana de Spotify”.
- “Minimiza la ventana”, “maximiza la ventana de Edge”, “restaura la ventana”.
- “Cierra la ventana de Paint” requiere confirmación.

Jarvis espera y verifica la aparición de la ventana al iniciar una aplicación. Si ya estaba abierta,
la trae al frente en lugar de crear copias innecesarias.

### Navegador controlado

- “Abre github.com”, “abre YouTube”, “busca en Google clima en Quito”.
- “Atrás”, “página siguiente”, “recarga la página”.
- “Abre una nueva pestaña”, “lista las pestañas”, “cambia a la pestaña GitHub”.
- “Lee la página”.
- “Escribe Juandi en el campo Nombre” llena el campo, pero nunca lo envía automáticamente.
- “Abre el primer resultado” activa un resultado visible después de confirmar.
- “Haz clic en Aceptar” y “cierra la pestaña” requieren confirmación.

Jarvis abre una ventana InPrivate visible de Microsoft Edge con un perfil aislado en `.data`. Esto
permite control y verificación mediante el árbol accesible del sitio sin acceder a las sesiones,
cookies ni contraseñas de tu navegador habitual. Las pestañas y la sesión privada se cierran con
Jarvis.

### Audio, multimedia y escritorio

- “Pon el volumen al 42 por ciento”, “súbele el volumen”, “silencia el sonido”, “dime el volumen”.
- “Pausa”, “siguiente canción”, “pista anterior”, “detén la música”.
- “Muestra los controles”, “haz clic en el control Guardar”.
- `escribe "Texto con acentos"`, “guarda”, “deshaz”, “presiona intro”.
- “Haz scroll abajo 8”, “muestra el escritorio”.
- “Haz clic en 400, 250” es una acción de riesgo alto y exige confirmación.
- “Captura la pantalla” requiere confirmación y guarda la imagen solo dentro de `.data`.

### Pantalla y flujos encadenados

- “Describe lo que ves”, “¿qué aparece en la pantalla?” y “encuentra el botón Continuar” usan
  visión local y requieren confirmación porque la pantalla puede contener información privada.
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
- URLs limitadas a HTTP/HTTPS; sin credenciales incrustadas. Edge usa un perfil aislado.
- Aplicaciones fijas usan comandos conocidos sin shell. Accesos del menú Inicio se resuelven y se
  rechazan si apuntan a terminales o intérpretes bloqueados.
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
auditoría, flujos encadenados, visión, controlador de Windows, navegador, API, voz y regresiones de
la etapa 1. El esquema
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
- **Piper no aparece disponible:** repite `setup.cmd`; las voces de Windows seguirán disponibles.
- **Manos libres se activa solo:** desactívalo, reduce el ruido y vuelve a activarlo para recalibrar.
