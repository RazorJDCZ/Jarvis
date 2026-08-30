# Arquitectura del agente local 1.0

Jarvis conserva el motor de acciones y sus confirmaciones, pero la decisión ya no depende de
una lista creciente de frases exactas.

## Flujo de una solicitud

1. Los bloqueos y las acciones simples de alta frecuencia pasan por rutas deterministas.
2. El recuperador de capacidades elige como máximo 18 herramientas relevantes del catálogo.
3. Qwen recibe esas funciones con esquemas JSON y propone llamadas nativas. `ActionCatalog`
   vuelve a validar tipos, rangos, rutas, riesgo y política remota antes de ejecutar.
4. Cada observación exitosa entra en `agent-state.sqlite3` con fuente, hora, confianza y TTL. El
   texto generado por el modelo nunca se convierte en un hecho.
5. Una meta que necesita observar y continuar se guarda con límites de rondas y acciones.
   `continúa`, `sigue` o `retoma` permite recuperarla tras reiniciar Jarvis.
6. El modelo 4B resuelve herramientas cotidianas. El 9B se usa solamente para solicitudes largas,
   comparativas o dependientes de observaciones, y se libera al terminar.

## Appa como estado personal

Appa sigue siendo la fuente de verdad; Jarvis no duplica su base de datos. El endpoint privado
`GET /v1/context` reúne tareas abiertas, proyectos activos, agenda, inbox y focus en una sola
lectura autenticada. `appa.briefing` incorpora ese resultado a WorldState durante tres minutos.

## Evaluación

`tests/fixtures/agent_intents.json` contiene formulaciones naturales que no ejecutan acciones. El
script siguiente mide la selección real de Qwen sin tocar la computadora:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_agent.py --model qwen3.5:4b --limit 8
```

Las flechas debajo de cada respuesta guardan evaluaciones exclusivamente en
`.data/agent-feedback.sqlite3`. No se envían a ningún servicio.

## Seguridad conservada

- No hay shell libre ni ejecución de código propuesta por el modelo.
- Acciones medias y altas conservan confirmación; desde el celular la política es más estricta.
- Los objetivos tienen tope de pasos y rondas y se detienen si falta evidencia.
- Portapapeles, contenido de archivos, campos escritos y resultados de desarrollo no se persisten.
- Appa escucha sólo en loopback, exige bearer token y no ofrece borrado ni acceso a archivos.
