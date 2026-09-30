'use strict';
document.querySelectorAll('.os-geo-form').forEach((form) => {
  let waiting = false;
  const button = form.querySelector('button[type="submit"]');
  const proceed = form.querySelector('.os-geo-continue');
  const message = form.querySelector('.os-geo-message');
  const set = (name, value) => { form.elements[name].value = value; };
  function failure(result, text) {
    set('resultado', result);
    ['latitude', 'longitude', 'precisao'].forEach(name => set(name, ''));
    message.textContent = text + ' Você pode continuar; a falha ficará registrada.';
    proceed.hidden = false;
    waiting = false;
    button.disabled = false;
    button.textContent = 'Tentar localização novamente';
  }
  proceed.addEventListener('click', () => {
    if (form.elements.resultado.value && form.elements.resultado.value !== 'OBTIDA') {
      proceed.disabled = true;
      button.disabled = true;
      HTMLFormElement.prototype.submit.call(form);
    }
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (waiting) return;
    waiting = true;
    button.disabled = true;
    proceed.hidden = true;
    message.textContent = 'Solicitando localização…';
    if (!navigator.geolocation) {
      failure('NAO_SUPORTADA', 'Este navegador não oferece localização.');
      return;
    }
    navigator.geolocation.getCurrentPosition((position) => {
      set('resultado', 'OBTIDA');
      set('latitude', position.coords.latitude);
      set('longitude', position.coords.longitude);
      set('precisao', position.coords.accuracy ?? '');
      HTMLFormElement.prototype.submit.call(form);
    }, (error) => {
      const result = {1: 'NEGADA', 2: 'INDISPONIVEL', 3: 'TIMEOUT'}[error.code] || 'INDISPONIVEL';
      failure(result, {NEGADA: 'Permissão de localização negada.', INDISPONIVEL: 'Localização indisponível.', TIMEOUT: 'Tempo para obter localização esgotado.'}[result]);
    }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
  });
});
