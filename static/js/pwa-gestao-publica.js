'use strict';

(() => {
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    // Ponto Digital has its own install identity and a narrower scope.
    if (!window.location.pathname.startsWith('/gestao-publica/ponto/')) {
      navigator.serviceWorker.register('/gestao-publica/sw.js', { scope: '/gestao-publica/' })
        .catch(() => {});
    }
  });

  let installPrompt;
  const installButton = document.querySelector('[data-gp-install]');
  if (!installButton) return;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    installButton.hidden = false;
  });
  installButton.addEventListener('click', async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = undefined;
    installButton.hidden = true;
  });
  window.addEventListener('appinstalled', () => { installButton.hidden = true; });
})();
