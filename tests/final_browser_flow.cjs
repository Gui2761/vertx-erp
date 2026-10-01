/* Fluxos adicionais reais; somente banco/storage de ensaio local. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const output=path.resolve(__dirname,'../tmp/validation');
const f=JSON.parse(fs.readFileSync(path.join(output,'final-browser.json'),'utf8'));
assert.ok(['127.0.0.1','localhost'].includes(new URL(f.base_url).hostname));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1365,height:900},acceptDownloads:true});
 const page=await context.newPage(), errors=[];
 page.on('pageerror',e=>errors.push(e.message)); page.on('dialog',dialog=>dialog.accept());
 const goto=async route=>{const response=await page.goto(f.base_url+route);assert.equal(response.status(),200,route)};
 const fill=async(name,value)=>page.locator('#id_'+name).fill(String(value));
 const select=async(name,value)=>page.locator('#id_'+name).selectOption(String(value));
 const save=async(pattern)=>{await page.getByRole('button',{name:'Salvar',exact:true}).click();await page.waitForURL(pattern);assert.equal(await page.locator('.errorlist').count(),0)};
 async function login(username){await goto('/contas/login/');await fill('username',username);await fill('password',f.password);await page.getByRole('button',{name:'Entrar',exact:true}).click();await page.waitForURL('**/vertyx/')}
 await login(f.username);
 const suffix=Date.now();
 await goto('/depositos/novo/');await fill('nome','Depósito '+suffix);await save('**/depositos/*/');const depot=new URL(page.url()).pathname.split('/')[2];
 await goto('/estoque/fornecedores/novo/');await fill('nome','Fornecedor '+suffix);await save('**/estoque/fornecedores/*/');const supplier=new URL(page.url()).pathname.split('/')[3];
 await goto('/estoque/novo/');await fill('sku','FINAL-'+suffix);await fill('descricao','Peça da homologação final');await fill('custo_aquisicao','10');await fill('preco_venda','25');await save('**/estoque/*/');const part=new URL(page.url()).pathname.split('/')[2];
 await goto('/compras/novo/');await select('fornecedor',supplier);await select('deposito',depot);await fill('necessidade','Reposição de teste');await fill('vencimento',f.validade);await save('**/compras/*/');const purchase=new URL(page.url()).pathname;
 await page.getByRole('link',{name:'Adicionar item',exact:true}).click();await select('peca',part);await fill('quantidade','5');await fill('custo_unitario','10');await save('**/compras/*/');
 await page.getByRole('button',{name:'Aprovar compra',exact:true}).click();await page.getByRole('button',{name:'Registrar pedido',exact:true}).click();await page.getByRole('button',{name:'Receber mercadoria',exact:true}).click();await page.getByRole('link',{name:'Ver conta vinculada',exact:true}).waitFor();
 await goto('/vendas/novo/');await select('cliente',f.cliente);await select('deposito',depot);await fill('vencimento',f.validade);await save('**/vendas/*/');const sale=new URL(page.url()).pathname;
 await page.getByRole('link',{name:'Adicionar item',exact:true}).click();await select('peca',part);await fill('quantidade','2');await fill('valor_unitario','25');await fill('desconto','0');await save('**/vendas/*/');await page.getByRole('button',{name:'Confirmar venda',exact:true}).click();await page.getByRole('link',{name:'Ver conta vinculada',exact:true}).waitFor();
 const invoice=await page.getByRole('link',{name:'Ver conta vinculada',exact:true}).getAttribute('href');
 await goto('/estoque/'+part+'/');assert.match(await page.locator('dl').textContent(),/3[,.]000/);
 await goto('/bancos/novo/');await fill('nome','Banco '+suffix);await fill('saldo_inicial','100');await save('**/bancos/*/');const bank=new URL(page.url()).pathname.split('/')[2];
 await goto(invoice);await page.getByRole('link',{name:'Pagamento parcial / com banco',exact:true}).click();await fill('valor','20');await fill('data',f.today);await select('conta',bank);await save('**/financeiro/lancamentos/*/');assert.match(await page.getByRole('heading',{name:/Saldo pendente/}).textContent(),/30[,.]00/);
 await goto('/checklists/novo/');await fill('nome','Checklist '+suffix);await fill('itens','* Verificar segurança\nTestar funcionamento');await save('**/checklists/*/');const checklist=new URL(page.url()).pathname.split('/')[2];
 await goto('/preventivas/novo/');await fill('nome','Plano '+suffix);await select('cliente',f.cliente);await select('equipamentos',f.equipamento);await select('checklist',checklist);await select('tecnico',f.tecnico);await fill('inicio',f.today);await fill('fim',f.end);await save('**/preventivas/*/');const plan=new URL(page.url()).pathname;
 const preventive=page.locator('form[action*="/preventivas/ocorrencias/"]').first();await preventive.locator('select').selectOption(String(f.tecnico));await preventive.getByRole('button',{name:'Gerar OS',exact:true}).click();await page.waitForURL('**/ordens/*/');const order=new URL(page.url()).pathname;assert.equal(await page.getByRole('heading',{name:'Checklist do atendimento',exact:true}).count(),1);
 await goto('/documentos/novo/?cliente='+f.cliente+'&equipamento='+f.equipamento);await fill('titulo','Manual privado '+suffix);await page.locator('#id_arquivo').setInputFiles({name:'manual.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4\n%%EOF')});await page.locator('#id_disponivel_portal').check();await save('**/documentos/*/');const doc=new URL(page.url()).pathname;
 const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'Baixar arquivo autorizado',exact:true}).click()]);await download.saveAs(path.join(output,'final-private-document.pdf'));
 const screens=['/assistencia/','/planejamento/?visao=MES','/planejamento/?visao=SEMANA','/planejamento/?visao=DIA','/tecnico/','/chamados/','/compras/',purchase,'/vendas/',sale,'/bancos/','/bancos/'+bank+'/',invoice,'/bancos/extrato/','/preventivas/',plan,order,'/documentos/',doc,'/fiscal/','/fiscal/novo/','/notificacoes/','/configuracoes/','/clientes/'+f.cliente+'/','/equipamentos/'+f.equipamento+'/','/relatorios/vendas_margem/'];
 for(const width of [320,390,768,1365]){await page.setViewportSize({width,height:900});for(const route of screens){await goto(route);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Overflow '+width+' '+route)}}
 await page.setViewportSize({width:1365,height:900});await goto('/assistencia/');await page.screenshot({path:path.join(output,'final-dashboard-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await goto('/planejamento/');assert.equal(await page.locator('#id_visao').inputValue(),'SEMANA');assert.ok(await page.locator('#id_data').inputValue());await page.screenshot({path:path.join(output,'final-calendar-mobile.png'),fullPage:true});
 await context.clearCookies();await login(f.portal_username);await page.getByRole('link',{name:'Entrar no ERP Assistência',exact:true}).click();await page.waitForURL('**/portal/');assert.ok(!(await page.locator('body').textContent()).includes('RECEITA PRIVADA'));
 await page.getByRole('link',{name:'Abrir chamado',exact:true}).click();await select('cliente',f.cliente);await select('unidade',f.unidade);await select('equipamento',f.equipamento);await fill('titulo','Chamado cliente '+suffix);await fill('descricao','Teste de abertura via portal');await save('**/portal/');await page.screenshot({path:path.join(output,'final-portal-mobile.png'),fullPage:true});
 for(const width of [320,390,768,1365]){await page.setViewportSize({width,height:900});await goto('/portal/');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Portal overflow '+width)}
 assert.deepEqual(errors,[]);await browser.close();
 fs.writeFileSync(path.join(output,'final-browser-result.json'),JSON.stringify({passed:true,screens:screens.length+1,viewports:[320,390,768,1365],purchase,sale,plan,invoice,privateS3UploadDownload:true,portalCustomerIsolation:true,noJavascriptErrors:true}));
 console.log('PASS: compras -> estoque -> pagar; vendas -> estoque -> receber; pagamento parcial com banco; plano -> checklist -> OS; documento privado S3; portal -> chamado; isolamento; 27 telas em quatro larguras; nenhum erro JavaScript.');
})().catch(e=>{console.error(e);process.exit(1)});
