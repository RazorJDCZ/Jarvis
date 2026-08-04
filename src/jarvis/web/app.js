"use strict";

const elements = {
  body: document.body,
  neuralField: document.querySelector("#neuralField"),
  clock: document.querySelector("#clock"),
  systemDate: document.querySelector("#systemDate"),
  stateLabel: document.querySelector("#stateLabel"),
  stateDetail: document.querySelector("#stateDetail"),
  micButton: document.querySelector("#micButton"),
  handsFreeButton: document.querySelector("#handsFreeButton"),
  muteButton: document.querySelector("#muteButton"),
  resetButton: document.querySelector("#resetButton"),
  transcript: document.querySelector("#transcript"),
  textForm: document.querySelector("#textForm"),
  textInput: document.querySelector("#textInput"),
  brainStatus: document.querySelector("#brainStatus"),
  sttStatus: document.querySelector("#sttStatus"),
  ttsStatus: document.querySelector("#ttsStatus"),
  actionsStatus: document.querySelector("#actionsStatus"),
  visionStatus: document.querySelector("#visionStatus"),
  memoryStatus: document.querySelector("#memoryStatus"),
  wakeWordLabel: document.querySelector("#wakeWordLabel"),
  monitorFocus: document.querySelector("#monitorFocus"),
  activityCode: document.querySelector("#activityCode"),
  coreLoad: document.querySelector("#coreLoad"),
  footerHint: document.querySelector("#footerHint"),
  toast: document.querySelector("#toast"),
  waveform: document.querySelector("#waveform"),
  actionConfirmation: document.querySelector("#actionConfirmation"),
  actionDescription: document.querySelector("#actionDescription"),
  actionRisk: document.querySelector("#actionRisk"),
  dialogChoiceButtons: document.querySelector("#dialogChoiceButtons"),
  approveActionButton: document.querySelector("#approveActionButton"),
  rejectActionButton: document.querySelector("#rejectActionButton"),
  remoteLinkChip: document.querySelector("#remoteLinkChip"),
  networkMode: document.querySelector("#networkMode"),
  mobileAccessButton: document.querySelector("#mobileAccessButton"),
  mobileAccessDialog: document.querySelector("#mobileAccessDialog"),
  closeMobileAccessButton: document.querySelector("#closeMobileAccessButton"),
  remoteAdminState: document.querySelector("#remoteAdminState"),
  remoteAdminDescription: document.querySelector("#remoteAdminDescription"),
  remoteOriginLink: document.querySelector("#remoteOriginLink"),
  createPairingButton: document.querySelector("#createPairingButton"),
  pairingCodePanel: document.querySelector("#pairingCodePanel"),
  pairingCode: document.querySelector("#pairingCode"),
  pairingExpiry: document.querySelector("#pairingExpiry"),
  remoteDeviceList: document.querySelector("#remoteDeviceList"),
  remoteGate: document.querySelector("#remoteGate"),
  remoteIdentityLabel: document.querySelector("#remoteIdentityLabel"),
  remoteAuthenticationPanel: document.querySelector("#remoteAuthenticationPanel"),
  authenticateRemoteButton: document.querySelector("#authenticateRemoteButton"),
  showPairingPanelButton: document.querySelector("#showPairingPanelButton"),
  showAuthenticationPanelButton: document.querySelector("#showAuthenticationPanelButton"),
  remotePairingForm: document.querySelector("#remotePairingForm"),
  remoteDeviceLabel: document.querySelector("#remoteDeviceLabel"),
  remotePairingCode: document.querySelector("#remotePairingCode"),
  remoteGateError: document.querySelector("#remoteGateError"),
  emergencyStopButton: document.querySelector("#emergencyStopButton"),
};

const stateLabels = {
  standby: "SISTEMA EN ESPERA",
  ready: "SISTEMA DISPONIBLE",
  listening: "ESCUCHANDO",
  transcribing: "ANALIZANDO VOZ",
  thinking: "PROCESANDO",
  speaking: "RESPONDIENDO",
  error: "ATENCIÓN REQUERIDA",
};

function persistentClientId() {
  const key = "jarvis-client-session-v1";
  try {
    const existing = localStorage.getItem(key);
    if (existing && /^[a-zA-Z0-9_-]{8,128}$/.test(existing)) return existing;
    const generated = crypto.randomUUID ? crypto.randomUUID() : `session-${Date.now()}`;
    localStorage.setItem(key, generated);
    return generated;
  } catch {
    return crypto.randomUUID ? crypto.randomUUID() : `session-${Date.now()}`;
  }
}

const appState = {
  sessionId: persistentClientId(),
  visualState: "standby",
  handsFree: false,
  muted: false,
  busy: false,
  speaking: false,
  manualIntent: false,
  ttsAvailable: false,
  toastTimer: null,
  socketPing: null,
  pendingAction: null,
  interruptionPending: false,
  interruptionPaused: false,
  interruptionCooldownUntil: 0,
  speechGeneration: 0,
  activityCount: 0,
  remote: false,
  remoteEnabled: false,
  remoteAuthenticated: false,
  remoteDeviceId: null,
  remoteStatus: null,
  socket: null,
  reconnectTimer: null,
  healthTimer: null,
  initialized: false,
  pairingTimer: null,
  operationGeneration: 0,
  activeControllers: new Set(),
  ttsController: null,
};

function setVisualState(state, detail) {
  appState.visualState = state;
  elements.body.dataset.state = state;
  elements.stateLabel.textContent = stateLabels[state] || state.toUpperCase();
  if (detail) elements.stateDetail.textContent = detail;
}

function showToast(message, duration = 3600) {
  window.clearTimeout(appState.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  appState.toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), duration);
}

function cancelActiveClientWork() {
  appState.operationGeneration += 1;
  for (const controller of appState.activeControllers) controller.abort();
  appState.activeControllers.clear();
  appState.busy = false;
}

async function cancellableFetch(input, init = {}) {
  const controller = new AbortController();
  appState.activeControllers.add(controller);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    appState.activeControllers.delete(controller);
  }
}

function addMessage(role, text, label) {
  const article = document.createElement("article");
  article.className = `message ${role}-message`;
  const displayLabel = label || (role === "jarvis" ? "JARVIS" : role === "user" ? "TÚ" : "SYSTEM");
  const labelElement = document.createElement("span");
  const textElement = document.createElement("p");
  labelElement.textContent = displayLabel;
  textElement.textContent = text;
  article.append(labelElement, textElement);
  elements.transcript.appendChild(article);
  appState.activityCount += 1;
  if (elements.activityCode) {
    elements.activityCode.textContent = `CTX-${String(appState.activityCount).padStart(3, "0")}`;
  }
  elements.transcript.scrollTo({ top: elements.transcript.scrollHeight, behavior: "smooth" });
}

async function readError(response) {
  if (response.status === 401 && appState.remote) {
    requireRemoteUnlock("La sesión del dispositivo expiró. Verifica nuevamente tu passkey.");
  }
  try {
    const payload = await response.json();
    return payload.detail || `Error HTTP ${response.status}`;
  } catch {
    return `Error HTTP ${response.status}`;
  }
}

function bytesToBase64Url(value) {
  const bytes =
    value instanceof ArrayBuffer
      ? new Uint8Array(value)
      : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64UrlToBytes(value) {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function registrationOptionsFromJson(options) {
  return {
    ...options,
    challenge: base64UrlToBytes(options.challenge),
    user: { ...options.user, id: base64UrlToBytes(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((credential) => ({
      ...credential,
      id: base64UrlToBytes(credential.id),
    })),
  };
}

function authenticationOptionsFromJson(options) {
  return {
    ...options,
    challenge: base64UrlToBytes(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((credential) => ({
      ...credential,
      id: base64UrlToBytes(credential.id),
    })),
  };
}

function registrationCredentialToJson(credential) {
  return {
    id: credential.id,
    rawId: bytesToBase64Url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      attestationObject: bytesToBase64Url(credential.response.attestationObject),
      clientDataJSON: bytesToBase64Url(credential.response.clientDataJSON),
      transports: credential.response.getTransports?.() || [],
    },
  };
}

function authenticationCredentialToJson(credential) {
  return {
    id: credential.id,
    rawId: bytesToBase64Url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      authenticatorData: bytesToBase64Url(credential.response.authenticatorData),
      clientDataJSON: bytesToBase64Url(credential.response.clientDataJSON),
      signature: bytesToBase64Url(credential.response.signature),
      userHandle: credential.response.userHandle
        ? bytesToBase64Url(credential.response.userHandle)
        : null,
    },
  };
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

function remoteDeviceStorageKey() {
  return `jarvis-passkey-device:${location.host}`;
}

function storedRemoteDeviceId() {
  try {
    const deviceId = localStorage.getItem(remoteDeviceStorageKey());
    return /^[a-f0-9]{32}$/.test(deviceId || "") ? deviceId : null;
  } catch {
    return null;
  }
}

function storeRemoteDeviceId(deviceId) {
  try {
    localStorage.setItem(remoteDeviceStorageKey(), deviceId);
  } catch {
    // La passkey sigue protegida aunque el navegador no permita persistir este identificador.
  }
}

function clearRemoteDeviceId() {
  try {
    localStorage.removeItem(remoteDeviceStorageKey());
  } catch {
    // Sin almacenamiento persistente, la pantalla ya está en modo de emparejamiento.
  }
}

function supportsPasskeys() {
  return Boolean(window.PublicKeyCredential && navigator.credentials?.create && navigator.credentials?.get);
}

function setRemoteGateError(message = "") {
  elements.remoteGateError.textContent = message;
}

function showRemotePairing() {
  elements.remoteAuthenticationPanel.hidden = true;
  elements.remotePairingForm.hidden = false;
  elements.showAuthenticationPanelButton.hidden = !storedRemoteDeviceId();
  setRemoteGateError();
}

function showRemoteAuthentication() {
  if (!storedRemoteDeviceId()) {
    showRemotePairing();
    return;
  }
  elements.remoteAuthenticationPanel.hidden = false;
  elements.remotePairingForm.hidden = true;
  setRemoteGateError();
}

function requireRemoteUnlock(message = "") {
  if (!appState.remote) return;
  cancelActiveClientWork();
  stopSpeaking();
  appState.remoteAuthenticated = false;
  appState.busy = false;
  if (appState.socket) appState.socket.close();
  appState.socket = null;
  elements.remoteGate.hidden = false;
  elements.emergencyStopButton.hidden = true;
  if (storedRemoteDeviceId()) showRemoteAuthentication();
  else showRemotePairing();
  if (message) setRemoteGateError(message);
}

async function finishRemoteUnlock(device) {
  appState.remoteAuthenticated = true;
  appState.remoteDeviceId = device.device_id;
  storeRemoteDeviceId(device.device_id);
  elements.remoteGate.hidden = true;
  elements.emergencyStopButton.hidden = false;
  elements.networkMode.innerHTML =
    '<i class="online-indicator"></i> TAILNET // PASSKEY // SECURE';
  startCore();
  await restoreRemoteSession();
}

async function pairRemoteDevice() {
  if (!supportsPasskeys()) {
    throw new Error("Este navegador no ofrece passkeys/WebAuthn. Usa Chrome, Edge o Safari actual.");
  }
  const code = elements.remotePairingCode.value.trim();
  const label = elements.remoteDeviceLabel.value.trim();
  const ceremony = await postJson("/api/remote/pair/options", { code, label });
  const credential = await navigator.credentials.create({
    publicKey: registrationOptionsFromJson(ceremony.options),
  });
  if (!credential) throw new Error("El emparejamiento fue cancelado.");
  const verified = await postJson("/api/remote/pair/verify", {
    ceremony_id: ceremony.ceremony_id,
    credential: registrationCredentialToJson(credential),
  });
  await finishRemoteUnlock(verified.device);
  showToast("Teléfono emparejado. El enlace privado está listo.");
}

async function authenticateRemoteDevice() {
  if (!supportsPasskeys()) {
    throw new Error("Este navegador no ofrece passkeys/WebAuthn.");
  }
  const deviceId = storedRemoteDeviceId();
  if (!deviceId) {
    showRemotePairing();
    return;
  }
  try {
    const ceremony = await postJson("/api/remote/auth/options", { device_id: deviceId });
    const credential = await navigator.credentials.get({
      publicKey: authenticationOptionsFromJson(ceremony.options),
    });
    if (!credential) throw new Error("La autenticación fue cancelada.");
    const verified = await postJson("/api/remote/auth/verify", {
      ceremony_id: ceremony.ceremony_id,
      credential: authenticationCredentialToJson(credential),
    });
    await finishRemoteUnlock(verified.device);
    showToast("Dispositivo verificado con passkey.");
  } catch (error) {
    if (/no está emparejado|no está autorizada|no está activo/i.test(error.message)) {
      clearRemoteDeviceId();
      showRemotePairing();
    }
    throw error;
  }
}

function renderRemoteDevices(devices = []) {
  elements.remoteDeviceList.replaceChildren();
  if (!devices.length) {
    const empty = document.createElement("div");
    empty.className = "remote-device-empty";
    empty.textContent = "Todavía no hay teléfonos emparejados.";
    elements.remoteDeviceList.appendChild(empty);
    return;
  }
  for (const device of devices) {
    const row = document.createElement("div");
    row.className = "remote-device";
    const info = document.createElement("div");
    const label = document.createElement("strong");
    const detail = document.createElement("small");
    const revoke = document.createElement("button");
    label.textContent = device.label;
    const lastSeen = new Date(device.last_seen_at * 1000).toLocaleString("es-EC");
    detail.textContent = `${device.display_name} // último acceso ${lastSeen}`;
    revoke.type = "button";
    revoke.textContent = "REVOCAR";
    revoke.addEventListener("click", async () => {
      if (!window.confirm(`¿Revocar el acceso de “${device.label}”?`)) return;
      const response = await fetch(`/api/remote/devices/${device.device_id}`, { method: "DELETE" });
      if (!response.ok) {
        showToast(await readError(response), 6000);
        return;
      }
      await refreshRemoteAdmin();
      showToast("Dispositivo revocado.");
    });
    info.append(label, detail);
    row.append(info, revoke);
    elements.remoteDeviceList.appendChild(row);
  }
}

function configureRemoteAdmin(status) {
  appState.remoteStatus = status;
  appState.remoteEnabled = Boolean(status.enabled);
  elements.createPairingButton.disabled = !status.enabled;
  elements.remoteOriginLink.hidden = !status.remote_origin;
  elements.remoteOriginLink.textContent = status.remote_origin || "";
  elements.remoteOriginLink.href = status.remote_origin || "#";
  if (status.enabled) {
    elements.remoteAdminState.textContent = "TAILNET LINK // READY";
    elements.remoteAdminDescription.textContent =
      "Jarvis acepta únicamente tu identidad de Tailscale y dispositivos verificados con passkey.";
    elements.mobileAccessButton.querySelector("small").textContent = "Enlace privado disponible";
    elements.remoteLinkChip.innerHTML = "<i></i> TAILNET READY";
  } else {
    elements.remoteAdminState.textContent = "TAILNET LINK // NOT CONFIGURED";
    elements.remoteAdminDescription.textContent =
      "Instala Tailscale y ejecuta scripts\\setup_remote_access.ps1 para activar el enlace privado.";
    elements.mobileAccessButton.querySelector("small").textContent = "Configurar enlace privado";
  }
  renderRemoteDevices(status.devices);
}

async function refreshRemoteAdmin() {
  const response = await fetch("/api/remote/status", { cache: "no-store" });
  if (!response.ok) throw new Error(await readError(response));
  const status = await response.json();
  configureRemoteAdmin(status);
}

async function restoreRemoteSession() {
  if (!appState.remote || !appState.remoteAuthenticated) return;
  try {
    const payload = await postJson("/api/remote/session", { session_id: appState.sessionId });
    if (payload.state) setVisualState(payload.state.state, payload.state.detail);
    if (payload.action) handleAction(payload.action);
  } catch (error) {
    console.debug("Remote session could not be restored", error);
  }
}

async function bootstrapApplication() {
  try {
    const response = await fetch("/api/remote/status", { cache: "no-store" });
    if (!response.ok) throw new Error(await readError(response));
    const status = await response.json();
    appState.remoteStatus = status;
    appState.remote = Boolean(status.remote);
    appState.remoteEnabled = Boolean(status.enabled);
    appState.remoteAuthenticated = Boolean(status.authenticated);
    if (!appState.remote) {
      configureRemoteAdmin(status);
      startCore();
      return;
    }
    document.body.classList.add("remote-client");
    elements.remoteLinkChip.innerHTML = "<i></i> TAILNET AUTHENTICATED";
    elements.mobileAccessButton.hidden = true;
    elements.remoteIdentityLabel.textContent = status.identity
      ? `${status.identity.name} // ${status.identity.login}`
      : "Identidad privada de Tailscale detectada.";
    if (status.authenticated && status.device) {
      await finishRemoteUnlock(status.device);
      return;
    }
    requireRemoteUnlock();
  } catch (error) {
    setVisualState("error", "No pude validar el canal privado");
    setRemoteGateError(error.message);
    elements.remoteGate.hidden = false;
  }
}

function updateProvider(element, status) {
  element.classList.toggle("online", Boolean(status.available));
  element.classList.toggle("offline", !status.available);
  const small = element.querySelector("small");
  if (small) small.textContent = status.detail;
  element.title = `${status.name}: ${status.detail}`;
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error(await readError(response));
    const health = await response.json();
    updateProvider(elements.brainStatus, health.brain);
    updateProvider(elements.sttStatus, health.stt);
    updateProvider(elements.ttsStatus, health.tts);
    updateProvider(elements.actionsStatus, health.actions);
    updateProvider(elements.visionStatus, health.vision);
    updateProvider(elements.memoryStatus, health.memory);
    elements.wakeWordLabel.textContent = health.wake_word.toUpperCase();
    appState.ttsAvailable = health.tts.available;
    const providers = [health.brain, health.stt, health.tts, health.actions, health.vision, health.memory];
    const online = providers.filter((provider) => provider.available).length;
    if (elements.coreLoad) elements.coreLoad.textContent = `${online}/6 NOMINAL`;
  } catch (error) {
    for (const element of [
      elements.brainStatus,
      elements.sttStatus,
      elements.ttsStatus,
      elements.actionsStatus,
      elements.visionStatus,
      elements.memoryStatus,
    ]) {
      element.classList.add("offline");
      element.querySelector("small").textContent = "Núcleo no disponible";
    }
    setVisualState("error", "No puedo conectar con el núcleo local");
    console.error(error);
  }
}

function handleAction(action) {
  const monitorLabel = action?.details?.monitor_label;
  const monitorCount = action?.details?.monitors?.length;
  if (elements.monitorFocus && typeof monitorLabel === "string") {
    elements.monitorFocus.textContent = `VISION // ${monitorLabel.toUpperCase()}`;
  } else if (elements.monitorFocus && Number.isInteger(monitorCount)) {
    elements.monitorFocus.textContent = `VISION // ${monitorCount} DISPLAYS`;
  }
  if (action?.requires_confirmation && action.action_id) {
    const riskLabels = { low: "BAJO", medium: "MEDIO", high: "ALTO", blocked: "BLOQUEADO" };
    appState.pendingAction = action;
    elements.actionDescription.textContent = action.description || action.name || "Acción pendiente";
    elements.actionRisk.textContent = `RIESGO ${riskLabels[action.risk] || "MEDIO"}`;
    const dialogOptions = action.details?.dialog_options;
    elements.dialogChoiceButtons.replaceChildren();
    if (Array.isArray(dialogOptions) && dialogOptions.length) {
      elements.dialogChoiceButtons.hidden = false;
      elements.approveActionButton.hidden = true;
      elements.rejectActionButton.hidden = true;
      for (const option of dialogOptions) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = option;
        button.addEventListener("click", () => decideAction(null, option));
        elements.dialogChoiceButtons.appendChild(button);
      }
    } else {
      elements.dialogChoiceButtons.hidden = true;
      elements.approveActionButton.hidden = false;
      elements.rejectActionButton.hidden = false;
    }
    elements.actionConfirmation.hidden = false;
    if (
      appState.remote &&
      document.hidden &&
      "Notification" in window &&
      Notification.permission === "granted"
    ) {
      new Notification("Jarvis necesita confirmación", {
        body: action.description || "Hay una acción pendiente.",
        icon: "/static/icon.svg?v=spider-v3",
        tag: "jarvis-action-confirmation",
      });
    }
    return;
  }
  appState.pendingAction = null;
  elements.dialogChoiceButtons.replaceChildren();
  elements.dialogChoiceButtons.hidden = true;
  elements.approveActionButton.hidden = false;
  elements.rejectActionButton.hidden = false;
  elements.actionConfirmation.hidden = true;
}

async function decideAction(approve, choice = null) {
  const pending = appState.pendingAction;
  if (!pending) return;
  stopSpeaking();
  appState.busy = true;
  elements.approveActionButton.disabled = true;
  elements.rejectActionButton.disabled = true;
  for (const button of elements.dialogChoiceButtons.querySelectorAll("button")) {
    button.disabled = true;
  }
  setVisualState("thinking", approve ? "Ejecutando acción confirmada" : "Cancelando acción");
  try {
    const response = await cancellableFetch("/api/actions/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: appState.sessionId,
        action_id: pending.action_id,
        approve,
        choice,
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (payload.action) handleAction(payload.action);
    addMessage("jarvis", payload.response, "JARVIS // ACTION ENGINE");
    await speak(payload.response);
  } catch (error) {
    if (error.name === "AbortError") return;
    appState.busy = false;
    setVisualState("error", "No pude procesar la confirmación");
    showToast(error.message, 6000);
  } finally {
    elements.approveActionButton.disabled = false;
    elements.rejectActionButton.disabled = false;
    for (const button of elements.dialogChoiceButtons.querySelectorAll("button")) {
      button.disabled = false;
    }
  }
}

function connectStateSocket() {
  if (appState.socket || (appState.remote && !appState.remoteAuthenticated)) return;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  appState.socket = socket;
  socket.addEventListener("open", () => {
    window.clearInterval(appState.socketPing);
    appState.socketPing = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20000);
  });
  socket.addEventListener("message", (event) => {
    try {
      const snapshot = JSON.parse(event.data);
      if (snapshot.detail === "REMOTE_STOP") {
        cancelActiveClientWork();
        stopSpeaking();
        handleAction(null);
        setVisualState("standby", "Detenido desde el control remoto");
        return;
      }
      if (appState.speaking) return;
      setVisualState(snapshot.state, snapshot.detail);
    } catch (error) {
      console.debug("State event ignored", error);
    }
  });
  socket.addEventListener("close", () => {
    window.clearInterval(appState.socketPing);
    appState.socket = null;
    window.clearTimeout(appState.reconnectTimer);
    if (!appState.remote || appState.remoteAuthenticated) {
      appState.reconnectTimer = window.setTimeout(connectStateSocket, 2500);
    }
  });
}

function chooseSpanishVoice() {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  const preferredNames = ["Pablo", "Raul", "Alvaro", "Jorge", "Dario"];
  return (
    voices.find((voice) =>
      voice.lang.toLowerCase().startsWith("es") &&
      preferredNames.some((name) => voice.name.includes(name)),
    ) || voices.find((voice) => voice.lang.toLowerCase().startsWith("es"))
  );
}

function finishSpeaking() {
  appState.interruptionPaused = false;
  appState.speaking = false;
  appState.busy = false;
  setVisualState(
    appState.handsFree ? "standby" : "ready",
    appState.handsFree ? "Di “Jarvis” para activarme" : "Mantén pulsado el núcleo para hablar",
  );
}

function stopSpeaking() {
  appState.speechGeneration += 1;
  if (appState.ttsController) {
    appState.ttsController.abort();
    appState.ttsController = null;
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (appState.audioPlayer) {
    appState.audioPlayer.pause();
    appState.audioPlayer.src = "";
    appState.audioPlayer = null;
  }
  if (appState.audioUrl) {
    URL.revokeObjectURL(appState.audioUrl);
    appState.audioUrl = null;
  }
  appState.speaking = false;
  appState.busy = false;
  appState.interruptionPaused = false;
}

function pauseSpeakingForInterruption() {
  if (!appState.speaking || appState.interruptionPaused) return;
  appState.interruptionPaused = true;
  if (appState.audioPlayer && !appState.audioPlayer.paused) {
    appState.audioPlayer.pause();
  }
  if (window.speechSynthesis?.speaking) window.speechSynthesis.pause();
  setVisualState("listening", "Escuchando posible interrupción");
}

async function resumeSpeakingAfterInterruption() {
  if (!appState.speaking || !appState.interruptionPaused) return;
  appState.interruptionPaused = false;
  setVisualState("speaking", "Transmitiendo respuesta");
  if (appState.audioPlayer?.paused) {
    try {
      await appState.audioPlayer.play();
    } catch (error) {
      console.debug("Could not resume local neural audio", error);
      finishSpeaking();
    }
    return;
  }
  if (window.speechSynthesis?.paused) window.speechSynthesis.resume();
}

function speakWithBrowser(text) {
  if (!("speechSynthesis" in window)) {
    finishSpeaking();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "es-ES";
  utterance.rate = 0.96;
  utterance.pitch = 0.92;
  utterance.volume = 0.96;
  const voice = chooseSpanishVoice();
  if (voice) utterance.voice = voice;
  utterance.onend = finishSpeaking;
  utterance.onerror = finishSpeaking;
  window.speechSynthesis.speak(utterance);
  if (appState.interruptionPaused) window.speechSynthesis.pause();
}

async function speak(text) {
  if (appState.muted || !text) {
    finishSpeaking();
    return;
  }
  stopSpeaking();
  const speechGeneration = appState.speechGeneration;
  appState.speaking = true;
  appState.busy = true;
  setVisualState("speaking", "Transmitiendo respuesta");

  if (appState.ttsAvailable) {
    try {
      const controller = new AbortController();
      appState.ttsController = controller;
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: controller.signal,
      });
      appState.ttsController = null;
      if (!response.ok) throw new Error(await readError(response));
      const audioBlob = await response.blob();
      if (speechGeneration !== appState.speechGeneration) return;
      appState.audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(appState.audioUrl);
      appState.audioPlayer = audio;
      audio.onended = () => {
        URL.revokeObjectURL(appState.audioUrl);
        appState.audioUrl = null;
        appState.audioPlayer = null;
        finishSpeaking();
      };
      audio.onerror = () => {
        appState.ttsAvailable = false;
        speakWithBrowser(text);
      };
      if (appState.interruptionPaused) return;
      await audio.play();
      return;
    } catch (error) {
      appState.ttsController = null;
      if (speechGeneration !== appState.speechGeneration) return;
      console.warn("Local neural voice unavailable, falling back to browser voice", error);
      appState.ttsAvailable = false;
    }
  }
  if (speechGeneration !== appState.speechGeneration) return;
  speakWithBrowser(text);
}

async function sendText(message) {
  const cleanMessage = message.trim();
  if (!cleanMessage || appState.busy) return;
  appState.busy = true;
  addMessage("user", cleanMessage);
  setVisualState("thinking", "Consultando el núcleo local");
  const generation = appState.operationGeneration;
  try {
    const response = await cancellableFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: cleanMessage, session_id: appState.sessionId }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (generation !== appState.operationGeneration) return;
    if (payload.action) handleAction(payload.action);
    addMessage("jarvis", payload.response, `JARVIS // ${payload.provider.toUpperCase()}`);
    await speak(payload.response);
  } catch (error) {
    if (error.name === "AbortError") return;
    appState.busy = false;
    setVisualState("error", "No pude completar la conversación");
    addMessage("system", error.message);
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let index = 0; index < samples.length; index += 1, offset += 2) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}

function concatenateChunks(chunks, totalSamples) {
  const output = new Float32Array(totalSamples);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}

class LocalMicrophone {
  constructor(onUtterance) {
    this.onUtterance = onUtterance;
    this.ready = false;
    this.manual = false;
    this.handsFree = false;
    this.capturing = false;
    this.chunks = [];
    this.totalSamples = 0;
    this.preRoll = [];
    this.preRollSamples = 0;
    this.silenceSamples = 0;
    this.threshold = 0.022;
    this.calibrationValues = [];
    this.calibrating = false;
    this.calibrationTimer = null;
    this.interruptionCapture = false;
  }

  async init() {
    if (this.ready) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Este navegador no permite acceder al micrófono");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    this.context = new AudioContext({ latencyHint: "interactive" });
    await this.context.resume();
    this.source = this.context.createMediaStreamSource(this.stream);
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    this.processor = this.context.createScriptProcessor(2048, 1, 1);
    this.silentGain = this.context.createGain();
    this.silentGain.gain.value = 0;
    this.source.connect(this.analyser);
    this.source.connect(this.processor);
    this.processor.connect(this.silentGain);
    this.silentGain.connect(this.context.destination);
    this.processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      this.process(new Float32Array(input));
    };
    this.ready = true;
  }

  calculateRms(samples) {
    let sum = 0;
    for (let index = 0; index < samples.length; index += 1) sum += samples[index] ** 2;
    return Math.sqrt(sum / samples.length);
  }

  process(samples) {
    if (this.manual) {
      this.addChunk(samples);
      return;
    }
    const interruptionMode =
      (this.capturing && this.interruptionCapture) || (this.ready && appState.speaking);
    if (
      (!this.handsFree && !interruptionMode) ||
      (appState.busy && !interruptionMode) ||
      appState.interruptionPending ||
      (interruptionMode && Date.now() < appState.interruptionCooldownUntil)
    ) {
      this.preRoll = [];
      this.preRollSamples = 0;
      return;
    }

    const rms = this.calculateRms(samples);
    if (this.calibrating) {
      this.calibrationValues.push(rms);
      return;
    }

    if (!this.capturing) {
      this.preRoll.push(samples);
      this.preRollSamples += samples.length;
      const maxPreRoll = this.context.sampleRate * (interruptionMode ? 0.18 : 0.45);
      while (this.preRollSamples > maxPreRoll && this.preRoll.length > 1) {
        this.preRollSamples -= this.preRoll.shift().length;
      }
      const triggerThreshold = interruptionMode
        ? Math.max(0.025, this.threshold * 1.25)
        : this.threshold;
      if (rms >= triggerThreshold) {
        this.interruptionCapture = interruptionMode;
        if (interruptionMode) pauseSpeakingForInterruption();
        this.capturing = true;
        this.chunks = [...this.preRoll];
        this.totalSamples = this.preRollSamples;
        this.silenceSamples = 0;
        if (!interruptionMode) {
          setVisualState("listening", "Detectando frase de activación");
        }
      }
      return;
    }

    this.addChunk(samples);
    if (rms < this.threshold * 0.72) this.silenceSamples += samples.length;
    else this.silenceSamples = 0;

    const duration = this.totalSamples / this.context.sampleRate;
    const silenceDuration = this.silenceSamples / this.context.sampleRate;
    const maximumDuration = this.interruptionCapture ? 6 : 18;
    if ((duration > 0.55 && silenceDuration > 0.85) || duration > maximumDuration) {
      this.finish(true, this.interruptionCapture);
    }
  }

  addChunk(samples) {
    this.chunks.push(samples);
    this.totalSamples += samples.length;
  }

  async calibrate() {
    this.calibrating = true;
    this.calibrationValues = [];
    setVisualState("listening", "Calibrando ruido ambiental... guarda silencio");
    await new Promise((resolve) => {
      this.calibrationTimer = window.setTimeout(resolve, 1250);
    });
    const values = this.calibrationValues.sort((a, b) => a - b);
    const median = values.length ? values[Math.floor(values.length / 2)] : 0.006;
    this.threshold = Math.min(0.11, Math.max(0.016, median * 3.4));
    this.calibrating = false;
    this.calibrationValues = [];
    setVisualState("standby", "Di “Jarvis” para activarme");
  }

  async enableHandsFree() {
    await this.init();
    this.handsFree = true;
    await this.calibrate();
  }

  disableHandsFree() {
    this.handsFree = false;
    this.capturing = false;
    this.chunks = [];
    this.totalSamples = 0;
    this.preRoll = [];
    this.preRollSamples = 0;
    this.interruptionCapture = false;
  }

  async startManual() {
    await this.init();
    this.manual = true;
    this.capturing = true;
    this.chunks = [];
    this.totalSamples = 0;
    this.silenceSamples = 0;
  }

  finish(wakeMode, interruptOnly = false) {
    if (!this.capturing) return;
    const duration = this.context ? this.totalSamples / this.context.sampleRate : 0;
    const wasInterruption = interruptOnly || this.interruptionCapture;
    const samples = concatenateChunks(this.chunks, this.totalSamples);
    this.manual = false;
    this.capturing = false;
    this.chunks = [];
    this.totalSamples = 0;
    this.silenceSamples = 0;
    this.preRoll = [];
    this.preRollSamples = 0;
    this.interruptionCapture = false;
    if (duration < 0.25) {
      if (wasInterruption) resumeSpeakingAfterInterruption();
      if (!wasInterruption) {
        setVisualState("ready", "Mantén pulsado un poco más para hablar");
      }
      return;
    }
    const blob = encodeWav(samples, this.context.sampleRate);
    this.onUtterance(blob, wakeMode, wasInterruption);
  }
}

async function sendInterruption(blob) {
  if (appState.interruptionPending) return;
  appState.interruptionPending = true;
  const form = new FormData();
  form.append("audio", blob, "interruption.wav");
  form.append("session_id", appState.sessionId);
  let interrupted = false;
  try {
    const response = await fetch("/api/voice/interrupt", { method: "POST", body: form });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (payload.interrupted) {
      interrupted = true;
      stopSpeaking();
      setVisualState("ready", "Respuesta interrumpida por voz");
      showToast("De acuerdo. He dejado de hablar.");
    }
  } catch (error) {
    console.debug("Voice interruption ignored", error);
  } finally {
    if (!interrupted) await resumeSpeakingAfterInterruption();
    appState.interruptionPending = false;
    appState.interruptionCooldownUntil = Date.now() + 1800;
  }
}

async function sendUtterance(blob, wakeMode, interruptOnly = false) {
  if (interruptOnly) {
    await sendInterruption(blob);
    return;
  }
  if (appState.busy) return;
  appState.busy = true;
  setVisualState("transcribing", "Convirtiendo voz en texto localmente");
  const form = new FormData();
  form.append("audio", blob, "utterance.wav");
  form.append("session_id", appState.sessionId);
  form.append("wake_mode", String(wakeMode));
  const generation = appState.operationGeneration;
  try {
    const response = await cancellableFetch("/api/voice/utterance", {
      method: "POST",
      body: form,
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (generation !== appState.operationGeneration) return;
    if (!payload.transcript) {
      appState.busy = false;
      setVisualState("standby", "No detecté una frase clara");
      return;
    }
    if (!payload.accepted) {
      appState.busy = false;
      setVisualState("standby", "En espera de “Jarvis”");
      return;
    }
    addMessage("user", payload.transcript, payload.activated ? "TÚ // WAKE DETECTED" : "TÚ");
    if (payload.needs_command) {
      appState.busy = false;
      setVisualState("listening", "Te escucho");
      await speak(payload.response || "Te escucho.");
      return;
    }
    if (payload.response) {
      if (payload.action) handleAction(payload.action);
      addMessage("jarvis", payload.response, `JARVIS // ${(payload.provider || "LOCAL").toUpperCase()}`);
      await speak(payload.response);
    } else {
      appState.busy = false;
      setVisualState("ready", "Solicitud recibida");
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    appState.busy = false;
    setVisualState("error", "El pipeline de voz no está disponible");
    addMessage("system", error.message);
    showToast(error.message, 6000);
  }
}

const microphone = new LocalMicrophone(sendUtterance);

async function beginManualCapture() {
  if (appState.handsFree || (appState.busy && !appState.speaking)) return;
  if (appState.speaking) stopSpeaking();
  try {
    await microphone.startManual();
    if (!appState.manualIntent) {
      microphone.finish(false);
      return;
    }
    setVisualState("listening", "Habla ahora");
  } catch (error) {
    setVisualState("error", "No tengo permiso para usar el micrófono");
    showToast(`${error.message}. Revisa el permiso del navegador.`, 6000);
  }
}

function endManualCapture() {
  appState.manualIntent = false;
  if (!microphone.manual) return;
  microphone.finish(false);
}

elements.micButton.addEventListener("pointerdown", (pointerEvent) => {
  pointerEvent.preventDefault();
  appState.manualIntent = true;
  elements.micButton.setPointerCapture?.(pointerEvent.pointerId);
  beginManualCapture();
});
for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
  elements.micButton.addEventListener(eventName, endManualCapture);
}

window.addEventListener("keydown", (keyboardEvent) => {
  if (
    keyboardEvent.code === "Space" &&
    !keyboardEvent.repeat &&
    document.activeElement !== elements.textInput &&
    !appState.handsFree
  ) {
    keyboardEvent.preventDefault();
    appState.manualIntent = true;
    beginManualCapture();
  }
});
window.addEventListener("keyup", (keyboardEvent) => {
  if (keyboardEvent.code === "Space" && document.activeElement !== elements.textInput) {
    keyboardEvent.preventDefault();
    appState.manualIntent = false;
    endManualCapture();
  }
});

elements.handsFreeButton.addEventListener("click", async () => {
  if (!appState.handsFree) {
    try {
      stopSpeaking();
      elements.handsFreeButton.disabled = true;
      await microphone.enableHandsFree();
      appState.handsFree = true;
      elements.handsFreeButton.setAttribute("aria-pressed", "true");
      elements.handsFreeButton.querySelector("small").textContent = "Escuchando “Jarvis”";
      elements.footerHint.textContent = "MODO MANOS LIBRES // TODO EL AUDIO SE PROCESA LOCALMENTE";
      showToast("Modo manos libres activo. El audio se procesa únicamente en este equipo.");
    } catch (error) {
      microphone.disableHandsFree();
      setVisualState("error", "No pude activar el micrófono");
      showToast(error.message, 6000);
    } finally {
      elements.handsFreeButton.disabled = false;
    }
  } else {
    microphone.disableHandsFree();
    appState.handsFree = false;
    elements.handsFreeButton.setAttribute("aria-pressed", "false");
    elements.handsFreeButton.querySelector("small").textContent = "Di “Jarvis”";
    elements.footerHint.textContent = "PULSA Y MANTÉN PARA HABLAR // ESPACIO TAMBIÉN FUNCIONA";
    setVisualState("ready", "Mantén pulsado el núcleo para hablar");
  }
});

elements.muteButton.addEventListener("click", () => {
  appState.muted = !appState.muted;
  elements.muteButton.setAttribute("aria-pressed", String(appState.muted));
  elements.muteButton.querySelector("small").textContent = appState.muted ? "Silenciada" : "Activada";
  if (appState.muted) stopSpeaking();
  showToast(appState.muted ? "Respuesta de voz silenciada" : "Respuesta de voz activada");
});

elements.textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = elements.textInput.value;
  elements.textInput.value = "";
  sendText(value);
});

elements.resetButton.addEventListener("click", async () => {
  cancelActiveClientWork();
  stopSpeaking();
  try {
    const response = await fetch(`/api/conversation/${encodeURIComponent(appState.sessionId)}`, {
      method: "DELETE",
    });
    if (!response.ok) throw new Error(await readError(response));
    elements.transcript.innerHTML = "";
    appState.activityCount = 0;
    if (elements.activityCode) elements.activityCode.textContent = "CTX-000";
    if (elements.monitorFocus) elements.monitorFocus.textContent = "VISION // ALL DISPLAYS";
    handleAction(null);
    addMessage("jarvis", "Conversación reiniciada. Te escucho.");
    setVisualState("ready", "Contexto de conversación eliminado");
  } catch (error) {
    showToast(error.message);
  }
});

elements.approveActionButton.addEventListener("click", () => decideAction(true));
elements.rejectActionButton.addEventListener("click", () => decideAction(false));

elements.mobileAccessButton.addEventListener("click", async () => {
  try {
    await refreshRemoteAdmin();
  } catch (error) {
    showToast(error.message, 6000);
  }
  elements.mobileAccessDialog.showModal();
});

elements.closeMobileAccessButton.addEventListener("click", () => {
  elements.mobileAccessDialog.close();
});

elements.mobileAccessDialog.addEventListener("click", (event) => {
  if (event.target === elements.mobileAccessDialog) elements.mobileAccessDialog.close();
});

elements.createPairingButton.addEventListener("click", async () => {
  elements.createPairingButton.disabled = true;
  try {
    const pairing = await postJson("/api/remote/pairing/start", {});
    elements.pairingCode.textContent = pairing.code;
    elements.pairingCodePanel.hidden = false;
    window.clearInterval(appState.pairingTimer);
    const updateExpiry = () => {
      const remaining = Math.max(0, Math.ceil(pairing.expires_at - Date.now() / 1000));
      const minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
      const seconds = String(remaining % 60).padStart(2, "0");
      elements.pairingExpiry.textContent =
        remaining > 0 ? `EXPIRA EN ${minutes}:${seconds}` : "CÓDIGO EXPIRADO";
      if (remaining <= 0) {
        window.clearInterval(appState.pairingTimer);
        elements.createPairingButton.disabled = false;
      }
    };
    updateExpiry();
    appState.pairingTimer = window.setInterval(updateExpiry, 1000);
  } catch (error) {
    showToast(error.message, 6000);
    elements.createPairingButton.disabled = !appState.remoteEnabled;
  }
});

elements.remotePairingCode.addEventListener("input", () => {
  const digits = elements.remotePairingCode.value.replace(/\D/g, "").slice(0, 8);
  elements.remotePairingCode.value =
    digits.length > 4 ? `${digits.slice(0, 4)}-${digits.slice(4)}` : digits;
});

elements.remotePairingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = elements.remotePairingForm.querySelector('button[type="submit"]');
  button.disabled = true;
  setRemoteGateError();
  try {
    await pairRemoteDevice();
  } catch (error) {
    setRemoteGateError(error.name === "NotAllowedError" ? "Operación cancelada." : error.message);
  } finally {
    button.disabled = false;
  }
});

elements.authenticateRemoteButton.addEventListener("click", async () => {
  elements.authenticateRemoteButton.disabled = true;
  setRemoteGateError();
  try {
    await authenticateRemoteDevice();
  } catch (error) {
    setRemoteGateError(error.name === "NotAllowedError" ? "Operación cancelada." : error.message);
  } finally {
    elements.authenticateRemoteButton.disabled = false;
  }
});

elements.showPairingPanelButton.addEventListener("click", showRemotePairing);
elements.showAuthenticationPanelButton.addEventListener("click", showRemoteAuthentication);

elements.emergencyStopButton.addEventListener("click", async () => {
  cancelActiveClientWork();
  stopSpeaking();
  microphone.disableHandsFree();
  appState.handsFree = false;
  appState.busy = false;
  handleAction(null);
  setVisualState("standby", "Enviando parada de emergencia");
  elements.emergencyStopButton.disabled = true;
  try {
    const result = await postJson("/api/remote/stop", { session_id: appState.sessionId });
    setVisualState("standby", "Jarvis detenido desde el celular");
    addMessage(
      "system",
      `Parada remota completada. ${result.pending_actions} acción(es) pendiente(s) cancelada(s).`,
      "EMERGENCY CONTROL",
    );
    showToast("Voz y acciones pendientes detenidas.");
  } catch (error) {
    setVisualState("error", "No pude confirmar la parada remota");
    showToast(error.message, 6000);
  } finally {
    elements.emergencyStopButton.disabled = false;
  }
});

function drawWaveform() {
  const canvas = elements.waveform;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.floor(rect.width * ratio) || canvas.height !== Math.floor(rect.height * ratio)) {
    canvas.width = Math.floor(rect.width * ratio);
    canvas.height = Math.floor(rect.height * ratio);
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);
  const center = rect.height / 2;
  const time = performance.now() / 1000;
  let audioData = null;
  if (microphone.analyser && microphone.ready) {
    audioData = new Uint8Array(microphone.analyser.frequencyBinCount);
    microphone.analyser.getByteTimeDomainData(audioData);
  }
  context.beginPath();
  for (let x = 0; x <= rect.width; x += 2) {
    const progress = x / rect.width;
    let amplitude;
    if (audioData && (appState.visualState === "listening" || microphone.capturing)) {
      const index = Math.min(audioData.length - 1, Math.floor(progress * audioData.length));
      amplitude = ((audioData[index] - 128) / 128) * 22;
    } else {
      const activity = ["thinking", "speaking", "transcribing"].includes(appState.visualState) ? 1 : 0.18;
      amplitude =
        Math.sin(progress * 36 + time * 4.2) * 5 * activity +
        Math.sin(progress * 83 - time * 2.5) * 2.5 * activity;
    }
    const envelope = Math.sin(progress * Math.PI) ** 0.7;
    const y = center + amplitude * envelope;
    if (x === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  }
  const gradient = context.createLinearGradient(0, 0, rect.width, 0);
  gradient.addColorStop(0, "rgba(255, 54, 88, 0)");
  gradient.addColorStop(0.28, "rgba(255, 54, 88, 0.72)");
  gradient.addColorStop(0.5, "rgba(232, 239, 255, 0.96)");
  gradient.addColorStop(0.62, "rgba(39, 126, 255, 0.7)");
  gradient.addColorStop(1, "rgba(39, 126, 255, 0)");
  context.strokeStyle = gradient;
  context.lineWidth = 1.2;
  context.stroke();
  requestAnimationFrame(drawWaveform);
}

function updateClock() {
  const now = new Date();
  elements.clock.textContent = new Intl.DateTimeFormat("es-EC", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now);
  if (elements.systemDate) {
    const date = new Intl.DateTimeFormat("es-EC", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    })
      .format(now)
      .replaceAll(".", "")
      .toUpperCase();
    elements.systemDate.textContent = `${date} // QUITO GMT-5`;
  }
}

function startNeuralField() {
  const canvas = elements.neuralField;
  if (!canvas) return;
  const context = canvas.getContext("2d");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let width = 0;
  let height = 0;

  const resize = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };

  const draw = (time = 0) => {
    if (document.hidden) {
      if (!reducedMotion) window.requestAnimationFrame(draw);
      return;
    }
    context.clearRect(0, 0, width, height);
    const active = ["listening", "thinking", "transcribing", "speaking"].includes(
      appState.visualState,
    );
    const orbBounds = elements.micButton?.getBoundingClientRect();
    const centerX = orbBounds ? orbBounds.left + orbBounds.width / 2 : width / 2;
    const centerY = orbBounds ? orbBounds.top + orbBounds.height / 2 : height * 0.46;
    const reach = Math.hypot(
      Math.max(centerX, width - centerX),
      Math.max(centerY, height - centerY),
    ) * 1.08;
    const spokes = width < 680 ? 12 : 16;
    const rings = width < 680 ? 7 : 10;
    const rotation = reducedMotion ? 0 : Math.sin(time / 9000) * 0.018;

    context.save();
    context.translate(centerX, centerY);
    context.rotate(rotation);

    for (let spoke = 0; spoke < spokes; spoke += 1) {
      const angle = -Math.PI / 2 + (spoke / spokes) * Math.PI * 2;
      const endpointX = Math.cos(angle) * reach;
      const endpointY = Math.sin(angle) * reach;
      const gradient = context.createLinearGradient(0, 0, endpointX, endpointY);
      const secondary = spoke % 4 === 2;
      gradient.addColorStop(0, secondary ? "rgba(39, 126, 255, 0.28)" : "rgba(255, 54, 88, 0.3)");
      gradient.addColorStop(0.35, secondary ? "rgba(39, 126, 255, 0.12)" : "rgba(255, 54, 88, 0.13)");
      gradient.addColorStop(1, "rgba(255, 54, 88, 0)");
      context.beginPath();
      context.moveTo(0, 0);
      context.lineTo(endpointX, endpointY);
      context.strokeStyle = gradient;
      context.lineWidth = secondary ? 0.8 : 0.65;
      context.stroke();
    }

    for (let ring = 1; ring <= rings; ring += 1) {
      const radius = (ring / rings) * reach;
      const ringOffset = (ring % 2 ? 0.013 : -0.009) * Math.sin(time / 2600 + ring);
      context.beginPath();
      for (let spoke = 0; spoke <= spokes; spoke += 1) {
        const normalizedSpoke = spoke % spokes;
        const angle = -Math.PI / 2 + (normalizedSpoke / spokes) * Math.PI * 2 + ringOffset;
        const angularTension = 1 + Math.sin(normalizedSpoke * 2.7 + ring * 1.9) * 0.025;
        const x = Math.cos(angle) * radius * angularTension;
        const y = Math.sin(angle) * radius * angularTension;
        if (spoke === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.closePath();
      context.strokeStyle = ring % 3 === 0
        ? `rgba(39, 126, 255, ${active ? 0.14 : 0.075})`
        : `rgba(255, 54, 88, ${active ? 0.16 : 0.085})`;
      context.lineWidth = ring % 3 === 0 ? 0.8 : 0.55;
      context.stroke();
    }

    const signals = active ? 12 : 7;
    for (let index = 0; index < signals; index += 1) {
      const spoke = (index * 5 + 1) % spokes;
      const angle = -Math.PI / 2 + (spoke / spokes) * Math.PI * 2;
      const travel = reducedMotion ? (index + 2) / (signals + 3) : ((time / 2600 + index * 0.137) % 1);
      const signalRadius = reach * (0.12 + travel * 0.84);
      const x = Math.cos(angle) * signalRadius;
      const y = Math.sin(angle) * signalRadius;
      const isSecondary = index % 4 === 3;
      context.beginPath();
      context.arc(x, y, active ? 1.55 : 1.05, 0, Math.PI * 2);
      context.fillStyle = isSecondary
        ? `rgba(86, 151, 255, ${active ? 0.86 : 0.48})`
        : `rgba(255, 76, 108, ${active ? 0.9 : 0.5})`;
      context.shadowBlur = active ? 9 : 5;
      context.shadowColor = isSecondary ? "#277eff" : "#ff3658";
      context.fill();
    }

    context.shadowBlur = 0;
    for (let ring = 2; ring <= Math.min(rings, 7); ring += 2) {
      const radius = (ring / rings) * reach;
      for (let spoke = 0; spoke < spokes; spoke += 4) {
        const angle = -Math.PI / 2 + (spoke / spokes) * Math.PI * 2;
        const x = Math.cos(angle) * radius;
        const y = Math.sin(angle) * radius;
        context.beginPath();
        context.moveTo(x - 4, y);
        context.lineTo(x + 4, y);
        context.strokeStyle = "rgba(255, 231, 235, 0.16)";
        context.lineWidth = 0.7;
        context.stroke();
      }
    }
    context.restore();
    if (!reducedMotion) window.requestAnimationFrame(draw);
  };

  resize();
  window.addEventListener("resize", resize, { passive: true });
  draw();
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () =>
    navigator.serviceWorker.register("/service-worker.js", { updateViaCache: "none" }),
  );
}

function startCore() {
  if (appState.initialized) {
    connectStateSocket();
    refreshHealth();
    return;
  }
  appState.initialized = true;
  refreshHealth();
  appState.healthTimer = window.setInterval(refreshHealth, 30000);
  connectStateSocket();
  drawWaveform();
}

updateClock();
window.setInterval(updateClock, 1000);
startNeuralField();
bootstrapApplication();
