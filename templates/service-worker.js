{% load static %}
const CACHE_NAME = "dubeyai-shell-v1";
const OFFLINE_URL = "{% url 'offline_page' %}";
const SHELL_ASSETS = [
    OFFLINE_URL,
    "{% static 'chatbot/css/app.css' %}",
    "{% static 'chatbot/js/chat.js' %}",
    "{% static 'core/js/pwa.js' %}",
    "{% static 'core/icons/icon-192.png' %}",
    "{% static 'core/icons/icon-512.png' %}",
];

self.addEventListener("install", (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") return;

    // Full page loads: try the network first, fall back to the cached
    // offline shell. Never serve stale personalised HTML from cache.
    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
        return;
    }

    // Static shell assets: cache-first, network fallback.
    if (SHELL_ASSETS.some((asset) => request.url.endsWith(asset))) {
        event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
    }
});

self.addEventListener("push", (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (err) {
        data = { title: "DubeyAI", body: event.data ? event.data.text() : "" };
    }
    const title = data.title || "DubeyAI";
    const options = {
        body: data.body || "",
        icon: "{% static 'core/icons/icon-192.png' %}",
        badge: "{% static 'core/icons/icon-192.png' %}",
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ("focus" in client) return client.focus();
            }
            if (self.clients.openWindow) return self.clients.openWindow("/");
        })
    );
});

// Best-effort Background Sync: the SW itself can't reach the page's
// localStorage-backed offline queue, so it just wakes any open tabs, which
// flush their own queue (see chat.js). The `online` event listener in the
// page is the reliable primary path; this is a progressive enhancement.
self.addEventListener("sync", (event) => {
    if (event.tag === "sync-messages") {
        event.waitUntil(
            self.clients.matchAll().then((clientList) => {
                clientList.forEach((client) => client.postMessage({ type: "flush-offline-queue" }));
            })
        );
    }
});
