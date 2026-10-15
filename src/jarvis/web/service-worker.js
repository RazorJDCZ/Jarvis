const CACHE_NAME = "jarvis-assistant-interface-v18";
const CACHE_PREFIX = "jarvis-assistant-interface-";
const STATIC_ASSETS = [
  "/",
  "/organizer",
  "/static/organizer.js?v=2",
  "/static/organizer.css?v=2",
  "/static/mail.css",
  "/static/styles.css?v=agent-v10",
  "/static/app.js?v=agent-v11",
  "/static/assistant.js?v=assistant-v4",
  "/static/icon.svg?v=agent-v9",
  "/manifest.webmanifest?v=agent-v9",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("push", (event) => {
  let payload = {};
  try { payload = event.data?.json() || {}; } catch { /* Display a generic notification. */ }
  event.waitUntil(self.registration.showNotification("Jarvis", {
    body: payload.body || "Tienes un pendiente para revisar.",
    tag: payload.tag || "jarvis-pending", icon: "/static/icon.svg", data: { url: "/organizer" },
  }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow("/organizer"));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(async (keys) => {
      const upgrading = keys.some(
        (key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME,
      );
      await Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)));
      await self.clients.claim();
      if (!upgrading) return;
      const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      await Promise.all(clients.map((client) => client.navigate(client.url)));
    }),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith("/api/")
  ) {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});
