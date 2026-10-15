# Integración de Codex con la cuenta de ChatGPT

Jarvis usa Codex como cerebro de razonamiento sin una API key. El proceso local
`codex app-server` conserva la sesión iniciada por `codex login` y expone un protocolo JSON-RPC
por `stdio`; no se abre otro puerto ni se almacenan credenciales dentro del proyecto.

## Flujo

1. Voz o texto entra por la interfaz existente. Whisper, wake word y síntesis siguen locales.
2. Las rutas deterministas resuelven comandos obvios sin consultar un modelo.
3. Para conversación, Jarvis abre un hilo Codex efímero con instrucciones mínimas y envía solo el
   contexto preparado para ese turno.
4. Para acciones ambiguas, Codex devuelve un objeto sujeto a un esquema JSON cerrado. No recibe
   herramientas de Codex ni las acciones de Jarvis.
5. `ActionCatalog` vuelve a validar nombre, argumentos, riesgo, permisos y estado. Las mutaciones
   propuestas por Codex suben al menos a confirmación media.
6. El controlador local ejecuta la acción permitida, verifica el resultado y guarda una observación
   con caducidad. Codex solo puede razonar sobre ella en una ronda posterior.
7. Como excepción explícita para programación, `dev.codex_task` abre otro hilo efímero después de
   una confirmación de riesgo alto. Ese turno puede usar herramientas solamente dentro del proyecto
   seleccionado y no tiene red.

La arquitectura conserva la separación recomendada en las guías de referencia: contexto,
conexiones, habilidades y autonomía son capas diferentes. En este proyecto, memoria/perfil forman
el contexto; correo, calendario, Appa y Windows son conexiones; el catálogo y las skills contienen
el procedimiento; el planificador acotado aporta autonomía. La autonomía solo se amplía después de
validación y nunca convierte al modelo en ejecutor directo.

## Límites de seguridad

- Los turnos normales usan `ephemeral=true`, `approvalPolicy=never` y sandbox de solo lectura.
- `turn/start` vuelve a fijar una política de solo lectura y desactiva red para conversación,
  planificación, correo, portapapeles y visión.
- Las instrucciones base prohíben terminal, archivos, red, plugins, MCP, skills y subagentes.
- Cualquier solicitud interna de herramienta que emita Codex se rechaza en el puente JSON-RPC.
- El único camino que modifica el equipo es el catálogo tipado existente de Jarvis. La acción de
  programación confirmada abre un App Server separado con el perfil `jarvis-project-only`: solo
  la carpeta exacta del proyecto y el directorio temporal del sistema admiten escritura, la red
  está desactivada, los secretos habituales dentro del proyecto quedan bloqueados y no se acepta
  una raíz implícita. El sandbox `elevated` de este Windows exige lectura general para ejecutar las
  herramientas, pero no permite modificar otros proyectos ni carpetas personales.
- Apagado, borrado, pagos, transferencias, terminales y ejecución arbitraria siguen bloqueados.

Dar más libertad significa permitir mejor inferencia, planes de hasta seis pasos y hasta cuatro
rondas verificadas. No significa eliminar límites de riesgo ni ejecutar una suposición sin observar
el resultado anterior.

## Datos y privacidad

Persisten localmente las bases SQLite, credenciales OAuth cifradas, audio, auditoría, perfil,
memoria, adjuntos y estados del agente. Para razonar pueden enviarse a OpenAI el mensaje actual,
fragmentos del historial, recuerdos recuperados, evidencia verificada, contenido de correo o
portapapeles solicitado y capturas seleccionadas para visión.
Los hilos solicitados por Jarvis son efímeros, pero el tratamiento del servicio sigue sujeto a la
cuenta y políticas de OpenAI. Tokens, contraseñas y secretos no deben entrar al prompt.

Ollama continúa siendo opcional únicamente para generar embeddings semánticos locales con
`embeddinggemma`. No participa en conversación, planes, correo, portapapeles ni visión.

## Configuración

```dotenv
JARVIS_BRAIN_MODE=codex
JARVIS_CODEX_COMMAND=codex
JARVIS_CODEX_MODEL=gpt-5.6-luna
JARVIS_CODEX_DEEP_MODEL=gpt-5.6-luna
JARVIS_CODEX_EFFORT=high
JARVIS_CODEX_DEEP_EFFORT=high
JARVIS_CODEX_ACTION_EFFORT=high
JARVIS_CODEX_TIMEOUT=240
JARVIS_CODEX_CODING_TIMEOUT=900
JARVIS_CODEX_CODING_PERMISSIONS=jarvis-project-only
JARVIS_CODEX_STARTUP_TIMEOUT=20
JARVIS_CODEX_MAX_PARALLEL=3
```

`auto` intenta Codex y mantiene un núcleo conversacional limitado si la sesión falla. `codex` es el
modo normal configurado en este equipo. `fallback` no contacta ningún modelo. El modo conversacional
de Ollama ya no está disponible.

Jarvis define el perfil mediante argumentos privados del proceso de programación. No escribe ni
depende de `~/.codex/config.toml`, de modo que una tarea de Jarvis no cambia permisos, sesiones ni
el acceso completo de Codex en VS Code. El proceso aislado se cierra al terminar cada tarea.

Comprobaciones útiles:

```powershell
codex --version
codex login status
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\measure_codex_tokens.py --runs 1
```

La última orden hace dos turnos reales con `gpt-5.6-luna` en `high`: una respuesta conversacional
y una planificación que no se ejecuta. Informa tokens de entrada, entrada cacheada, entrada no
cacheada, salida y razonamiento tal como los publica Codex. Usa datos sintéticos y un directorio
temporal; sí consume cuota de la cuenta porque es una prueba en vivo.

Referencias: [Codex App Server](https://developers.openai.com/codex/app-server/),
[autenticación de Codex](https://developers.openai.com/codex/auth/),
[mapa de cuatro capas](https://app.notion.com/p/El-mapa-de-mi-Jarvis-las-4-capas-y-los-8-pasos-3e65639562328150aeb3dc0694f2a24a)
y [guía de cinco piezas](https://app.notion.com/p/Crea-tu-propio-Jarvis-en-un-fin-de-semana-la-gu-a-completa-de-5-pasos-3e9845d3373a81198fa5f7d7456c218a).
