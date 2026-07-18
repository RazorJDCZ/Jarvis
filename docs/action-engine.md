# Motor de acciones — etapa 2

## Flujo de ejecución

1. El parser determinista intenta reconocer la orden.
2. Solo si parece una orden directa y no hubo coincidencia, Qwen puede proponer una acción tipada o
   un flujo explícito de hasta tres pasos.
3. El catálogo vuelve a validar el nombre y todos los argumentos; el modelo nunca ejecuta código.
4. Las acciones de riesgo bajo se ejecutan. Las de riesgo medio o alto crean una confirmación
   temporal ligada a la sesión.
5. El controlador ejecuta y verifica cuando Windows o el navegador ofrecen una señal comprobable.
6. El resultado se registra en una auditoría local con censura de contenido sensible.

## Catálogo

| Área | Acciones | Riesgo habitual |
|---|---|---|
| Aplicaciones | abrir fija o acceso confiable del menú Inicio | bajo / medio |
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
| Portapapeles | leer, escribir | medio |
| Sistema | CPU, memoria y batería | bajo |
| Rutas | abrir archivo seguro, abrir carpeta | medio / bajo |

Hay 47 acciones ejecutables cerradas en `ActionName`, además del contenedor interno
`workflow.run`. Agregar otra requiere definir explícitamente su riesgo, validación, ejecución y
pruebas.

## Decisiones de seguridad

- El navegador controlado usa CDP sobre un puerto aleatorio enlazado a `127.0.0.1`, una ventana
  InPrivate y un perfil independiente. Jarvis termina únicamente el proceso de Edge que él creó al
  cerrarse.
- `browser.fill` no presiona Enter ni envía formularios. Los clics web se resuelven por rol o nombre
  accesible y exigen confirmación.
- Los nombres asociados a compras, pagos, transferencias o eliminación se bloquean incluso después
  de una petición de clic.
- Un clic por coordenadas puede verse afectado por cambios de foco o movimiento de ventanas; por eso
  está marcado como riesgo alto.
- La visión solo se conecta a Ollama por loopback. Captura las pantallas en memoria, reduce la
  imagen antes de inferir y no conserva el archivo. El contenido visible se delimita como datos no
  confiables para resistir instrucciones incrustadas en páginas.
- Un clic visual usa primero UI Automation. Si debe estimar píxeles, solo mueve el cursor; una
  segunda autorización independiente crea el clic. Los objetivos de compra, pago, transferencia o
  eliminación se rechazan antes de moverlo. Si el cursor cambia de posición mientras espera la
  segunda autorización, el clic se cancela.
- Un flujo encadenado hereda el riesgo más alto y se detiene en el primer error. No puede incluir un
  clic visual porque ese protocolo exige revisar la posición y confirmar por separado.
- Abrir una aplicación no acepta una línea de comandos. Las aplicaciones fijas tienen vectores de
  argumentos constantes y los accesos dinámicos deben vivir dentro del menú Inicio.
- Abrir un archivo acepta únicamente extensiones de una lista positiva. No se abren ejecutables,
  scripts, accesos directos, documentos con macros ni contenido web local.
- La auditoría no cambia el resultado de una acción si el disco no está disponible y rota al llegar
  aproximadamente a 2 MB.

## Límites actuales

- La automatización de aplicaciones depende de Microsoft UI Automation; algunos programas antiguos,
  juegos o interfaces dibujadas completamente por GPU no exponen controles con nombre.
- El navegador controlado no reutiliza sesiones del navegador personal por diseño.
- Esta etapa admite hasta tres acciones explícitas y percepción visual bajo demanda. Los planes
  autónomos de varios minutos, seguimiento visual continuo y proactividad pertenecen a la etapa 5.
- La localización por píxeles es probabilística y puede ser imprecisa, especialmente con varias
  pantallas o interfaces escaladas; la confirmación humana sigue siendo obligatoria.
- El acceso desde el celular permanece deshabilitado hasta implementar identidad de dispositivo,
  cifrado y permisos remotos en la etapa 3.
