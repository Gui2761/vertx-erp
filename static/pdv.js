(() => {
  const form = document.getElementById('pdv-pagamento');
  form?.addEventListener('submit', () => {
    const payments = [...document.querySelectorAll('.pagamento-linha')].filter(row => row.querySelector('.forma').value).map(row => {
      const result = {forma: row.querySelector('.forma').value, valor: row.querySelector('.valor').value};
      const received = row.querySelector('.recebido').value;
      if (received) result.recebido = received;
      return result;
    });
    document.getElementById('pagamentos').value = JSON.stringify(payments);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'F2') {event.preventDefault(); document.getElementById('codigo')?.focus();}
    if (event.key === 'F4') {event.preventDefault(); document.getElementById('forma-1')?.focus();}
    if (event.key === 'F8' && form) {event.preventDefault(); form.requestSubmit();}
  });
})();
