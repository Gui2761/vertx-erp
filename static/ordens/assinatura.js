'use strict';
(() => {
  const canvas = document.getElementById('signature-canvas');
  if (!canvas) return;
  const context = canvas.getContext('2d');
  const form = document.getElementById('os-sign-form');
  const hidden = document.getElementById('id_imagem');
  const message = document.getElementById('signature-message');
  const techCanvas = document.getElementById('technician-signature-canvas');
  let techInk = false, techDrawing = false, techPointer = null;
  if (techCanvas) {
    const ctx = techCanvas.getContext('2d');
    ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.strokeStyle = '#102d42';
    const pointTech = e => { const r=techCanvas.getBoundingClientRect(); return [(e.clientX-r.left)*techCanvas.width/r.width,(e.clientY-r.top)*techCanvas.height/r.height]; };
    const clearTech = () => { ctx.fillStyle='#fff'; ctx.fillRect(0,0,techCanvas.width,techCanvas.height); techInk=false; techDrawing=false; document.getElementById('id_imagem_tecnico').value=''; };
    clearTech();
    techCanvas.addEventListener('pointerdown',e=>{ if(!e.isPrimary || (e.pointerType==='mouse' && e.button!==0)) return; e.preventDefault(); techPointer=e.pointerId; techCanvas.setPointerCapture(e.pointerId); techDrawing=true; ctx.beginPath(); ctx.moveTo(...pointTech(e)); });
    techCanvas.addEventListener('pointermove',e=>{if(!techDrawing || e.pointerId!==techPointer)return;e.preventDefault();ctx.lineTo(...pointTech(e));ctx.stroke();techInk=true;});
    ['pointerup','pointercancel','lostpointercapture'].forEach(t=>techCanvas.addEventListener(t,()=>{techDrawing=false;techPointer=null;}));
    document.getElementById('clear-technician-signature').addEventListener('click',clearTech);
  }
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
    if (techCanvas && techInk) document.getElementById('id_imagem_tecnico').value=techCanvas.toDataURL('image/png');
    document.getElementById('confirm-signature').disabled = true;
  });
})();
