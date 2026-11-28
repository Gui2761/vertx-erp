'use strict';

const CACHE_STATIC = 'vertyx-static-v8';
const CACHE_DYNAMIC = 'vertyx-dynamic-v8';

const STATIC_ASSETS = [
  '/',
  '/static/pwa/offline.html',
  '/static/pwa/pdv-offline.html',
  '/static/pwa/icon-192.png',
  '/static/pwa/icon-512.png',
  '/static/css/vertyx.css',
  '/static/css/technician.css',
  '/static/css/pdv-offline.css',
  '/static/vendor/bootstrap.min.css',
  '/static/vendor/bootstrap.bundle.min.js',
  '/static/js/vertyx.js',
  '/static/js/pdv-outbox.js',
  '/static/js/pdv-offline.js'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('[SW] Falha ao pré-cachear alguns itens:', err);
      });
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_STATIC && key !== CACHE_DYNAMIC)
            .map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  // Apenas requisições GET do mesmo domínio
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // 1. Navegação de Páginas (HTML): Network-First com Fallback Resiliente em Cache
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(networkResponse => {
          if (networkResponse && networkResponse.status === 200) {
            const copy = networkResponse.clone();
            caches.open(CACHE_DYNAMIC).then(cache => cache.put(request, copy));
          }
          return networkResponse;
        })
        .catch(async () => {
          // Sem conexão de rede: busca página em cache
          const cachedPage = await caches.match(request);
          if (cachedPage) return cachedPage;

          // Se for rota do PDV, serve o shell offline completo
          if (url.pathname.startsWith('/pdv/')) {
            const pdvOffline = await caches.match('/static/pwa/pdv-offline.html');
            if (pdvOffline) return pdvOffline;
          }

          // Se for rota de técnico, tenta a página principal do técnico
          if (url.pathname.startsWith('/tecnico/')) {
            const tecPage = await caches.match('/tecnico/');
            if (tecPage) return tecPage;
          }

          // Tenta a página raiz em cache
          const rootCached = await caches.match('/');
          if (rootCached) return rootCached;

          // Fallback para a Central Offline enriquecida
          return caches.match('/static/pwa/offline.html');
        })
    );
    return;
  }

  // 2. Arquivos Estáticos (CSS, JS, Imagens, Fontes): Cache First com Stale-While-Revalidate
  event.respondWith(
    caches.match(request).then(cachedResponse => {
      if (cachedResponse) {
        // Atualiza o cache em background quando online
        fetch(request).then(freshResponse => {
          if (freshResponse && freshResponse.status === 200) {
            caches.open(CACHE_DYNAMIC).then(cache => cache.put(request, freshResponse));
          }
        }).catch(() => {});
        return cachedResponse;
      }

      // Se não estava em cache, busca na rede e guarda no cache dinâmico
      return fetch(request).then(networkResponse => {
        if (networkResponse && networkResponse.status === 200) {
          const isStatic = url.pathname.startsWith('/static/') ||
                          url.pathname.endsWith('.css') ||
                          url.pathname.endsWith('.js') ||
                          url.pathname.endsWith('.png') ||
                          url.pathname.endsWith('.svg') ||
                          url.pathname.endsWith('.woff2');
          if (isStatic) {
            const copy = networkResponse.clone();
            caches.open(CACHE_DYNAMIC).then(cache => cache.put(request, copy));
          }
        }
        return networkResponse;
      }).catch(() => {
        if (request.destination === 'image') {
          return caches.match('/static/pwa/icon-192.png');
        }
      });
    })
  );
});

self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
