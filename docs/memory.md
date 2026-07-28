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
se optimizan para ser escuchadas: una a tres oraciones, frases fluidas y sin ofertas genéricas. Una
pregunta de seguimiento solo es apropiada para resolver una ambigüedad real o continuar de forma
natural algo personal que Juandi acaba de compartir.

Kokoro 82M usa de forma predeterminada la voz masculina española `em_alex` a velocidad moderada.
Piper Sharvard queda como respaldo local y, si ambos motores faltan, el navegador intenta elegir
una voz masculina en español instalada en Windows. Todos estos parámetros son configurables desde
`.env`.
