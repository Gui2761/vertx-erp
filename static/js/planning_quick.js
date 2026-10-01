(() => {
  const values=JSON.parse(document.querySelector('#planning-quick-choices').textContent);
  const customer=document.querySelector('#id_cliente'),unit=document.querySelector('#id_unidade'),equipment=document.querySelector('#id_equipamento');
  const options=(select,rows)=>{const selected=select.value;select.replaceChildren(new Option('---------',''));for(const row of rows)select.add(new Option(row.nome,String(row.id)));if([...select.options].some(option=>option.value===selected))select.value=selected;};
  const updateEquipment=()=>options(equipment,values.equipment.filter(row=>String(row.cliente_id)===customer.value && String(row.unidade_id || '')===unit.value));
  const update=()=>{options(unit,values.units.filter(row=>String(row.cliente_id)===customer.value));updateEquipment();};
  customer.addEventListener('change',update);unit.addEventListener('change',updateEquipment);update();
})();
