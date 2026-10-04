(() => {
  const button = document.getElementById('ponto-localizar');
  button?.addEventListener('click', () => {
    const status = document.getElementById('geo-status');
    if (!document.getElementById('geo-consent').checked) {status.textContent = 'Autorize esta coleta para obter localização.'; return;}
    if (!navigator.geolocation) {status.textContent = 'Localização indisponível. Registre sem localização.'; return;}
    navigator.geolocation.getCurrentPosition(position => {
      document.getElementById('latitude').value = position.coords.latitude.toFixed(6);
      document.getElementById('longitude').value = position.coords.longitude.toFixed(6);
      status.textContent = 'Localização obtida somente para esta marcação.';
    }, () => {status.textContent = 'Localização negada ou indisponível. Pode registrar sem localização.';}, {timeout: 10000, maximumAge: 0});
  });
  document.getElementById('geo-consent')?.addEventListener('change', event => {
    if (!event.target.checked) {document.getElementById('latitude').value='';document.getElementById('longitude').value='';}
  });
})();
