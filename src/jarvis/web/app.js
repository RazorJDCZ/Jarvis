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

const appState = {
  sessionId: crypto.randomUUID ? crypto.randomUUID() : `session-${Date.now()}`,
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
  try {
    const payload = await response.json();
    return payload.detail || `Error HTTP ${response.status}`;
  } catch {
    return `Error HTTP ${response.status}`;
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
    const response = await fetch("/api/actions/decision", {
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
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  socket.addEventListener("open", () => {
    window.clearInterval(appState.socketPing);
    appState.socketPing = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20000);
  });
  socket.addEventListener("message", (event) => {
    if (appState.speaking) return;
    try {
      const snapshot = JSON.parse(event.data);
      setVisualState(snapshot.state, snapshot.detail);
    } catch (error) {
      console.debug("State event ignored", error);
    }
  });
  socket.addEventListener("close", () => {
    window.clearInterval(appState.socketPing);
    window.setTimeout(connectStateSocket, 2500);
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
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
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
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: cleanMessage, session_id: appState.sessionId }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    if (payload.action) handleAction(payload.action);
    addMessage("jarvis", payload.response, `JARVIS // ${payload.provider.toUpperCase()}`);
    await speak(payload.response);
  } catch (error) {
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
  try {
    const response = await fetch("/api/voice/utterance", { method: "POST", body: form });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
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
  gradient.addColorStop(0, "rgba(97, 219, 255, 0)");
  gradient.addColorStop(0.3, "rgba(97, 219, 255, 0.65)");
  gradient.addColorStop(0.5, "rgba(196, 245, 255, 0.95)");
  gradient.addColorStop(0.7, "rgba(97, 219, 255, 0.65)");
  gradient.addColorStop(1, "rgba(97, 219, 255, 0)");
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
  let particles = [];

  const seedParticles = () => {
    const count = Math.max(24, Math.min(62, Math.floor((width * height) / 28000)));
    particles = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.12,
      vy: (Math.random() - 0.5) * 0.12,
      radius: 0.55 + Math.random() * 1.05,
      phase: Math.random() * Math.PI * 2,
    }));
  };

  const resize = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    seedParticles();
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
    const connectionDistance = active ? 142 : 112;
    for (let first = 0; first < particles.length; first += 1) {
      const particle = particles[first];
      if (!reducedMotion) {
        particle.x += particle.vx * (active ? 1.8 : 1);
        particle.y += particle.vy * (active ? 1.8 : 1);
        if (particle.x < -10) particle.x = width + 10;
        if (particle.x > width + 10) particle.x = -10;
        if (particle.y < -10) particle.y = height + 10;
        if (particle.y > height + 10) particle.y = -10;
      }
      for (let second = first + 1; second < particles.length; second += 1) {
        const neighbor = particles[second];
        const distance = Math.hypot(particle.x - neighbor.x, particle.y - neighbor.y);
        if (distance >= connectionDistance) continue;
        const alpha = (1 - distance / connectionDistance) * (active ? 0.15 : 0.075);
        context.beginPath();
        context.moveTo(particle.x, particle.y);
        context.lineTo(neighbor.x, neighbor.y);
        context.strokeStyle = `rgba(88, 209, 255, ${alpha})`;
        context.lineWidth = 0.55;
        context.stroke();
      }
      const pulse = 0.55 + Math.sin(time / 900 + particle.phase) * 0.25;
      context.beginPath();
      context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
      context.fillStyle = `rgba(116, 229, 255, ${active ? pulse : pulse * 0.55})`;
      context.fill();
    }
    if (!reducedMotion) window.requestAnimationFrame(draw);
  };

  resize();
  window.addEventListener("resize", resize, { passive: true });
  draw();
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
}

updateClock();
window.setInterval(updateClock, 1000);
refreshHealth();
window.setInterval(refreshHealth, 30000);
connectStateSocket();
drawWaveform();
startNeuralField();
