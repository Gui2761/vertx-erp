'use strict';
importScripts('/static/js/pdv-outbox.js');
const CACHE='vertyx-pdv-shell-v2';
const ASSETS=['/static/pwa/pdv-offline.html','/static/css/pdv-offline.css','/static/js/pdv-outbox.js','/static/js/pdv-offline.js','/static/pwa/icon-192.png','/static/pwa/icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{
  const r=event.request,u=new URL(r.url);if(r.method!=='GET'||u.origin!==self.location.origin)return;
  if(r.mode==='navigate'&&u.pathname.startsWith('/pdv/')){
    event.respondWith(fetch(r).catch(()=>caches.match('/static/pwa/pdv-offline.html')));return;
  }
  if(ASSETS.includes(u.pathname))event.respondWith(caches.match(u.pathname).then(hit=>hit||fetch(r)));
});
self.addEventListener('sync',event=>{if(event.tag==='vertyx-pdv-sales')event.waitUntil(PDVOutbox.sync());});
self.addEventListener('message',event=>{if(event.data?.type==='SYNC_PDV')event.waitUntil(PDVOutbox.sync());});
