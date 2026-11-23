'use strict';

const CACHE_STATIC = 'vertyx-tecnico-shell-v6';
const CACHE_DYNAMIC = 'vertyx-tecnico-dynamic-v6';

const STATIC_ASSETS = [
  '/tecnico/',
  '/static/pwa/offline.html',
  '/static/pwa/icon-192.png',
  '/static/pwa/icon-512.png',
  '/static/css/technician.css',
  '/static/vendor/bootstrap.min.css',
  '/static/vendor/bootstrap.bundle.min.js',
  '/static/js/vertyx.js'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('[Tecnico SW] Pré-cacheamento parcial:', err);
      });
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(k => k.startsWith('vertyx-tecnico-') && k !== CACHE_STATIC && k !== CACHE_DYNAMIC)
            .map(k => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Navegação no PWA do Técnico: Network-First com Fallback no Cache
  if (request.mode === 'navigate' && url.pathname.startsWith('/tecnico/')) {
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
          // Offline no campo: recupera a última agenda e demandas em cache
          const cached = await caches.match(request);
          if (cached) return cached;

          const tecHome = await caches.match('/tecnico/');
          if (tecHome) return tecHome;

          return caches.match('/static/pwa/offline.html');
        })
    );
    return;
  }

  // Assets estáticos do técnico
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) {
        fetch(request).then(fresh => {
          if (fresh && fresh.status === 200) {
            caches.open(CACHE_DYNAMIC).then(c => c.put(request, fresh));
          }
        }).catch(() => {});
        return cached;
      }
      return fetch(request).then(response => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_DYNAMIC).then(c => c.put(request, clone));
        }
        return response;
      }).catch(() => caches.match('/static/pwa/icon-192.png'));
    })
  );
});

self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
