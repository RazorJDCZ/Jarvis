"use strict";
const $ = (selector) => document.querySelector(selector);
const message = $("#message");
const node = (tag, text, parent) => { const e = document.createElement(tag); e.textContent = text; parent.append(e); return e; };
async function api(path, method = "GET", data) {
  const response = await fetch(`/api/organizer/${path}`, { method, headers: { "Content-Type": "application/json" }, ...(data === undefined ? {} : { body: JSON.stringify(data) }) });
  const result = await response.json();
  if (!response.ok) { const error = new Error(typeof result.detail === "string" ? result.detail : "Revisa los datos ingresados."); error.status = response.status; throw error; }
  return result;
}
async function run(button, action) { button.disabled = true; try { await action(); } catch (error) { message.textContent = error.message; } finally { button.disabled = false; } }
const zone = "America/Guayaquil";
const dateText = (value) => value?.length === 10 ? value : new Date(value).toLocaleString("es-EC", { timeZone: zone });
function emptyState(parent, title, description, symbol = "◇") {
  const box = node("div", "", parent); box.className = "day-empty-state";
  const icon = node("span", "", box); icon.className = "day-empty-symbol"; icon.setAttribute("aria-hidden", "true"); node("span", symbol, icon);
  node("strong", title, box); node("p", description, box);
}
function row(parent, title, detail, label = "") {
  const item = node("article", "", parent); item.className = "day-row";
  const copy = node("div", "", item); copy.className = "day-row-copy";
  if (label) node("span", label, copy).className = "day-source";
  node("strong", title, copy); if (detail) node("small", detail, copy);
  return item;
}
function proposalsEmpty() {
  if (!$("#proposals").children.length) emptyState($("#proposals"), "Nada por revisar, por ahora", "Aquí aparecerán las fechas detectadas en tus correos y las sesiones de estudio que prepares.");
}
$("#dayDate").textContent = new Intl.DateTimeFormat("es-EC", { weekday: "long", day: "numeric", month: "long", timeZone: zone }).format(new Date());
function selectSection() {
  for (const link of document.querySelectorAll(".day-navigation a")) {
    const selected = link.hash === (location.hash || "#overview");
    link.classList.toggle("selected", selected);
    if (selected) link.setAttribute("aria-current", "location"); else link.removeAttribute("aria-current");
  }
}
window.addEventListener("hashchange", selectSection); selectSection();
function input(form, label, name, value, type = "text") { const l = node("label", label, form); const e = node("input", "", l); e.name = name; e.type = type; e.value = value; e.required = true; return e; }
function localTime(value) { if (!value) return ""; return new Date(new Date(value).getTime() - 5 * 3600000).toISOString().slice(0, 16); }
let draftsLoaded = false;
async function refresh() {
  let data;
  try { data = await api("today"); }
  catch (error) { $("#syncStatus").textContent = "Sin conexión con Jarvis"; $("#syncStatus").dataset.state = "offline"; throw error; }
  $("#syncStatus").textContent = "Actualizado " + new Date().toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit", timeZone: zone });
  $("#syncStatus").dataset.state = "ready";
  for (const [id, items] of [["eventCount", data.events], ["taskCount", data.tasks], ["mailCount", data.mail], ["captureCount", data.captures]]) $("#" + id).textContent = items.length;
  for (const name of ["priorities", "events", "pending", "captures"]) $("#" + name).replaceChildren();
  for (const [index, p] of data.priorities.entries()) {
    const item = row($("#priorities"), p.title, p.reason);
    const number = node("span", String(index + 1).padStart(2, "0"), item); number.className = "day-row-number"; item.prepend(number);
  }
  if (!data.priorities.length) emptyState($("#priorities"), "Tu día empieza aquí", "Guarda una idea o conecta tu agenda para reunir aquí tus próximos pasos.", "◎");
  for (const e of data.events) {
    const allDay = e.start_at?.length === 10;
    const date = new Date(allDay ? e.start_at + "T12:00:00-05:00" : e.start_at);
    const validDate = !Number.isNaN(date.getTime());
    const detail = allDay ? "Todo el día" : validDate ? date.toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit", timeZone: zone }) + " · Quito" : "Fecha por confirmar";
    const item = row($("#events"), e.title, detail, /google/i.test(e.source) ? "GOOGLE CALENDAR" : "APPA");
    const stamp = node("div", validDate ? date.toLocaleDateString("es-EC", { day: "2-digit", month: "short", timeZone: zone }) : "—", item); stamp.className = "day-event-date"; item.prepend(stamp);
    if (validDate) node("small", date.toLocaleDateString("es-EC", { weekday: "long", timeZone: zone }), stamp);
  }
  if (!data.events.length) emptyState($("#events"), "Tu agenda, en un solo lugar", "Los eventos de Appa aparecerán aquí. También puedes conectar Google Calendar.", "◷");
  if (data.calendar.error) node("p", data.calendar.error, $("#events")).className = "day-help";
  for (const t of data.tasks) row($("#pending"), t.title, t.due_date ? "Entrega: " + t.due_date : "Sin fecha límite", "TAREA / APPA");
  const mailStates = { reply: "Por responder", waiting: "Esperando respuesta", review: "Por revisar", resolved: "Resuelto" };
  for (const m of data.mail.slice(0, 10)) row($("#pending"), m.subject, mailStates[m.state] || "Pendiente de revisar", "CORREO");
  if (!data.tasks.length && !data.mail.length) emptyState($("#pending"), "Sin pendientes en esta vista", "Aquí encontrarás tus tareas de Appa y los correos que necesiten atención.", "✓");
  for (const c of data.captures) { const row = node("article", c.text + (c.due_at ? " · " + dateText(c.due_at) : ""), $("#captures")); const b = node("button", "Hecho", row); b.onclick = () => run(b, async () => { await api(`captures/${encodeURIComponent(c.id)}`, "DELETE"); await refresh(); }); }
  // Do not destroy edits while the user completes an event proposal.
  if (!draftsLoaded) {
    $("#proposals").replaceChildren();
    for (const p of data.proposals) {
      const form = node("form", "", $("#proposals")); node("h3", p.title, form); node("p", p.quote ? `Correo: “${p.quote}”` : "Sesión de estudio", form); node("p", p.warning, form);
      input(form, "Título", "title", p.title); const allDay = input(form, "Todo el día", "all_day", "", "checkbox"); allDay.required = false; allDay.checked = p.all_day;
      const start = input(form, "Inicio", "start_at", p.all_day ? p.start_at : localTime(p.start_at), p.all_day ? "date" : "datetime-local");
      const end = input(form, "Fin (en todo el día: día siguiente)", "end_at", p.all_day ? p.end_at : localTime(p.end_at), p.all_day ? "date" : "datetime-local");
      allDay.onchange = () => { for (const e of [start, end]) { e.type = allDay.checked ? "date" : "datetime-local"; e.value = ""; } };
      const reminders = input(form, "Avisos: minutos antes, separados por coma", "reminders", p.reminders.join(",")); reminders.required = false;
      const save = node("button", p.published ? "Actualizar evento en Calendar" : "Guardar en Calendar", form);
      save.className = "day-primary";
      form.onsubmit = (event) => { event.preventDefault(); void run(save, async () => { await api(`proposals/${encodeURIComponent(p.id)}/publish`, "POST", { title: form.elements.title.value, start_at: allDay.checked ? start.value : start.value + ":00-05:00", end_at: allDay.checked ? end.value : end.value + ":00-05:00", all_day: allDay.checked, reminders: reminders.value ? reminders.value.split(",").map(Number) : [], revision: p.revision }); form.remove(); proposalsEmpty(); message.textContent = "Evento guardado en Google Calendar."; }); };
      const discard = node("button", "Descartar propuesta", form); discard.type = "button"; discard.onclick = () => run(discard, async () => { await api(`proposals/${encodeURIComponent(p.id)}`, "DELETE"); form.remove(); proposalsEmpty(); });
    }
    proposalsEmpty();
    draftsLoaded = true;
    const settings = data.followup_settings;
    for (const k of ["after_days", "repeat_hours"]) $("#followups").elements[k].value = settings[k];
    $("#followups").elements.enabled.checked = settings.enabled;
  }
  $("#calendarStatus").textContent = data.calendar.accounts.map(a => a.email).join(", ") || "Calendar todavía no está conectado.";
  if (data.calendar.error) $("#calendarStatus").textContent += " · " + data.calendar.error;
  if (data.appa.error) node("p", data.appa.error, $("#pending"));
  $("#backupStatus").textContent = data.recovery.backups?.length ? `Último respaldo: ${new Date(data.recovery.backups[0].created * 1000).toLocaleString()}` : "El primer respaldo se prepara automáticamente.";
}
let captureKey = crypto.randomUUID();
const queueKey = "jarvis-quick-captures-v1";
function queue() { try { return JSON.parse(localStorage.getItem(queueKey) || "[]"); } catch { return []; } }
let flushing = false;
function renderQueue() {
  let container = $("#offlineCaptures");
  if (!container) { container = node("div", "", $("#capture").parentElement); container.id = "offlineCaptures"; }
  container.replaceChildren();
  for (const entry of queue()) {
    const row = node("article", `${entry.text} · ${entry.error || "Pendiente de sincronizar"}`, container);
    const edit = node("button", "Editar captura pendiente", row);
    edit.onclick = () => { $("#capture").elements.text.value = entry.text; $("#capture").elements.due.value = ""; captureKey = crypto.randomUUID(); localStorage.setItem(queueKey, JSON.stringify(queue().filter(e => e.request_id !== entry.request_id))); renderQueue(); };
  }
}
async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    for (const entry of queue()) {
      if (entry.error) continue;
      try { await api("captures", "POST", entry); localStorage.setItem(queueKey, JSON.stringify(queue().filter(e => e.request_id !== entry.request_id))); }
      catch (error) { if (error.status === 400 || error.status === 422) { localStorage.setItem(queueKey, JSON.stringify(queue().map(e => e.request_id === entry.request_id ? { ...e, error: error.message } : e))); } else break; }
    }
  } finally { flushing = false; renderQueue(); }
}
$("#capture").onsubmit = (event) => { event.preventDefault(); const form = event.currentTarget; void run(form.querySelector("button"), async () => { const entry = { text: form.elements.text.value, request_id: captureKey, due_at: form.elements.due.value ? new Date(form.elements.due.value).toISOString() : null }; const pending = queue(); if (pending.length >= 100) throw new Error("Hay 100 capturas sin sincronizar; conecta Jarvis primero."); if (!pending.some(e => e.request_id === captureKey)) pending.push(entry); localStorage.setItem(queueKey, JSON.stringify(pending)); await flush(); const offline = queue().some(e => e.request_id === captureKey); message.textContent = offline ? "Guardado en este dispositivo; pendiente de sincronizar con Jarvis." : "Captura guardada."; form.reset(); captureKey = crypto.randomUUID(); if (!offline) await refresh(); }); };
$("#refresh").onclick = (e) => run(e.currentTarget, async () => { await api("refresh", "POST"); draftsLoaded = false; await flush(); await refresh(); });
$("#study").onsubmit = (e) => { e.preventDefault(); const f = e.currentTarget; void run(f.querySelector("button"), async () => { const payload = Object.fromEntries(new FormData(f)); for (const k of ["sessions", "minutes", "start_hour", "end_hour"]) payload[k] = Number(payload[k]); const result = await api("study", "POST", payload); message.textContent = `${result.slots.length} sesiones propuestas. Faltan ${result.missing}. ${result.warning}`; draftsLoaded = false; await refresh(); }); };
$("#followups").onsubmit = (e) => { e.preventDefault(); const f = e.currentTarget; void run(f.querySelector("button"), async () => { await api("followups", "PUT", { enabled: f.elements.enabled.checked, after_days: Number(f.elements.after_days.value), repeat_hours: Number(f.elements.repeat_hours.value) }); message.textContent = "Seguimiento guardado."; }); };
$("#connect").onclick = (e) => run(e.target, async () => { const tab = window.open("about:blank", "_blank"); try { const data = await api("calendar/connect", "POST"); if (tab) tab.location = data.url; else location.href = data.url; } catch (error) { tab?.close(); throw error; } });
$("#disconnect").onclick = (e) => run(e.target, async () => { if (confirm("¿Desconectar Calendar? Los eventos guardados en Google se conservarán.")) { await api("calendar", "DELETE"); await refresh(); } });
$("#backup").onclick = (e) => run(e.target, async () => { await api("backups", "POST"); message.textContent = "Respaldo cifrado creado."; await refresh(); });
async function worker() { if (!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("Este navegador no admite avisos. En iPhone abre Jarvis desde la pantalla de inicio."); await navigator.serviceWorker.register("/service-worker.js"); return navigator.serviceWorker.ready; }
$("#push").onclick = (e) => run(e.target, async () => { const registration = await worker(); const data = await api("push"); const key = Uint8Array.from(atob(data.public_key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - data.public_key.length % 4) % 4)), c => c.charCodeAt(0)); const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }); await api("push", "POST", subscription.toJSON()); $("#pushStatus").textContent = "Avisos activados en este dispositivo."; });
$("#pushTest").onclick = (e) => run(e.target, async () => { await api("push/test", "POST"); $("#pushStatus").textContent = "Prueba en cola. Respeta el horario de silencio; puede tardar unos segundos."; });
$("#pushOff").onclick = (e) => run(e.target, async () => { const data = await api("push"); for (const s of data.subscriptions) await api("push/" + s.id, "DELETE"); const registration = await worker(); await (await registration.pushManager.getSubscription())?.unsubscribe(); $("#pushStatus").textContent = "Avisos desactivados."; });
let recorder, recordingStream;
$("#dictate").onclick = (e) => { if (recorder?.state === "recording") { recorder.stop(); return; } void run(e.target, async () => { recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true }); const chunks = []; recorder = new MediaRecorder(recordingStream); recorder.ondataavailable = (event) => chunks.push(event.data); recorder.onstop = async () => { recordingStream.getTracks().forEach(t => t.stop()); e.target.textContent = "Dictar"; const body = new FormData(); body.append("audio", new Blob(chunks, { type: recorder.mimeType }), "capture.webm"); try { const response = await fetch("/api/organizer/transcribe", { method: "POST", body }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "No se pudo transcribir"); $("#capture").elements.text.value = data.text; } catch (error) { message.textContent = error.message; } }; recorder.start(); e.target.textContent = "Terminar dictado"; setTimeout(() => { if (recorder?.state === "recording") recorder.stop(); }, 60000); }); };
window.addEventListener("online", () => void flush());
void flush().then(refresh).catch(error => { message.textContent = error.message + " Puedes guardar una captura para sincronizar después."; });

if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/service-worker.js").catch(() => {});
