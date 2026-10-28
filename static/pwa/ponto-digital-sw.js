'use strict';

// The Ponto PWA deliberately has no Cache API and no fetch handler. Authenticated
// pages and point records always require a live, authenticated server response.
self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});
