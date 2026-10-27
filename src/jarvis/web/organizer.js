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
const financeKind = { purchase: "Compra", transfer: "Transferencia", withdrawal: "Retiro", interest: "Ingreso" };
let financeData = null;
function money(value) { const amount = Number(value); return Number.isFinite(amount) ? amount.toLocaleString("es-EC", { style: "currency", currency: "USD" }) : "$—"; }
async function selectedFinance() {
  const selectedMonth = $("#financeMonth").value;
  return api("finance/query", "POST", { month: selectedMonth || "" });
}
async function saveFinance(transaction, category, included, button, merchant = null, rememberMerchant = false) {
  await run(button, async () => {
    await api(`finance/transactions/${encodeURIComponent(transaction.id)}`, "PATCH", { version: transaction.version, category, included, merchant, remember_merchant: rememberMerchant });
    renderFinance(await selectedFinance());
    message.textContent = included ? "Movimiento actualizado." : "Movimiento excluido del total mensual.";
  });
}
function renderFinanceSignals(parent, items, emptyTitle, emptyDescription, renderer) {
  parent.replaceChildren();
  for (const item of items) renderer(item, parent);
  if (!items.length) emptyState(parent, emptyTitle, emptyDescription, "◇");
}
function renderFinance(data) {
  financeData = data;
  $("#financeMonth").value = data.month;
  $("#financeExport").href = `/api/organizer/finance/export.csv?month=${encodeURIComponent(data.month)}`;
  $("#spentTotal").textContent = money(data.total_spent);
  $("#spentCaption").firstChild.textContent = `${data.transaction_count} movimientos · `;
  $("#financeTotal").textContent = money(data.total_spent);
  $("#financeProjection").textContent = money(data.projection.amount);
  $("#financeProjectionCaption").textContent = data.projection.days_elapsed
    ? `${data.projection.days_elapsed} de ${data.projection.days_total} días observados`
    : "Mes futuro · todavía sin ritmo de gasto";
  $("#financeBudgetRemaining").textContent = data.budget.configured ? money(data.budget.remaining) : "$—";
  $("#financeBudgetCaption").textContent = data.budget.configured
    ? `${data.budget.used_percent}% de ${money(data.budget.limit)} utilizado`
    : "Configura un límite mensual";
  $("#financeSavings").textContent = data.profile.configured ? money(data.profile.projected_savings) : "$—";
  $("#financeSavingsCaption").textContent = data.profile.configured
    ? data.profile.goal_progress === null ? "Sin meta de ahorro definida" : `${data.profile.goal_progress}% de la meta proyectado`
    : "Configura ingreso y meta";
  $("#financePurchases").textContent = money(data.purchases);
  $("#financeTransfers").textContent = money(data.transfers);
  $("#financeCash").textContent = money(data.withdrawals);
  $("#financeIncome").textContent = money(data.income);
  const comparison = data.comparison;
  $("#financeComparison").textContent = comparison.available
    ? `${comparison.direction === "up" ? "↑" : comparison.direction === "down" ? "↓" : "="} ${money(comparison.difference)} frente a ${comparison.previous_month}${comparison.percent === null ? "" : ` · ${comparison.percent}%`}`
    : comparison.partial ? "Historial anterior parcial · sin comparación" : "Aún no hay un mes anterior comparable";
  const accounts = data.accounts.filter(account => account.messages);
  const syncing = accounts.some(account => account.syncing);
  $("#financeStatus").textContent = accounts.length
    ? `${accounts.map(account => account.email).join(", ")} · ${syncing ? "completando historial en segundo plano" : "historial local actualizado"}`
    : "No hay notificaciones bancarias reconocidas en las cuentas conectadas.";
  $("#financeReviewCount").textContent = data.review_count ? `${data.review_count} POR REVISAR` : "TODO REVISADO";
  $("#financeDisclaimer").textContent = data.disclaimer;
  const categories = $("#financeCategories"); categories.replaceChildren();
  for (const category of data.categories) {
    const item = node("article", "", categories); item.className = "finance-category";
    const heading = node("div", "", item); node("strong", category.name, heading); node("span", money(category.total), heading);
    const share = category.budget_configured ? Math.min(100, category.budget_used_percent) : category.share;
    const bar = node("i", "", item); bar.style.setProperty("--finance-share", `${Math.max(2, share)}%`); bar.dataset.status = category.budget_status;
    node("small", category.budget_configured
      ? `${category.count} movimientos · ${category.budget_used_percent}% de ${money(category.budget)}`
      : `${category.count} movimientos · ${category.share}% del gasto`, item);
  }
  if (!data.categories.length) emptyState(categories, "Sin gastos clasificados", "Los consumos reconocidos del mes aparecerán aquí.", "$");
  const transactions = $("#financeTransactions"); transactions.replaceChildren();
  for (const transaction of data.transactions) {
    const item = node("article", "", transactions); item.className = "finance-transaction";
    if (!transaction.included) item.dataset.included = "false";
    if (transaction.needs_review) item.dataset.review = "true";
    const top = node("div", "", item); top.className = "finance-transaction-main";
    const copy = node("div", "", top); copy.className = "finance-transaction-copy";
    const title = node("a", transaction.merchant, copy); title.href = transaction.url || "/mail"; title.target = "_blank"; title.rel = "noopener";
    const date = new Date(transaction.occurred_at).toLocaleDateString("es-EC", { day: "2-digit", month: "short", timeZone: zone });
    node("small", `${transaction.bank} · ${financeKind[transaction.kind] || transaction.kind} · ${date}`, copy);
    const amount = node("strong", `${transaction.direction === "income" ? "+" : ""}${money(transaction.amount)}`, top); amount.className = transaction.direction === "income" ? "finance-income" : "";
    const controls = node("div", "", item); controls.className = "finance-controls";
    const select = node("select", "", controls); select.setAttribute("aria-label", `Categoría de ${transaction.merchant}`);
    for (const option of data.category_options) { const element = node("option", option.name, select); element.value = option.id; element.selected = option.id === transaction.category; }
    const toggle = node("button", transaction.included ? "Excluir del total" : "Incluir en el total", controls); toggle.type = "button";
    const rename = node("button", "Corregir comercio", controls); rename.type = "button";
    select.onchange = () => void saveFinance(transaction, select.value, transaction.included, select);
    toggle.onclick = () => void saveFinance(transaction, select.value, !transaction.included, toggle);
    rename.onclick = () => { const value = prompt("Nombre correcto del comercio. Se recordará para movimientos equivalentes.", transaction.merchant); if (value?.trim() && value.trim() !== transaction.merchant) void saveFinance(transaction, select.value, transaction.included, rename, value.trim(), true); };
    if (transaction.needs_review) { const flag = node("span", "REVISAR", controls); flag.className = "finance-review"; }
  }
  if (!data.transactions.length) emptyState(transactions, "Todavía no hay movimientos", "Jarvis mostrará aquí pagos, transferencias y retiros reconocidos en tus correos.", "$");
  const maxHistory = Math.max(1, ...data.history.map(item => Number(item.total)));
  renderFinanceSignals($("#financeHistory"), data.history, "Sin tendencia todavía", "El historial crecerá sin volver a descargar correos ya archivados.", (item, parent) => {
    const bar = node("article", "", parent); bar.className = "finance-history-item"; if (item.selected) bar.dataset.selected = "true";
    node("span", item.month, bar); const track = node("i", "", bar); track.style.setProperty("--history-height", `${Math.max(4, Number(item.total) / maxHistory * 100)}%`); node("strong", money(item.total), bar);
  });
  renderFinanceSignals($("#financeRecurring"), data.recurring, "Sin recurrencias confirmadas", "Se necesitan al menos dos cargos separados por unas cuatro semanas.", (item, parent) => {
    const card = node("article", "", parent); node("strong", item.merchant, card); node("span", `${money(item.monthly_estimate)} al mes · ${item.occurrences} apariciones`, card); node("small", `Próxima fecha estimada: ${item.next_estimated} · confianza ${item.confidence === "high" ? "alta" : "media"}`, card);
  });
  renderFinanceSignals($("#financeAlerts"), data.alerts, "Nada inusual detectado", "Jarvis compara importes con tu historial local; esto no es una alerta bancaria.", (item, parent) => {
    const card = node("article", "", parent); card.className = "finance-alert"; node("strong", `${item.merchant} · ${money(item.amount)}`, card); node("span", item.reason, card); if (item.baseline) node("small", `Referencia histórica: ${money(item.baseline)}`, card);
  });
  $("#financeProfile").elements.monthly_income.value = data.profile.monthly_income;
  $("#financeProfile").elements.savings_goal.value = data.profile.savings_goal;
}
let latestBackupName = "";
const localConsole = ["127.0.0.1", "localhost"].includes(location.hostname);
function renderReliability(data) {
  const container = $("#reliabilityChecks"); container.replaceChildren();
  const checks = [...(data.services || []), ...(data.recovery?.checks || [])];
  for (const check of checks) {
    const item = node("article", "", container); item.dataset.status = check.status;
    node("i", "", item); const copy = node("div", "", item); node("strong", check.name, copy); node("small", check.detail, copy);
  }
  latestBackupName = data.recovery?.backups?.[0]?.name || "";
  $("#resourceMode").elements.resource_mode.value = data.settings.resource_mode;
  $("#reliabilityStatus").textContent = `Comprobación ${data.status === "ok" ? "correcta" : data.status === "warning" ? "con observaciones" : "con errores"} · ${data.recovery?.duration_ms ?? 0} ms`;
}
async function loadReliability() {
  if (!localConsole) {
    $("#reliabilityStatus").textContent = "El diagnóstico detallado solo se ejecuta desde la computadora principal.";
    return;
  }
  renderReliability(await api("reliability"));
}
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
  renderFinance(data.finance);
  $("#backupStatus").textContent = data.recovery.backups?.length ? `Último respaldo: ${new Date(data.recovery.backups[0].created * 1000).toLocaleString()}` : "El primer respaldo se prepara automáticamente.";
  latestBackupName = data.recovery.backups?.[0]?.name || latestBackupName;
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
$("#financeMonth").onchange = (e) => { void run(e.currentTarget, async () => renderFinance(await selectedFinance())); };
$("#financeBudget").onsubmit = (e) => { e.preventDefault(); const form = e.currentTarget; void run(form.querySelector("button"), async () => { await api("finance/budget", "PUT", { category: form.elements.category.value, monthly_limit: form.elements.monthly_limit.value.replace(",", ".") }); renderFinance(await selectedFinance()); message.textContent = "Presupuesto actualizado."; }); };
$("#financeProfile").onsubmit = (e) => { e.preventDefault(); const form = e.currentTarget; void run(form.querySelector("button"), async () => { await api("finance/profile", "PUT", { monthly_income: form.elements.monthly_income.value.replace(",", "."), savings_goal: form.elements.savings_goal.value.replace(",", ".") }); renderFinance(await selectedFinance()); message.textContent = "Meta financiera actualizada."; }); };
$("#study").onsubmit = (e) => { e.preventDefault(); const f = e.currentTarget; void run(f.querySelector("button"), async () => { const payload = Object.fromEntries(new FormData(f)); for (const k of ["sessions", "minutes", "start_hour", "end_hour"]) payload[k] = Number(payload[k]); const result = await api("study", "POST", payload); message.textContent = `${result.slots.length} sesiones propuestas. Faltan ${result.missing}. ${result.warning}`; draftsLoaded = false; await refresh(); }); };
$("#followups").onsubmit = (e) => { e.preventDefault(); const f = e.currentTarget; void run(f.querySelector("button"), async () => { await api("followups", "PUT", { enabled: f.elements.enabled.checked, after_days: Number(f.elements.after_days.value), repeat_hours: Number(f.elements.repeat_hours.value) }); message.textContent = "Seguimiento guardado."; }); };
$("#connect").onclick = (e) => run(e.target, async () => { const tab = window.open("about:blank", "_blank"); try { const data = await api("calendar/connect", "POST"); if (tab) tab.location = data.url; else location.href = data.url; } catch (error) { tab?.close(); throw error; } });
$("#disconnect").onclick = (e) => run(e.target, async () => { if (confirm("¿Desconectar Calendar? Los eventos guardados en Google se conservarán.")) { await api("calendar", "DELETE"); await refresh(); } });
$("#backup").onclick = (e) => run(e.target, async () => { const result = await api("backups", "POST"); message.textContent = result.verified ? "Respaldo cifrado creado y verificado." : "Respaldo cifrado creado."; await refresh(); await loadReliability(); });
$("#diagnose").onclick = (e) => run(e.target, async () => { await loadReliability(); message.textContent = "Diagnóstico de confiabilidad actualizado."; });
$("#verifyBackup").onclick = (e) => run(e.target, async () => { if (!latestBackupName) throw new Error("Todavía no existe un respaldo para verificar."); const result = await api(`backups/${encodeURIComponent(latestBackupName)}/verify`, "POST"); message.textContent = `Respaldo verificado: ${result.files} archivos y ${result.databases} bases de datos íntegros.`; await loadReliability(); });
$("#resourceMode").onsubmit = (e) => { e.preventDefault(); const form = e.currentTarget; void run(form.querySelector("button"), async () => { await api("reliability/settings", "PUT", { resource_mode: form.elements.resource_mode.value }); message.textContent = "Modo de actividad guardado."; await loadReliability(); }); };
async function worker() { if (!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("Este navegador no admite avisos. En iPhone abre Jarvis desde la pantalla de inicio."); await navigator.serviceWorker.register("/service-worker.js"); return navigator.serviceWorker.ready; }
$("#push").onclick = (e) => run(e.target, async () => { const registration = await worker(); const data = await api("push"); const key = Uint8Array.from(atob(data.public_key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - data.public_key.length % 4) % 4)), c => c.charCodeAt(0)); const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }); await api("push", "POST", subscription.toJSON()); $("#pushStatus").textContent = "Avisos activados en este dispositivo."; });
$("#pushTest").onclick = (e) => run(e.target, async () => { await api("push/test", "POST"); $("#pushStatus").textContent = "Prueba en cola. Respeta el horario de silencio; puede tardar unos segundos."; });
$("#pushOff").onclick = (e) => run(e.target, async () => { const data = await api("push"); for (const s of data.subscriptions) await api("push/" + s.id, "DELETE"); const registration = await worker(); await (await registration.pushManager.getSubscription())?.unsubscribe(); $("#pushStatus").textContent = "Avisos desactivados."; });
let recorder, recordingStream;
$("#dictate").onclick = (e) => { if (recorder?.state === "recording") { recorder.stop(); return; } void run(e.target, async () => { recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true }); const chunks = []; recorder = new MediaRecorder(recordingStream); recorder.ondataavailable = (event) => chunks.push(event.data); recorder.onstop = async () => { recordingStream.getTracks().forEach(t => t.stop()); e.target.textContent = "Dictar"; const body = new FormData(); body.append("audio", new Blob(chunks, { type: recorder.mimeType }), "capture.webm"); try { const response = await fetch("/api/organizer/transcribe", { method: "POST", body }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "No se pudo transcribir"); $("#capture").elements.text.value = data.text; } catch (error) { message.textContent = error.message; } }; recorder.start(); e.target.textContent = "Terminar dictado"; setTimeout(() => { if (recorder?.state === "recording") recorder.stop(); }, 60000); }); };
window.addEventListener("online", () => void flush());
void flush().then(async () => { await refresh(); await loadReliability(); }).catch(error => { message.textContent = error.message + " Puedes guardar una captura para sincronizar después."; });

if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/service-worker.js").catch(() => {});
