'use strict';
document.querySelectorAll('[data-workday-gps]').forEach(form => {
  let submitting = false;
  form.addEventListener('submit', event => {
    if (submitting) return;
    event.preventDefault();
    const status = document.getElementById('workday-gps-status');
    if (!navigator.onLine) { status.textContent = 'Sem conexão. Reconecte antes de registrar a atividade.'; return; }
    submitting = true;
    const finish = (result, position) => {
      form.elements.resultado.value = result;
      if (position) {
        form.elements.latitude.value = position.coords.latitude;
        form.elements.longitude.value = position.coords.longitude;
        form.elements.precisao.value = position.coords.accuracy;
      }
      // Validação HTML já ocorreu no submit original; backend valida todos os
      // campos novamente. Mesmo fluxo utilizado pela geolocalização da OS.
      HTMLFormElement.prototype.submit.call(form);
    };
    status.textContent = 'Registrando atividade…';
    if (!form.querySelector('[data-gps-consent]').checked) { finish('NEGADA'); return; }
    if (!navigator.geolocation) { finish('INDISPONIVEL'); return; }
    navigator.geolocation.getCurrentPosition(p => finish('OBTIDA', p), e => finish(e.code === 1 ? 'NEGADA' : e.code === 3 ? 'TIMEOUT' : 'INDISPONIVEL'), {enableHighAccuracy:true, timeout:10000, maximumAge:0});
  });
});
