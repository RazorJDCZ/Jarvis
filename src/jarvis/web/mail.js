"use strict";
const message = document.querySelector("#message");
async function api(path, method = "GET", data) {
  const response = await fetch(`/api/mail/${path}`, { method, headers: { "Content-Type": "application/json" },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "No se pudo completar la operación.");
  return result;
}
const node = (tag, text, parent) => { const element = document.createElement(tag); element.textContent = text; parent.append(element); return element; };
async function action(button, callback) {
  button.disabled = true; message.textContent = "";
  try { await callback(); } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
}
async function refresh() {
  const [status, data, attention] = await Promise.all([
    api("status"), api("items"), api("insights"),
  ]);
  const accounts = document.querySelector("#accounts"); accounts.replaceChildren();
  document.querySelector("#coverage").textContent = status.coverage;
  if (!status.accounts.length) node("p", "Todavía no has conectado cuentas.", accounts);
  for (const account of status.accounts) {
    const row = node("article", "", accounts);
    node("strong", account.email, row);
    const state = account.error || (account.progress
      ? `Descarga gradual en curso: ${account.progress.processed} conversaciones revisadas en esta ronda`
      : (account.synced ? `Última revisión: ${new Date(account.synced * 1000).toLocaleString()}` : "Primera revisión pendiente"));
    node("p", state, row);
    const button = node("button", "Desconectar y borrar copia local", row);
    button.onclick = () => action(button, async () => {
      if (!window.confirm(`¿Desconectar ${account.email} y borrar su copia local de correos? Las tareas creadas en Appa se conservarán.`)) return;
      await api(`accounts/${account.id}`, "DELETE"); await refresh();
    });
  }
  for (const button of document.querySelectorAll("[data-connect]")) {
    button.disabled = !status.providers[button.dataset.connect];
  }
  if (!status.providers.google || !status.providers.microsoft) document.querySelector("#setup").open = true;
  const insights = document.querySelector("#insights"); insights.replaceChildren();
  if (!attention.items.length) node("p", "No hay correos que requieran atención especial.", insights);
  for (const item of attention.items.slice(0, 12)) {
    const row = node("article", "", insights); row.className = "attention-item";
    const heading = node("div", "", row); heading.className = "attention-heading";
    node("h3", item.subject || "Sin asunto", heading);
    node("span", `PRIORIDAD ${Math.round(item.attention_score)}`, heading).className = "attention-score";
    node("p", item.sender || "Remitente no disponible", row);
    node("p", item.summary || "Resumen pendiente.", row);
    const reasons = [
      ...(item.attention_reasons || []),
      ...(item.topics || []).map((topic) => `tema: ${topic}`),
    ];
    if (reasons.length) node("p", reasons.join(" · "), row).className = "attention-reasons";
  }
  const items = document.querySelector("#items"); items.replaceChildren();
  if (!data.items.length) node("p", status.syncing ? "Revisando tus correos…" : "No hay pendientes registrados.", items);
  for (const item of data.items.slice(0, 30)) {
    const row = node("article", "", items);
    node("h3", item.subject, row); node("p", `${item.email} · ${item.sender}`, row);
    node("p", item.summary || "Mensaje sin texto disponible.", row);
    if (item.summary_kind !== "ai") node("p", "Extracto del mensaje; resumen pendiente o no disponible.", row).className = "muted";
    const link = node("a", "Abrir correo original", row);
    const url = new URL(item.url);
    if (url.protocol === "https:" && ["mail.google.com", "outlook.office.com", "outlook.office365.com", "outlook.live.com"].includes(url.hostname)) link.href = url.href;
    link.target = "_blank"; link.rel = "noopener noreferrer";
  }
}
for (const form of document.querySelectorAll("form[data-provider]")) {
  form.onsubmit = (event) => { event.preventDefault(); action(form.querySelector("button"), async () => {
    await api("config", "PUT", { provider: form.dataset.provider, client_id: form.elements.client_id.value.trim(), client_secret: form.elements.client_secret?.value.trim() || "" });
    if (form.elements.client_secret) form.elements.client_secret.value = "";
    message.textContent = "Configuración guardada. Ya puedes conectar la cuenta."; await refresh();
  }); };
}
document.querySelector("#googleFile").onchange = async (event) => {
  try {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 20000) throw new Error("El archivo es demasiado grande para ser un cliente OAuth.");
    const client = JSON.parse(await file.text()).installed;
    if (!client?.client_id || !client?.client_secret) throw new Error("Importa un cliente OAuth de tipo Aplicación de escritorio.");
    const form = event.target.closest("form"); form.elements.client_id.value = client.client_id; form.elements.client_secret.value = client.client_secret;
    message.textContent = "Cliente importado. Pulsa Guardar conexión de Gmail.";
  } catch (error) { message.textContent = error.message; }
};
for (const button of document.querySelectorAll("[data-connect]")) {
  button.onclick = () => {
    const popup = window.open("about:blank", "jarvis-mail-login");
    action(button, async () => {
      try {
        const { url } = await api(`connect/${button.dataset.connect}`, "POST");
        const parsed = new URL(url);
        if (parsed.protocol !== "https:" || !["accounts.google.com", "login.microsoftonline.com"].includes(parsed.hostname)) throw new Error("Dirección de autorización inválida.");
        if (popup) { popup.opener = null; popup.location = url; } else window.location = url;
        message.textContent = "Completa el inicio de sesión en la ventana del proveedor. Esta vista se actualizará automáticamente.";
      } catch (error) { popup?.close(); throw error; }
    });
  };
}
document.querySelector("#sync").onclick = (event) => action(event.target, async () => { await api("sync", "POST"); message.textContent = "Revisión solicitada. Puedes seguir usando Jarvis."; });
document.querySelector("#refresh").onclick = (event) => action(event.target, refresh);
refresh().catch((error) => { message.textContent = error.message; });
setInterval(() => refresh().catch(() => {}), 10000);
