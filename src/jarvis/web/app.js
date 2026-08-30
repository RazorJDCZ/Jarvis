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
  rememberActionButton: document.querySelector("#rememberActionButton"),
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
  remoteGateEyebrow: document.querySelector("#remoteGateEyebrow"),
  remoteGateTitle: document.querySelector("#remoteGateTitle"),
  remoteIdentityLabel: document.querySelector("#remoteIdentityLabel"),
  remoteOfflinePanel: document.querySelector("#remoteOfflinePanel"),
  remoteOfflineDescription: document.querySelector("#remoteOfflineDescription"),
  retryCoreButton: document.querySelector("#retryCoreButton"),
  remoteAuthenticationPanel: document.querySelector("#remoteAuthenticationPanel"),
  authenticateRemoteButton: document.querySelector("#authenticateRemoteButton"),
  showPairingPanelButton: document.querySelector("#showPairingPanelButton"),
  showAuthenticationPanelButton: document.querySelector("#showAuthenticationPanelButton"),
  remotePairingForm: document.querySelector("#remotePairingForm"),
  remoteDeviceLabel: document.querySelector("#remoteDeviceLabel"),
  remotePairingCode: document.querySelector("#remotePairingCode"),
  remoteGateError: document.querySelector("#remoteGateError"),
  remoteSecurityNoteText: document.querySelector("#remoteSecurityNoteText"),
  emergencyStopButton: document.querySelector("#emergencyStopButton"),
  controlDeckButton: document.querySelector("#controlDeckButton"),
  controlDeckCompactButton: document.querySelector("#controlDeckCompactButton"),
  controlDeckDialog: document.querySelector("#controlDeckDialog"),
  closeControlDeckButton: document.querySelector("#closeControlDeckButton"),
  controlDeckSummary: document.querySelector("#controlDeckSummary"),
  deckTabs: [...document.querySelectorAll("[data-deck-tab]")],
  deckPanels: [...document.querySelectorAll("[data-deck-panel]")],
  deckRefreshButtons: [...document.querySelectorAll("[data-deck-refresh]")],
  traceList: document.querySelector("#traceList"),
  reminderForm: document.querySelector("#reminderForm"),
  reminderTitle: document.querySelector("#reminderTitle"),
  reminderDue: document.querySelector("#reminderDue"),
  reminderRecurrence: document.querySelector("#reminderRecurrence"),
  reminderCount: document.querySelector("#reminderCount"),
  reminderList: document.querySelector("#reminderList"),
  connectorList: document.querySelector("#connectorList"),
  systemConnectorList: document.querySelector("#systemConnectorList"),
  attachmentButton: document.querySelector("#attachmentButton"),
  cameraButton: document.querySelector("#cameraButton"),
  attachmentInput: document.querySelector("#attachmentInput"),
  attachmentTray: document.querySelector("#attachmentTray"),
  deckAttachButton: document.querySelector("#deckAttachButton"),
  deckCameraButton: document.querySelector("#deckCameraButton"),
  deckAttachmentList: document.querySelector("#deckAttachmentList"),
  knowledgeSourceList: document.querySelector("#knowledgeSourceList"),
  workspaceList: document.querySelector("#workspaceList"),
  cameraPanel: document.querySelector("#cameraPanel"),
  cameraPreview: document.querySelector("#cameraPreview"),
  cameraCanvas: document.querySelector("#cameraCanvas"),
  cameraPlaceholder: document.querySelector("#cameraPlaceholder"),
  cameraStatus: document.querySelector("#cameraStatus"),
  captureCameraButton: document.querySelector("#captureCameraButton"),
  stopCameraButton: document.querySelector("#stopCameraButton"),
  systemMetrics: document.querySelector("#systemMetrics"),
  skillList: document.querySelector("#skillList"),
  permissionList: document.querySelector("#permissionList"),
  interfaceVersion: document.querySelector("#interfaceVersion"),
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
  notificationTimer: null,
  notificationPending: false,
  initialized: false,
  pairingTimer: null,
  bootstrapRetryTimer: null,
  bootstrapPending: false,
  operationGeneration: 0,
  activeControllers: new Set(),
  ttsController: null,
  attachments: [],
  uploadingAttachments: 0,
  activeDeckTab: "activity",
  deckMetricsTimer: null,
  cameraStream: null,
  cameraStarting: false,
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

async function submitAgentFeedback(traceId, rating, controls) {
  for (const button of controls.querySelectorAll("button")) button.disabled = true;
  try {
    const response = await cancellableFetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: appState.sessionId,
        trace_id: traceId,
        rating,
        category: "conversation",
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    controls.dataset.rating = String(rating);
    controls.setAttribute("aria-label", "Evaluación guardada localmente");
    showToast("Evaluación guardada sólo en esta PC.", 3500);
  } catch (error) {
    for (const button of controls.querySelectorAll("button")) button.disabled = false;
    showToast(error.message || "No pude guardar la evaluación.", 5000);
  }
}

function addMessage(role, text, label, metadata = {}) {
  const article = document.createElement("article");
  article.className = `message ${role}-message`;
  const displayLabel = label || (role === "jarvis" ? "JARVIS" : role === "user" ? "TÚ" : "SYSTEM");
  const labelElement = document.createElement("span");
  const textElement = document.createElement("p");
  labelElement.textContent = displayLabel;
  textElement.textContent = text;
  article.append(labelElement, textElement);
  if (metadata.traceId) {
    attachTraceDetails(article, metadata.traceId);
    if (role === "jarvis") {
      const feedback = document.createElement("div");
      feedback.className = "message-feedback";
      feedback.setAttribute("aria-label", "Evaluar respuesta");
      for (const [rating, symbol, title] of [
        [1, "↑", "Respuesta útil"],
        [-1, "↓", "Respuesta incorrecta o poco útil"],
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = symbol;
        button.title = title;
        button.setAttribute("aria-label", title);
        button.addEventListener("click", () => submitAgentFeedback(metadata.traceId, rating, feedback));
        feedback.appendChild(button);
      }
      article.appendChild(feedback);
    }
  }
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

const ATTACHMENT_CLIENT_LIMIT = 12 * 1024 * 1024;
const ATTACHMENT_CLIENT_COUNT = 4;

function deckSessionPath(path, extra = {}) {
  const url = new URL(path, location.origin);
  url.searchParams.set("session_id", appState.sessionId);
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return `${url.pathname}${url.search}`;
}

async function optionalJson(path, init = {}) {
  try {
    const response = await fetch(path, { cache: "no-store", ...init });
    if ([404, 405, 501].includes(response.status)) {
      return { available: false, data: null, message: "Módulo todavía no publicado por el núcleo." };
    }
    if (!response.ok) {
      return { available: false, data: null, message: await readError(response) };
    }
    if (response.status === 204) return { available: true, data: {}, message: "" };
    const text = await response.text();
    return {
      available: true,
      data: text ? JSON.parse(text) : {},
      message: "",
    };
  } catch (error) {
    return {
      available: false,
      data: null,
      message: error.name === "AbortError" ? "Solicitud cancelada." : error.message,
    };
  }
}

function payloadArray(payload, keys = []) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of keys) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  if (payload.data && payload.data !== payload) return payloadArray(payload.data, keys);
  return [];
}

function payloadRecords(payload, keys = []) {
  const list = payloadArray(payload, keys);
  if (list.length) return list;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return [];
  for (const key of keys) {
    const nested = payload[key];
    if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      return Object.entries(nested).map(([id, value]) =>
        value && typeof value === "object"
          ? { id, ...value }
          : { id, name: id, value, enabled: typeof value === "boolean" ? value : undefined },
      );
    }
  }
  const ignored = new Set(["status", "summary", "counts", "version", "timestamp", "metrics"]);
  return Object.entries(payload)
    .filter(([key]) => !ignored.has(key))
    .map(([key, value]) =>
      value && typeof value === "object"
        ? { id: key, ...value }
        : { id: key, name: key, value, enabled: typeof value === "boolean" ? value : undefined },
    );
}

function firstText(item, keys, fallback = "") {
  if (!item || typeof item !== "object") return fallback;
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return fallback;
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "TAMAÑO DESCONOCIDO";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatDeckDate(value) {
  if (value === undefined || value === null || value === "") return "SIN FECHA";
  let date;
  if (typeof value === "number") date = new Date(value < 10_000_000_000 ? value * 1000 : value);
  else date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("es-EC", { dateStyle: "medium", timeStyle: "short" });
}

function statusTone(value) {
  const status = String(value || "").toLowerCase();
  if (/failed|error|blocked|rejected|cancelled|offline|disabled/.test(status)) return "failed";
  if (/pending|warning|waiting|paused|due|confirm/.test(status)) return "warning";
  if (/complete|success|ready|active|available|online|enabled|ok/.test(status)) return "success";
  return "";
}

function setDeckState(container, title, detail, tone = "loading") {
  if (!container) return;
  container.replaceChildren();
  const state = document.createElement("div");
  state.className = `deck-${tone}`;
  const heading = document.createElement("strong");
  const copy = document.createElement("small");
  heading.textContent = title;
  copy.textContent = detail;
  state.append(heading, copy);
  container.appendChild(state);
}

function createBadge(text, tone = "") {
  const badge = document.createElement("span");
  badge.className = `deck-badge ${tone}`.trim();
  badge.textContent = String(text || "INFO").toUpperCase();
  return badge;
}

function normalizedCollectionItem(item) {
  if (typeof item === "string") return { name: item };
  if (typeof item === "number" || typeof item === "boolean") return { value: item };
  return item && typeof item === "object" ? item : {};
}

function renderSimpleCollection(container, result, options = {}) {
  const { keys = [], emptyTitle = "SIN REGISTROS", emptyDetail = "No hay elementos disponibles." } = options;
  if (!result.available) {
    setDeckState(
      container,
      "MÓDULO EN PREPARACIÓN",
      result.message || "Esta capacidad estará disponible cuando el núcleo termine de integrarla.",
      "unavailable",
    );
    return;
  }
  const records = payloadRecords(result.data, keys).map(normalizedCollectionItem);
  container.replaceChildren();
  if (!records.length) {
    setDeckState(container, emptyTitle, emptyDetail, "empty");
    return;
  }
  for (const item of records) {
    const row = document.createElement("article");
    const tone = statusTone(item.status ?? item.state ?? item.enabled ?? item.available);
    row.className = `deck-item ${tone}`.trim();
    const rowTop = document.createElement("div");
    rowTop.className = "deck-item-row";
    const copy = document.createElement("div");
    copy.className = "deck-item-copy";
    const title = document.createElement("strong");
    const subtitle = document.createElement("small");
    const description = document.createElement("p");
    title.textContent = firstText(
      item,
      ["title", "name", "label", "action", "id"],
      "Elemento local",
    );
    const state = firstText(item, ["status", "state", "mode", "decision"], "");
    const detail = firstText(
      item,
      ["description", "detail", "summary", "path", "source", "origin", "expires_at", "value"],
      "",
    );
    subtitle.textContent = state ? state.toUpperCase() : "LOCAL // PRIVATE";
    copy.append(title, subtitle);
    rowTop.append(copy, createBadge(state || (item.enabled === false ? "OFF" : "READY"), tone));
    row.appendChild(rowTop);
    if (detail && detail !== title.textContent) {
      description.textContent = detail;
      row.appendChild(description);
    }
    container.appendChild(row);
  }
}

async function forgetPermission(permission, button) {
  const action = firstText(permission, ["action"], "");
  if (!action) return;
  const remote = permission.remote === true || String(permission.remote).toLowerCase() === "true";
  button.disabled = true;
  try {
    const path = `/api/permissions/${encodeURIComponent(action)}?remote=${remote}`;
    const response = await fetch(path, { method: "DELETE" });
    if (response.status === 403) {
      throw new Error("Por seguridad, los permisos solo pueden olvidarse desde la consola local de la PC.");
    }
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    showToast(payload.deleted === false ? "La regla ya no estaba activa." : "Permiso olvidado.");
    await loadSystem();
  } catch (error) {
    showToast(error.message, 7000);
  } finally {
    button.disabled = false;
  }
}

function renderPermissions(result) {
  renderSimpleCollection(elements.permissionList, result, {
    keys: ["permissions", "rules", "items"],
    emptyTitle: "POLÍTICA PREDETERMINADA",
    emptyDetail: "Jarvis seguirá solicitando confirmación según el riesgo de cada acción.",
  });
  if (!result.available) return;
  const permissions = payloadRecords(result.data, ["permissions", "rules", "items"])
    .map(normalizedCollectionItem);
  const rows = [...elements.permissionList.querySelectorAll(".deck-item")];
  permissions.forEach((permission, index) => {
    const action = firstText(permission, ["action"], "");
    const rowTop = rows[index]?.querySelector(".deck-item-row");
    if (!action || !rowTop) return;
    const controls = document.createElement("div");
    controls.className = "deck-item-controls";
    const badge = rowTop.querySelector(".deck-badge");
    if (badge) controls.appendChild(badge);
    const forget = document.createElement("button");
    forget.type = "button";
    forget.className = "deck-item-action";
    forget.textContent = "OLVIDAR";
    forget.title = `Olvidar el permiso guardado para ${action}`;
    forget.setAttribute("aria-label", `Olvidar permiso para ${action}`);
    forget.addEventListener("click", () => forgetPermission(permission, forget));
    controls.appendChild(forget);
    rowTop.appendChild(controls);
  });
}

function traceIdentifier(trace) {
  return firstText(trace, ["trace_id", "id", "request_id"], "");
}

function traceSteps(trace) {
  return payloadArray(trace, ["spans", "steps", "events", "actions", "timeline"]);
}

function buildTraceEntry(rawTrace, open = false) {
  const trace = normalizedCollectionItem(rawTrace);
  const status = firstText(trace, ["status", "state", "result"], "completed");
  const tone = statusTone(status);
  const details = document.createElement("details");
  details.className = `trace-entry ${tone}`.trim();
  details.open = open;
  const summary = document.createElement("summary");
  const copy = document.createElement("div");
  copy.className = "deck-item-copy";
  const title = document.createElement("strong");
  const subtitle = document.createElement("small");
  title.textContent = firstText(
    trace,
    ["title", "input_summary", "request_label", "request", "action", "name", "summary"],
    "Interacción registrada",
  );
  const timestamp = trace.started_at ?? trace.timestamp ?? trace.created_at;
  const duration = Number(trace.duration_ms);
  subtitle.textContent = `${formatDeckDate(timestamp)}${
    Number.isFinite(duration) ? ` // ${Math.round(duration)} MS` : ""
  }`;
  copy.append(title, subtitle);
  summary.append(copy, createBadge(status, tone));
  details.appendChild(summary);

  const description = firstText(trace, ["description", "message", "outcome", "detail"], "");
  if (description && description !== title.textContent) {
    const paragraph = document.createElement("p");
    paragraph.textContent = description;
    details.appendChild(paragraph);
  }
  const steps = traceSteps(trace);
  if (steps.length) {
    const stepList = document.createElement("div");
    stepList.className = "trace-steps";
    steps.forEach((rawStep, index) => {
      const step = normalizedCollectionItem(rawStep);
      const row = document.createElement("div");
      row.className = "trace-step";
      const number = document.createElement("span");
      const label = document.createElement("span");
      const stepStatus = firstText(step, ["status", "state", "result"], "");
      number.textContent = String(index + 1).padStart(2, "0");
      label.textContent = firstText(
        step,
        ["title", "name", "action", "event", "description", "message"],
        "Paso verificado",
      );
      row.append(number, label, createBadge(stepStatus || "OK", statusTone(stepStatus)));
      stepList.appendChild(row);
    });
    details.appendChild(stepList);
  }
  return details;
}

async function loadTraces() {
  setDeckState(elements.traceList, "RECUPERANDO TRAZAS", "Consultando el historial local censurado.");
  const result = await optionalJson(deckSessionPath("/api/traces", { limit: 50 }));
  if (!result.available) {
    setDeckState(
      elements.traceList,
      "TRAZAS TODAVÍA NO DISPONIBLES",
      result.message || "El historial aparecerá aquí al integrarse el colector local.",
      "unavailable",
    );
    return;
  }
  const traces = payloadArray(result.data, ["traces", "entries", "items"]);
  elements.traceList.replaceChildren();
  if (!traces.length) {
    setDeckState(
      elements.traceList,
      "SIN ACTIVIDAD REGISTRADA",
      "Las próximas decisiones y acciones verificadas aparecerán aquí.",
      "empty",
    );
    return;
  }
  for (const trace of traces.slice().reverse()) elements.traceList.appendChild(buildTraceEntry(trace));
}

function attachTraceDetails(article, traceId) {
  const details = document.createElement("details");
  details.className = "message-trace";
  const summary = document.createElement("summary");
  const body = document.createElement("div");
  body.className = "message-trace-body";
  summary.textContent = "VER TRAZA DE EJECUCIÓN";
  details.append(summary, body);
  details.addEventListener("toggle", async () => {
    if (!details.open || details.dataset.loaded === "true") return;
    details.dataset.loaded = "true";
    setDeckState(body, "RECUPERANDO TRAZA", "Leyendo únicamente la sesión actual.");
    const result = await optionalJson(deckSessionPath("/api/traces", { limit: 50 }));
    const traces = result.available
      ? payloadArray(result.data, ["traces", "entries", "items"])
      : [];
    const trace = traces.find((entry) => traceIdentifier(entry) === String(traceId));
    body.replaceChildren();
    if (trace) body.appendChild(buildTraceEntry(trace, true));
    else {
      setDeckState(
        body,
        result.available ? "TRAZA RESUMIDA" : "TRAZA NO DISPONIBLE",
        result.available
          ? "El núcleo confirmó la ejecución, pero el detalle ya no está en la ventana reciente."
          : result.message,
        result.available ? "empty" : "unavailable",
      );
    }
  });
  article.appendChild(details);
}

function renderReminders(result) {
  if (!result.available) {
    elements.reminderCount.textContent = "OFFLINE";
    setDeckState(
      elements.reminderList,
      "AGENDA EN PREPARACIÓN",
      result.message || "Los recordatorios estarán disponibles al iniciar su servicio local.",
      "unavailable",
    );
    return;
  }
  const reminders = payloadArray(result.data, ["reminders", "tasks", "items"]);
  elements.reminderCount.textContent = String(reminders.length).padStart(2, "0");
  elements.reminderList.replaceChildren();
  if (!reminders.length) {
    setDeckState(
      elements.reminderList,
      "AGENDA DESPEJADA",
      "No tienes recordatorios activos en esta sesión.",
      "empty",
    );
    return;
  }
  for (const rawReminder of reminders) {
    const reminder = normalizedCollectionItem(rawReminder);
    const status = firstText(reminder, ["status", "state"], "active");
    const tone = statusTone(status);
    const row = document.createElement("article");
    row.className = `deck-item ${tone}`.trim();
    const top = document.createElement("div");
    top.className = "deck-item-row";
    const copy = document.createElement("div");
    copy.className = "deck-item-copy";
    const title = document.createElement("strong");
    const due = document.createElement("small");
    title.textContent = firstText(reminder, ["title", "name", "text"], "Recordatorio");
    const dueValue = reminder.due ?? reminder.due_at ?? reminder.scheduled_at ?? reminder.next_run;
    const recurrence = firstText(reminder, ["recurrence", "schedule"], "");
    due.textContent = `${formatDeckDate(dueValue)}${recurrence ? ` // ${recurrence.toUpperCase()}` : ""}`;
    copy.append(title, due);
    top.append(copy, createBadge(status, tone));
    const reminderId = firstText(reminder, ["id", "reminder_id", "task_id"], "");
    if (reminderId && !/completed|cancelled/i.test(status)) {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "deck-item-action";
      cancel.textContent = "CANCELAR";
      cancel.addEventListener("click", () => cancelReminder(reminderId, title.textContent, cancel));
      top.appendChild(cancel);
    }
    row.appendChild(top);
    elements.reminderList.appendChild(row);
  }
}

async function loadAgenda() {
  setDeckState(elements.reminderList, "SINCRONIZANDO AGENDA", "Consultando recordatorios locales.");
  setDeckState(elements.connectorList, "COMPROBANDO APPA", "Validando conectores privados.");
  const [reminders, connectors] = await Promise.all([
    optionalJson(deckSessionPath("/api/reminders")),
    optionalJson("/api/connectors"),
  ]);
  renderReminders(reminders);
  renderSimpleCollection(elements.connectorList, connectors, {
    keys: ["connectors", "integrations", "items"],
    emptyTitle: "SIN CONECTORES ACTIVOS",
    emptyDetail: "Appa y otros servicios locales aparecerán aquí cuando estén configurados.",
  });
  renderSimpleCollection(elements.systemConnectorList, connectors, {
    keys: ["connectors", "integrations", "items"],
    emptyTitle: "SIN ENLACES ACTIVOS",
    emptyDetail: "No hay conectores adicionales en ejecución.",
  });
}

async function cancelReminder(reminderId, title, button) {
  if (!window.confirm(`¿Cancelar el recordatorio “${title}”?`)) return;
  button.disabled = true;
  const path = deckSessionPath(`/api/reminders/${encodeURIComponent(reminderId)}`);
  const result = await optionalJson(path, { method: "DELETE" });
  if (!result.available) {
    button.disabled = false;
    showToast(result.message || "No pude cancelar el recordatorio.", 6000);
    return;
  }
  showToast("Recordatorio cancelado.");
  await loadAgenda();
}

async function createReminder(event) {
  event.preventDefault();
  const title = elements.reminderTitle.value.trim();
  const dueValue = elements.reminderDue.value;
  if (!title || !dueValue) return;
  const submit = elements.reminderForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    if ("Notification" in window && Notification.permission === "default") {
      try {
        await Notification.requestPermission();
      } catch (error) {
        console.debug("Notification permission could not be requested", error);
      }
    }
    const dueDate = new Date(dueValue);
    if (Number.isNaN(dueDate.getTime())) throw new Error("La fecha del recordatorio no es válida.");
    const response = await fetch("/api/reminders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: appState.sessionId,
        title,
        due: dueDate.toISOString(),
        recurrence: elements.reminderRecurrence.value || null,
      }),
    });
    if ([404, 405, 501].includes(response.status)) {
      throw new Error("La agenda local todavía está en preparación.");
    }
    if (!response.ok) throw new Error(await readError(response));
    elements.reminderForm.reset();
    setDefaultReminderDue();
    showToast("Recordatorio guardado en la agenda local.");
    await loadAgenda();
  } catch (error) {
    showToast(error.message, 6000);
  } finally {
    submit.disabled = false;
  }
}

async function pollNotifications() {
  if (
    appState.notificationPending ||
    (appState.remote && !appState.remoteAuthenticated)
  ) {
    return;
  }
  appState.notificationPending = true;
  try {
    const result = await optionalJson(
      deckSessionPath("/api/notifications", { consume: true }),
    );
    if (!result.available) return;
    const notifications = payloadArray(result.data, ["notifications", "items"]);
    for (const notification of notifications) {
      const isSystemAlert = firstText(notification, ["event"], "") === "system-alert";
      const title = firstText(
        notification,
        isSystemAlert ? ["message", "title"] : ["title", "message"],
        isSystemAlert ? "El monitor detectó una condición que requiere atención." : "Recordatorio",
      );
      const messageLabel = isSystemAlert ? "JARVIS // SYSTEM MONITOR" : "JARVIS // AGENDA";
      const toastLabel = isSystemAlert ? "Alerta del sistema" : "Recordatorio";
      addMessage("system", title, messageLabel);
      showToast(`${toastLabel}: ${title}`, 8000);
      if (
        "Notification" in window &&
        Notification.permission === "granted" &&
        document.hidden
      ) {
        try {
          new Notification(
            isSystemAlert ? "Alerta del sistema de Jarvis" : "Recordatorio de Jarvis",
            {
              body: title,
              icon: "/static/icon.svg?v=agent-v8",
              tag: isSystemAlert
                ? `jarvis-system-${notification.metric || title}`
                : `jarvis-reminder-${notification.id || title}`,
            },
          );
        } catch (error) {
          console.debug("System notification could not be displayed", error);
        }
      }
    }
  } finally {
    appState.notificationPending = false;
  }
}

function setDefaultReminderDue() {
  if (elements.reminderDue.value) return;
  const due = new Date(Date.now() + 60 * 60 * 1000);
  due.setMinutes(Math.ceil(due.getMinutes() / 5) * 5, 0, 0);
  const local = new Date(due.getTime() - due.getTimezoneOffset() * 60_000);
  elements.reminderDue.value = local.toISOString().slice(0, 16);
}

function attachmentId(item) {
  return firstText(item, ["id", "attachment_id", "file_id"], "");
}

function attachmentName(item) {
  return firstText(item, ["name", "filename", "original_name", "title"], "Archivo adjunto");
}

function attachmentMime(item) {
  return firstText(item, ["mime_type", "content_type", "type"], "application/octet-stream");
}

function attachmentFromResponse(payload, file, localItem) {
  const candidates = payloadArray(payload, ["attachments", "items", "files"]);
  const raw = payload?.attachment ?? payload?.file ?? candidates[0] ?? payload;
  const item = normalizedCollectionItem(raw);
  const id = attachmentId(item);
  if (!id) throw new Error("El núcleo recibió el archivo, pero no devolvió su identificador.");
  return {
    ...item,
    id,
    name: firstText(item, ["name", "filename", "original_name", "title"], localItem.name),
    size: Number(item.size ?? item.bytes ?? file.size),
    mime_type: firstText(
      item,
      ["mime_type", "content_type", "type"],
      file.type || "application/octet-stream",
    ),
    localKey: localItem.localKey,
    previewUrl: localItem.previewUrl,
    status: "ready",
  };
}

function releaseAttachmentPreview(item) {
  if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl);
}

function attachmentStatusLabel(item) {
  if (item.status === "uploading") return "CARGANDO";
  if (item.status === "failed") return "ERROR";
  return formatBytes(item.size ?? item.bytes);
}

function buildAttachmentChip(item) {
  const chip = document.createElement("article");
  chip.className = `attachment-chip ${item.status || "ready"}`;
  const preview = document.createElement("div");
  preview.className = "attachment-chip-preview";
  if (item.previewUrl && attachmentMime(item).startsWith("image/")) {
    const image = document.createElement("img");
    image.src = item.previewUrl;
    image.alt = "";
    preview.appendChild(image);
  } else {
    const extension = attachmentName(item).split(".").pop()?.slice(0, 4).toUpperCase();
    preview.textContent = extension || "FILE";
  }
  const copy = document.createElement("div");
  copy.className = "attachment-chip-copy";
  const title = document.createElement("strong");
  const status = document.createElement("small");
  title.textContent = attachmentName(item);
  status.textContent = attachmentStatusLabel(item);
  copy.append(title, status);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `Quitar ${attachmentName(item)}`);
  remove.disabled = item.status === "uploading";
  remove.addEventListener("click", () => removeSelectedAttachment(item));
  chip.append(preview, copy, remove);
  return chip;
}

function renderAttachmentTray() {
  elements.attachmentTray.replaceChildren();
  elements.attachmentTray.hidden = appState.attachments.length === 0;
  for (const item of appState.attachments) {
    elements.attachmentTray.appendChild(buildAttachmentChip(item));
  }
  elements.attachmentButton.disabled = appState.uploadingAttachments > 0;
  elements.cameraButton.disabled = appState.uploadingAttachments > 0 || appState.cameraStarting;
}

function clearAttachmentSelection() {
  for (const item of appState.attachments) releaseAttachmentPreview(item);
  appState.attachments = [];
  renderAttachmentTray();
}

async function removeSelectedAttachment(item) {
  const id = attachmentId(item);
  if (id) {
    const result = await optionalJson(
      deckSessionPath(`/api/attachments/${encodeURIComponent(id)}`),
      { method: "DELETE" },
    );
    if (!result.available && !/no encontr|not found/i.test(result.message || "")) {
      showToast(result.message || "No pude retirar el adjunto.", 6000);
      return;
    }
  }
  appState.attachments = appState.attachments.filter((candidate) => candidate !== item);
  releaseAttachmentPreview(item);
  renderAttachmentTray();
  if (elements.controlDeckDialog.open && appState.activeDeckTab === "files") await loadFiles();
}

async function uploadFiles(fileList, source = "file") {
  const remaining = Math.max(0, ATTACHMENT_CLIENT_COUNT - appState.attachments.length);
  const files = [...fileList].slice(0, remaining);
  if (fileList.length > remaining) {
    showToast(`Puedes adjuntar hasta ${ATTACHMENT_CLIENT_COUNT} archivos por solicitud.`, 6000);
  }
  const completed = [];
  for (const file of files) {
    if (!(file instanceof Blob) || !file.size) {
      showToast("Omití un archivo vacío.", 5000);
      continue;
    }
    if (file.size > ATTACHMENT_CLIENT_LIMIT) {
      showToast(`${file.name} supera el límite preventivo de 12 MB.`, 6000);
      continue;
    }
    const localItem = {
      localKey: crypto.randomUUID ? crypto.randomUUID() : `upload-${Date.now()}-${Math.random()}`,
      name: file.name || `capture-${Date.now()}.jpg`,
      size: file.size,
      mime_type: file.type || "application/octet-stream",
      source,
      previewUrl: file.type?.startsWith("image/") ? URL.createObjectURL(file) : null,
      status: "uploading",
    };
    appState.attachments.push(localItem);
    appState.uploadingAttachments += 1;
    renderAttachmentTray();
    try {
      const form = new FormData();
      form.append("session_id", appState.sessionId);
      form.append("source", source);
      form.append("file", file, localItem.name);
      const response = await cancellableFetch("/api/attachments", { method: "POST", body: form });
      if ([404, 405, 501].includes(response.status)) {
        throw new Error("El receptor seguro de archivos todavía está en preparación.");
      }
      if (!response.ok) throw new Error(await readError(response));
      const ready = attachmentFromResponse(await response.json(), file, localItem);
      const index = appState.attachments.indexOf(localItem);
      if (index >= 0) appState.attachments.splice(index, 1, ready);
      completed.push(ready);
    } catch (error) {
      if (error.name === "AbortError") {
        appState.attachments = appState.attachments.filter((candidate) => candidate !== localItem);
        releaseAttachmentPreview(localItem);
      } else {
        localItem.status = "failed";
        localItem.error = error.message;
        showToast(`${localItem.name}: ${error.message}`, 6500);
      }
    } finally {
      appState.uploadingAttachments = Math.max(0, appState.uploadingAttachments - 1);
      renderAttachmentTray();
    }
  }
  elements.attachmentInput.value = "";
  if (elements.controlDeckDialog.open && appState.activeDeckTab === "files") await loadFiles();
  return completed;
}

function renderDeckAttachments(result) {
  if (!result.available) {
    if (appState.attachments.length) {
      elements.deckAttachmentList.replaceChildren();
      for (const item of appState.attachments) {
        const row = document.createElement("div");
        row.className = `deck-item ${item.status === "failed" ? "failed" : ""}`.trim();
        const title = document.createElement("strong");
        const detail = document.createElement("small");
        title.textContent = attachmentName(item);
        detail.textContent = attachmentStatusLabel(item);
        row.append(title, detail);
        elements.deckAttachmentList.appendChild(row);
      }
      return;
    }
    setDeckState(
      elements.deckAttachmentList,
      "ARCHIVOS EN PREPARACIÓN",
      result.message || "El almacén efímero todavía no está disponible.",
      "unavailable",
    );
    return;
  }
  const attachments = payloadArray(result.data, ["attachments", "files", "items"]);
  elements.deckAttachmentList.replaceChildren();
  if (!attachments.length) {
    setDeckState(
      elements.deckAttachmentList,
      "SIN ADJUNTOS",
      "Los archivos se conservan solo durante el tiempo necesario.",
      "empty",
    );
    return;
  }
  for (const rawItem of attachments) {
    const item = normalizedCollectionItem(rawItem);
    const row = document.createElement("article");
    row.className = "deck-item";
    const title = document.createElement("strong");
    const detail = document.createElement("small");
    title.textContent = attachmentName(item);
    detail.textContent = `${formatBytes(item.size ?? item.bytes)} // ${attachmentMime(item)}`;
    row.append(title, detail);
    elements.deckAttachmentList.appendChild(row);
  }
}

async function loadFiles() {
  setDeckState(elements.deckAttachmentList, "LEYENDO ADJUNTOS", "Consultando la sesión actual.");
  setDeckState(elements.knowledgeSourceList, "LEYENDO BIBLIOTECA", "Buscando fuentes locales.");
  setDeckState(elements.workspaceList, "LEYENDO WORKSPACES", "Consultando carpetas autorizadas.");
  const [attachments, knowledge, workspaces] = await Promise.all([
    optionalJson(deckSessionPath("/api/attachments")),
    optionalJson(deckSessionPath("/api/knowledge/sources")),
    optionalJson("/api/workspaces"),
  ]);
  renderDeckAttachments(attachments);
  renderSimpleCollection(elements.knowledgeSourceList, knowledge, {
    keys: ["sources", "documents", "items"],
    emptyTitle: "BIBLIOTECA VACÍA",
    emptyDetail: "Puedes adjuntar un documento y pedir que se incorpore a tu biblioteca.",
  });
  renderSimpleCollection(elements.workspaceList, workspaces, {
    keys: ["workspaces", "projects", "items"],
    emptyTitle: "SIN WORKSPACES AUTORIZADOS",
    emptyDetail: "Las carpetas de desarrollo deben autorizarse desde la PC.",
  });
}

function stopCamera() {
  const stream = appState.cameraStream;
  appState.cameraStream = null;
  if (stream) {
    for (const track of stream.getTracks()) track.stop();
  }
  if (elements.cameraPreview) {
    elements.cameraPreview.pause();
    elements.cameraPreview.srcObject = null;
  }
  appState.cameraStarting = false;
  elements.cameraButton.disabled = appState.uploadingAttachments > 0;
  elements.cameraPanel.hidden = true;
  elements.cameraPlaceholder.hidden = false;
  elements.cameraStatus.textContent = "";
}

async function startCamera() {
  if (appState.cameraStream || appState.cameraStarting) return;
  elements.cameraPanel.hidden = false;
  elements.cameraPlaceholder.hidden = false;
  elements.cameraStatus.textContent = "Solicitando acceso explícito a la cámara de este dispositivo.";
  appState.cameraStarting = true;
  elements.cameraButton.disabled = true;
  elements.captureCameraButton.disabled = true;
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Este navegador no ofrece acceso seguro a la cámara.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
    });
    appState.cameraStream = stream;
    elements.cameraPreview.srcObject = stream;
    await elements.cameraPreview.play();
    elements.cameraPlaceholder.hidden = true;
    elements.cameraStatus.textContent =
      "La imagen permanece en este dispositivo hasta que pulses Capturar y adjuntar.";
    elements.captureCameraButton.disabled = false;
  } catch (error) {
    stopCamera();
    elements.cameraPanel.hidden = false;
    elements.cameraStatus.textContent =
      error.name === "NotAllowedError"
        ? "Permiso de cámara rechazado. Puedes habilitarlo desde la configuración del navegador."
        : error.message;
  } finally {
    appState.cameraStarting = false;
    elements.cameraButton.disabled = appState.uploadingAttachments > 0;
  }
}

function cameraBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("No pude preparar la captura."))),
      "image/jpeg",
      0.88,
    );
  });
}

async function captureCamera() {
  const stream = appState.cameraStream;
  const video = elements.cameraPreview;
  if (!stream || !video.videoWidth || !video.videoHeight) {
    showToast("La cámara todavía no tiene una imagen lista.", 5000);
    return;
  }
  elements.captureCameraButton.disabled = true;
  elements.cameraStatus.textContent = "Preparando captura efímera…";
  let completed = [];
  try {
    const scale = Math.min(1, 1600 / video.videoWidth);
    const canvas = elements.cameraCanvas;
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("El navegador no pudo preparar el lienzo de captura.");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await cameraBlob(canvas);
    const file = new File([blob], `jarvis-camera-${Date.now()}.jpg`, { type: "image/jpeg" });
    completed = await uploadFiles([file], "camera");
  } catch (error) {
    showToast(error.message, 6000);
  } finally {
    stopCamera();
    elements.captureCameraButton.disabled = false;
  }
  if (completed.length) {
    showToast("Captura adjuntada. Ya puedes indicar qué deseas analizar.");
    elements.controlDeckDialog.close();
    elements.textInput.focus();
  }
}

function metricValue(metrics, keys) {
  for (const key of keys) {
    const value = metrics?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function addMetricCard(label, value, detail, percent = null) {
  const card = document.createElement("article");
  card.className = "metric-card";
  const name = document.createElement("span");
  const reading = document.createElement("strong");
  const copy = document.createElement("small");
  name.textContent = label;
  reading.textContent = value;
  copy.textContent = detail;
  card.append(name, reading, copy);
  if (typeof percent === "number") {
    const track = document.createElement("div");
    track.className = "metric-track";
    const progress = document.createElement("progress");
    progress.max = 100;
    progress.value = Math.max(0, Math.min(100, percent));
    progress.setAttribute("aria-label", `${label}: ${Math.round(percent)} por ciento`);
    track.appendChild(progress);
    card.appendChild(track);
  }
  elements.systemMetrics.appendChild(card);
}

function renderSystemMetrics(result) {
  if (!result.available) {
    setDeckState(
      elements.systemMetrics,
      "TELEMETRÍA EN PREPARACIÓN",
      result.message || "Las métricas ampliadas todavía no están publicadas.",
      "unavailable",
    );
    return;
  }
  const metrics = result.data?.metrics ?? result.data?.system ?? result.data ?? {};
  const cpu = metricValue(metrics, ["cpu_percent", "cpu", "processor_percent"]);
  const memory = metricValue(metrics, ["memory_percent", "ram_percent", "memory"]);
  const disk = metricValue(metrics, ["disk_percent", "storage_percent", "disk"]);
  const battery = metricValue(metrics, ["battery_percent", "battery"]);
  const temperature = metricValue(metrics, ["temperature_c", "cpu_temperature", "temperature"]);
  elements.systemMetrics.replaceChildren();
  if ([cpu, memory, disk, battery, temperature].every((value) => value === null)) {
    setDeckState(
      elements.systemMetrics,
      "SIN MUESTRAS DISPONIBLES",
      "El monitor está activo, pero todavía no entregó una lectura compatible.",
      "empty",
    );
    return;
  }
  if (cpu !== null) addMetricCard("CPU LOAD", `${Math.round(cpu)}%`, "Carga instantánea", cpu);
  if (memory !== null) {
    const available = metricValue(metrics, ["memory_available_gb", "available_memory_gb"]);
    addMetricCard(
      "MEMORY",
      `${Math.round(memory)}%`,
      available === null ? "Memoria en uso" : `${available.toFixed(1)} GB disponibles`,
      memory,
    );
  }
  if (disk !== null) addMetricCard("STORAGE", `${Math.round(disk)}%`, "Almacenamiento en uso", disk);
  if (battery !== null) {
    const plugged = Boolean(metrics.plugged_in ?? metrics.power_plugged);
    addMetricCard("BATTERY", `${Math.round(battery)}%`, plugged ? "Conectado a corriente" : "En batería", battery);
  }
  if (temperature !== null) {
    addMetricCard("THERMAL", `${Math.round(temperature)}°C`, "Lectura térmica disponible");
  }
}

async function loadSystemMetrics() {
  const result = await optionalJson("/api/system/metrics");
  renderSystemMetrics(result);
}

async function loadSystem() {
  setDeckState(elements.systemMetrics, "LEYENDO TELEMETRÍA", "Tomando una muestra segura del sistema.");
  setDeckState(elements.skillList, "LEYENDO SKILLS", "Validando recetas locales.");
  setDeckState(elements.permissionList, "LEYENDO PERMISOS", "Consultando la política efectiva.");
  setDeckState(elements.systemConnectorList, "LEYENDO ENLACES", "Consultando conectores locales.");
  const [metrics, skills, permissions, connectors] = await Promise.all([
    optionalJson("/api/system/metrics"),
    optionalJson("/api/skills"),
    optionalJson("/api/permissions"),
    optionalJson("/api/connectors"),
  ]);
  renderSystemMetrics(metrics);
  renderSimpleCollection(elements.skillList, skills, {
    keys: ["skills", "recipes", "items"],
    emptyTitle: "SIN SKILLS INSTALADAS",
    emptyDetail: "Las recetas verificadas aparecerán aquí sin ejecutar código arbitrario.",
  });
  renderPermissions(permissions);
  renderSimpleCollection(elements.systemConnectorList, connectors, {
    keys: ["connectors", "integrations", "items"],
    emptyTitle: "SIN ENLACES ACTIVOS",
    emptyDetail: "No hay conectores adicionales en ejecución.",
  });
}

function stopDeckMetricsPolling() {
  window.clearInterval(appState.deckMetricsTimer);
  appState.deckMetricsTimer = null;
}

function startDeckMetricsPolling() {
  stopDeckMetricsPolling();
  appState.deckMetricsTimer = window.setInterval(() => {
    if (elements.controlDeckDialog.open && appState.activeDeckTab === "system") {
      loadSystemMetrics();
    }
  }, 10000);
}

async function loadControlDeckSummary() {
  const result = await optionalJson(deckSessionPath("/api/control-center"));
  if (!result.available) {
    elements.controlDeckSummary.textContent = "LOCAL MODULES // STAGED";
    return;
  }
  const summary = result.data?.summary ?? result.data?.status ?? result.data;
  if (typeof summary === "string") {
    elements.controlDeckSummary.textContent = summary.toUpperCase().slice(0, 80);
    return;
  }
  const counts = result.data?.counts ?? summary?.counts ?? {};
  const capabilityCounts = [
    ["reminders", "AGENDA"],
    ["attachments", "FILES"],
    ["knowledge_sources", "SOURCES"],
    ["skills", "SKILLS"],
  ].filter(([key]) => Number.isFinite(Number(counts[key])));
  if (capabilityCounts.length) {
    elements.controlDeckSummary.textContent = capabilityCounts
      .map(([key, label]) => `${Number(counts[key])} ${label}`)
      .join(" // ")
      .slice(0, 80);
    return;
  }
  const ready = Number(counts.ready ?? counts.available ?? summary?.ready);
  const total = Number(counts.total ?? summary?.total);
  elements.controlDeckSummary.textContent =
    Number.isFinite(ready) && Number.isFinite(total)
      ? `${ready}/${total} MODULES // READY`
      : "PRIVATE MODULES // READY";
}

async function loadDeckTab(name) {
  if (name === "activity") await loadTraces();
  else if (name === "agenda") await loadAgenda();
  else if (name === "files") await loadFiles();
  else if (name === "system") await loadSystem();
}

function activateDeckTab(name, { load = true } = {}) {
  const requested = elements.deckTabs.some((tab) => tab.dataset.deckTab === name)
    ? name
    : "activity";
  appState.activeDeckTab = requested;
  for (const tab of elements.deckTabs) {
    const active = tab.dataset.deckTab === requested;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  for (const panel of elements.deckPanels) {
    panel.hidden = panel.dataset.deckPanel !== requested;
  }
  if (requested === "system") startDeckMetricsPolling();
  else stopDeckMetricsPolling();
  if (load) loadDeckTab(requested);
}

function openControlDeck(name = appState.activeDeckTab) {
  if (!elements.controlDeckDialog.open) elements.controlDeckDialog.showModal();
  activateDeckTab(name);
  loadControlDeckSummary();
  if (name === "agenda") setDefaultReminderDue();
}

function closeControlDeck() {
  stopCamera();
  stopDeckMetricsPolling();
  if (elements.controlDeckDialog.open) elements.controlDeckDialog.close();
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

function isLoopbackLocation() {
  const host = location.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function resetRemoteGatePresentation() {
  elements.remoteGateEyebrow.textContent = "JARVIS // TWO-FACTOR DEVICE LINK";
  elements.remoteGateTitle.textContent = "Verifica este dispositivo";
  elements.remoteIdentityLabel.textContent = "Conexión privada detectada.";
  elements.remoteOfflinePanel.hidden = true;
  elements.remoteSecurityNoteText.textContent =
    "Tailscale autentica tu red y la passkey confirma este dispositivo. Jarvis nunca recibe tu huella, rostro o PIN.";
}

function scheduleBootstrapRetry() {
  window.clearTimeout(appState.bootstrapRetryTimer);
  appState.bootstrapRetryTimer = window.setTimeout(() => {
    if (!document.hidden && !appState.initialized) void bootstrapApplication();
    else if (!appState.initialized) scheduleBootstrapRetry();
  }, 4000);
}

function showCoreUnavailable() {
  const local = isLoopbackLocation();
  cancelActiveClientWork();
  appState.remoteAuthenticated = false;
  elements.remoteGateEyebrow.textContent = local
    ? "JARVIS // LOCAL CORE OFFLINE"
    : "JARVIS // PRIVATE LINK OFFLINE";
  elements.remoteGateTitle.textContent = local
    ? "Jarvis no está en ejecución"
    : "No puedo alcanzar tu computadora";
  elements.remoteIdentityLabel.textContent = local
    ? "Chrome conservó la interfaz en caché, pero no hay un núcleo escuchando en este puerto."
    : "La interfaz quedó disponible sin conexión, pero el enlace privado no responde.";
  elements.remoteOfflineDescription.textContent = local
    ? "Inicia Jarvis con start.cmd. Esta pantalla volverá a conectarse automáticamente."
    : "Verifica que Jarvis y Tailscale estén activos en la PC. Reintentaremos automáticamente.";
  elements.remoteAuthenticationPanel.hidden = true;
  elements.remotePairingForm.hidden = true;
  elements.remoteOfflinePanel.hidden = false;
  elements.remoteSecurityNoteText.textContent =
    "La interfaz sin conexión no puede escuchar, responder ni ejecutar acciones en tu computadora.";
  elements.emergencyStopButton.hidden = true;
  elements.remoteGate.hidden = false;
  setRemoteGateError();
  setVisualState("error", local ? "Núcleo local desconectado" : "Enlace privado desconectado");
  scheduleBootstrapRetry();
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
  if (appState.bootstrapPending) return;
  appState.bootstrapPending = true;
  window.clearTimeout(appState.bootstrapRetryTimer);
  try {
    const response = await fetch("/api/remote/status", { cache: "no-store" });
    if (!response.ok) throw new Error(await readError(response));
    const status = await response.json();
    resetRemoteGatePresentation();
    appState.remoteStatus = status;
    appState.remote = Boolean(status.remote);
    appState.remoteEnabled = Boolean(status.enabled);
    appState.remoteAuthenticated = Boolean(status.authenticated);
    if (!appState.remote) {
      elements.remoteGate.hidden = true;
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
  } catch {
    showCoreUnavailable();
  } finally {
    appState.bootstrapPending = false;
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
    if (elements.interfaceVersion) {
      elements.interfaceVersion.textContent = `JARVIS ${health.version} // AGENT CORE`;
    }
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
      elements.rememberActionButton.hidden = true;
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
      elements.rememberActionButton.hidden = action.details?.rememberable !== true;
      elements.rejectActionButton.hidden = false;
    }
    elements.actionConfirmation.hidden = false;
    if (
      appState.remote &&
      document.hidden &&
      "Notification" in window &&
      Notification.permission === "granted"
    ) {
      try {
        new Notification("Jarvis necesita confirmación", {
          body: action.description || "Hay una acción pendiente.",
          icon: "/static/icon.svg?v=agent-v8",
          tag: "jarvis-action-confirmation",
        });
      } catch (error) {
        console.debug("Action notification could not be displayed", error);
      }
    }
    return;
  }
  appState.pendingAction = null;
  elements.dialogChoiceButtons.replaceChildren();
  elements.dialogChoiceButtons.hidden = true;
  elements.approveActionButton.hidden = false;
  elements.rememberActionButton.hidden = true;
  elements.rejectActionButton.hidden = false;
  elements.actionConfirmation.hidden = true;
}

async function decideAction(approve, choice = null, remember = false) {
  const pending = appState.pendingAction;
  if (!pending) return;
  stopSpeaking();
  appState.busy = true;
  elements.approveActionButton.disabled = true;
  elements.rememberActionButton.disabled = true;
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
        remember,
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (payload.action) handleAction(payload.action);
    addMessage("jarvis", payload.response, "JARVIS // ACTION ENGINE", {
      traceId: payload.trace_id,
    });
    await speak(payload.response);
  } catch (error) {
    if (error.name === "AbortError") return;
    appState.busy = false;
    setVisualState("error", "No pude procesar la confirmación");
    showToast(error.message, 6000);
  } finally {
    elements.approveActionButton.disabled = false;
    elements.rememberActionButton.disabled = false;
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
  const readyAttachments = appState.attachments.filter(
    (attachment) => attachment.status === "ready" && attachmentId(attachment),
  );
  const cleanMessage =
    message.trim() || (readyAttachments.length ? "Analiza los archivos adjuntos." : "");
  if (!cleanMessage || appState.busy) return;
  if (appState.uploadingAttachments > 0) {
    showToast("Espera a que terminen de cargarse los adjuntos.", 5000);
    return;
  }
  appState.busy = true;
  addMessage(
    "user",
    cleanMessage,
    readyAttachments.length
      ? `TÚ // ${readyAttachments.length} ADJUNTO${readyAttachments.length === 1 ? "" : "S"}`
      : undefined,
  );
  setVisualState("thinking", "Consultando el núcleo local");
  const generation = appState.operationGeneration;
  try {
    const response = await cancellableFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: cleanMessage,
        session_id: appState.sessionId,
        attachment_ids: readyAttachments.map(attachmentId),
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (generation !== appState.operationGeneration) return;
    if (payload.action) handleAction(payload.action);
    addMessage("jarvis", payload.response, `JARVIS // ${payload.provider.toUpperCase()}`, {
      traceId: payload.trace_id,
    });
    clearAttachmentSelection();
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
      addMessage(
        "jarvis",
        payload.response,
        `JARVIS // ${(payload.provider || "LOCAL").toUpperCase()}`,
        { traceId: payload.trace_id },
      );
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

elements.controlDeckButton.addEventListener("click", () => openControlDeck());
elements.controlDeckCompactButton.addEventListener("click", () => openControlDeck());
elements.closeControlDeckButton.addEventListener("click", closeControlDeck);
elements.controlDeckDialog.addEventListener("close", () => {
  stopCamera();
  stopDeckMetricsPolling();
});
elements.controlDeckDialog.addEventListener("click", (event) => {
  if (event.target === elements.controlDeckDialog) closeControlDeck();
});

for (const tab of elements.deckTabs) {
  tab.addEventListener("click", () => activateDeckTab(tab.dataset.deckTab));
  tab.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const current = elements.deckTabs.indexOf(tab);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = elements.deckTabs[(current + direction + elements.deckTabs.length) % elements.deckTabs.length];
    activateDeckTab(next.dataset.deckTab);
    next.focus();
  });
}

for (const button of elements.deckRefreshButtons) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await loadDeckTab(button.dataset.deckRefresh);
      await loadControlDeckSummary();
    } finally {
      button.disabled = false;
    }
  });
}

elements.reminderForm.addEventListener("submit", createReminder);
elements.attachmentButton.addEventListener("click", () => elements.attachmentInput.click());
elements.deckAttachButton.addEventListener("click", () => elements.attachmentInput.click());
elements.attachmentInput.addEventListener("change", () => uploadFiles(elements.attachmentInput.files));

async function openCameraFromComposer() {
  openControlDeck("files");
  await startCamera();
}

elements.cameraButton.addEventListener("click", openCameraFromComposer);
elements.deckCameraButton.addEventListener("click", startCamera);
elements.captureCameraButton.addEventListener("click", captureCamera);
elements.stopCameraButton.addEventListener("click", stopCamera);

document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopCamera();
});
window.addEventListener("pagehide", stopCamera);

elements.resetButton.addEventListener("click", async () => {
  cancelActiveClientWork();
  stopSpeaking();
  stopCamera();
  clearAttachmentSelection();
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
elements.rememberActionButton.addEventListener("click", () => decideAction(true, null, true));
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
elements.retryCoreButton.addEventListener("click", () => void bootstrapApplication());
window.addEventListener("online", () => {
  if (!appState.initialized) void bootstrapApplication();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !appState.initialized) void bootstrapApplication();
});

elements.emergencyStopButton.addEventListener("click", async () => {
  cancelActiveClientWork();
  stopSpeaking();
  stopCamera();
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
  pollNotifications();
  appState.notificationTimer = window.setInterval(pollNotifications, 10000);
  connectStateSocket();
  drawWaveform();
}

updateClock();
window.setInterval(updateClock, 1000);
startNeuralField();
bootstrapApplication();
