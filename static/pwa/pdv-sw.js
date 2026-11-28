'use strict';
importScripts('/static/js/pdv-outbox.js');

const CACHE_STATIC = 'vertyx-pdv-shell-v8';
const CACHE_DYNAMIC = 'vertyx-pdv-dynamic-v8';

const STATIC_ASSETS = [
  '/pdv/',
  '/static/pwa/pdv-offline.html',
  '/static/css/pdv-offline.css',
  '/static/js/pdv-outbox.js',
  '/static/js/pdv-offline.js',
  '/static/pwa/icon-192.png',
  '/static/pwa/icon-512.png',
  '/static/css/vertyx.css',
  '/static/vendor/bootstrap.min.css',
  '/static/vendor/bootstrap.bundle.min.js'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('[PDV SW] Cache parcial de ativos:', err);
      });
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(k => k.startsWith('vertyx-pdv-') && k !== CACHE_STATIC && k !== CACHE_DYNAMIC)
            .map(k => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Navegação no PDV: Network-First com Fallback para PDV em Cache ou Shell Offline
  if (request.mode === 'navigate' && url.pathname.startsWith('/pdv/')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_DYNAMIC).then(cache => cache.put(request, clone));
          }
          return response;
        })
        .catch(async () => {
          // Sem conexão de rede: tenta página em cache
          const cached = await caches.match(request);
          if (cached) return cached;

          // Se não houver cache daquela URL específica, entrega o PDV Offline com carrinho e outbox
          const pdvOffline = await caches.match('/static/pwa/pdv-offline.html');
          if (pdvOffline) return pdvOffline;

          return caches.match('/static/pwa/offline.html');
        })
    );
    return;
  }

  // Assets estáticos do PDV
  event.respondWith(
    caches.match(request).then(hit => {
      if (hit) {
        fetch(request).then(fresh => {
          if (fresh && fresh.status === 200) {
            caches.open(CACHE_DYNAMIC).then(c => c.put(request, fresh));
          }
        }).catch(() => {});
        return hit;
      }
      return fetch(request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE_DYNAMIC).then(c => c.put(request, clone));
        }
        return res;
      }).catch(() => caches.match('/static/pwa/icon-192.png'));
    })
  );
});

self.addEventListener('sync', event => {
  if (event.tag === 'vertyx-pdv-sales') {
    event.waitUntil(PDVOutbox.sync());
  }
});

self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data?.type === 'SYNC_PDV') event.waitUntil(PDVOutbox.sync());
});
