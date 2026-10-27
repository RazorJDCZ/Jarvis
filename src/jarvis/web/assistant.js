"use strict";

const TEXT_STREAM_TIMEOUT_MS = 300000;
const VOICE_STREAM_TIMEOUT_MS = 180000;

function resampleVoice(samples, sampleRate) {
  if (sampleRate === 16000) return samples;
  const ratio = sampleRate / 16000;
  const result = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < result.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    result[i] = sum / Math.max(1, end - start);
  }
  return result;
}

async function receiveAssistantStream(url, options, timeoutMs = TEXT_STREAM_TIMEOUT_MS) {
  const controller = new AbortController();
  appState.activeControllers.add(controller);
  const generation = appState.operationGeneration;
  const started = performance.now();
  const timing = {};
  let article = null;
  let text = "";
  let pendingSpeech = "";
  let speechQueue = Promise.resolve();
  let finalPayload = null;
  let timedOut = false;
  const timeoutTimer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  appState.streaming = true;
  const cancelled = () => controller.signal.aborted || generation !== appState.operationGeneration;
  const enqueue = (sentence) => {
    if (!sentence.trim() || appState.muted) return;
    // Synthesize upcoming speech while the previous fragment is playing. This removes the
    // artificial multi-second gap that otherwise appears after every streamed sentence.
    const preparedAudio = appState.ttsAvailable
      ? prepareSpeech(sentence).catch((error) => ({ error }))
      : Promise.resolve(null);
    speechQueue = speechQueue.then(async () => {
      if (cancelled()) return;
      const prepared = await preparedAudio;
      if (cancelled()) return;
      await speak(sentence, prepared);
      const speechGeneration = appState.speechGeneration;
      let recorded = false;
      while (appState.speaking && !cancelled() && speechGeneration === appState.speechGeneration) {
        if (!recorded && ((appState.audioPlayer && !appState.audioPlayer.paused) || window.speechSynthesis?.speaking)) {
          timing.first_audio_ms ??= Math.round(performance.now() - started);
          recorded = true;
        }
        await new Promise((resolve) => setTimeout(resolve, 40));
      }
    });
  };
  const append = (chunk) => {
    if (!article) {
      addMessage("jarvis", "", "JARVIS");
      article = elements.transcript.lastElementChild;
      timing.first_text_ms = Math.round(performance.now() - started);
    }
    text += chunk;
    article.querySelector("p").textContent = text;
    pendingSpeech += chunk;
    // Speak complete sentences only; never manufacture a result or action confirmation.
    let match;
    while ((match = pendingSpeech.match(/^([\s\S]*?[.!?](?:\s|$)|[\s\S]{80,240}\n)/))) {
      enqueue(match[0]);
      pendingSpeech = pendingSpeech.slice(match[0].length);
    }
  };
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(await readError(response));
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!cancelled()) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.event === "token") append(event.text);
        if (event.event === "error") throw new Error(event.detail);
        if (event.event === "done") {
          finalPayload = event;
          timing.response_ms = Math.round(performance.now() - started);
          if (event.transcript && event.accepted) {
            addMessage("user", event.transcript);
            if (article) elements.transcript.insertBefore(elements.transcript.lastElementChild, article);
          }
          if (!text && event.response) append(event.response);
          if (article && event.response) article.querySelector("p").textContent = event.response;
          if (article && event.trace_id) attachTraceDetails(article, event.trace_id);
          if (event.action) handleAction(event.action);
          enqueue(pendingSpeech);
          pendingSpeech = "";
          appState.lastTiming = { ...timing, server: event.timings_ms };
        }
      }
      if (done) break;
    }
    if (cancelled()) throw new DOMException("Cancelado", "AbortError");
    if (!finalPayload) throw new Error("La conexión terminó antes de completar la respuesta.");
    // La petición ya terminó. La reproducción tiene su propio watchdog y no debe convertir
    // una respuesta móvil correcta en un falso timeout mientras Jarvis todavía habla.
    window.clearTimeout(timeoutTimer);
    await speechQueue;
    if (cancelled()) throw new DOMException("Cancelado", "AbortError");
    appState.lastTiming = { ...timing, server: finalPayload.timings_ms };
    return finalPayload;
  } catch (error) {
    controller.abort();
    if (generation === appState.operationGeneration) stopSpeaking();
    if (article) article.dataset.incomplete = "true";
    if (timedOut) {
      throw new Error("Jarvis tardó demasiado en responder. Cancelé la solicitud para que puedas volver a hablar.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutTimer);
    appState.activeControllers.delete(controller);
    if (generation === appState.operationGeneration) {
      appState.streaming = false;
      appState.busy = false;
      if (!appState.speaking) finishSpeaking();
    }
  }
}

async function assistantJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

function assistantButton(label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await action(); } catch (error) { showToast(error.message, 7000); }
    finally { button.disabled = false; }
  });
  return button;
}

function appendPersonalSearch(panel) {
  const form = document.createElement("form");
  form.className = "assistant-search";
  const label = document.createElement("label");
  label.textContent = "Buscar en todo lo personal";
  const input = document.createElement("input");
  input.type = "search";
  input.maxLength = 300;
  input.placeholder = "Correo, agenda, Appa, memoria, biblioteca y archivos";
  const output = document.createElement("div");
  output.className = "assistant-search-results";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Buscar sin modificar nada";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!input.value.trim()) return;
    submit.disabled = true;
    output.replaceChildren();
    try {
      const payload = await assistantJson(deckSessionPath("/api/assistant/search", {
        query: input.value.trim(),
      }));
      if (!payload.items.length) {
        output.textContent = "No encontre coincidencias en las fuentes disponibles.";
        return;
      }
      for (const item of payload.items.slice(0, 20)) {
        const article = document.createElement("article");
        const title = document.createElement("strong");
        title.textContent = `${item.source.toUpperCase()} // ${item.title}`;
        const detail = document.createElement("p");
        detail.textContent = item.detail || "Sin detalles adicionales";
        article.append(title, detail);
        output.append(article);
      }
    } catch (error) {
      output.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  label.append(input);
  form.append(label, submit, output);
  panel.append(form);
}

async function loadAssistantPanel() {
  const panel = document.querySelector("#assistantContent");
  panel.replaceChildren();
  const preferences = await assistantJson("/api/assistant/preferences");
  const title = document.createElement("h3");
  title.textContent = "Tu asistente cotidiano";
  panel.append(title);
  appendPersonalSearch(panel);
  panel.append(assistantButton("Correos Pendientes · conectar cuentas", async () => {
    window.location.href = "/mail";
  }));
  panel.append(assistantButton("Preparar mi día", async () => {
    const result = await assistantJson(deckSessionPath("/api/assistant/briefing"));
    addMessage("jarvis", result.summary, `JARVIS // ${result.source}`);
    closeControlDeck();
    await speak(result.summary);
  }));
  panel.append(assistantButton("Consultar clima actual", async () => {
    const result = await assistantJson("/api/assistant/weather");
    addMessage("jarvis", result.summary, `JARVIS // ${result.source}`);
    closeControlDeck();
    await speak(result.summary);
  }));
  const skills = await assistantJson("/api/skills").catch(() => ({ skills: [] }));
  for (const skill of skills.skills) {
    panel.append(assistantButton(skill.name, async () => {
      closeControlDeck();
      await sendText(`Ejecuta la receta ${skill.name}`);
    }));
  }
  const form = document.createElement("form");
  form.className = "assistant-settings";
  const fields = {};
  const select = (label, name, values, current) => {
    const wrapper = document.createElement("label");
    wrapper.textContent = label;
    const input = document.createElement("select");
    input.name = name;
    for (const [value, text] of values) {
      const option = document.createElement("option");
      option.value = value; option.textContent = text; input.append(option);
    }
    input.value = current;
    wrapper.append(input); form.append(wrapper); fields[name] = input;
    return input;
  };
  select("Rendimiento de la PC", "performance", [["adaptive", "Adaptativo"], ["economy", "Ahorrar memoria"], ["quality", "Priorizar calidad cuando haya recursos"]], preferences.performance);
  select("Voz", "voice", [["am_onyx", "Onyx · masculina grave"], ["em_santa", "Santa · masculina cálida"], ["em_alex", "Alex · masculina clara"], ["ef_dora", "Dora · femenina"]], preferences.voice);
  select("Velocidad de voz", "voice_speed", [["0.90", "Pausada"], ["1", "Normal"], ["1.10", "Natural"], ["1.20", "Ágil"]], String(preferences.voice_speed));
  select("Resumen diario y avisos anticipados", "proactive", [["false", "Desactivados"], ["true", "Activados"]], String(preferences.proactive));
  select("Nivel mínimo de avisos", "notification_level", [["all", "Todos"], ["important", "Solo importantes y urgentes"], ["urgent", "Solo urgentes"]], preferences.notification_level);
  const hours = Array.from({ length: 24 }, (_, hour) => [String(hour), `${String(hour).padStart(2, "0")}:00`]);
  for (const [key, label] of [["briefing_hour", "Resumen a partir de"], ["quiet_start", "No molestar desde"], ["quiet_end", "No molestar hasta"]]) {
    select(label, key, hours, String(preferences[key]));
  }
  const wake = select("Activación en este dispositivo", "wake", [["compatible", "Jarvis · compatible"], ["light", "Hey Jarvis · pronunciación inglesa, bajo consumo"]], localStorage.getItem("jarvis-wake-mode") || "compatible");
  wake.addEventListener("change", () => localStorage.setItem("jarvis-wake-mode", wake.value));
  const compact = select("Vista en este dispositivo", "compact", [["false", "Interfaz completa"], ["true", "Conversación compacta"]], localStorage.getItem("jarvis-compact") || "false");
  compact.addEventListener("change", () => {
    localStorage.setItem("jarvis-compact", compact.value);
    document.body.classList.toggle("compact-mode", compact.value === "true");
  });
  const devices = await navigator.mediaDevices?.enumerateDevices().catch(() => []) || [];
  const mic = select("Micrófono en este dispositivo", "microphone", [["", "Predeterminado"], ...devices.filter((d) => d.kind === "audioinput" && d.deviceId).map((d, i) => [d.deviceId, d.label || `Micrófono ${i + 1}`])], localStorage.getItem("jarvis-microphone") || "");
  mic.addEventListener("change", () => {
    localStorage.setItem("jarvis-microphone", mic.value);
    showToast("Micrófono guardado. Recarga la página para aplicarlo.", 5000);
  });
  const submit = assistantButton("Guardar ajustes de la PC", async () => {
    const value = { ...preferences };
    for (const key of Object.keys(preferences)) value[key] = fields[key].value;
    value.proactive = value.proactive === "true";
    for (const key of ["voice_speed", "briefing_hour", "quiet_start", "quiet_end"]) value[key] = Number(value[key]);
    await assistantJson("/api/assistant/preferences", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
    showToast("Ajustes guardados.", 4000);
  });
  submit.disabled = appState.remote;
  if (appState.remote) {
    for (const key of Object.keys(preferences)) fields[key].disabled = true;
    const note = document.createElement("p"); note.textContent = "Los ajustes compartidos y la memoria se editan desde tu PC. La vista, activación y micrófono se guardan en este dispositivo.";
    form.append(note);
  }
  form.append(submit); panel.append(form);
  panel.append(assistantButton("Diagnosticar conexión y respuesta", async () => {
    const started = performance.now();
    const status = await assistantJson(deckSessionPath("/api/performance"));
    const output = document.createElement("p");
    const last = appState.lastTiming;
    output.textContent = `Consulta al servidor: ${Math.round(performance.now() - started)} ms. RAM libre: ${status.available_ram_gb} GB. Activación ligera: ${status.lightweight_wake ? "disponible" : "no instalada"}.` +
      (last ? ` Última petición: primer texto ${last.first_text_ms ?? "—"} ms; primer audio ${last.first_audio_ms ?? "—"} ms; respuesta ${last.response_ms} ms.` : " Envía una petición para medir texto y voz.");
    panel.append(output);
  }));
  panel.append(assistantButton("Permisos y seguridad", async () => {
    const security = await assistantJson("/api/assistant/security");
    const output = document.createElement("p");
    output.textContent = `${security.local.policy} Desde el celular, los cambios piden confirmacion y las acciones de riesgo alto siempre la requieren. La busqueda de archivos es solo lectura. Contexto visual temporal: ${security.screen_context_expires_seconds / 60} minutos. Permisos recordados: ${security.remembered_permissions.length}.`;
    panel.append(output);
  }));
  panel.append(assistantButton("Ver cambios reversibles", async () => {
    closeControlDeck();
    await sendText("muestra los cambios reversibles");
  }));
  panel.append(assistantButton("Deshacer el ultimo cambio", async () => {
    closeControlDeck();
    await sendText("deshaz el ultimo cambio");
  }));
  if (!appState.remote) {
    panel.append(assistantButton("Automatizaciones proactivas", loadAutomationEditor));
    panel.append(assistantButton("Ver y corregir memoria", loadMemoryEditor));
  }
}

async function loadAutomationEditor() {
  const panel = document.querySelector("#assistantMemory");
  panel.replaceChildren();
  const payload = await assistantJson("/api/assistant/automations");
  const heading = document.createElement("h3");
  heading.textContent = "Automatizaciones proactivas";
  const note = document.createElement("p");
  note.textContent = "Estas reglas solo consultan tus datos y envían avisos privados. Activa cada una conscientemente; el horario de no molestar sigue teniendo prioridad.";
  panel.append(heading, note);
  const queue = document.createElement("small");
  queue.textContent = `Cola fiable: ${payload.queue.pending || 0} pendientes, ${payload.queue.failed || 0} fallidos.`;
  panel.append(queue);
  const labels = {
    daily_briefing: "Resumen diario",
    important_mail: "Correos importantes",
    calendar_soon: "Calendario próximo",
    weather_daily: "Clima diario",
    deadline_watch: "Fechas limite detectadas en correo",
  };
  for (const rule of payload.rules) {
    const row = document.createElement("form");
    row.className = "automation-edit-row";
    const name = document.createElement("strong");
    name.textContent = rule.name;
    const kind = document.createElement("small");
    kind.textContent = labels[rule.kind] || rule.kind;
    const enabledLabel = document.createElement("label");
    const enabled = document.createElement("input");
    enabled.type = "checkbox"; enabled.checked = rule.enabled;
    enabledLabel.append(enabled, document.createTextNode(" Activada"));
    const hourLabel = document.createElement("label");
    hourLabel.textContent = "Hora";
    const hour = document.createElement("input");
    hour.type = "number"; hour.min = "0"; hour.max = "23"; hour.value = String(rule.hour);
    hourLabel.append(hour);
    const leadLabel = document.createElement("label");
    leadLabel.textContent = "Anticipación (minutos)";
    const lead = document.createElement("input");
    lead.type = "number"; lead.min = "5"; lead.max = "1440"; lead.value = String(rule.lead_minutes);
    leadLabel.append(lead);
    row.append(name, kind, enabledLabel, hourLabel, leadLabel);
    row.append(assistantButton("Guardar regla", async () => {
      await assistantJson(`/api/assistant/automations/${encodeURIComponent(rule.rule_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: rule.name,
          kind: rule.kind,
          enabled: enabled.checked,
          hour: Number(hour.value),
          lead_minutes: Number(lead.value),
        }),
      });
      showToast("Automatización actualizada.", 4000);
      await loadAutomationEditor();
    }));
    panel.append(row);
  }
}

async function loadMemoryEditor() {
  const panel = document.querySelector("#assistantMemory");
  panel.replaceChildren();
  const payload = await assistantJson("/api/assistant/memory");
  const heading = document.createElement("h3"); heading.textContent = "Recuerdos y perfil"; panel.append(heading);
  const note = document.createElement("p"); note.textContent = "Revisa ambas fuentes si un dato se contradice: el perfil base tiene prioridad en preguntas personales. Los recuerdos muestran su fecha de aprendizaje y última actualización."; panel.append(note);
  const entityHeading = document.createElement("h4");
  entityHeading.textContent = "Mapa personal estructurado";
  panel.append(entityHeading);
  const entityForm = document.createElement("form");
  entityForm.className = "personal-entity-form";
  const type = document.createElement("select");
  for (const value of ["persona", "lugar", "preferencia", "rutina", "objetivo", "organizacion", "proyecto"]) {
    const option = document.createElement("option"); option.value = value; option.textContent = value; type.append(option);
  }
  const entityName = document.createElement("input"); entityName.placeholder = "Nombre"; entityName.maxLength = 160; entityName.required = true;
  const relation = document.createElement("input"); relation.placeholder = "Relación contigo"; relation.maxLength = 160;
  const details = document.createElement("textarea"); details.placeholder = "Detalles útiles, sin contraseñas ni secretos"; details.maxLength = 1000;
  const expires = document.createElement("input"); expires.type = "date"; expires.title = "Caducidad opcional"; expires.setAttribute("aria-label", "Caducidad opcional");
  entityForm.append(type, entityName, relation, details, expires, assistantButton("Añadir al mapa personal", async () => {
    await assistantJson("/api/assistant/memory/entities", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: type.value, name: entityName.value, relation: relation.value, details: details.value, expires_at: expires.value || null }),
    });
    await loadMemoryEditor();
  }));
  panel.append(entityForm);
  for (const entity of payload.entities || []) {
    const row = document.createElement("div"); row.className = "personal-entity-row";
    const label = document.createElement("strong"); label.textContent = `${entity.kind.toUpperCase()} // ${entity.name}`;
    const entityRelation = document.createElement("input"); entityRelation.value = entity.relation; entityRelation.maxLength = 160; entityRelation.placeholder = "Relación";
    const entityDetails = document.createElement("textarea"); entityDetails.value = entity.details; entityDetails.maxLength = 1000;
    const entityExpires = document.createElement("input"); entityExpires.type = "date"; entityExpires.value = entity.expires_at ? entity.expires_at.slice(0, 10) : ""; entityExpires.title = "Caducidad opcional"; entityExpires.setAttribute("aria-label", "Caducidad opcional");
    row.append(label, entityRelation, entityDetails, entityExpires, assistantButton("Guardar entidad", async () => {
      await assistantJson(`/api/assistant/memory/entities/${encodeURIComponent(entity.entity_id)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: entity.kind, name: entity.name, relation: entityRelation.value, details: entityDetails.value, expires_at: entityExpires.value || null, updated_at: entity.updated_at }),
      });
      await loadMemoryEditor();
    }), assistantButton("Eliminar entidad", async () => {
      if (!window.confirm(`¿Eliminar ${entity.name} del mapa personal?`)) return;
      await assistantJson(`/api/assistant/memory/entities/${encodeURIComponent(entity.entity_id)}?updated_at=${encodeURIComponent(entity.updated_at)}`, { method: "DELETE" });
      await loadMemoryEditor();
    }));
    panel.append(row);
  }
  const learnedHeading = document.createElement("h4"); learnedHeading.textContent = "Recuerdos aprendidos"; panel.append(learnedHeading);
  for (const entry of payload.memories) {
    const row = document.createElement("div"); row.className = "memory-edit-row";
    const input = document.createElement("textarea"); input.value = entry.content; input.maxLength = 500; input.setAttribute("aria-label", "Contenido del recuerdo");
    const date = document.createElement("small"); date.textContent = `Aprendido: ${new Date(entry.created_at).toLocaleString()} · Actualizado: ${new Date(entry.updated_at).toLocaleString()}`;
    const update = async (content) => {
      await assistantJson("/api/assistant/memory", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: entry.memory_key, content, updated_at: entry.updated_at }) });
      await loadMemoryEditor();
    };
    row.append(input, date, assistantButton("Guardar corrección", () => update(input.value)), assistantButton("Eliminar recuerdo", async () => {
      if (window.confirm(`¿Eliminar este recuerdo?\n${entry.content}`)) await update(null);
    }));
    panel.append(row);
  }
  for (const [key, label] of [["preferred_name", "Nombre preferido"], ["location", "Ubicación"], ["degree", "Estudios"], ["university", "Universidad"], ["academic_status", "Situación académica"], ["work_context", "Trabajo"], ["assistant_role", "Cómo debe ayudarte Jarvis"], ["future_vision", "Planes de futuro"]]) {
    const row = document.createElement("label"); row.textContent = label;
    const input = document.createElement("textarea"); input.value = payload.profile[key] || ""; input.maxLength = 500;
    row.append(input, assistantButton("Actualizar perfil", async () => {
      await assistantJson("/api/assistant/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [key]: input.value }) });
      showToast("Perfil actualizado; copia anterior conservada en la PC.", 4000);
    })); panel.append(row);
  }
  panel.append(assistantButton("Exportar memoria y perfil", async () => {
    const data = await assistantJson("/api/assistant/memory/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "jarvis-memoria.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
}

document.body.classList.toggle("compact-mode", localStorage.getItem("jarvis-compact") === "true");
