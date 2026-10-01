/* Ensaio real dos módulos em Chromium, somente contra localhost. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'tmp', 'validation');
const f = JSON.parse(fs.readFileSync(path.join(output, 'modules-browser.json'), 'utf8'));
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(f.base_url).hostname));
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE});
  const context = await browser.newContext({ignoreHTTPSErrors: true, viewport: {width: 1365, height: 900}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function goto(url) {
    const response = await page.goto(f.base_url + url);
    assert.equal(response.status(), 200, url);
  }
  async function fill(name, value) { await page.locator('#id_' + name).fill(String(value)); }
  async function select(name, value) { await page.locator('#id_' + name).selectOption(String(value)); }
  async function save(pattern) {
    await page.getByRole('button', {name: 'Salvar', exact: true}).click();
    await page.waitForURL(pattern);
    assert.equal(await page.locator('.errorlist').count(), 0);
  }
  async function download(label, file) {
    const [fileDownload] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', {name: label, exact: true}).click()]);
    await fileDownload.saveAs(path.join(output, file));
  }
  await goto('/contas/login/');
  await fill('username', f.username); await fill('password', f.password);
  await page.getByRole('button', {name: 'Entrar', exact: true}).click();
  await page.waitForURL('**/vertyx/');
  await page.getByRole('link', {name: 'Entrar no ERP Assistência'}).click();
  await page.waitForURL('**/assistencia/');
  for (const label of ['Planejamento', 'Peças e Estoque', 'Orçamentos', 'Contratos', 'Financeiro', 'Relatórios']) {
    assert.equal(await page.getByRole('link', {name: label, exact: true}).count(), 1);
    assert.equal(await page.getByRole('link', {name: label, exact: true}).evaluate(el => el.classList.contains('disabled')), false);
  }
  const suffix = Date.now();
  await goto('/estoque/novo/');
  await fill('sku', 'BROWSER-' + suffix); await fill('descricao', 'Fonte do ensaio');
  await fill('estoque_minimo', '2'); await fill('custo_aquisicao', '10'); await fill('preco_venda', '25');
  await save('**/estoque/*/');
  const part = Number(new URL(page.url()).pathname.split('/')[2]);
  await page.getByRole('link', {name: 'Movimentar', exact: true}).click();
  await select('tipo', 'ENTRADA'); await fill('quantidade', '10'); await fill('observacao', 'Entrada sintética do ensaio');
  await save('**/estoque/*/');
  assert.match(await page.locator('dl').textContent(), /10[,.]000/);
  await goto('/orcamentos/novo/');
  await select('cliente', f.cliente); await select('unidade', f.unidade); await select('equipamento', f.equipamento);
  await fill('validade', f.validade); await fill('diagnostico', 'Fonte defeituosa'); await fill('servicos', 'Reparar e testar');
  await fill('condicoes_pagamento', 'Após execução');
  await save('**/orcamentos/*/');
  const quotePath = new URL(page.url()).pathname;
  await page.getByRole('link', {name: 'Adicionar item', exact: true}).click();
  await select('tipo', 'SERVICO'); await fill('descricao', 'Reparo técnico'); await fill('quantidade', '1'); await fill('valor_unitario', '100');
  await save('**/orcamentos/*/');
  await page.getByRole('link', {name: 'Adicionar item', exact: true}).click();
  await select('tipo', 'PECA'); await select('peca', part); await fill('descricao', 'Fonte de reposição'); await fill('quantidade', '2'); await fill('valor_unitario', '25');
  await save('**/orcamentos/*/');
  await download('Baixar PDF do orçamento', 'modules-quote.pdf');
  await page.getByRole('button', {name: 'Marcar como enviado', exact: true}).click();
  await page.getByRole('button', {name: 'Aprovar', exact: true}).click();
  await select('tecnico', f.tecnico);
  await page.getByRole('button', {name: 'Converter em OS', exact: true}).click();
  await page.waitForURL('**/ordens/*/');
  const orderPath = new URL(page.url()).pathname;
  await page.getByRole('link', {name: 'Registrar utilização / devolução de peça', exact: true}).click();
  await select('peca', part); await fill('quantidade', '2');
  await save('**/estoque/*/');
  assert.match(await page.locator('dl').textContent(), /8[,.]000/);
  await goto('/contratos/novo/');
  await fill('numero', 'CT-BROWSER-' + suffix); await select('cliente', f.cliente);
  await page.locator('#id_unidades').selectOption([String(f.unidade)]);
  await page.locator('#id_equipamentos').selectOption([String(f.equipamento)]);
  await fill('data_inicial', f.today); await fill('data_final', f.end); await fill('valor', '200'); await fill('quantidade_visitas', '3');
  await save('**/contratos/*/');
  const contractPath = new URL(page.url()).pathname;
  assert.match(await page.locator('body').textContent(), /CT-BROWSER/);
  await page.getByRole('link', {name: 'Abrir planejamento', exact: true}).click();
  assert.equal(await page.getByRole('button', {name: 'Gerar OS preventiva', exact: true}).count() >= 3, true);
  const planning = page.locator('form[action$="/gerar-os/"]').first();
  await planning.locator('select').selectOption(String(f.tecnico));
  await planning.getByRole('button', {name: 'Gerar OS preventiva', exact: true}).click();
  await page.waitForURL('**/ordens/*/');
  await goto(contractPath);
  const invoice = await page.locator('a[href^="/financeiro/lancamentos/"]').first().getAttribute('href');
  await goto(invoice);
  await page.getByRole('button', {name: 'Liquidar integralmente', exact: true}).click();
  await page.getByRole('heading', {name: 'Histórico financeiro', exact: true}).waitFor();
  assert.match(await page.locator('body').textContent(), /LIQUIDADO/);
  await goto('/financeiro/');
  await page.screenshot({path: path.join(output, 'modules-finance-desktop.png'), fullPage: true});
  await goto('/relatorios/pecas_utilizadas/?equipamento=' + f.equipamento);
  assert.match(await page.locator('table').textContent(), /Fonte do ensaio/);
  await download('Exportar CSV', 'modules-parts.csv');
  await download('Baixar PDF', 'modules-parts.pdf');
  assert.ok(fs.readFileSync(path.join(output, 'modules-parts.csv'), 'utf8').includes('BROWSER-' + suffix));
  for (const pdf of ['modules-quote.pdf', 'modules-parts.pdf']) assert.equal(fs.readFileSync(path.join(output, pdf)).subarray(0, 5).toString(), '%PDF-');
  const paths = ['/assistencia/', '/estoque/', '/estoque/novo/', '/estoque/movimentar/', quotePath, '/orcamentos/novo/', contractPath, '/contratos/novo/', '/contratos/planejamento/', '/financeiro/', invoice, '/financeiro/lancamentos/novo/', '/relatorios/', '/relatorios/os_periodo/', orderPath];
  for (const width of [390, 1365]) {
    await page.setViewportSize({width, height: 900});
    for (const route of paths) {
      await goto(route);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `Overflow: ${route} at ${width}`);
    }
  }
  await page.setViewportSize({width: 390, height: 844});
  await goto('/assistencia/');
  await page.locator('.navbar-toggler').click();
  await page.locator('#menuPrincipal.show').waitFor();
  await page.getByRole('link', {name: 'Peças e Estoque', exact: true}).waitFor({state: 'visible'});
  await page.screenshot({path: path.join(output, 'modules-menu-mobile.png'), fullPage: true});
  await page.getByRole('link', {name: 'Peças e Estoque', exact: true}).click();
  await page.screenshot({path: path.join(output, 'modules-stock-mobile.png'), fullPage: true});
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'modules-browser-result.json'), JSON.stringify({passed: true, viewports: [390, 1365], screens: paths.length, quote: quotePath, order: orderPath, contract: contractPath, downloads: ['modules-quote.pdf', 'modules-parts.pdf', 'modules-parts.csv']}));
  await browser.close();
  console.log('PASS: CRUD real; estoque 10 -> 8; orçamento -> OS; contrato -> planejamento -> OS; cobrança -> liquidação; filtros CSV/PDF; menu; 15 telas em mobile/desktop; nenhum erro JavaScript.');
})().catch(error => {console.error(error); process.exit(1);});
