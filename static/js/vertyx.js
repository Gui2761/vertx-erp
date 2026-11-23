// Redirecionamento de segurança para apps ou abas abertas no domínio legado do Render
if (window.location.hostname.includes('render.com')) {
  window.location.replace('https://vertyxerp.com.br' + window.location.pathname + window.location.search + window.location.hash);
}

// Auto-atualização transparente e registro de Service Worker
if ('serviceWorker' in navigator && window.isSecureContext) {
  const swUrl = document.body.classList.contains('vx-technician')
    ? '/tecnico/sw.js'
    : location.pathname.startsWith('/pdv/')
    ? '/pdv/sw.js'
    : location.pathname.startsWith('/vendedor/')
    ? '/vendedor/sw.js'
    : '/sw.js';

  navigator.serviceWorker.register(swUrl).then(reg => {
    try { reg.update(); } catch (e) {}

    if (reg.waiting) {
      reg.waiting.postMessage({ type: 'SKIP_WAITING' });
    }

    reg.addEventListener('updatefound', () => {
      const newWorker = reg.installing;
      if (newWorker) {
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            newWorker.postMessage({ type: 'SKIP_WAITING' });
          }
        });
      }
    });
  }).catch(() => {
    const status = document.querySelector('[data-install-status]');
    if (status) status.textContent = 'Não foi possível ativar o service worker. Recarregue com conexão e confira o painel Application do navegador. As vendas continuam exigindo conexão.';
  });

  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!refreshing) {
      refreshing = true;
      window.location.reload();
    }
  });
}
// Capture the install event before DOMContentLoaded; some browsers emit it early.
let vertyxInstallPrompt;
addEventListener('beforeinstallprompt',event=>{
  event.preventDefault();
  vertyxInstallPrompt=event;
  document.querySelectorAll('[data-install]').forEach(button=>{
    button.hidden=false;
    if(button.classList.contains('vx-install-btn')){
      button.classList.remove('d-none');
      button.classList.add('d-flex');
    }
  });
});
/* Comportamentos compartilhados; nenhum dado empresarial é guardado em cache. */
document.addEventListener('DOMContentLoaded',()=>{
  const connection=document.querySelector('[data-connection-status]');
  if(connection){
    const report=()=>{connection.dataset.offline=String(!navigator.onLine);connection.textContent=navigator.onLine?'Conexão disponível. Alterações são confirmadas ao salvar.':'Sem conexão. Nenhuma alteração será enviada ou sincronizada automaticamente. Reconecte antes de salvar.';};
    report();addEventListener('online',report);addEventListener('offline',report);
    document.addEventListener('submit',event=>{if(!navigator.onLine){event.preventDefault();report();connection.scrollIntoView({block:'nearest'});}},true);
  }

  // Banner global de modo offline e persistência de navegação
  const updateGlobalOfflineBanner = () => {
    let banner = document.getElementById('vx-global-offline-banner');
    if (!navigator.onLine) {
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'vx-global-offline-banner';
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#d97706;color:#ffffff;text-align:center;padding:7px 14px;font-size:13px;font-weight:600;box-shadow:0 2px 10px rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;gap:8px;';
        document.body.prepend(banner);
      }
      banner.innerHTML = '<span>📡</span> <span>Modo Offline Ativo · Operando com dados locais salvos em cache. O sistema sincronizará ao reconectar.</span> <a href="/static/pwa/pdv-offline.html" style="color:#fff;text-decoration:underline;margin-left:8px;font-weight:700;">Abrir Caixa Offline</a>';
      banner.style.display = 'flex';
      banner.style.background = '#d97706';
    } else if (banner && banner.style.display !== 'none') {
      banner.style.background = '#059669';
      banner.innerHTML = '<span>✅</span> <span>Conexão Restabelecida! Atualizando informações...</span>';
      setTimeout(() => {
        banner.style.display = 'none';
      }, 2500);
    }
  };

  if (navigator.onLine) {
    sessionStorage.setItem('vx_last_online_url', window.location.href);
  }
  window.addEventListener('online', () => {
    sessionStorage.setItem('vx_last_online_url', window.location.href);
    updateGlobalOfflineBanner();
  });
  window.addEventListener('offline', updateGlobalOfflineBanner);
  if (!navigator.onLine) updateGlobalOfflineBanner();
  const sidebarToggles=document.querySelectorAll('[data-sidebar-toggle]');
  if(sidebarToggles.length){
    const apply=(collapsed)=>{
      document.body.classList.toggle('vx-sidebar-collapsed',collapsed);
      sidebarToggles.forEach(btn=>{
        btn.setAttribute('aria-expanded',String(!collapsed));
        btn.setAttribute('aria-label',collapsed?'Expandir menu lateral':'Recolher menu lateral');
        btn.setAttribute('title',collapsed?'Expandir menu lateral':'Recolher menu lateral (Modo Ícones MarketUP)');
        const icon = btn.querySelector('i');
        if (icon) {
          icon.className = collapsed ? 'bi bi-layout-sidebar-inset-reverse' : 'bi bi-layout-sidebar-inset';
        }
      });
      if(!collapsed){
        document.querySelectorAll('.vx-nav-sublist').forEach(s=>{
          s.style.top='';
          s.style.left='';
        });
      }
    };
    try{apply(localStorage.getItem('vertyx.sidebarCollapsed')==='true');}catch{}
    sidebarToggles.forEach(btn=>{
      btn.addEventListener('click',()=>{
        const collapsed=!document.body.classList.contains('vx-sidebar-collapsed');
        apply(collapsed);
        try{localStorage.setItem('vertyx.sidebarCollapsed',String(collapsed));}catch{}
      });
    });

    // MarketUP Collapsed Dock Flyout Positioning
    const groups = document.querySelectorAll('.vx-nav-group');
    groups.forEach(group=>{
      const sublist = group.querySelector('.vx-nav-sublist');
      const summary = group.querySelector('summary');
      if(summary){
        summary.addEventListener('click', (e)=>{
          if(document.body.classList.contains('vx-sidebar-collapsed')){
            e.preventDefault();
          }
        });
      }
      if(!sublist) return;
      const positionFlyout = ()=>{
        if(!document.body.classList.contains('vx-sidebar-collapsed')) return;
        const rect = group.getBoundingClientRect();
        const subHeight = sublist.offsetHeight || 220;
        let top = rect.top;
        if(top + subHeight > window.innerHeight - 12){
          top = Math.max(12, window.innerHeight - subHeight - 12);
        }
        sublist.style.top = top + 'px';
        sublist.style.left = (rect.right + 6) + 'px';
      };
      group.addEventListener('mouseenter', positionFlyout);
      group.addEventListener('focusin', positionFlyout);
    });

    const navBar = document.querySelector('.vx-nav');
    if (navBar) {
      navBar.addEventListener('scroll', () => {
        if (!document.body.classList.contains('vx-sidebar-collapsed')) return;
        const hovered = document.querySelector('.vx-nav-group:hover');
        if (hovered) {
          const sub = hovered.querySelector('.vx-nav-sublist');
          if (sub) {
            const rect = hovered.getBoundingClientRect();
            const subHeight = sub.offsetHeight || 220;
            let top = rect.top;
            if (top + subHeight > window.innerHeight - 12) {
              top = Math.max(12, window.innerHeight - subHeight - 12);
            }
            sub.style.top = top + 'px';
            sub.style.left = (rect.right + 6) + 'px';
          }
        }
      }, { passive: true });
    }
  }
  const navLinks = Array.from(document.querySelectorAll('.navbar-nav a[href]')).filter(a => {
    const p = a.pathname;
    return p && p !== '#' && !a.classList.contains('vx-back-link') && !a.classList.contains('vx-onboarding-link');
  });
  if (navLinks.length > 0) {
    const curPath = location.pathname;
    const curSearch = location.search;
    let bestLink = null;
    let bestScore = -1;

    navLinks.forEach(a => {
      const p = a.pathname;
      const s = a.search;
      let score = -1;

      if (s) {
        if (p === curPath && curSearch === s) {
          score = 1000 + p.length + s.length;
        }
      } else {
        if (p === curPath) {
          score = 500 + p.length;
        } else if (p !== '/' && p !== '/assistencia/' && p.length > 2 && curPath.startsWith(p)) {
          score = 100 + p.length;
        }
      }

      if (score > bestScore) {
        bestScore = score;
        bestLink = a;
      }
    });

    navLinks.forEach(a => {
      a.classList.remove('active');
      a.removeAttribute('aria-current');
    });

    if (bestLink && bestScore > 0) {
      bestLink.classList.add('active');
      bestLink.setAttribute('aria-current', 'page');
      const details = bestLink.closest('details');
      if (details) { details.open = true; }
    }
  }
  document.querySelectorAll('.sv-bottom a').forEach(a=>{if(a.pathname===location.pathname || (a.pathname==='/pdv/' && location.pathname.startsWith('/pdv/')))a.setAttribute('aria-current','page');});
  if(document.body.classList.contains('vx-seller')&&location.hash==='#abrir-meu-caixa'){const panel=document.getElementById('abrir-meu-caixa');if(panel){panel.open=true;panel.scrollIntoView({block:'center'});}}
  document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
    if(!form.checkValidity())return;
    const button=event.submitter;
    if(button&&!form.classList.contains('os-geo-form')){button.classList.add('vx-loading');button.setAttribute('aria-busy','true');}
  }));
  document.querySelectorAll('[data-confirm]').forEach(button=>button.addEventListener('click',event=>{if(!confirm(button.dataset.confirm))event.preventDefault();}));
  const installButtons = document.querySelectorAll('[data-install]');
  installButtons.forEach(btn => {
    btn.hidden = !vertyxInstallPrompt;
    if (vertyxInstallPrompt && btn.classList.contains('vx-install-btn')) {
      btn.classList.remove('d-none');
      btn.classList.add('d-flex');
    }
    btn.addEventListener('click', async () => {
      if (vertyxInstallPrompt) {
        await vertyxInstallPrompt.prompt();
        vertyxInstallPrompt = null;
        installButtons.forEach(b => {
          b.hidden = true;
          if (b.classList.contains('vx-install-btn')) {
            b.classList.add('d-none');
            b.classList.remove('d-flex');
          }
        });
      }
    });
  });
  const installStatus=document.querySelector('[data-install-status]');
  if(installStatus&&!window.isSecureContext)installStatus.textContent='A instalação exige HTTPS ou localhost. Este endereço não é um contexto seguro.';

  // Pré-carregamento instantâneo inteligente (com debounce de 150ms para evitar rajadas e 429)
  const prefetchedUrls = new Set();
  let hoverTimeout = null;
  const prefetchTarget = (url) => {
    if (!url || prefetchedUrls.has(url) || prefetchedUrls.size > 25) return;
    if (url.includes('/logout') || url.includes('/excluir') || url.includes('/deletar') || (url.includes('?') && url.includes('export='))) return;
    prefetchedUrls.add(url);
    const link = document.createElement('link');
    link.rel = 'prefetch';
    link.href = url;
    document.head.appendChild(link);
  };

  document.addEventListener('mouseover', (e) => {
    const a = e.target.closest('a[href^="/"]');
    if (hoverTimeout) clearTimeout(hoverTimeout);
    if (a && a.href && a.origin === location.origin) {
      hoverTimeout = setTimeout(() => prefetchTarget(a.pathname + a.search), 150);
    }
  }, { passive: true });

  document.addEventListener('mouseout', () => {
    if (hoverTimeout) clearTimeout(hoverTimeout);
  }, { passive: true });

  document.addEventListener('touchstart', (e) => {
    const a = e.target.closest('a[href^="/"]');
    if (a && a.href && a.origin === location.origin) {
      prefetchTarget(a.pathname + a.search);
    }
  }, { passive: true });
});
// bfcache: permite navegação instantânea pelo botão Voltar sem recarregar a tela inteira
addEventListener('pageshow', event => {
  if (event.persisted && sessionStorage.getItem('vx_force_reload')) {
    sessionStorage.removeItem('vx_force_reload');
    location.reload();
  }
});

// Logout/tenant switching lock the offline identity; pending intents are retained.
document.addEventListener('submit',async event=>{
  const form=event.target;
  if(!globalThis.PDVOutbox||form.dataset.pdvIdentityLocked)return;
  // A control named "action" shadows HTMLFormElement.action in commerce forms.
  const action=form.getAttribute('action')||location.pathname;
  if(action.includes('/logout')||action.includes('/organizacao/')){
    event.preventDefault();
    try{await PDVOutbox.state.put('active',null);}catch(_){}
    form.dataset.pdvIdentityLocked='true';form.requestSubmit();
  }
});

// Global Vertyx Theme Management (Dark / Light Mode)
window.getVertyxTheme = function() {
  try {
    return localStorage.getItem('vertyx_theme') || 'dark';
  } catch (e) {
    return 'dark';
  }
};

window.applyVertyxTheme = function(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.setAttribute('data-bs-theme', theme);
  try {
    localStorage.setItem('vertyx_theme', theme);
  } catch (e) {}

  document.querySelectorAll('.vx-theme-toggle-btn').forEach(btn => {
    const label = btn.querySelector('.vx-theme-label');
    if (label) {
      label.textContent = theme === 'dark' ? 'Modo Claro' : 'Modo Escuro';
    }
  });

  window.dispatchEvent(new CustomEvent('vertyxThemeChanged', { detail: { theme: theme } }));
};

window.toggleVertyxTheme = function() {
  const current = document.documentElement.getAttribute('data-theme') || window.getVertyxTheme();
  const next = current === 'light' ? 'dark' : 'light';
  window.applyVertyxTheme(next);
};

(() => {
  const current = window.getVertyxTheme();
  document.documentElement.setAttribute('data-theme', current);
  document.addEventListener('DOMContentLoaded', () => {
    window.applyVertyxTheme(window.getVertyxTheme());
  });
})();

// Instant Navigation: Hover/Touch Prefetching
(function() {
  const prefetched = new Set();
  function prefetchUrl(url) {
    if (!url || prefetched.has(url) || url.startsWith('javascript:') || url.startsWith('#')) return;
    try {
      const parsed = new URL(url, location.origin);
      if (parsed.origin !== location.origin) return;
      if (parsed.pathname.includes('/logout') || parsed.pathname.includes('/organizacao/')) return;
      prefetched.add(url);
      const link = document.createElement('link');
      link.rel = 'prefetch';
      link.href = url;
      link.as = 'document';
      document.head.appendChild(link);
    } catch(e) {}
  }

  document.addEventListener('mouseover', function(e) {
    const a = e.target.closest('a[href]');
    if (a && a.href) prefetchUrl(a.href);
  }, { passive: true });

  document.addEventListener('touchstart', function(e) {
    const a = e.target.closest('a[href]');
    if (a && a.href) prefetchUrl(a.href);
  }, { passive: true });
})();
