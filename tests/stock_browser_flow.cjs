/* Ensaio real de estoque e Gestão em Chromium, exclusivamente localhost. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),output=path.join(root,'tmp/validation');
let f=JSON.parse(fs.readFileSync(path.join(output,'stock-browser.json'),'utf8'));
assert.ok(['127.0.0.1','localhost'].includes(new URL(f.base_url).hostname));
const python=path.resolve(root,'../.venv/Scripts/python.exe');
const run=mode=>execFileSync(python,[path.join(__dirname,'stock_browser_fixture.py'),mode],{cwd:root,encoding:'utf8'});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1365,height:900},acceptDownloads:true});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept());
 const goto=async route=>{const response=await page.goto(f.base_url+route);assert.equal(response.status(),200,route)};
 const fill=async(name,value)=>page.locator('#id_'+name).fill(String(value));
 const select=async(name,value)=>page.locator('#id_'+name).selectOption(String(value));
 const save=async pattern=>{await page.getByRole('button',{name:'Salvar',exact:true}).click();await page.waitForURL(pattern);assert.equal(await page.locator('.errorlist').count(),0)};
 async function login(username){await context.clearCookies();await goto('/contas/login/');await fill('username',username);await fill('password',f.password);await page.getByRole('button',{name:'Entrar',exact:true}).click();await page.waitForURL('**/vertyx/')}
 await login(f.username);
 for(const [number,date,quantity] of [['PROXIMO',f.dates.near,1],['DISTANTE',f.dates.far,10],['VENCIDO',f.dates.expired,1]]){
   await goto('/estoque/lotes/entrada/');await select('peca',f.part);await select('deposito',f.depot);await fill('numero',number);await fill('validade',date);await fill('quantidade',quantity);await select('fornecedor',f.supplier);await fill('custo_unitario','12.50');await fill('localizacao','Prateleira A');await fill('documento_entrada','NF de ensaio');await fill('motivo','Homologação de múltiplos lotes');await save('**/estoque/lotes/');
 }
 await goto('/vendas/novo/');await select('cliente',f.cliente);await select('deposito',f.depot);await fill('vencimento',f.today);await save('**/vendas/*/');const sale=new URL(page.url()).pathname;
 await page.getByRole('link',{name:'Adicionar item',exact:true}).click();await select('peca',f.part);await fill('quantidade','1');await fill('valor_unitario','20');await fill('desconto','0');await save('**/vendas/*/');await page.getByRole('button',{name:'Confirmar venda',exact:true}).click();await page.getByRole('link',{name:'Ver conta vinculada',exact:true}).waitFor();
 await goto('/estoque/reservas/');await page.locator('summary').filter({hasText:'Reservar produto'}).click();await select('peca',f.part);await select('deposito',f.depot);await fill('quantidade','4');await fill('motivo','Separação operacional autorizada');await page.getByRole('button',{name:'Reservar estoque',exact:true}).click();await page.waitForURL('**/estoque/reservas/');
 run('tick');f=JSON.parse(fs.readFileSync(path.join(output,'stock-browser.json'),'utf8'));
 await goto('/assistencia/');assert.ok((await page.locator('body').textContent()).includes('PRODUTOS PRECISAM DE REPOSIÇÃO'));
 await page.locator('[data-sidebar-toggle]').click();assert.equal(await page.locator('[data-sidebar-toggle]').getAttribute('aria-expanded'),'false');await page.reload();assert.equal(await page.locator('[data-sidebar-toggle]').getAttribute('aria-expanded'),'false');await page.locator('[data-sidebar-toggle]').click();
 await goto('/estoque/relatorios/'+f.report+'/');assert.equal(await page.locator('#id_quantidade_'+f.line).inputValue(),'12.000');
 for(const [label,extension] of [['PDF','pdf'],['Excel','xlsx']]){const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:label,exact:true}).click()]);await download.saveAs(path.join(output,'stock-weekly-report.'+extension));}
 await page.locator('#id_selecionar_'+f.line).check();await fill('quantidade_'+f.line,'11');await select('deposito',f.depot);await fill('vencimento',f.validade);await page.getByRole('button',{name:'GERAR SOLICITAÇÃO DE COMPRA',exact:true}).click();assert.deepEqual(await page.locator('.errorlist').allTextContents(),[]);await page.waitForURL('**/compras/*/');const purchase=new URL(page.url()).pathname;
 await page.getByRole('link',{name:'Adicionar cotação de fornecedor',exact:true}).click();await select('fornecedor',f.supplier);await fill('valor','137.50');await fill('validade',f.validade);await fill('prazo','Entrega em 3 dias');await save('**/compras/*/');
 const quotation=await page.locator('#cotacao option').last().getAttribute('value');assert.ok(quotation);await page.locator('#cotacao').selectOption(quotation);await page.getByRole('button',{name:'Aprovar compra',exact:true}).click();await page.getByRole('button',{name:'Registrar pedido',exact:true}).click();
 await page.getByRole('link',{name:'Identificar lote',exact:true}).click();await fill('lote','RECEBIMENTO');await fill('validade',f.dates.received);await fill('documento_entrada','NF de reposição');await save('**/compras/*/');await page.getByRole('button',{name:'Receber mercadoria',exact:true}).click();await page.getByRole('link',{name:'Ver conta vinculada',exact:true}).waitFor();run('verify');
 const screens=['/assistencia/','/assistencia/?periodo=HOJE&grafico=7','/assistencia/?periodo=SEMANA&grafico=3M','/assistencia/?periodo=PERSONALIZADO&inicio='+f.today+'&fim='+f.today+'&grafico=12M','/estoque/','/estoque/'+f.part+'/','/estoque/lotes/?peca='+f.part,'/estoque/lotes/entrada/','/estoque/reservas/','/estoque/ocorrencias/','/estoque/ocorrencias/?historico=1','/estoque/relatorios/','/estoque/relatorios/'+f.report+'/','/configuracoes/estoque-compras/','/compras/sugestoes/',purchase,sale];
 for(const width of [320,390,768,1365]){await page.setViewportSize({width,height:900});for(const route of screens){await goto(route);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Overflow '+width+' '+route)}}
 await page.setViewportSize({width:1365,height:1000});await goto('/assistencia/');await page.screenshot({path:path.join(output,'stock-dashboard-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await goto('/assistencia/');await page.screenshot({path:path.join(output,'stock-dashboard-mobile.png'),fullPage:true});await goto('/estoque/relatorios/'+f.report+'/');await page.screenshot({path:path.join(output,'stock-report-mobile.png'),fullPage:true});
 for(const role of ['GESTOR','ESTOQUE','TECNICO']){
   await login(f.roles[role]);await goto('/assistencia/');const text=await page.locator('body').textContent();
   if(role!=='GESTOR'){assert.ok(!text.includes('Contas e caixa'));assert.ok(!text.includes('Recebimentos do mês'));}
   let response=await page.goto(f.base_url+'/estoque/relatorios/');assert.equal(response.status(),role==='TECNICO'?403:200,role);
   response=await page.goto(f.base_url+'/configuracoes/estoque-compras/');assert.equal(response.status(),403,role);
 }
 assert.deepEqual(errors,[]);await browser.close();
 fs.writeFileSync(path.join(output,'stock-browser-result.json'),JSON.stringify({passed:true,screens:screens.length,viewports:[320,390,768,1365],multipleLots:true,fefo:true,reservations:true,pendingPurchase:true,weeklyReport:true,pdfExcel:true,existingPurchaseQuotationReceipt:true,immutableHistory:true,permissions:true,sidebarCollapse:true,noJavascriptErrors:true}));
 console.log('PASS: lotes -> FEFO -> reserva -> relatório PDF/Excel -> seleção editada -> cotação -> pedido -> recebimento -> pagar; resolução de alerta; histórico preservado; Gestão e permissões; 17 telas em quatro larguras.');
})().catch(error=>{console.error(error);process.exit(1)});
