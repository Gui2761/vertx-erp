if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
/* Comportamentos compartilhados; nenhum dado empresarial é guardado em cache. */
document.addEventListener('DOMContentLoaded',()=>{
  const connection=document.querySelector('[data-connection-status]');
  if(connection){
    const report=()=>{connection.dataset.offline=String(!navigator.onLine);connection.textContent=navigator.onLine?'Conexão disponível. Alterações são confirmadas ao salvar.':'Sem conexão. Nenhuma alteração será enviada ou sincronizada automaticamente. Reconecte antes de salvar.';};
    report();addEventListener('online',report);addEventListener('offline',report);
    document.addEventListener('submit',event=>{if(!navigator.onLine){event.preventDefault();report();connection.scrollIntoView({block:'nearest'});}},true);
  }
  const sidebar=document.querySelector('[data-sidebar-toggle]');
  if(sidebar){
    const apply=(collapsed)=>{document.body.classList.toggle('vx-sidebar-collapsed',collapsed);sidebar.setAttribute('aria-expanded',String(!collapsed));sidebar.setAttribute('aria-label',collapsed?'Expandir menu lateral':'Recolher menu lateral');};
    try{apply(localStorage.getItem('vertyx.sidebarCollapsed')==='true');}catch{}
    sidebar.addEventListener('click',()=>{const collapsed=!document.body.classList.contains('vx-sidebar-collapsed');apply(collapsed);try{localStorage.setItem('vertyx.sidebarCollapsed',String(collapsed));}catch{}});
  }
  document.querySelectorAll('.navbar-nav a').forEach(a=>{if(a.pathname===location.pathname)a.setAttribute('aria-current','page');});
  document.querySelectorAll('.sv-bottom a').forEach(a=>{if(a.pathname===location.pathname || (a.pathname==='/pdv/' && location.pathname.startsWith('/pdv/')))a.setAttribute('aria-current','page');});
  if(document.body.classList.contains('vx-seller')&&location.hash==='#abrir-meu-caixa'){const panel=document.getElementById('abrir-meu-caixa');if(panel){panel.open=true;panel.scrollIntoView({block:'center'});}}
  document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
    if(!form.checkValidity())return;
    const button=event.submitter;
    if(button&&!form.classList.contains('os-geo-form')){button.classList.add('vx-loading');button.setAttribute('aria-busy','true');}
  }));
  document.querySelectorAll('[data-confirm]').forEach(button=>button.addEventListener('click',event=>{if(!confirm(button.dataset.confirm))event.preventDefault();}));
  let prompt;
  const install=document.querySelector('[data-install]');
  addEventListener('beforeinstallprompt',event=>{event.preventDefault();prompt=event;if(install)install.hidden=false;});
  if(install)install.addEventListener('click',async()=>{if(prompt){await prompt.prompt();prompt=null;install.hidden=true;}});
});
// A restored browser page must reauthorize against the current login/tenant.
addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
