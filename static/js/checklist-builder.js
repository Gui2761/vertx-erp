/* Model editing only; executed checklists remain in the existing OS snapshot. */
document.querySelectorAll('[data-checklist-builder]').forEach(function (source) {
  const container = document.createElement('div');
  const rows = document.createElement('div');
  const add = document.createElement('button');
  const kinds = {'': 'Confirmação de execução', BOOLEANO: 'Sim / Não', CONFORMIDADE: 'Conforme / Não conforme', TEXTO: 'Texto', NUMERO: 'Número', MEDICAO: 'Medição', DATA: 'Data', SELECAO: 'Seleção', FOTO: 'Foto da OS', OBSERVACAO: 'Observação'};
  let initial;
  try { initial = JSON.parse(source.value); }
  catch (_) { initial = source.value.split('\n').filter(x => x.trim()).map(x => ({item: x.trim().replace(/^\*\s*/, ''), obrigatorio: x.trim().startsWith('*')})); }
  if (!Array.isArray(initial)) return;
  function sync() {
    source.value = JSON.stringify(Array.from(rows.children).map(function (row) {
      const item = {item: row.querySelector('[data-question]').value, obrigatorio: row.querySelector('[data-required]').checked};
      const kind = row.querySelector('[data-kind]').value;
      if (kind) item.tipo = kind;
      const unit = row.querySelector('[data-unit]').value.trim();
      if (kind === 'MEDICAO' && unit) item.unidade = unit;
      if (kind === 'SELECAO') item.opcoes = row.querySelector('[data-options]').value.split('\n').map(x => x.trim()).filter(Boolean);
      return item;
    }));
  }
  function insert(value) {
    if (rows.children.length >= 100) return;
    const row = document.createElement('fieldset');
    row.className = 'border rounded p-3 mb-3';
    function input(label, tag, attribute) {
      const wrapper = document.createElement('label'); wrapper.className = 'd-block mb-2'; wrapper.append(document.createTextNode(label));
      const control = document.createElement(tag); control.className = 'form-control'; control.setAttribute(attribute, ''); wrapper.append(control); row.append(wrapper); return control;
    }
    const question = input('Pergunta', 'input', 'data-question'); question.value = value.item || ''; question.maxLength = 255;
    const kind = input('Resposta', 'select', 'data-kind');
    Object.entries(kinds).forEach(([key, label]) => { const option = document.createElement('option'); option.value = key; option.textContent = label; kind.append(option); }); kind.value = value.tipo || '';
    const unit = input('Unidade de medição (ex.: °C)', 'input', 'data-unit'); unit.value = value.unidade || ''; unit.maxLength = 40;
    const options = input('Alternativas — uma por linha', 'textarea', 'data-options'); options.value = (value.opcoes || []).join('\n');
    const required = input('Resposta obrigatória', 'input', 'data-required'); required.type = 'checkbox'; required.className = 'form-check-input ms-2'; required.checked = Boolean(value.obrigatorio);
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-sm btn-outline-danger'; remove.textContent = 'Remover pergunta'; remove.addEventListener('click', () => { row.remove(); sync(); }); row.append(remove);
    function toggle() { unit.parentElement.hidden = kind.value !== 'MEDICAO'; options.parentElement.hidden = kind.value !== 'SELECAO'; }
    row.addEventListener('input', sync); kind.addEventListener('change', () => { toggle(); sync(); }); toggle(); rows.append(row);
  }
  initial.forEach(insert);
  add.type = 'button'; add.className = 'btn btn-outline-primary'; add.textContent = 'Adicionar pergunta'; add.addEventListener('click', () => { insert({}); sync(); });
  container.append(rows, add); source.after(container); source.hidden = true; source.form.addEventListener('submit', sync);
});
