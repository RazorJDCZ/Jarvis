# Motor de acciones — etapa 2

## Flujo de ejecución

1. El parser determinista resuelve las acciones evidentes y detecta metas sobre la computadora sin
   depender de formulaciones exactas.
2. Si no existe una coincidencia segura, Qwen traduce la intención completa y el contexto reciente
   a una acción tipada, una aclaración puntual o un flujo de hasta cinco pasos.
3. El catálogo vuelve a validar el nombre y todos los argumentos; el modelo nunca ejecuta código.
4. Las acciones de riesgo bajo se ejecutan. Las de riesgo medio o alto crean una confirmación
   temporal ligada a la sesión.
5. El controlador ejecuta y verifica cuando Windows o el navegador ofrecen una señal comprobable.
6. Si aparece un diálogo nativo nuevo, el flujo se pausa y Jarvis presenta sus botones como
   opciones; ninguna respuesta se elige automáticamente.
7. Si una decisión depende del resultado observado, el agente vuelve a planear con esa evidencia
   delimitada como no confiable. Se permiten como máximo tres rondas y cinco acciones totales.
8. El resultado se registra en una auditoría local con censura de contenido sensible.

## Catálogo

| Área | Acciones | Riesgo habitual |
|---|---|---|
| Aplicaciones | listar; abrir fija o entrada segura del catálogo de Windows | bajo / medio |
| Navegador | abrir, buscar, atrás, adelante, recargar, crear/listar/cambiar/cerrar pestaña | bajo; cerrar es medio |
| Página web | leer, activar botón/enlace, llenar un campo sin enviar | bajo / medio |
| Resultados web | abrir por posición dentro de la página controlada | medio |
| Volumen | consultar, establecer, cambiar, silenciar | bajo |
| Multimedia | reproducir/pausar, siguiente, anterior, detener | bajo |
| Ventanas | listar, identificar, enfocar, minimizar, maximizar, restaurar, cerrar | bajo; cerrar es medio |
| Interfaz accesible | inspeccionar, activar control, escribir, atajo, tecla | bajo / medio |
| Puntero | clic por coordenadas, desplazamiento | alto / medio |
| Escritorio | captura, mostrar escritorio | medio / bajo |
| Visión local | describir, preguntar, localizar y preparar clic visual | medio / alto |
| Portapapeles | leer, escribir, analizar efímeramente | medio |
| Sistema | CPU, memoria, disco, batería y alertas locales | bajo |
| Rutas | abrir archivo seguro, abrir carpeta | medio / bajo |
| Skills | listar y ejecutar recetas declarativas | bajo / medio |
| Appa | tareas, proyectos, calendario, inbox y focus | bajo / medio |
| Recordatorios | listar, programar, cancelar | bajo / medio |
| Biblioteca / adjuntos | listar, buscar, indexar un adjunto | bajo / medio |
| Permisos recordados | listar y olvidar | bajo / medio |
| Desarrollo | listar, inspeccionar, buscar, ejecutar pruebas permitidas | bajo / alto |
| Juegos | listar manifiestos, iniciar mediante URI validado | bajo / medio |

Hay 78 acciones ejecutables cerradas en `ActionName`, además del contenedor interno
`workflow.run`. Agregar otra requiere definir explícitamente su riesgo, validación, ejecución y
pruebas.

La implementación y configuración de estas extensiones se documenta en
[capabilities.md](capabilities.md).

## Decisiones de seguridad

- El modo predeterminado reutiliza el último perfil personal válido de Chrome, Edge o Brave y el
  navegador predeterminado de Windows cuando no se especifica otro. No añade incógnito, invitado,
  `user-data-dir` ni depuración remota. La orden se ejecuta como vector fijo, sin shell, y al cerrar
  Jarvis no se terminan procesos ni ventanas personales.
- En modo personal, la navegación básica usa atajos fijos y los campos o controles se buscan por
  accesibilidad de Windows. `JARVIS_BROWSER_PERSONAL_PROFILE=false` habilita el modo aislado anterior
  con CDP y un perfil dentro de `.data` cuando se necesita control DOM más preciso.
- `browser.fill` no presiona Enter ni envía formularios. Los clics web se resuelven por rol o nombre
  accesible y exigen confirmación.
- Los nombres asociados a compras, pagos, transferencias o eliminación se bloquean incluso después
  de una petición de clic.
- Un clic por coordenadas puede verse afectado por cambios de foco o movimiento de ventanas; por eso
  está marcado como riesgo alto.
- Una confirmación pendiente es una capacidad de un solo turno: cualquier solicitud nueva la
  invalida y queda auditada como cancelada. Así, un “sí” posterior no puede ejecutar una mutación
  perteneciente a un tema anterior.
- La visión solo se conecta a Ollama por loopback. Captura las pantallas en memoria, reduce la
  imagen antes de inferir y no conserva el archivo. El contenido visible se delimita como datos no
  confiables para resistir instrucciones incrustadas en páginas. Cada observación usa hasta 1280 px
  y exige confianza calibrada; texto o controles dudosos se omiten en vez de completarse.
- `screen.list` enumera los monitores activos. Las acciones visuales aceptan `all`, `primary`,
  `left`, `right` o el número de pantalla que reporta Windows y recortan únicamente esa región.
- Cada sesión conserva hasta cinco minutos el monitor observado, un resumen y los nombres de los
  controles relevantes. Ese contexto solo resuelve continuaciones conversacionales: toda consulta
  o clic vuelve a capturar la pantalla y recalcula la posición, de modo que no actúa con píxeles
  obsoletos. El contexto no se comparte entre sesiones y se elimina al reiniciar la conversación.
- Un clic visual usa primero UI Automation. Si debe estimar píxeles, solo mueve el cursor; una
  segunda autorización independiente crea el clic. Los objetivos de compra, pago, transferencia o
  eliminación se rechazan antes de moverlo. Si el cursor cambia de posición mientras espera la
  segunda autorización, el clic se cancela.
- Una localización visual sin monitor explícito inspecciona cada pantalla por separado. Si encuentra
  más de una coincidencia pide el monitor, en lugar de escoger una posición ambigua sobre una imagen
  ultrapanorámica.
- Un flujo encadenado hereda el riesgo más alto y se detiene en el primer error. No puede incluir un
  clic visual porque ese protocolo exige revisar la posición y confirmar por separado.
- Los diálogos estándar se detectan por su identificador nativo, se leen mediante UI Automation y
  se vinculan a la sesión. Antes de pulsar una opción se vuelve a comprobar el identificador, el
  texto exacto del botón y que haya una sola coincidencia. Si aparece otro diálogo, se repite el
  mismo protocolo.
- UAC y otros avisos del escritorio seguro quedan fuera del alcance: Jarvis no intenta evadir esa
  frontera del sistema operativo.
- Abrir una aplicación no acepta una línea de comandos. Las aplicaciones fijas tienen vectores de
  argumentos constantes y las dinámicas deben estar publicadas en `shell:AppsFolder`. Nombre,
  identificador y destino se vuelven a comprobar antes de invocar la entrada exacta; documentos,
  desinstaladores, scripts, terminales e intérpretes quedan fuera.
- El inventario seguro de aplicaciones se conserva 60 segundos. El listado y selección de ventanas
  se hace primero mediante Win32 no bloqueante, por lo que una aplicación congelada no detiene el
  motor completo; UI Automation queda reservada para inspeccionar controles de la ventana elegida.
- Abrir un archivo acepta únicamente extensiones de una lista positiva. No se abren ejecutables,
  scripts, accesos directos, documentos con macros ni contenido web local.
- La auditoría no cambia el resultado de una acción si el disco no está disponible y rota al llegar
  aproximadamente a 2 MB.

## Límites actuales

- La automatización de aplicaciones depende de Microsoft UI Automation; algunos programas antiguos,
  juegos o interfaces dibujadas completamente por GPU no exponen controles con nombre.
- El perfil personal protege la cuenta del usuario frente a control por CDP, por lo que leer el DOM,
  enumerar pestañas o seleccionar un resultado solo por número depende de lo que Chrome exponga a
  UI Automation. Jarvis puede usar el nombre visible o la visión local; para control DOM completo
  existe el modo aislado opcional. Firefox todavía no participa en el canal web automatizado.
- El núcleo agente admite hasta cinco acciones y tres rondas verificadas. Los planes autónomos de
  varios minutos, seguimiento visual continuo y proactividad todavía quedan fuera de alcance.
- La localización por píxeles es probabilística y puede ser imprecisa, especialmente con varias
  pantallas o interfaces escaladas; la confirmación humana sigue siendo obligatoria.
- El acceso móvil usa Tailscale, identidad del tailnet, emparejamiento y passkey. Toda mutación
  iniciada desde el teléfono se eleva como mínimo a riesgo medio y exige confirmación.
- La interrupción por voz requiere que el micrófono ya tenga permiso y una frase cerrada que incluya
  “Jarvis”. Funciona en manos libres y tras una captura manual. La voz se pausa apenas el detector
  local percibe habla, Whisper valida la orden y la reproducción continúa si no era una
  interrupción; pulsar el micrófono la cancela inmediatamente.
