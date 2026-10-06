/* Employee and schedule presentation only; backend validates every submitted value. */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-employee-form]');
  if (form) {
    const profiles = JSON.parse(document.getElementById('employee-profiles').textContent);
    const technical = JSON.parse(document.getElementById('employee-technical-data').textContent);
    const field = name => form.elements.namedItem(name);
    const show = (selector, condition) => {
      const element = form.querySelector(selector);
      if (!element) return;
      element.hidden = !condition;
      // Inactive branches must not block native browser form validation.
      element.querySelectorAll('input, select, textarea').forEach(input => {
        if (!('originalRequired' in input.dataset)) input.dataset.originalRequired = String(input.required);
        input.required = condition && input.dataset.originalRequired === 'true';
      });
    };
    const update = () => {
      const newAccount = field('conta_modo').value === 'NOVA';
      const profile = field('perfil')?.value || profiles[field('usuario')?.value]?.perfil;
      show('[data-existing-account]', !newAccount);
      show('[data-new-account]', newAccount);
      show('[data-existing-schedule]', field('jornada_modo').value !== 'NOVA');
      show('[data-new-schedule]', field('jornada_modo').value === 'NOVA');
      show('[data-technical-section]', profile === 'TECNICO');
      const label = form.querySelector('[data-access-profile]');
      if (label) label.textContent = profile ? 'Perfil vinculado: ' + profile : '';
    };
    field('usuario')?.addEventListener('change', () => {
      const selected = field('usuario').value;
      if (field('perfil') && profiles[selected]) field('perfil').value = profiles[selected].perfil;
      if (field('acesso_assistencia') && profiles[selected]) field('acesso_assistencia').checked = profiles[selected].acesso;
      if (technical[selected]) for (const [key, value] of Object.entries(technical[selected])) {
        const input = field('tecnico_' + key);
        if (input) { if (input.type === 'checkbox') input.checked = Boolean(value); else input.value = value ?? ''; }
      }
      update();
    });
    for (const name of ['conta_modo', 'perfil', 'jornada_modo']) field(name)?.addEventListener('change', update);
    update();
  }
  document.querySelectorAll('[data-schedule-editor]').forEach(editor => {
    const rows = [...editor.querySelectorAll('[data-schedule-day]')];
    const updateDay = row => {
      const working = row.querySelector('[data-working-day]').checked;
      row.dataset.working = String(working);
      row.querySelector('[data-day-state]').textContent = working ? '' : 'Folga';
      row.querySelectorAll('[data-schedule-time]').forEach(input => { input.disabled = !working; });
    };
    rows.forEach(row => { row.querySelector('[data-working-day]').addEventListener('change', () => updateDay(row)); updateDay(row); });
    editor.querySelector('[data-apply-weekdays]').addEventListener('click', () => {
      const values = Object.fromEntries([...editor.querySelectorAll('[data-bulk-time]')].map(input => [input.dataset.bulkTime, input.value]));
      const feedback = editor.querySelector('[data-schedule-feedback]');
      if (!values.entrada || !values.saida || Boolean(values.inicio_intervalo) !== Boolean(values.fim_intervalo)) {
        feedback.textContent = 'Informe entrada e saída; quando houver intervalo, preencha os dois horários.';
        return;
      }
      rows.filter(row => Number(row.dataset.scheduleDay) < 5).forEach(row => {
        row.querySelector('[data-working-day]').checked = true;
        row.querySelectorAll('[data-schedule-time]').forEach(input => { input.value = values[input.dataset.scheduleTime]; });
        updateDay(row);
      });
      feedback.textContent = 'Horário aplicado de segunda a sexta. Sábado e domingo mantêm a configuração escolhida.';
    });
  });
});
