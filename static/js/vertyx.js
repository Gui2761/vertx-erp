if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
/* Comportamentos compartilhados; nenhum dado empresarial é guardado em cache. */
document.addEventListener('DOMContentLoaded',()=>{
  const sidebar=document.querySelector('[data-sidebar-toggle]');
  if(sidebar){
    const apply=(collapsed)=>{document.body.classList.toggle('vx-sidebar-collapsed',collapsed);sidebar.setAttribute('aria-expanded',String(!collapsed));sidebar.setAttribute('aria-label',collapsed?'Expandir menu lateral':'Recolher menu lateral');};
    try{apply(localStorage.getItem('vertyx.sidebarCollapsed')==='true');}catch{}
    sidebar.addEventListener('click',()=>{const collapsed=!document.body.classList.contains('vx-sidebar-collapsed');apply(collapsed);try{localStorage.setItem('vertyx.sidebarCollapsed',String(collapsed));}catch{}});
  }
  document.querySelectorAll('.navbar-nav a').forEach(a=>{if(a.pathname===location.pathname)a.setAttribute('aria-current','page');});
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
