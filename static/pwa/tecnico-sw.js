'use strict';
const CACHE='vertyx-tecnico-shell-v4';
const ASSETS=['/static/pwa/offline.html','/static/pwa/icon-192.png','/static/pwa/icon-512.png','/static/css/technician.css','/static/vendor/bootstrap.min.css'];
self.addEventListener('install',event=>{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));
});
self.addEventListener('activate',event=>event.waitUntil(
  caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('vertyx-tecnico-')&&k!==CACHE).map(k=>caches.delete(k))))
  .then(()=>self.clients.claim())
));
self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url);
  if(request.method!=='GET'||url.origin!==self.location.origin)return;
  // Páginas autenticadas e respostas do tenant sempre dependem da rede; não cachear documentos privados.
  if(request.mode==='navigate'&&url.pathname.startsWith('/tecnico/')){
    event.respondWith(fetch(request).catch(()=>caches.match('/static/pwa/offline.html')));
    return;
  }
  if(ASSETS.includes(url.pathname)&&!url.search){
    event.respondWith(caches.match(request).then(cached=>cached||fetch(request)));
  }
});
self.addEventListener('message',event=>{
  if(event.data?.type==='SKIP_WAITING')self.skipWaiting();
});
