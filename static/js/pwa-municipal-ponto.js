'use strict';

(() => {
  const form = document.querySelector('[data-point-form]');
  if (form) {
    const requestField = form.querySelector('[name="request_id"]');
    const deviceField = form.querySelector('[name="device"]');
    const uuid = () => {
      if (crypto.randomUUID) return crypto.randomUUID();
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      return [...bytes].map((value, index) => `${index === 4 || index === 6 || index === 8 || index === 10 ? '-' : ''}${value.toString(16).padStart(2, '0')}`).join('');
    };
    form.addEventListener('submit', event => {
      if (!requestField.value) requestField.value = uuid();
      if (deviceField && !deviceField.value) deviceField.value = `${navigator.userAgentData?.platform || navigator.platform || 'Dispositivo'} · ${navigator.userAgent.slice(0, 90)}`;
      const optIn = form.querySelector('[data-location-opt-in]:checked');
      if (!optIn || form.dataset.locationEnabled !== 'true' || !navigator.geolocation) return;
      event.preventDefault();
      navigator.geolocation.getCurrentPosition(position => {
        form.querySelector('[name="latitude"]').value = position.coords.latitude.toFixed(6);
        form.querySelector('[name="longitude"]').value = position.coords.longitude.toFixed(6);
        form.submit();
      }, () => form.submit(), { enableHighAccuracy: false, timeout: 5000, maximumAge: 30000 });
    }, { once: true });
  }
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/gestao-publica/ponto/sw.js', { scope: '/gestao-publica/ponto/' }).catch(() => {});
    });
  }
})();
