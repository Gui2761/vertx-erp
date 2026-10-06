const CACHE='vertyx-public-v2';
const ASSETS=['/static/pwa/offline.html','/static/pwa/icon-192.png','/static/pwa/icon-512.png','/static/css/vertyx.css','/static/css/technician.css','/static/vendor/bootstrap.min.css'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));self.skipWaiting()});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('vertyx-public-')&&key!==CACHE).map(key=>caches.delete(key)))));self.clients.claim()});
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin)return;
  // Dados empresariais, sessão, documentos, GPS e assinaturas nunca entram no cache.
  if(event.request.mode==='navigate'){event.respondWith(fetch(event.request).catch(()=>caches.match('/static/pwa/offline.html')));return}
  if(ASSETS.includes(url.pathname)&&!url.search)event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));
});
