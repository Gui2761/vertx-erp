document.addEventListener('DOMContentLoaded',()=>{
  const toggle=document.querySelector('[data-menu-toggle]');
  const menu=document.querySelector('#public-menu');
  if(toggle&&menu){
    const setMenu=open=>{toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Fechar menu':'Abrir menu');menu.classList.toggle('is-open',open);};
    toggle.addEventListener('click',()=>setMenu(toggle.getAttribute('aria-expanded')!=='true'));
    menu.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>setMenu(false)));
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){const mobileWasOpen=toggle.getAttribute('aria-expanded')==='true';setMenu(false);if(mobileWasOpen)toggle.focus();}});
    matchMedia('(min-width:1101px)').addEventListener('change',event=>{if(event.matches)setMenu(false)});
  }
  const form=document.querySelector('.demo-form');
  if(form)form.addEventListener('submit',event=>{
    if(!form.checkValidity())return;
    const button=event.submitter;if(button){button.setAttribute('aria-busy','true');button.textContent='Enviando solicitação…';}
  });
});
