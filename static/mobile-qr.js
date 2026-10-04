(() => {
  const video=document.getElementById('qr-video'), status=document.getElementById('qr-status');
  let stream=null, reading=false;
  const stop=()=>{reading=false;stream?.getTracks().forEach(track=>track.stop());stream=null;video.srcObject=null;};
  const open=value=>{
    let code=value.trim();
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(code)) {
      try {const url=new URL(code,window.location.origin);if(url.origin!==window.location.origin)throw Error();const match=url.pathname.match(/^\/equipamentos\/qr\/([0-9a-f-]{36})\/$/i);if(!match)throw Error();code=match[1];}catch{status.textContent='QR inválido ou de outro ambiente. Informe o UUID do equipamento.';return;}
    }
    stop();window.location.assign('/equipamentos/qr/'+encodeURIComponent(code)+'/');
  };
  document.getElementById('qr-manual').addEventListener('submit',event=>{event.preventDefault();open(document.getElementById('qr-code').value);});
  document.getElementById('qr-stop').addEventListener('click',()=>{stop();status.textContent='Câmera encerrada. Pode usar o código manual.';});
  document.getElementById('qr-camera').addEventListener('click',async()=>{
    stop();
    if(!('BarcodeDetector' in window)||!navigator.mediaDevices?.getUserMedia){status.textContent='Leitor por câmera não suportado neste navegador. Use o UUID ou URL.';return;}
    try{
      const detector=new BarcodeDetector({formats:['qr_code']});
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});video.srcObject=stream;await video.play();reading=true;status.textContent='Aponte para o QR.';
      const scan=async()=>{if(!reading)return;try{const codes=await detector.detect(video);if(codes.length){open(codes[0].rawValue);return;}}catch{status.textContent='Não foi possível ler. Use o código manual.';stop();return;}setTimeout(scan,300);};scan();
    }catch{stop();status.textContent='Câmera negada ou indisponível. Use o código manual.';}
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});window.addEventListener('pagehide',stop);
})();
