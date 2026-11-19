'use strict';
const CACHE='vertyx-vendedor-shell-v4';
const ASSETS=['/static/pwa/vendedor-offline.html','/static/pwa/icon-192.png','/static/pwa/icon-512.png'];
self.addEventListener('install',e=>{
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));
});
self.addEventListener('activate',e=>e.waitUntil(
  caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('vertyx-vendedor-')&&k!==CACHE).map(k=>caches.delete(k))))
  .then(()=>self.clients.claim())
));
self.addEventListener('fetch',e=>{
  const r=e.request,u=new URL(r.url);if(r.method!=='GET'||u.origin!==self.location.origin)return;
  if(r.mode==='navigate'&&u.pathname.startsWith('/vendedor/'))e.respondWith(fetch(r).catch(()=>caches.match('/static/pwa/vendedor-offline.html')));
  else if(ASSETS.includes(u.pathname))e.respondWith(caches.match(u.pathname).then(hit=>hit||fetch(r)));
});
self.addEventListener('message',e=>{
  if(e.data?.type==='SKIP_WAITING')self.skipWaiting();
});
