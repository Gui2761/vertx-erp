"""Tenant-safe executive dashboard, limited to contracted modules and scope."""
from collections import defaultdict

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_GET

from platform_core.context import current_organization

from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, require_municipal_permission, scoped_queryset
from .public_views import _context


# These are aggregate counts only. They never expose rows, identifiers, patient
# data, amounts, or cross-module data to a user lacking that module's permission.
METRICS = (
    ('Finanças e orçamento', 'orcamento_publico', 'budget.view',
     'rh_municipal.DotacaoOrcamentariaMunicipal', 'Dotações orçamentárias ativas', 'ativa'),
    ('Finanças e orçamento', 'contabilidade_pub', 'accounting.view',
     'rh_municipal.LancamentoContabilMunicipal', 'Registros contábeis da fundação', None),
    ('Finanças e orçamento', 'tesouraria_publica', 'treasury.view',
     'rh_municipal.MovimentacaoTesourariaMunicipal', 'Registros de tesouraria', None),
    ('Compras e contratos', 'compras_publicas', 'compras.view',
     'rh_municipal.SolicitacaoCompra', 'Solicitações de compra', None),
    ('Compras e contratos', 'licitacoes_publicas', 'licitacao.view',
     'rh_municipal.LicitacaoMunicipal', 'Processos licitatórios', None),
    ('Compras e contratos', 'contratos_publicos', 'contract.view',
     'rh_municipal.ContratoPublicoMunicipal', 'Contratos cadastrados', None),
    ('Pessoas e ponto', 'rh_municipal', 'rh.view',
     'rh_municipal.Servidor', 'Servidores ativos', 'ativo'),
    ('Pessoas e ponto', 'ponto_digital', 'ponto.report',
     'rh_municipal.PontoServidor', 'Registros de ponto no escopo', None),
    ('Patrimônio e frotas', 'patrimonio', 'patrimonio.view',
     'rh_municipal.BemPatrimonial', 'Bens patrimoniais', None),
    ('Patrimônio e frotas', 'frotas', 'frotas.view',
     'rh_municipal.VeiculoMunicipal', 'Veículos cadastrados', None),
    ('Saúde', 'saude_sus', 'saude.dashboard.view',
     'rh_municipal.AtendimentoSaudeMunicipal', 'Atendimentos (total agregado)', None),
    ('Tributação', 'tributos_municipais', 'arrecadacao.view',
     'rh_municipal.PagamentoArrecadacaoMunicipal', 'Registros de arrecadação', None),
    ('Processos', 'processo_digital', 'process.view',
     'rh_municipal.ProcessoDigitalMunicipal', 'Processos digitais cadastrados', None),
)


@login_required
@require_GET
def executive_dashboard(request):
    """Show only tenant and organizational-scope aggregates the user may see."""
    if not has_municipal_permission(request.user, 'dashboard.view'):
        raise PermissionDenied('Acesso ao painel municipal não autorizado.')
    require_municipal_permission(request.user, 'executive.dashboard.view')

    organization = current_organization()
    groups = defaultdict(list)
    for group, module, capability, model_label, label, active_field in METRICS:
        if not public_module_available(organization, module):
            continue
        if not has_municipal_permission(request.user, capability, module=module):
            continue
        model = apps.get_model(model_label)
        queryset = model.objects.filter(organization=organization)
        if active_field:
            queryset = queryset.filter(**{active_field: True})
        queryset = scoped_queryset(request.user, queryset)
        groups[group].append({'label': label, 'value': queryset.count()})

    response = render(request, 'rh_municipal/phase_k_executive_dashboard.html', _context(
        request, metric_groups=list(groups.items()), has_metrics=bool(groups),
    ))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
