(() => {
  const form = document.getElementById('pdv-pagamento');
  const updateInstallments = row => {
    const kind = row.querySelector('.forma')?.selectedOptions[0]?.dataset.kind;
    const control = row.querySelector('.parcelas-control');
    const installments = row.querySelector('.parcelas');
    if (control) control.hidden = kind !== 'CREDITO';
    if (installments) installments.disabled = kind !== 'CREDITO';
  };
  document.querySelectorAll('.pagamento-linha').forEach(row => {
    row.querySelector('.forma')?.addEventListener('change', () => updateInstallments(row));
    updateInstallments(row);
  });
  form?.addEventListener('submit', () => {
    const payments = [...document.querySelectorAll('.pagamento-linha')].filter(row => row.querySelector('.forma').value).map(row => {
      const result = {forma: row.querySelector('.forma').value, valor: row.querySelector('.valor').value};
      const received = row.querySelector('.recebido').value;
      if (received) result.recebido = received;
      const installments = row.querySelector('.parcelas');
      if (row.querySelector('.forma').selectedOptions[0]?.dataset.kind === 'CREDITO' && installments) result.parcelas = installments.value || '1';
      return result;
    });
    document.getElementById('pagamentos').value = JSON.stringify(payments);
  });
  document.addEventListener('keydown', event => {
    if (document.querySelector('.sv-console')) return;
    if (event.key === 'F2') {event.preventDefault(); document.getElementById('codigo')?.focus();}
    if (event.key === 'F4') {event.preventDefault(); document.getElementById('forma-1')?.focus();}
    if (event.key === 'F8' && form) {event.preventDefault(); form.requestSubmit();}
  });
})();
