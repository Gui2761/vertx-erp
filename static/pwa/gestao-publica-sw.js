'use strict';

// Network-only by design: authenticated municipal pages and data are never cached.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
  const path = new URL(request.url).pathname;
  if (path.startsWith('/gestao-publica/saude/prontuarios/') || path.endsWith('/prontuario/')) return;
  event.respondWith(fetch(request, { cache: 'no-store' }));
});
