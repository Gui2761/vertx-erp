'use strict';
const CACHE='vertyx-vendedor-shell-v1';
const ASSETS=['/static/pwa/vendedor-offline.html','/static/pwa/icon-192.png','/static/pwa/icon-512.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
  const r=e.request,u=new URL(r.url);if(r.method!=='GET'||u.origin!==self.location.origin)return;
  if(r.mode==='navigate'&&u.pathname.startsWith('/vendedor/'))e.respondWith(fetch(r).catch(()=>caches.match('/static/pwa/vendedor-offline.html')));
  else if(ASSETS.includes(u.pathname))e.respondWith(caches.match(u.pathname).then(hit=>hit||fetch(r)));
});
