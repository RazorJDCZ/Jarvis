# Mejoras del asistente y del acceso móvil

Implementación y pruebas realizadas el 6 de septiembre de 2026. La configuración local aplicada
se conserva en `.env`; su copia anterior está en `.data/env-before-assistant-upgrade.env`.

## Las siete mejoras

| Mejora | Comportamiento disponible |
| --- | --- |
| Respuesta progresiva | Texto mediante NDJSON y voz por frases completas; cancelación de la petición y cola de voz. |
| Activación ligera | openWakeWord local evita transcribir intervenciones sin «Hey Jarvis». Es opcional y requiere pronunciación inglesa; «Jarvis» compatible sigue disponible. |
| Memoria editable | Consultar, corregir, eliminar y exportar recuerdos desde la consola de la PC; editar campos del perfil con copia de respaldo. Ediciones de recuerdos verifican conflictos. |
| Rutinas y proactividad | Preparar el día, consultar tareas/recordatorios y preparar estudio; resumen diario y avisos anticipados configurables con horario de silencio. |
| Biblioteca semántica | embeddinggemma local busca fragmentos por significado con fuente y número de fragmento; PDFs conservan marcas de página. Respaldo textual si el modelo falla. |
| Ajustes y diagnóstico | Pestaña Asistente: voz, velocidad, micrófono, modo compacto y tiempos de conexión/respuesta. Los ajustes del equipo y la memoria se modifican desde la PC. |
| Recursos adaptativos | Qwen 4B para uso habitual, 9B reservado para solicitudes complejas con RAM suficiente; retención breve del modelo, límites de hilos y Whisper GPU/CPU. |

Las notificaciones pendientes ahora sobreviven a reinicios y requieren confirmación de recepción
del cliente. La evaluación `--fixture all` incluye los cinco archivos; admite verificar argumentos
y todos los pasos esperados de un plan.

Las rutinas nuevas utilizan el catálogo de acciones y sus confirmaciones. Los avisos se entregan
cuando la interfaz puede conectarse; no se añadió un servicio de notificaciones push del sistema
operativo para despertar un teléfono con el navegador cerrado.

## Ajuste al equipo

Se midieron un Intel i5-10400F (6 núcleos/12 hilos), 15,86 GiB de RAM y una RTX 3050 con
6 GiB de VRAM. Qwen 4B ocupa aproximadamente 3,2 GB de GPU con contexto de 4096 tokens.
Con el escritorio y Qwen activos queda poco espacio para Whisper: se usa CPU como respaldo;
con GPU libre, Whisper utiliza float16 y devuelve sus pesos a RAM al terminar la transcripción.
Kokoro emplea tres hilos y Whisper cuatro. Los vectores se recorren sin cargar toda la biblioteca
en RAM; embeddinggemma usa CPU y se descarga después de la operación.

La adaptación conserva Qwen hasta tres minutos cuando hay al menos 2,5 GiB de RAM libre.
La vigilancia cada 15 segundos solicita descargarlo si quedan menos de 1,8 GiB de RAM o
512 MiB de VRAM. El modelo 9B necesita al menos 8 GiB de RAM libre para ser candidato.
Esto reduce recargas entre peticiones; una consulta tras inactividad puede volver a pagar el
costo de cargar el modelo. La PC debe permanecer encendida y Jarvis/Tailscale activos.

## Mediciones reales

Son muestras locales con texto y audio sintéticos; no representan percentiles ni incluyen la
red del teléfono. La longitud del audio, la respuesta y las otras aplicaciones cambian los tiempos.

| Prueba del servicio completo | Tiempo medido |
| --- | --- |
| «Dime la hora» por texto | 0,087 s, respuesta completa |
| Historia breve, carga inicial de Qwen | 9,698 s al primer texto; 11,272 s completa |
| Segunda historia, Qwen cargado | 1,192 s al primer texto; 3,691 s completa |
| Síntesis de «Dime la hora» con Kokoro preparado | 0,553 s para generar el WAV |
| Audio «Dime la hora», primer uso del respaldo CPU | 5,079 s, respuesta completa |
| Mismo audio, respaldo CPU preparado | 2,654 s, respuesta completa |

Antes de corregir la clasificación, una petición de historia entraba al planificador y tardaba
45 s en pedir una aclaración. Ahora esa petición entra directamente a conversación. Ese fallo
de clasificación tiene pruebas de regresión, incluyendo destinos explícitos como el bloc de notas.

Una prueba separada con la misma frase de audio midió Whisper preparado en 2,796 s en CPU
frente a 0,344 s en GPU; esa aceleración requiere VRAM disponible. El ensayo aislado de Qwen
midió 8,954 s para la respuesta completa descargando el modelo, frente a 1,861 s al reutilizarlo
(primer texto a los 0,663 s). La comparación del servicio completo de arriba es más representativa.

## Validación

- 826 pruebas aprobadas y 3 omitidas por sus condiciones de entorno.
- Ruff y comprobación sintáctica de los tres archivos JavaScript sin errores.
- Navegador Chrome automatizado en escritorio y pantalla móvil: texto y primer audio antes de
  terminar la generación, edición de memoria, ajustes, diagnóstico y cancelación; sin errores JS.
- Acceso remoto con credencial WebAuthn virtual, reautenticación, confirmaciones y parada de
  emergencia comprobados en la prueba existente del navegador.
- Modelos reales: Qwen, Kokoro, Whisper, búsqueda semántica con cita y detector ligero con
  frases positivas inglesas y negativas. El audio sintético español no activó de forma fiable
  openWakeWord; por eso el modo compatible permanece predeterminado.

Los resultados locales están en `.data/live-assistant-verification.json`,
`.data/assistant-benchmark.json`, `.data/stt-gpu-benchmark.json` y `.data/wake-benchmark.json`.
Se pueden repetir con `scripts/verify_live_assistant.py`, `scripts/benchmark_assistant.py`,
`scripts/smoke_assistant_upgrade.py` y `scripts/verify_lightweight_wake.py`.
El benchmark de modelos consume recursos: ejecútalo separado de otras pruebas.

## Probar desde el celular

1. Cierra y vuelve a abrir la PWA o recarga su página para recibir la interfaz actualizada.
2. Escribe «Dime la hora» y después pide una historia breve; repite para comparar el modelo cargado.
3. Prueba la misma petición pulsando para hablar y verifica que puedas interrumpir la respuesta.
4. Abre Control Deck → Asistente → Diagnosticar conexión y respuesta para consultar tiempos.
5. Prueba modo compacto y, si deseas el detector ligero, selecciona «Hey Jarvis» y pronúncialo en inglés.

Si la red móvil continúa lenta, esos tiempos ayudan a separar red, transcripción y generación.
No se midió el enlace físico de tu celular durante la implementación.

## Referencias técnicas

Se usó la transmisión nativa documentada en [Ollama](https://docs.ollama.com/api/streaming)
y la [API de embeddings](https://docs.ollama.com/api/embed). La detección opcional utiliza
[openWakeWord](https://github.com/dscripka/openWakeWord). El traslado de pesos de Whisper
entre dispositivos usa [CTranslate2 Whisper](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html).
