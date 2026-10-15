# Diagnóstico de lenguaje de Jarvis — 22 de septiembre de 2026

Jarvis todavía no interpreta la conversación cotidiana con la consistencia esperada. Reconoce muchos saludos, correcciones sencillas y mensajes con errores de escritura, pero falla en expresiones figuradas, ironías, referencias entre personas y reconocimiento de ambigüedad. Además, completa algunos vacíos con hechos inventados y suele extenderse sin necesidad. Corregir el enrutamiento de un saludo no demuestra que el modelo comprenda bien el resto del lenguaje.

Se obtuvieron y revisaron **207 respuestas reales del modelo local**: 137 de la batería principal, 38 de repeticiones y reformulaciones, y 32 de una comparación de instrucciones. Las primeras 175 respuestas corresponden a 129 diálogos. No se ejecutaron herramientas de Jarvis ni se accedió a correos, calendario o archivos personales para responder.

## Resultado principal

Cada intervención tenía un criterio escrito antes de generar la respuesta. La evaluación semántica fue manual, realizada por el asistente; no fue ciega ni contó con varios evaluadores independientes.

| Evaluación | Respuestas | Significado |
| --- | ---: | --- |
| Satisfactoria, 2 puntos | 68 | Cumple la intención y la restricción principal; puede tener defectos menores de estilo. |
| Parcial, 1 punto | 51 | Entiende parte del mensaje, pero añade suposiciones, irrelevancias o incumple alguna instrucción. |
| Fallo central, 0 puntos | 18 | Confunde el significado, se contradice o inventa contexto o actividad de forma grave. |
| Total principal | 137 | Casos seleccionados para detectar debilidades. |

Estos números **no representan un porcentaje de comprensión general del español**: se eligieron expresamente casos difíciles, los turnos de un mismo diálogo no son independientes y la rúbrica incluye pertinencia y cumplimiento, además de comprensión. Las repeticiones se concentraron en errores ya encontrados, por lo que tampoco deben mezclarse con la batería principal para anunciar una tasa global.

| Grupo | Satisfactorias | Parciales | Fallos centrales |
| --- | ---: | ---: | ---: |
| Saludos y conversación social | 3 | 4 | 1 |
| Expresiones coloquiales de Ecuador | 4 | 4 | 2 |
| Expresiones figuradas | 5 | 3 | 2 |
| Ironía y humor | 2 | 4 | 2 |
| Emociones y límites conversacionales | 6 | 1 | 1 |
| Errores de escritura y mezcla de idiomas | 7 | 1 | 0 |
| Negaciones y citas | 6 | 2 | 2 |
| Ambigüedad | 1 | 2 | 3 |
| Correcciones del usuario | 6 | 13 | 2 |
| Contexto y referencias | 14 | 10 | 1 |
| Restricciones de respuesta | 4 | 0 | 2 |
| Conversación larga | 10 | 7 | 0 |

## Hallazgos concretos

| Entrada o situación | Comportamiento observado | Interpretación esperada |
| --- | --- | --- |
| «¿Qué has hecho mientras no estaba?» | Inventó revisión de archivos, correos, calendario o mantenimiento; volvió a hacerlo en repeticiones. | Responder sin atribuirse actividad no registrada. |
| «Se me cruzaron los cables cuando me preguntaron eso» | En dos de las tres primeras muestras lo llevó a cables físicos; en otra captó la confusión mental. | Entender el bloqueo o la confusión en ese contexto. |
| «Me dejaron en visto y ya me hice mil películas» | Habló de cine, películas y proyectos creativos en las tres primeras muestras. | Entender que la persona imaginó explicaciones o escenarios al no recibir respuesta. |
| «Solo Ana no vino; Luis y Carla sí llegaron. ¿Quién faltó?» | En la primera respuesta dijo Juan Diego; en repeticiones sí respondió Ana. | Ana, de manera consistente. |
| «Ana vio a Laura cuando salía de clase. ¿Quién salía?» | Llegó a inventar que Juan Diego salía con ambas; otras variantes aseguraron que era Laura. | Reconocer que la oración permite más de una interpretación. |
| Laura presta su libro a Mateo; él se lo devuelve; se pregunta quién lo tiene. | Contestó Mateo y después explicó que lo había devuelto a Laura. También alteró una referencia temporal. | Laura; mantener coherencia entre conclusión y explicación. |
| «Sí, claro, porque dormir tres horas es la receta del éxito» | Interpretó como positiva o sincera una formulación irónica. | Reconocer la ironía en vez de desarrollar la idea literal. |
| «Estoy feliz... se nota muchísimo 🙃» | Supuso felicidad; algunas respuestas añadieron una cita, sonrisa u otros detalles no aportados. | Contemplar un tono irónico o mixto, sin dar por hecho el estado emocional. |
| Aclaración de que un ensayo requiere 800 palabras | En un diálogo introdujo 780 y caracteres antes de volver a 800; una repetición respondió correctamente pero divagó. | Mantener 800 palabras y confirmar de forma directa. |
| Significado de «estar chiro» en Ecuador | Una reformulación explícita produjo una definición invertida, relacionada con tener dinero. | Reconocer la expresión regional o admitir desconocimiento. |

También hubo resultados positivos: entendió varias faltas de ortografía y mezclas de español e inglés; aceptó correcciones como martes → jueves y gato → perro; resolvió referencias sencillas entre dos cuadernos y una selección de la segunda opción; respetó varias peticiones de escuchar sin dar consejos; y distinguió algunos condicionales y negaciones correctamente.

En un diálogo de 17 intervenciones conservó varios datos y una corrección numérica, pero perdió la asociación de una palabra clave al final. Parte de la información conservada había sido repetida por el propio modelo: eso no demuestra recuerdo intacto del inicio. La configuración permite 16 mensajes de historial, aproximadamente ocho intercambios; esta prueba tuvo la memoria persistente desactivada.

## Comparación de instrucciones

Se compararon las instrucciones actuales con una alternativa breve sobre ocho casos problemáticos, usando dos semillas por caso y variante: 32 respuestas. Se mantuvieron el modelo y los parámetros de generación. La alternativa pidió contestar directamente, interpretar el contexto, reconocer ambigüedades y no inventar hechos.

| Variante | Satisfactorias | Parciales | Fallos centrales |
| --- | ---: | ---: | ---: |
| Instrucciones actuales | 2 | 2 | 12 |
| Alternativa breve | 6 | 3 | 7 |

La alternativa reconoció mejor la ironía sobre dormir tres horas y evitó algunos relatos de actividad inventada. Aun así, falló con el emoji irónico, «hacerme películas» y las dos frases ambiguas. Algunas respuestas breves negaron capacidades de forma demasiado general, por lo que **esa alternativa no está lista para incorporarse sin ajustes**.

La comparación indica que las instrucciones influyen y que simplificarlas merece una prueba más amplia. No permite atribuir la mejora únicamente a la longitud: también cambió el contenido y se retiraron referencias a la identidad del usuario. Tampoco demuestra que cambiar solo las instrucciones resuelva el problema del modelo.

## Qué parece estar ocurriendo

1. **Comprensión irregular del modelo en su configuración actual.** Los errores semánticos aparecen incluso con las herramientas ausentes. La variación entre repeticiones muestra que un ejemplo correcto aislado no basta para validar una capacidad.
2. **Contaminación por las instrucciones personales.** El nombre Juan Diego aparece en respuestas sobre relatos que no lo incluyen. Las instrucciones actuales mencionan al usuario repetidamente. Es una hipótesis compatible con lo observado; no una causa aislada demostrada.
3. **Tendencia a rellenar y sobreexplicar.** Introduce causas psicológicas, actividades o detalles personales sin evidencia. La longitud adicional a veces transforma una respuesta parcialmente correcta en una contradicción.
4. **Gestión limitada del contexto reciente.** La ventana de mensajes y las repeticiones del modelo influyen en qué información queda disponible. Esta evaluación no mide la memoria persistente de producción.
5. **Quedan candidatos de enrutamiento por revisar.** La inspección del parser encontró cero acciones deterministas, tres candidatos explícitos y 35 candidatos semánticos en la batería principal. Ser candidato no significa ejecutar una acción: el planificador posterior puede descartarlo y estuvo desactivado. No deben contarse como 38 ejecuciones erróneas ni como una tasa de fallo del motor completo.

## Prioridades recomendadas

1. Simplificar y unificar las instrucciones conversacionales, separando identidad del usuario, hechos disponibles y solicitudes operativas. Validar con esta batería y con ejemplos nuevos que no se hayan utilizado para ajustar el sistema.
2. Exigir respuestas basadas en el contexto real: reconocer ambigüedad, pedir una aclaración breve cuando haga falta y evitar afirmaciones de actividad sin registro. Favorecer respuestas breves para preguntas simples.
3. Comparar modelos o configuraciones locales candidatas con los mismos diálogos, midiendo a la vez calidad, memoria y tiempo de respuesta. No asumir que un modelo más grande cabrá o será suficientemente rápido en este equipo.
4. Mejorar la conservación explícita de entidades, números y correcciones en conversaciones largas; comprobar que los resúmenes no introduzcan hechos nuevos.
5. Convertir los casos críticos en una evaluación de regresión con varias formulaciones y repeticiones. Evitar una colección de respuestas automáticas para frases concretas: debe mejorar la generalización.

No es posible certificar que entenderá absolutamente todo sin confundirse. El objetivo verificable es reducir estos errores, reconocer incertidumbre y sostener resultados consistentes en conversaciones nuevas.

## Entorno, límites y estado final

- Modelo real instalado: `qwen3.5:4b` mediante Ollama; metadatos del archivo: 4.7B parámetros, cuantización Q4_K_M. Generación sin pensamiento, contexto 4096, máximo 512 tokens de salida, temperatura 0.45, top_p 0.9 y repeat_penalty 1.08.
- Las primeras 175 respuestas pasaron por `ConversationService`, con historial por diálogo, perfil vacío, almacenamiento temporal, memoria persistente desactivada y verificación externa desactivada. El sustituto del motor de acciones nunca ejecutó acciones. La comparación adicional de 32 respuestas llamó al modelo con instrucciones capturadas del servicio o con la alternativa.
- Se mantuvo el modelo cargado durante tres minutos en los procesos de evaluación para evitar recargas entre cada caso. Eso no modifica la configuración persistente de Jarvis.
- Hubo un timeout registrado de 180,24 segundos durante las repeticiones y otra petición interrumpida al detener el proceso de evaluación. No se calificaron como errores lingüísticos. Se repitieron los casos pendientes y se obtuvieron las 38 respuestas de seguimiento previstas.
- Durante esa incidencia se observaron unos 216 MB libres de memoria gráfica. El servicio de producción tiene un guardián que libera el modelo por debajo de 512 MB de GPU o 1,8 GB de RAM. Esto es compatible con interferencia entre procesos, pero no demuestra por sí solo la causa exacta del timeout. La evaluación terminó tras pausar temporalmente el servicio de producción. Estos tiempos no constituyen una medición fiable de latencia del celular.
- La pausa temporal fue retirada y se verificó `/api/health`: `status: ok`; supervisor `ready`. Jarvis quedó nuevamente ejecutándose.
- No se probó reconocimiento de audio, uso de herramientas, integración de cuentas ni memoria personal persistente. Las pruebas fueron textuales, incluidas expresiones parecidas a transcripciones habladas.
- Durante esta evaluación no se modificó el comportamiento de producción ni se desplegó la alternativa de instrucciones. Se añadió el ejecutor de pruebas y se guardaron resultados y diagnóstico.

## Evidencia y reproducción

- [Ejecutor de evaluación](../scripts/evaluate_language.py).
- [Transcripción completa con criterios y calificaciones](../.data/language-evaluation-transcripts-20260922.md).
- [Batería principal y criterios](../.data/language-eval-20260922/cases.json), [respuestas originales](../.data/language-eval-20260922/responses.jsonl), [evaluaciones](../.data/language-eval-20260922/reviews.json).
- [Repeticiones y reformulaciones](../.data/language-eval-followups-20260922/responses.jsonl), [casos recuperados tras la incidencia](../.data/language-eval-retry-20260922/responses.jsonl).
- [Comparación de instrucciones, con prompts y semillas](../.data/language-prompt-comparison-20260922/responses.jsonl), [evaluaciones de la comparación](../.data/language-prompt-comparison-20260922/reviews.json), [script de comparación](../.data/compare_language_prompts.py).

Los archivos de `.data` son evidencia local y pueden estar excluidos de Git. Para repetir un subconjunto desde la raíz del proyecto: `.venv\Scripts\python.exe scripts/evaluate_language.py --ids g05,m02,n07,a05 --output .data/language-eval-new-run`. Usar una carpeta nueva y evitar dos evaluaciones concurrentes. La generación puede variar entre ejecuciones; guardar siempre las respuestas y revisarlas contra los criterios.
