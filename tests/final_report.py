"""Consolida a validação local da central; exclui credenciais, cookies e logs."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
validation=root/'tmp/validation'
def suite(name):
    text=(validation/name).read_text(encoding='utf-8-sig')
    match=re.search(r'Ran (\d+) tests in ([\d.]+)s\s+OK(?: \(skipped=(\d+)\))?',text)
    assert match and 'FAILED (' not in text,name
    count,skipped=int(match[1]),int(match[3] or 0)
    return {'resultado':'PASS','testes':count,'aprovados':count-skipped,'ignorados':skipped,'segundos':float(match[2])}
postgres=suite('planning-postgresql-tests.log')
sqlite=suite('planning-sqlite-tests.log')
assert postgres['testes']==sqlite['testes']==258
assert postgres['ignorados']==0 and sqlite['ignorados']==12
browser=json.loads((validation/'planning-browser-result.json').read_text())
responsive=json.loads((validation/'planning-responsive-result.json').read_text())
assert responsive['passed'] and responsive['noClippedNote'] and responsive['unknownDurationLabelBounds']
assert browser['passed'] and browser['noJavascriptErrors'] and browser['noHttp500']
assert browser['viewports']==[320,390,768,1365] and browser['fullHD']==[1920,1080]
for name in ['planning-original-modules.log','planning-stock-regression.log','planning-original-browser-a.log','planning-original-browser-b.log','planning-probe-a.log','planning-probe-b.log','planning-cross-isolation.log']:
    assert 'PASS' in (validation/name).read_text(encoding='utf-8-sig'),name
for name,expected in [('planning-check.log','no issues'),('planning-makemigrations.log','No changes detected'),('planning-migrate-plan.log','No planned migration operations'),('planning-collectstatic.log','post-processed')]:
    assert expected in (validation/name).read_text(encoding='utf-8-sig'),name
deploy=(validation/'planning-deploy-check.log').read_text(encoding='utf-8-sig')
assert 'ERRORS:' not in deploy
upgrade=json.loads((validation/'final-upgrade.json').read_text())
assert upgrade['postgresql_upgrade']=='PASS' and upgrade['old_columns_identical']
previous=json.loads((root/'VALIDACAO_FINAL.json').read_text(encoding='utf-8'))
history=previous['historico_previo'] if previous.get('fase')=='CENTRAL_OPERACOES' else previous
result={'data':'2026-10-01','fase':'CENTRAL_OPERACOES','referencia':'vertyx_estoque_gestao.zip',
    'ambiente':'Local isolado; dados sintéticos; PostgreSQL 16.15; HTTPS; Moto S3 TLS; Chromium',
    'producao_acessada':False,'deploy_commit_push':False,'credenciais_alteradas':False,
    'postgresql':postgres,'sqlite':sqlite,'testes_anteriores':208,'testes_novos':50,
    'upgrade':upgrade,'migrations_novas':['contas.0006','platform_core.0004','ordens.0009','operacao.0005'],
    'migrations_anteriores':'Preservadas byte a byte; hashes em AUDITORIA_OPERACOES_ARQUIVOS.json',
    'schema':'Sem novas tabelas/modelos de atividade; término previsto e preferências adicionais; FK técnico existente passa a aceitar NULL',
    'inventario':{'modelos_concretos':68,'rotas':393,'relatorios_globais_preservados':31,'relatorio_compras_por_snapshot_preservado':True},
    'central_browser':browser,
    'responsividade_final':responsive,
    'regressoes_browser':{'modulos_anteriores':{'resultado':'PASS','telas':27,'larguras':[320,390,768,1365]},'estoque_compras_gestao':{'resultado':'PASS','telas':17,'larguras':[320,390,768,1365]},'atendimento_original':{'resultado':'PASS','empresas':2,'gps_simulado_e_negado_foto_conferencia_assinatura_pdf':True},'integridade_s3':{'foto_assinatura_snapshot_pdf':'PASS'},'isolamento_http':{'resultado':'PASS','tentativas':8,'status':404,'recursos':['OS','foto','assinatura','PDF']}},
    'permissoes':{'planejamento':'ADMIN/GESTOR/PLANEJADOR/ATENDIMENTO; TÉCNICO somente próprias atividades','tv':'Grant explícito por membership/ERP/organização, default False','conta_tv':'PAINEL, sem acesso aos demais módulos','financeiro_estoque_ampliados':False,'isolamento_entre_organizacoes':'PASS','revogacao_por_consulta':'PASS'},
    'tv':{'polling_autenticado':True,'intervalos_segundos':[15,30,60],'padrao_segundos':30,'sem_recarga_completa':True,'sem_servico_adicional':True,'temas':['CLARO','ESCURO'],'fullscreen_e_rotacao_paginas':True,'dto_privacidade':'Campos operacionais explícitos, sem textos livres/documentos/CPF/contatos/endereço/custos/valores'},
    'checks':{'django':'PASS','makemigrations_check_dry_run':'No changes detected','migrate_plan':'No planned migration operations','collectstatic':'PASS','deploy_debug_false':{'erros':0,'avisos':['security.W005','security.W021'],'motivo':'Configuração HSTS subdomínios/preload preservada; depende do domínio real'}},
    'render_yaml':'Preservado byte a byte; Web plan free; nenhuma ativação ou credencial modificada',
    'automacao_estoque':'Mecanismo anterior preservado; AUTOMACAO_ESTOQUE.md',
    'revisao_visual':'Central, painel lateral, TV escura/clara Full HD e agenda técnica móvel inspecionados',
    'limites':['Validação local; aparelhos/infraestrutura reais não homologados nesta fase','Sem duração informada não se presume ocupação futura','Geradores legados de preventivas preservam regras; central destaca seus conflitos','Sem drag-and-drop, GPS contínuo ou ponto/RH','Ativação externa do runner de estoque permanece pendente'],
    'documentacao':'CENTRAL_OPERACOES.md','historico_previo':history}
(root/'VALIDACAO_FINAL.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'postgresql':postgres['aprovados'],'sqlite':sqlite['aprovados'],'skipped':sqlite['ignorados'],'new_tests':50,'output':'VALIDACAO_FINAL.json'}))
