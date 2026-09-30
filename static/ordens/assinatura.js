'use strict';
(() => {
  const canvas = document.getElementById('signature-canvas');
  if (!canvas) return;
  const context = canvas.getContext('2d');
  const form = document.getElementById('os-sign-form');
  const hidden = document.getElementById('id_imagem');
  const message = document.getElementById('signature-message');
  let drawing = false, hasInk = false, activePointer = null;
  context.lineWidth = 3;
  context.lineCap = 'round';
  context.lineJoin = 'round';
  context.strokeStyle = '#102d42';
  function clear() {
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    hidden.value = '';
    hasInk = false;
    drawing = false;
    activePointer = null;
    message.textContent = 'Área limpa. Você pode refazer a assinatura.';
  }
  clear();
  function point(event) {
    const rect = canvas.getBoundingClientRect();
    return [(event.clientX - rect.left) * canvas.width / rect.width, (event.clientY - rect.top) * canvas.height / rect.height];
  }
  canvas.addEventListener('pointerdown', event => {
    if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return;
    event.preventDefault();
    activePointer = event.pointerId;
    canvas.setPointerCapture(event.pointerId);
    drawing = true;
    context.beginPath();
    context.moveTo(...point(event));
    message.textContent = '';
  });
  canvas.addEventListener('pointermove', event => {
    if (!drawing || event.pointerId !== activePointer) return;
    event.preventDefault();
    context.lineTo(...point(event));
    context.stroke();
    hasInk = true;
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => canvas.addEventListener(type, event => {
    if (event.pointerId === activePointer) { drawing = false; activePointer = null; }
  }));
  document.getElementById('clear-signature').addEventListener('click', clear);
  form.addEventListener('submit', event => {
    if (!hasInk) {
      event.preventDefault();
      message.textContent = 'Desenhe sua assinatura antes de finalizar.';
      canvas.focus();
      return;
    }
    hidden.value = canvas.toDataURL('image/png');
    document.getElementById('confirm-signature').disabled = true;
  });
})();
