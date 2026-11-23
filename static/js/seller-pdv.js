/* Presentation only. Prices, ownership, discounts and payments are authorized server-side. */
(() => {
  const openDialog=id=>{const dialog=document.getElementById(id);if(dialog&&!dialog.open)dialog.showModal();};
  const focusCode=()=>{const details=document.getElementById('seller-barcode');if(details){details.open=true;document.getElementById('seller-barcode-code').focus();}};
  document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  document.querySelectorAll('[data-open-payment]').forEach(button=>button.addEventListener('click',()=>{openDialog('seller-checkout');document.getElementById('forma-1')?.focus();}));
  document.querySelectorAll('[data-focus-code]').forEach(button=>button.addEventListener('click',focusCode));
  const action=kind=>{
    if(kind==='search'){const sb=document.getElementById('codigo-busca');if(sb){sb.focus();sb.select();}return;}
    if(kind==='advanced'){focusCode();return;}
    if(kind==='cancel'){openDialog('seller-cancel');return;}
    if(kind==='cash'){openDialog('seller-cash-summary');return;}
    const info=document.querySelector('[data-pdv-info]');if(!info)return;
    const text={help:'Busque um produto, ajuste o carrinho e selecione o cliente, se necessário. Finalizar venda abre o pagamento; a venda só é registrada ao confirmar. Códigos exatos podem ser adicionados diretamente. F3 busca, F7 cancela, F8 abre o pagamento e F9 resume seu caixa.',seller:'Esta venda pertence ao vendedor autenticado. A troca de vendedor exige o responsável autorizado; não é possível atribuir sua venda a outra pessoa por esta experiência.',withdraw:'Retiradas e sangrias exigem o responsável autorizado. O vendedor não pode movimentar valores manualmente. Utilize o controle de caixa existente com ADMIN/GESTOR.',supply:'Suprimentos exigem o responsável autorizado no controle de caixa existente. Esta tela preserva as permissões financeiras.'};
    info.textContent=text[kind]||'Operação ainda não disponível.';openDialog('seller-info');
  };
  document.querySelectorAll('[data-pdv-action]').forEach(button=>button.addEventListener('click',()=>action(button.dataset.pdvAction)));
  document.addEventListener('keydown',event=>{
    if(!document.querySelector('.sv-console')||event.ctrlKey||event.altKey||event.metaKey)return;
    const keys={F1:'help',F3:'search',F4:'seller',F5:'advanced',F7:'cancel',F9:'cash',F10:'withdraw',F11:'supply'};
    if(document.querySelector('dialog[open]'))return;
    if(event.key==='F8'){event.preventDefault();document.querySelector('[data-open-payment]:not(:disabled)')?.click();}
    else if(event.key==='F2'){event.preventDefault();location.href='/pdv/#abrir-meu-caixa';}
    else if(event.key==='F6'){event.preventDefault();}
    else if(keys[event.key]){event.preventDefault();action(keys[event.key]);}
  });
  document.querySelectorAll('[data-qty-delta]').forEach(button => button.addEventListener('click', () => {
    const form = button.closest('form'), input = form.querySelector('[name=quantidade]');
    const value = Number(input.value) + Number(button.dataset.qtyDelta);
    if (Number.isFinite(value) && value > 0) { input.value = value.toFixed(3); form.requestSubmit(); }
  }));
  const cents = value => {const number=Number(value);return Number.isFinite(number)?Math.round(number*100):0;};
  const currency = value => (value/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const change = document.querySelector('[data-seller-change]');
  
  // Sincronização das pills visuais de pagamento
  document.querySelectorAll('[data-pill-forma]').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('[data-pill-forma]').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const forma1 = document.getElementById('forma-1');
      if (forma1) {
        forma1.value = pill.dataset.pillForma;
        forma1.dispatchEvent(new Event('change'));
      }
    });
  });

  // Sincronização do tipo de emissão (Cupom Térmico vs NFC-e Fiscal)
  document.querySelectorAll('[data-emission]').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('[data-emission]').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const hidden = document.getElementById('tipo_emissao');
      const btnText = document.getElementById('btn-finalizar-text');
      const kind = pill.dataset.emission;
      if (hidden) hidden.value = kind;
      if (btnText) {
        btnText.textContent = (kind === 'NFCE') ? 'Confirmar Venda e Emitir NFC-e' : 'Confirmar Venda e Emitir Cupom';
      }
    });
  });

  const recalculate = () => {
    let troco = 0;
    const due = cents(document.querySelector('.sv-pdv')?.dataset.total || 0);
    const line1 = document.querySelector('.pagamento-linha');
    if (line1) {
      const forma1 = line1.querySelector('.forma');
      const kind1 = forma1?.selectedOptions[0]?.dataset.kind;
      const valor1 = line1.querySelector('.valor');
      const rec1 = line1.querySelector('.recebido');
      const cashSection = document.getElementById('cash-section-1');
      const installmentControl = line1.querySelector('.parcelas-control');
      const installments = line1.querySelector('.parcelas');

      const additionalLines = [...document.querySelectorAll('.pagamento-linha')].slice(1).filter(r => r.querySelector('.forma')?.value);
      if (!additionalLines.length && valor1) {
        valor1.value = (due / 100).toFixed(2);
      }

      if (cashSection) {
        cashSection.style.display = (kind1 === 'DINHEIRO') ? 'block' : 'none';
      }
      if (installmentControl) {
        installmentControl.hidden = (kind1 !== 'CREDITO');
      }
      if (installments) {
        installments.disabled = (kind1 !== 'CREDITO');
      }

      if (kind1 === 'DINHEIRO' && valor1) {
        const valCents = cents(valor1.value);
        const recCents = cents(rec1?.value);
        if (recCents > valCents) {
          troco = (recCents - valCents);
        }
      }
    }
    if (change) change.textContent = currency(troco);
  };

  document.querySelectorAll('.pagamento-linha input,.pagamento-linha select').forEach(field=>field.addEventListener('input',recalculate));
  document.querySelectorAll('.pagamento-linha select').forEach(field=>field.addEventListener('change',recalculate));
  recalculate();

  const checkout=document.getElementById('pdv-pagamento');
  checkout?.addEventListener('submit',event=>{
    const due=cents(document.querySelector('.sv-pdv').dataset.total);
    const line1 = document.querySelector('.pagamento-linha');
    const valor1 = line1?.querySelector('.valor');
    const forma1 = line1?.querySelector('.forma');
    const rec1 = line1?.querySelector('.recebido');

    const additionalLines = [...document.querySelectorAll('.pagamento-linha')].slice(1).filter(r => r.querySelector('.forma')?.value);
    if (!additionalLines.length) {
      if (valor1) valor1.value = (due / 100).toFixed(2);
      if (forma1?.selectedOptions[0]?.dataset.kind === 'DINHEIRO' && rec1) {
        if (!rec1.value || Number(rec1.value) < Number(valor1.value)) {
          rec1.value = valor1.value;
        }
      }
    }

    const payments=[...document.querySelectorAll('.pagamento-linha')].filter(row=>row.querySelector('.forma').value);
    const total=payments.reduce((sum,row)=>sum+cents(row.querySelector('.valor').value),0);
    if(!payments.length || total!==due){
      event.preventDefault();
      if (change) {
        change.textContent='Os pagamentos devem somar exatamente '+currency(due)+'.';
        change.scrollIntoView({block:'center'});
      }
      return;
    }
    const rows = payments.map(row => {
      const result = { forma: row.querySelector('.forma').value, valor: row.querySelector('.valor').value };
      const received = row.querySelector('.recebido')?.value;
      if (received) result.recebido = received;
      const installments = row.querySelector('.parcelas');
      if (row.querySelector('.forma')?.selectedOptions[0]?.dataset.kind === 'CREDITO' && installments && !installments.disabled) {
        result.parcelas = installments.value;
      }
      return result;
    });
    const pagamentosInput = document.getElementById('pagamentos');
    if (pagamentosInput) {
      pagamentosInput.value = JSON.stringify(rows);
    }
  });
  const scan=document.querySelector('[data-seller-scan]'), video=document.querySelector('[data-scan-video]'), stop=document.querySelector('[data-scan-stop]'), feedback=document.querySelector('[data-scan-feedback]');
  let stream, scanning=false;
  const release=()=>{scanning=false;stream?.getTracks().forEach(track=>track.stop());stream=null;if(video){video.srcObject=null;video.hidden=true;}if(stop)stop.hidden=true;if(scan)scan.disabled=false;};
  stop?.addEventListener('click',()=>{release();feedback.textContent='Câmera encerrada.';});
  scan?.addEventListener('click',async()=>{
    if(!('BarcodeDetector' in window)||!navigator.mediaDevices?.getUserMedia){feedback.textContent='Leitura pela câmera indisponível neste navegador. Digite o código ou use um leitor conectado.';document.getElementById('codigo-busca').focus();return;}
    try{
      release();scan.disabled=true;const detector=new BarcodeDetector({formats:['ean_13','ean_8','code_128','code_39','qr_code','upc_a']});
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});video.srcObject=stream;video.hidden=false;stop.hidden=false;await video.play();scanning=true;
      feedback.textContent='Aponte a câmera para o código. Nenhuma imagem será enviada.';
      const detect=async()=>{if(!scanning)return;try{const codes=await detector.detect(video);if(codes.length){const field=document.getElementById('seller-barcode-code');field.value=codes[0].rawValue;document.getElementById('seller-barcode').open=true;release();field.form.requestSubmit();return;}}catch{release();feedback.textContent='Não foi possível ler o código. Use a busca.';return;}if(scanning)requestAnimationFrame(detect);};detect();
    }catch{release();feedback.textContent='Câmera indisponível ou permissão negada. Use a busca.';}
  });
  addEventListener('pagehide',release);

  // Autocomplete em tempo real para a barra de busca
  const searchForm = document.getElementById('form-busca-pdv');
  const searchInput = document.getElementById('codigo-busca');
  const dropdown = document.getElementById('sv-autocomplete-dropdown');
  const barcodeForm = document.getElementById('seller-barcode-form');
  const barcodeCodeInput = document.getElementById('seller-barcode-code');

  if (searchInput && dropdown) {
    let debounceTimer = null;
    let selectedIndex = -1;
    let currentResults = [];

    const closeDropdown = () => {
      dropdown.hidden = true;
      dropdown.innerHTML = '';
      selectedIndex = -1;
      currentResults = [];
    };

    const addItemDirect = (sku) => {
      if (barcodeForm && barcodeCodeInput) {
        barcodeCodeInput.value = sku;
        barcodeForm.requestSubmit();
      } else {
        searchInput.value = sku;
        searchForm?.requestSubmit();
      }
    };

    const renderResults = (results) => {
      currentResults = results;
      selectedIndex = -1;
      if (!results || results.length === 0) {
        dropdown.innerHTML = '<div class="sv-auto-empty"><i class="bi bi-info-circle me-1"></i> Nenhum produto encontrado. Pressione Enter para buscar.</div>';
        dropdown.hidden = false;
        return;
      }

      dropdown.innerHTML = results.map((item, idx) => `
        <div class="sv-autocomplete-item" data-index="${idx}" data-sku="${item.sku}">
          <div class="sv-auto-info">
            <span class="sv-auto-title" title="${item.descricao}">${item.descricao}</span>
            <div class="sv-auto-meta">
              <span class="sv-auto-code">${item.sku}</span>
              <span>${item.unidade}</span>
              ${item.codigo_barras && item.codigo_barras !== item.sku ? `<span class="text-secondary">EAN: ${item.codigo_barras}</span>` : ''}
            </div>
          </div>
          <div class="sv-auto-actions">
            <span class="sv-auto-price">R$ ${item.preco}</span>
            <span class="sv-auto-stock ${item.tem_estoque ? 'ok' : 'empty'}">
              ${item.tem_estoque ? `Estoque: ${item.disponivel}` : 'Sem estoque'}
            </span>
            <button type="button" class="sv-auto-btn-add" data-add-sku="${item.sku}">
              <i class="bi bi-cart-plus"></i> Add
            </button>
          </div>
        </div>
      `).join('');

      dropdown.hidden = false;

      dropdown.querySelectorAll('.sv-autocomplete-item').forEach(el => {
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          const sku = el.dataset.sku;
          addItemDirect(sku);
        });
      });
    };

    const doSearch = () => {
      const q = searchInput.value.trim();
      if (q.length < 2) {
        closeDropdown();
        return;
      }
      const url = searchForm?.dataset.autocompleteUrl || '/pdv/autocomplete/';
      fetch(`${url}${url.includes('?') ? '&' : '?'}q=${encodeURIComponent(q)}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
      .then(res => res.ok ? res.json() : { results: [] })
      .then(data => renderResults(data.results || []))
      .catch(() => closeDropdown());
    };

    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(doSearch, 200);
    });

    searchInput.addEventListener('keydown', (e) => {
      if (dropdown.hidden || currentResults.length === 0) return;
      const items = dropdown.querySelectorAll('.sv-autocomplete-item');

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % items.length;
        items.forEach((it, i) => it.classList.toggle('active', i === selectedIndex));
        items[selectedIndex]?.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        items.forEach((it, i) => it.classList.toggle('active', i === selectedIndex));
        items[selectedIndex]?.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter') {
        if (selectedIndex >= 0 && selectedIndex < currentResults.length) {
          e.preventDefault();
          addItemDirect(currentResults[selectedIndex].sku);
        } else {
          const val = searchInput.value.trim();
          if (/^\d{6,}$/.test(val)) {
            e.preventDefault();
            addItemDirect(val);
          }
        }
      } else if (e.key === 'Escape') {
        closeDropdown();
      }
    });

    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target) && e.target !== searchInput) {
        closeDropdown();
      }
    });
  }

  window.addEventListener('DOMContentLoaded',()=>{
    if(!document.querySelector('dialog[open]')){
      const bc = document.getElementById('seller-barcode-code');
      if (bc) {
        bc.focus();
      } else {
        const sb = document.getElementById('codigo-busca');
        if (sb) { sb.focus(); if (sb.value) sb.select(); }
      }
    }
  });
})();
