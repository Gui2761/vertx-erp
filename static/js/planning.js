(() => {
  'use strict';
  const dialog = document.querySelector('#planning-drawer');
  if (!dialog) return;
  const content = document.querySelector('#drawer-content');
  const title = document.querySelector('#drawer-title');
  const events = JSON.parse(document.querySelector('#planning-events').textContent);
  let controller;
  const node = (tag, value, className) => { const el = document.createElement(tag); if(value !== undefined) el.textContent = value; if(className) el.className = className; return el; };
  function show(data) {
    content.replaceChildren(); title.textContent = data.numero;
    const fields = node('dl', undefined, 'vx-drawer-fields');
    for (const [label,key] of [['Status','status'],['Prioridade','prioridade'],['Cliente','cliente'],['Unidade','unidade'],['Endereço','endereco'],['Equipamento','equipamento'],['Fabricante','fabricante'],['Modelo','modelo'],['Patrimônio','patrimonio'],['Número de série','serie'],['Serviço','tipo'],['Origem','source'],['Contrato','contrato'],['Técnico','tecnico'],['Data e horário','start'],['Término previsto','end'],['SLA','prazo'],['Descrição','descricao']]) {
      const value = data[key]; if (!value && ['endereco','fabricante','modelo','patrimonio','serie','prazo','descricao'].includes(key)) continue;
      const group = node('div'); group.append(node('dt',label),node('dd',value && ['start','end','prazo'].includes(key) ? new Date(value).toLocaleString('pt-BR') : value || 'Não informado')); fields.append(group);
    }
    content.append(fields);
    if(data.late) content.append(node('p','⚠ Atividade atrasada','alert alert-danger'));
    if(data.conflicts?.length) content.append(node('p','⚠ Conflito com '+data.conflicts.join(', '),'alert alert-warning'));
    const actions = node('div',undefined,'vx-drawer-actions');
    for(const [label,url] of [['Abrir OS',data.open_url],['Ver origem preventiva / contrato',data.origin_url],['Reagendar / atribuir / prioridade',data.can_write && data.edit_url],['Iniciar atendimento',data.can_start && data.open_url && data.open_url+'#atendimento']]) {
      if (url) { const link = node('a',label,'btn btn-outline-primary'); link.href=url; actions.append(link); }
    }
    content.append(actions);
    if(data.status_code==='AG_PECA') content.append(node('p','Aguardando peças. Disponibilidade e compras abaixo vêm do estoque atual.','alert alert-warning'));
    if(data.pecas) {
      content.append(node('h3','Peças reservadas','h5'));
      if(!data.pecas.length) content.append(node('p','Nenhuma reserva vinculada. Descrições manuais não indicam saldo ou reserva.'));
      for(const part of data.pecas) content.append(node('p',`${part.sku} · ${part.produto}\nDepósito: ${part.deposito}\nReservado nesta OS: ${part.reservado_os} · Disponível: ${part.disponivel} · Em compra: ${part.em_compra}`,'vx-drawer-stock'));
    }
  }
  document.addEventListener('click',async event => {
    const button=event.target.closest('[data-order-url],[data-preventive]'); if(!button) return;
    controller?.abort(); controller=new AbortController();
    content.replaceChildren(node('p','Carregando atividade…')); if(!dialog.open) dialog.showModal();
    if(button.dataset.preventive) { const data=events.find(row=>row.kind+'-'+row.id===button.dataset.preventive); if(data) show(data); else content.replaceChildren(node('p','Atividade fora do período. Abra o dia correspondente.')); return; }
    try { const response=await fetch(button.dataset.orderUrl,{signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}}); if(!response.ok) throw new Error('Não foi possível carregar a OS. Acesso ou sessão indisponível.'); show(await response.json()); }
    catch(error) { if(error.name!=='AbortError') content.replaceChildren(node('p',error.message,'alert alert-danger')); }
  });
  document.querySelector('[data-close-drawer]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>controller?.abort());
})();
