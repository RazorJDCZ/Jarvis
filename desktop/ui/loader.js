const statusText = document.querySelector("#status");
const detailText = document.querySelector("#detail");
const actions = document.querySelector("#actions");
const retryButton = document.querySelector("#retryButton");
const logsButton = document.querySelector("#logsButton");

let phaseTimer = null;

function invoke(command) {
  const bridge = window.__TAURI__?.core;
  if (!bridge?.invoke) throw new Error("El puente nativo de Jarvis no está disponible.");
  return bridge.invoke(command);
}

async function connect() {
  actions.hidden = true;
  retryButton.disabled = true;
  statusText.textContent = "Comprobando el núcleo de Jarvis…";
  detailText.textContent = "Tus cuentas, memoria y conexiones permanecen en el servicio local existente.";
  clearTimeout(phaseTimer);
  phaseTimer = setTimeout(() => {
    statusText.textContent = "Iniciando los sistemas locales…";
    detailText.textContent = "Whisper y los conectores pueden tardar unos segundos después de encender Windows.";
  }, 2_500);

  try {
    const result = await invoke("ensure_jarvis");
    clearTimeout(phaseTimer);
    if (!result.ready) {
      throw new Error(result.detail || "Jarvis no respondió dentro del tiempo esperado.");
    }
    statusText.textContent = "Enlace establecido";
    detailText.textContent = "Abriendo la interfaz completa…";
    window.location.replace(result.url);
  } catch (error) {
    clearTimeout(phaseTimer);
    statusText.textContent = "No pude iniciar Jarvis";
    detailText.textContent = error instanceof Error ? error.message : String(error);
    actions.hidden = false;
    retryButton.disabled = false;
  }
}

retryButton.addEventListener("click", connect);
logsButton.addEventListener("click", async () => {
  try {
    await invoke("open_diagnostics");
  } catch (error) {
    detailText.textContent = error instanceof Error ? error.message : String(error);
  }
});

void connect();
