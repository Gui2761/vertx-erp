/* Revisa a apresentação final depois do ajuste de rótulos sem duração. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const output=path.resolve(__dirname,'../tmp/validation'),f=JSON.parse(fs.readFileSync(path.join(output,'planning-browser.json'),'utf8'));
assert.equal(new URL(f.base_url).hostname,'127.0.0.1');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1920,height:1080}}),page=await context.newPage(),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 const goto=async route=>assert.equal((await page.goto(f.base_url+route)).status(),200);
 await goto('/contas/login/');await page.locator('#id_username').fill(f.username);await page.locator('#id_password').fill(f.password);await page.getByRole('button',{name:'Entrar',exact:true}).click();await page.waitForURL('**/vertyx/');
 for(const theme of ['ESCURO','CLARO']){
  await goto('/configuracoes/painel-operacional/');await page.locator('#id_painel_tema').selectOption(theme);await page.getByRole('button',{name:'Salvar',exact:true}).click();await goto('/painel-operacional/');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1&&document.documentElement.scrollHeight<=innerHeight+1),true);
  assert.equal(await page.locator('[data-block="alertas"]').evaluate(el=>el.querySelector('.tv-note').getBoundingClientRect().bottom<=el.getBoundingClientRect().bottom-8),true,'Nota cortada');
  await page.screenshot({path:path.join(output,theme==='ESCURO'?'planning-tv-fullhd.png':'planning-tv-light-fullhd.png'),fullPage:true});
 }
 const routes=['/planejamento/?visao=MES','/planejamento/?modo=LISTA','/planejamento/?modo=TIMELINE','/tecnico/','/painel-operacional/'];
 for(const width of [320,390,768,1365]){
  await page.setViewportSize({width,height:900});
  for(const route of routes){await goto(route);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,width+' '+route);}
  // Ponto às 16:55: o rótulo deve caber sem indicar duração fictícia.
  await page.evaluate(()=>{const bar=document.createElement('span');bar.className='tv-bar point label-before';bar.style.left='99%';bar.textContent='◇';const label=document.createElement('span');label.className='tv-unknown-label';label.textContent='OS sem duração';bar.append(label);document.querySelector('.tv-track').append(bar);});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Rótulo '+width);
 }
 assert.deepEqual(errors,[]);await browser.close();fs.writeFileSync(path.join(output,'planning-responsive-result.json'),JSON.stringify({passed:true,screens:routes.length,viewports:[320,390,768,1365],fullHD:[1920,1080],themes:['ESCURO','CLARO'],noClippedNote:true,unknownDurationLabelBounds:true,noJavascriptErrors:true}));console.log('PASS: apresentação final, quatro larguras, TV clara/escura Full HD e rótulo de duração desconhecida.');
})().catch(error=>{console.error(error);process.exit(1)});
