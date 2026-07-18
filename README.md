# JARVIS Local Core

MVP de voz privado y local para Windows. Esta es la **etapa 1 de 5** del proyecto:

1. MVP de voz — completado.
2. Motor de acciones.
3. Acceso móvil.
4. Memoria y personalidad.
5. Visión y proactividad.

## Qué hace esta versión

- Interfaz futurista adaptable a escritorio y móvil.
- Conversación escrita y por voz.
- Captura de micrófono con cancelación de eco y ruido del navegador.
- Transcripción local con Faster Whisper.
- Conversación local con Qwen 3.5 mediante Ollama.
- Síntesis local con Piper y respaldo automático en las voces de Windows.
- Modo pulsar-para-hablar y modo manos libres con la frase “Jarvis”.
- Historial temporal por sesión y botón de borrado.
- Comandos locales seguros mediante una lista blanca estricta.
- Estados visuales y telemetría de cada proveedor.
- PWA instalable; el servidor sigue limitado a `127.0.0.1` en esta etapa.

El modo manos libres actual detecta la frase de activación después de transcribir localmente cada
intervención. Esto nos permite validar todo el flujo sin dejar una dependencia crítica en un modelo
de wake word. En una iteración posterior se podrá incorporar openWakeWord para reducir consumo.

## Instalación

Desde el Explorador de Windows, ejecuta:

```text
setup.cmd
```

El script crea `.venv`, instala dependencias únicamente dentro del proyecto, descarga una voz
Piper española de aproximadamente 77 MB y Whisper `small` (aproximadamente 464 MB). No modifica la
política de ejecución de PowerShell.

Después inicia la aplicación con:

```text
start.cmd
```

Se abrirá `http://127.0.0.1:8765`. La primera transcripción cargará el modelo Whisper configurado y
puede tardar un poco más que las siguientes.

### Modelo conversacional

La UI y el pipeline pueden arrancar sin Ollama usando un núcleo limitado de respaldo. Para instalar
la edición portátil dentro de este mismo proyecto y descargar el modelo recomendado, ejecuta:

```text
scripts\install_ollama.cmd
```

La descarga ocupa varios GB. Jarvis iniciará ese Ollama automáticamente, lo mantendrá oculto y lo
apagará al cerrar `start.cmd`. También puede conectarse a una instalación normal que ya esté activa
en `http://127.0.0.1:11434`.

## Uso

- Mantén presionado el núcleo central mientras hablas; también puedes mantener la barra espaciadora.
- Activa **Manos libres**, guarda silencio durante la breve calibración y di “Jarvis”.
- Puedes decir “Jarvis, dime la hora” en una frase, o decir primero “Jarvis” y después la orden.
- Pulsa **Respuesta de voz** para silenciar o reactivar el audio.
- Escribe en la consola derecha si no quieres usar el micrófono.

### Comandos locales seguros

Jarvis reconoce estas órdenes sin depender del modelo conversacional:

- “Dime la hora”, “dime la fecha”, “¿qué versión eres?” y “ayuda”.
- “Olvida esta conversación”.
- “Abre la calculadora”, “abre el bloc de notas” y “abre el explorador”.
- “Sube el volumen”, “baja el volumen” y “silencia el sonido”.

Las acciones del sistema solo aceptan frases completas predefinidas. No se interpreta texto como
PowerShell, CMD, rutas, argumentos ni nombres arbitrarios. Puedes desactivarlas con
`JARVIS_SAFE_ACTIONS_ENABLED=false` en `.env`.

El navegador pedirá permiso para el micrófono la primera vez. El audio se envía solamente al servidor
local en esta computadora.

## Configuración

`setup.cmd` crea `.env` a partir de `.env.example`. Las opciones más útiles son:

```dotenv
JARVIS_OLLAMA_MODEL=qwen3.5:4b
JARVIS_STT_MODEL=small
JARVIS_STT_DEVICE=cpu
JARVIS_STT_COMPUTE_TYPE=int8
JARVIS_WAKE_WORD=jarvis
JARVIS_MAX_SESSIONS=64
JARVIS_SAFE_ACTIONS_ENABLED=true
```

La configuración CPU/int8 es deliberadamente conservadora para evitar conflictos entre Whisper y
el modelo conversacional dentro de los 6 GB de VRAM de la RTX 3050. Más adelante mediremos si conviene
mover Whisper a CUDA.

## Desarrollo y pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

La entrega de la etapa 1 cuenta con 90 pruebas automatizadas, además de verificaciones reales del
pipeline Piper → Whisper → Qwen.

El esquema OpenAPI del backend está disponible localmente en
`http://127.0.0.1:8765/api/openapi.json`.

## Seguridad de esta etapa

- El servidor escucha exclusivamente en loopback; ningún otro equipo puede conectarse todavía.
- Las solicitudes web de otros orígenes se rechazan y la UI aplica una política CSP restrictiva.
- No hay shell, ejecución de comandos arbitrarios ni acceso a archivos del usuario.
- Las pocas acciones disponibles usan una lista blanca de ejecutables fijos y teclas multimedia.
- Los audios temporales se borran al terminar cada transcripción.
- El historial vive en memoria y desaparece al detener Jarvis o pulsar reiniciar.
- `.env`, modelos, temporales y el entorno virtual quedan fuera de Git.

La exposición por Tailscale, autenticación de dispositivos y permisos por nivel llegarán en las
etapas 2 y 3, antes de aceptar acciones remotas.

## Solución rápida de problemas

- **El micrófono no abre:** permite el acceso a `127.0.0.1` en Edge o Chrome.
- **La primera frase tarda mucho:** Whisper está descargando/cargando su modelo por primera vez.
- **CORE aparece limitado:** instala/inicia Ollama y ejecuta `ollama pull qwen3.5:4b`.
- **Piper no aparece disponible:** repite `setup.cmd`; la voz de Windows seguirá funcionando.
- **Manos libres se activa solo:** desactívalo, reduce el ruido y vuelve a activarlo para recalibrar.
