(() => {
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/gestao-publica/territorio/sw.js', {
      scope: '/gestao-publica/territorio/',
    }).catch(() => {});
  }, { once: true });
})();
