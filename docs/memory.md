# Memoria y personalidad — etapa 4

## Capas de contexto

Jarvis mantiene cuatro capas separadas para no mezclar datos con instrucciones:

1. El perfil base confirmado en `.data/user_profile.json`.
2. Recuerdos duraderos y selectivos en `.data/memory.sqlite3`.
3. Una ventana limitada de intercambios recientes agrupados por sesión, con retención
   predeterminada de 30 días.
4. El historial temporal de la sesión activa, que permanece en memoria RAM.

Solo los recuerdos relacionados con la consulta actual se añaden al prompt. Los fragmentos de
sesiones anteriores se añaden únicamente en el primer mensaje de una sesión nueva. El perfil, los
recuerdos y el diálogo previo se delimitan como datos; nunca pueden reemplazar las instrucciones de
seguridad del sistema.

La continuidad entre sesiones se filtra por palabras relevantes y solo reutiliza lo que Juan Diego
dijo, no respuestas antiguas del modelo. Así una alucinación previa no puede convertirse en aparente
contexto personal ni contaminar una pregunta sobre otra persona.

## Aprendizaje

El extractor determinista reconoce datos claros sobre ubicación, estudios, trabajo, relaciones,
preferencias, proyectos y objetivos. Una frase explícita como “recuerda que…” siempre tiene
prioridad. Las preguntas, órdenes sobre la computadora y estados pasajeros no se almacenan.

Contraseñas, tokens, códigos de acceso, claves privadas, frases semilla y datos bancarios se
rechazan tanto en recuerdos como en el historial persistente. No se usa un modelo externo ni se
envía el contenido de la memoria por red.

## Almacenamiento y límites

- SQLite en modo WAL con `synchronous=NORMAL`, `secure_delete=ON` e índices por categoría y fecha.
- Actualización por clave estable para no duplicar datos como residencia, estudios o relaciones.
- Máximo predeterminado de 500 recuerdos y 60 pares conversacionales. La interfaz cuenta sesiones
  distintas e intercambios por separado; no presenta cada par como una conversación nueva.
- Un intercambio consecutivo idéntico no se inserta dos veces.
- Los pares conversacionales caducan después de 30 días.
- Los límites pueden ajustarse con las variables `JARVIS_MEMORY_*` de `.env.example`.
- Olvidar un dato elimina su fila y compacta la base. Borrar todo exige confirmación de voz,
  vacía recuerdos y conversaciones, trunca el WAL y conserva el perfil base.

## Personalidad y voz

El prompt define una personalidad gentil, servicial, serena y ligeramente ingeniosa. Las respuestas
se optimizan para ser escuchadas: una o dos oraciones para hechos simples y de tres a seis oraciones
sustantivas para conversación, opinión o análisis normal, con frases fluidas y sin ofertas genéricas.
Una pregunta de seguimiento solo es apropiada para resolver una ambigüedad real o continuar de forma
natural algo personal que Juan Diego acaba de compartir.

Los datos sobre personas importantes son apuntes privados estructurados. Las preguntas de identidad
como “¿quién es?” usan una ruta factual determinista para no inventar personas, estudios ni
relaciones. Una pregunta reflexiva sobre una sola persona usa una composición local fundamentada:
sintetiza hechos, marca límites y evita convertir carreras, aficiones o roles de grupo en rasgos
inventados. Las comparaciones que sí necesitan el modelo reciben únicamente la pregunta y evidencia
actuales, nunca las respuestas de un tema anterior. Si el perfil no contiene evidencia suficiente,
Jarvis rechaza el análisis con honestidad.

Las consultas sobre Juan Diego tienen una separación adicional. “¿Quién soy?” es factual y “¿qué
recuerdas de mí?” consulta la memoria; en cambio, “¿qué sabes de mí?”, “¿cómo me describirías?”,
“¿qué impresión tienes de Juan Diego?” y “analízame” son reflexivas. Para estas últimas se recupera
el perfil propio completo, sin incluir las descripciones privadas de cada amigo, y se usa una
composición analítica local. Solo admite conexiones respaldadas entre estudios, prácticas,
proyectos, metas, rutina, visión futura y preferencias operativas. Gustos, herramientas y reglas de
seguridad no se convierten en rasgos psicológicos, y una debilidad solo se presenta como riesgo
práctico cuando el perfil no aporta evidencia de que ya exista.

Una intención analítica ofrece un modo profundo opcional. La confirmación verbal o escrita “sí,
profundiza” vuelve a procesar la solicitud original con una tesis, varios ángulos, alternativas,
implicaciones y una conclusión útil; rechazarla produce la respuesta analítica normal. Una petición
explícita como “analiza a fondo” no pregunta dos veces. El plazo de confirmación se configura con
`JARVIS_DEEP_ANALYSIS_CONFIRMATION_SECONDS` y el flujo completo puede desactivarse con
`JARVIS_DEEP_ANALYSIS_CONFIRMATION_ENABLED=false`.

Kokoro 82M usa de forma predeterminada la voz masculina española `em_alex` a velocidad moderada.
Piper Sharvard queda como respaldo local y, si ambos motores faltan, el navegador intenta elegir
una voz masculina en español instalada en Windows. Todos estos parámetros son configurables desde
`.env`.
