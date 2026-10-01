"""Inventário de schema e rotas, sem ler linhas ou credenciais do banco."""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['DJANGO_SETTINGS_MODULE'] = 'tecnolmed.test_settings'
import django
django.setup()
from django.apps import apps
from django.urls import URLResolver, get_resolver

lines = [
    '# Inventário final — VERTYX', '',
    'Gerado por `tests/final_inventory.py` a partir do registry Django e do resolver.',
    'Não consulta registros, variáveis secretas ou credenciais. Consulte ENTREGA_FINAL.md',
    'e CENTRAL_OPERACOES.md para regras atuais de acesso e AUDITORIA_OPERACOES_ARQUIVOS.json para o diff.', '',
    'Os modelos empresariais usam Organization/contexto tenant. Identidades, catálogo',
    'ERP e tabelas internas Django são globais; memberships/grants delimitam acesso.',
    'Tabelas intermediárias automáticas de relações M2M não aparecem como modelos',
    'independentes. O Django Admin exige o operador autorizado da plataforma.', '',
    '## Modelos e campos', '',
]
model_count = 0
for config in apps.get_app_configs():
    models = list(config.get_models())
    if not models:
        continue
    lines += [f'### {config.label}', '']
    for model in models:
        model_count += 1
        lines += [f'#### {model._meta.label} — tabela `{model._meta.db_table}`', '',
                  '| Campo | Tipo | Relacionamento |', '|---|---|---|']
        for field in [*model._meta.fields, *model._meta.many_to_many]:
            relation = field.related_model._meta.label if field.is_relation and field.related_model else '—'
            lines.append(f'| `{field.name}` | {field.get_internal_type()} | {relation} |')
        lines.append('')

routes = []
def visit(patterns, prefix='', namespace=''):
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            child_namespace = namespace + (pattern.namespace + ':' if pattern.namespace else '')
            visit(pattern.url_patterns, route, child_namespace)
        else:
            routes.append((route, namespace + pattern.name if pattern.name else '—'))
visit(get_resolver().url_patterns)
lines += ['## URLs registradas', '',
          'Padrões com `<int:pk>`/`<str:action>` são resolvidos dinamicamente.',
          'A presença da rota não concede permissão; decorators, serviços, middleware',
          'e contexto da organização aplicam as regras do módulo.', '',
          '| Rota | Nome |', '|---|---|']
for route, name in routes:
    lines.append(f'| `/{route}` | `{name}` |')
lines += ['', f'Totais: {model_count} modelos concretos; {len(routes)} padrões de URL.', '',
          '## Estoque e automação', '',
          'LoteEstoque e MovimentacaoLote detalham Peca/Movimentacao/SaldoDeposito existentes.',
          'ReservaEstoque compromete disponibilidade; OcorrenciaEstoque preserva ciclos e resolução.',
          'RelatorioEstoque/ItemRelatorioEstoque guardam snapshots e geram Compra/ItemCompra atuais.',
          'Comando: `processar_estoque [--organization SLUG] [--loop] [--poll-seconds 30]`.',
          'Comando anterior `atualizar_alertas --organization SLUG` preservado.',
          'Scheduler: operacao/stock_scheduler.py; serviços: operacao/stock.py.',
          'Runner local: serviço estoque_runner no Docker Compose; Render: AUTOMACAO_ESTOQUE.md.',
          'Gestão: operacao/executive.py/navigation.py; Assistência técnica preservada.', '']
lines += ['## Central de operações e TV', '', 'Planejamento reutiliza OrdemServico, PreventivaProgramada e AgendaPreventiva.', 'Views/forms/serviços: operacao/planning.py, planning_forms.py, planning_services.py.', 'TV: operacao/operational_panel.py; polling GET autenticado e grant explícito.', 'Configuracao guarda blocos/tema/intervalo; MembershipERP guarda permissão de TV.', 'Sem modelo de atividade paralelo; 68 modelos concretos preservados.', 'Detalhes de uso, migrations e limites: CENTRAL_OPERACOES.md.', 'Validação atual e histórico: VALIDACAO_FINAL.json.', '']
(root / 'INVENTARIO_FINAL.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps({'models': model_count, 'routes': len(routes), 'output': 'INVENTARIO_FINAL.md'}))
