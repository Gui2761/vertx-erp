from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from platform_core.context import current_organization, tenant_context
from platform_core.models import ERPCatalog, MembershipERP, Organization, OrganizationMembership, PlatformAudit
from platform_core.modules import analytics_level, module_enabled

from .models import (
    AcessoMunicipal, ConviteMunicipal, DepartamentoMunicipal, PerfilPrefeitura, PermissaoMunicipal,
    Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal, PRODUCT_CODE,
)
from .public_forms import AcessoMunicipalForm, ConviteAceiteForm, ConviteMunicipalForm, PerfilPrefeituraForm
from .public_forms import EstruturaItemEdicaoForm, EstruturaPublicaForm, SecretariaEdicaoForm
from .public_services import (
    PUBLIC_PERMISSION_LABELS, accesses_for, assign_municipal_access,
    audit_public, create_municipal_invite, has_municipal_permission,
    initialize_secretary_catalog, INITIAL_SECRETARY_CATALOG,
    municipal_modules, require_municipal_permission, scope_allows, scoped_queryset,
)


def _phase_e_allowed(user, capability, module, record=None):
    from .phase_e_services import public_module_available
    organization = current_organization()
    return public_module_available(organization, module) and has_municipal_permission(
        user, capability, module=module, record=record,
    )


def _context(request, **extra):
    user = request.user
    modules = municipal_modules(user)
    return {
        'organization': current_organization(),
        'profile': PerfilPrefeitura.objects.filter(organization=current_organization()).first(),
        'municipal_accesses': accesses_for(user),
        'municipal_modules': modules,
        'can_health_dashboard': _phase_e_allowed(user, 'saude.dashboard.view', 'saude_sus'),
        'can_health_charts': all(_phase_e_allowed(user, code, 'saude_sus') for code in (
            'saude.records.view', 'saude.patients.view',
        )),
        'can_manage_access': has_municipal_permission(user, 'access.manage'),
        'can_view_access': has_municipal_permission(user, 'access.view'),
        'can_view_structure': has_municipal_permission(user, 'structure.view'),
        'can_view_executive_dashboard': (
            has_municipal_permission(user, 'dashboard.view')
            and has_municipal_permission(user, 'executive.dashboard.view')
        ),
        'can_view_integrations': any(
            has_municipal_permission(user, 'integration.view', module=module)
            for module in ('compras_publicas', 'contabilidade_pub', 'rh_municipal', 'saude_sus')
        ),
        'can_manage_structure': has_municipal_permission(user, 'structure.manage'),
        'can_manage_profile': has_municipal_permission(user, 'profile.manage'),
        'can_invite': has_municipal_permission(user, 'invite.create'),
        'can_revoke_invites': has_municipal_permission(user, 'invite.revoke'),
        'can_access_rh': has_municipal_permission(user, 'rh.access', module='rh_municipal'),
        'can_view_planning': has_municipal_permission(user, 'planning.view', module='planejamento_publico'),
        'can_view_budget': has_municipal_permission(user, 'budget.view', module='orcamento_publico'),
        'can_view_accounting': has_municipal_permission(user, 'accounting.view', module='contabilidade_pub'),
        'can_view_treasury': has_municipal_permission(user, 'treasury.view', module='tesouraria_publica'),
        'can_view_public_purchases': has_municipal_permission(user, 'compras.view', module='compras_publicas'),
        'can_view_public_bids': has_municipal_permission(user, 'licitacao.view', module='licitacoes_publicas'),
        'can_view_public_registry': has_municipal_permission(user, 'price_registry.view', module='registro_precos'),
        'can_view_public_contracts': has_municipal_permission(user, 'contract.view', module='contratos_publicos'),
        'can_view_rh_municipal': has_municipal_permission(user, 'rh.view', module='rh_municipal'),
        'can_view_governance': any(has_municipal_permission(user, capability, module='controle_interno') for capability in (
            'governance.dashboard.view', 'governance.risks.view', 'governance.risks.manage',
            'governance.controls.view', 'governance.controls.manage',
            'governance.findings.view', 'governance.findings.manage', 'governance.findings.close',
            'governance.actions.view', 'governance.actions.manage', 'governance.actions.approve',
            'governance.evidence.view', 'governance.evidence.manage',
        )),
        'can_view_ponto_digital': has_municipal_permission(user, 'ponto.view', module='ponto_digital'),
        'can_register_ponto': has_municipal_permission(user, 'ponto.register', module='ponto_digital') or has_municipal_permission(user, 'servidor.portal', module='ponto_digital'),
        'can_adjust_ponto': has_municipal_permission(user, 'ponto.adjust', module='ponto_digital'),
        'can_approve_ponto': has_municipal_permission(user, 'ponto.approve', module='ponto_digital'),
        'can_view_folha_fundacao': has_municipal_permission(user, 'folha.view', module='rh_municipal'),
        'can_manage_folha_fundacao': has_municipal_permission(user, 'folha.manage', module='rh_municipal'),
        'can_view_patrimonio': has_municipal_permission(user, 'patrimonio.view', module='patrimonio'),
        'can_manage_patrimonio': has_municipal_permission(user, 'patrimonio.manage', module='patrimonio'),
        'can_view_almoxarifado': has_municipal_permission(user, 'almoxarifado.view', module='almoxarifado'),
        'can_manage_almoxarifado': has_municipal_permission(user, 'almoxarifado.manage', module='almoxarifado'),
        'can_view_frotas': has_municipal_permission(user, 'frotas.view', module='frotas'),
        'can_manage_frotas': has_municipal_permission(user, 'frotas.manage', module='frotas'),
        'can_view_processes': _phase_e_allowed(user, 'protocol.view', 'processo_digital') or _phase_e_allowed(user, 'process.view', 'processo_digital'),
        'can_view_transparency': _phase_e_allowed(user, 'transparency.view', 'transparencia'),
        'can_manage_transparency': _phase_e_allowed(user, 'transparency.manage', 'transparencia'),
        'can_publish_transparency': _phase_e_allowed(user, 'transparency.publish', 'transparencia'),
        'can_view_ouvidoria': _phase_e_allowed(user, 'ouvidoria.view', 'ouvidoria') or _phase_e_allowed(user, 'ouvidoria.manage', 'ouvidoria') or _phase_e_allowed(user, 'ouvidoria.respond', 'ouvidoria'),
        'can_view_esic': _phase_e_allowed(user, 'esic.view', 'esic') or _phase_e_allowed(user, 'esic.manage', 'esic') or _phase_e_allowed(user, 'esic.respond', 'esic') or _phase_e_allowed(user, 'esic.appeal', 'esic'),
        'can_view_tributary': any(_phase_e_allowed(user, code, 'tributos_municipais') for code in ('contribuinte.view', 'contribuinte.manage', 'tributo.view', 'tributo.manage', 'arrecadacao.view', 'arrecadacao.manage', 'divida.view', 'divida.manage')),
        'can_manage_tributary': _phase_e_allowed(user, 'contribuinte.manage', 'tributos_municipais') or _phase_e_allowed(user, 'tributo.manage', 'tributos_municipais') or _phase_e_allowed(user, 'arrecadacao.manage', 'tributos_municipais') or _phase_e_allowed(user, 'divida.manage', 'tributos_municipais'),
        'can_view_territory': _phase_e_allowed(user, 'imovel.view', 'gestao_territorial') or _phase_e_allowed(user, 'imovel.manage', 'gestao_territorial'),
        'can_view_nfse': _phase_e_allowed(user, 'nfse.view', 'nfse_municipal') or _phase_e_allowed(user, 'nfse.manage', 'nfse_municipal'),
        'can_view_education': _phase_e_allowed(user, 'educacao.dashboard.view', 'educacao_municipal'),
        'can_manage_education_schools': _phase_e_allowed(user, 'educacao.schools.manage', 'educacao_municipal'),
        'can_manage_education_students': _phase_e_allowed(user, 'educacao.students.manage', 'educacao_municipal'),
        'can_register_education_students': (
            _phase_e_allowed(user, 'educacao.enrollment.manage', 'educacao_municipal')
            and _phase_e_allowed(user, 'educacao.students.manage', 'educacao_municipal')
        ),
        **extra,
    }


def home(request):
    if not request.user.is_authenticated:
        return render(request, 'rh_municipal/public_solution.html')
    if not has_municipal_permission(request.user, 'dashboard.view'):
        return render(request, 'rh_municipal/public_access_denied.html', status=403)
    require_municipal_permission(request.user, 'dashboard.view')
    secretaries = scoped_queryset(request.user, Secretaria.objects.filter(ativo=True)).prefetch_related('departamentos__setores__unidades')
    departments = scoped_queryset(request.user, DepartamentoMunicipal.objects.filter(
        ativo=True, secretaria__ativo=True,
    ))
    sectors = scoped_queryset(request.user, SetorMunicipal.objects.filter(
        ativo=True, departamento__ativo=True, departamento__secretaria__ativo=True,
    ))
    units = scoped_queryset(request.user, UnidadeMunicipal.objects.filter(
        ativo=True, setor__ativo=True, setor__departamento__ativo=True,
        setor__departamento__secretaria__ativo=True,
    ))
    professionals = scoped_queryset(request.user, Servidor.objects.filter(
        ativo=True, secretaria__ativo=True, departamento__ativo=True,
        setor__ativo=True, unidade__ativo=True,
    ))
    accesses = list(accesses_for(request.user))
    visible_accesses = scoped_queryset(request.user, AcessoMunicipal.objects.filter(ativo=True).select_related('membership__user'))
    cards = {
        'secretarias': secretaries.count(),
        'departamentos': departments.count(),
        'setores': sectors.count(),
        'unidades': units.count(),
        'profissionais': professionals.count(),
        'usuarios': visible_accesses.values('membership_id').distinct().count(),
    }
    level = analytics_level(current_organization(), erp_code='gestao-publica') or 'BASICO'
    chart_groups = []
    if has_municipal_permission(request.user, 'dashboard.view'):
        series = [('Unidades por Secretaria', 'unidades')]
        if level in {'AVANCADO', 'COMPLETO'}:
            series.append(('Departamentos por Secretaria', 'departamentos'))
        if level == 'COMPLETO':
            series.append(('Setores por Secretaria', 'setores'))
        for title, kind in series:
            rows = []
            source = {'unidades': UnidadeMunicipal, 'departamentos': DepartamentoMunicipal, 'setores': SetorMunicipal}[kind]
            for secretary in secretaries[:12]:
                relation = {
                    'unidades': 'setor__departamento__secretaria',
                    'departamentos': 'secretaria',
                    'setores': 'departamento__secretaria',
                }[kind]
                count = scoped_queryset(request.user, source.objects.filter(ativo=True, **{relation: secretary})).count()
                rows.append({'name': secretary.nome, 'value': count})
            chart_max = max([row['value'] for row in rows] or [1])
            for row in rows:
                row['percent'] = max(8, int(row['value'] * 100 / chart_max))
            chart_groups.append({'title': title, 'rows': rows})
    pending_invites = None
    if has_municipal_permission(request.user, 'invite.create') or has_municipal_permission(request.user, 'invite.revoke'):
        pending_invites = scoped_queryset(request.user, ConviteMunicipal.objects.filter(
            usado_em__isnull=True, revogado_em__isnull=True, expira_em__gt=timezone.now(),
        )).count()
    module_rows = municipal_modules(request.user)
    module_permissions = {
        'planejamento_publico': ('planning.view', 'planejamento_publico'),
        'orcamento_publico': ('budget.view', 'orcamento_publico'),
        'contabilidade_pub': ('accounting.view', 'contabilidade_pub'),
        'tesouraria_publica': ('treasury.view', 'tesouraria_publica'),
        'compras_publicas': ('compras.view', 'compras_publicas'),
        'licitacoes_publicas': ('licitacao.view', 'licitacoes_publicas'),
        'registro_precos': ('price_registry.view', 'registro_precos'),
        'contratos_publicos': ('contract.view', 'contratos_publicos'),
        'patrimonio': ('patrimonio.view', 'patrimonio'),
        'almoxarifado': ('almoxarifado.view', 'almoxarifado'),
        'frotas': ('frotas.view', 'frotas'),
        'processo_digital': ('process.view', 'processo_digital'),
        'transparencia': ('transparency.view', 'transparencia'),
        'ouvidoria': ('ouvidoria.view', 'ouvidoria'),
        'esic': ('esic.view', 'esic'),
    }
    for row in module_rows:
        if row['code'] == 'rh_municipal':
            row['accessible'] = row['enabled'] and has_municipal_permission(request.user, 'rh.access', module='rh_municipal')
        elif row['code'] in {'processo_digital', 'ouvidoria', 'esic'}:
            row['accessible'] = row['enabled'] and (
                _phase_e_allowed(request.user, 'protocol.view', 'processo_digital')
                or _phase_e_allowed(request.user, 'process.view', 'processo_digital')
                if row['code'] == 'processo_digital' else
                _phase_e_allowed(request.user, f"{row['code']}.view", row['code'])
                or _phase_e_allowed(request.user, f"{row['code']}.manage", row['code'])
                or _phase_e_allowed(request.user, f"{row['code']}.respond", row['code'])
                or row['code'] == 'esic' and _phase_e_allowed(request.user, 'esic.appeal', 'esic')
            )
        elif row['code'] in module_permissions:
            capability, module_code = module_permissions[row['code']]
            row['accessible'] = row['enabled'] and has_municipal_permission(request.user, capability, module=module_code)
        else:
            row['accessible'] = row['enabled']
    from . import phase_a_models as civic
    phase_widgets = []
    phase_definitions = (
        ('planning.view', 'planejamento_publico', 'Planejamento', 'rh_municipal_public:planejamento', civic.ProgramaPlanejamentoMunicipal, 'programa(s)'),
        ('budget.view', 'orcamento_publico', 'Orçamento Público', 'rh_municipal_public:orcamento', civic.DotacaoOrcamentariaMunicipal, 'dotação(ões)'),
        ('accounting.view', 'contabilidade_pub', 'Contabilidade Pública', 'rh_municipal_public:contabilidade', civic.LancamentoContabilMunicipal, 'lançamento(s) preparatório(s)'),
        ('treasury.view', 'tesouraria_publica', 'Tesouraria', 'rh_municipal_public:tesouraria', civic.ContaBancariaMunicipal, 'conta(s) cadastrada(s)'),
    )
    for permission, module_code, label, route, model, unit_label in phase_definitions:
        if has_municipal_permission(request.user, permission, module=module_code):
            phase_widgets.append({
                'label': label, 'url': reverse(route),
                'count': scoped_queryset(request.user, model.objects.all()).count(),
                'unit_label': unit_label,
            })
    from . import phase_b_models as procurement
    from django.db.models import Sum
    procurement_widgets = []
    procurement_summary = {}
    procurement_definitions = (
        ('compras.view', 'compras_publicas', 'Compras', 'rh_municipal_public:compras_module', 'compras', procurement.SolicitacaoCompra, 'solicitação(ões)'),
        ('licitacao.view', 'licitacoes_publicas', 'Licitações e processos', 'rh_municipal_public:licitacoes_module', 'licitacoes', procurement.ProcessoContratacaoMunicipal, 'processo(s)'),
        ('price_registry.view', 'registro_precos', 'Registro de preços', 'rh_municipal_public:registro_precos_module', 'registro-precos', procurement.AtaRegistroPrecosMunicipal, 'ata(s)'),
        ('contract.view', 'contratos_publicos', 'Contratos públicos', 'rh_municipal_public:contratos_module', 'contratos', procurement.ContratoPublicoMunicipal, 'contrato(s)'),
    )
    for permission, module_code, label, route, family, model, unit_label in procurement_definitions:
        if has_municipal_permission(request.user, permission, module=module_code):
            procurement_widgets.append({
                'label': label,
                'url': reverse(route, kwargs={'family': family}),
                'count': scoped_queryset(request.user, model.objects.all()).count(),
                'unit_label': unit_label,
            })
    from . import phase_d_models as phase_d
    phase_d_widgets = []
    phase_d_summary = {}
    phase_d_definitions = (
        ('patrimonio.view', 'patrimonio', 'Patrimônio', 'rh_municipal_public:patrimonio_home', phase_d.BemPatrimonial, 'bem(ns)'),
        ('almoxarifado.view', 'almoxarifado', 'Almoxarifado', 'rh_municipal_public:almoxarifado_home', phase_d.DepositoAlmoxarifadoMunicipal, 'depósito(s)'),
        ('frotas.view', 'frotas', 'Frotas', 'rh_municipal_public:frotas_home', phase_d.VeiculoMunicipal, 'veículo(s)'),
    )
    for permission, module_code, label, route, model, unit_label in phase_d_definitions:
        if has_municipal_permission(request.user, permission, module=module_code):
            rows = scoped_queryset(request.user, model.objects.all())
            phase_d_widgets.append({'label': label, 'url': reverse(route), 'count': rows.count(), 'unit_label': unit_label})
    from . import phase_e_models as phase_e
    phase_e_widgets = []
    phase_e_definitions = (
        ('protocol.view', 'processo_digital', 'Protocolos', 'rh_municipal_public:processes_home', phase_e.ProtocoloMunicipal, 'protocolo(s)'),
        ('process.view', 'processo_digital', 'Processos digitais', 'rh_municipal_public:processes_home', phase_e.ProcessoDigitalMunicipal, 'processo(s)'),
        ('transparency.view', 'transparencia', 'Transparência', 'rh_municipal_public:transparencia_home', phase_e.PublicacaoTransparenciaMunicipal, 'publicação(ões)'),
        ('ouvidoria.view', 'ouvidoria', 'Ouvidoria', 'rh_municipal_public:ouvidoria_home', phase_e.ManifestacaoOuvidoriaMunicipal, 'manifestação(ões)'),
        ('esic.view', 'esic', 'E-SIC', 'rh_municipal_public:esic_home', phase_e.PedidoEsicMunicipal, 'pedido(s)'),
    )
    for permission, module_code, label, route, model, unit_label in phase_e_definitions:
        if has_municipal_permission(request.user, permission, module=module_code):
            phase_e_widgets.append({
                'label': label, 'url': reverse(route),
                'count': scoped_queryset(request.user, model.objects.all()).count(),
                'unit_label': unit_label,
            })
    from . import phase_f_models as phase_f
    phase_f_widgets = []
    phase_f_definitions = (
        ('tributo.view', 'tributos_municipais', 'Tributos e arrecadação', 'rh_municipal_public:tributary_home', phase_f.LancamentoTributarioMunicipal, 'lançamento(s)'),
        ('imovel.view', 'gestao_territorial', 'Gestão territorial', 'rh_municipal_public:territory_home', phase_f.ImovelMunicipal, 'imóvel(is)'),
        ('nfse.view', 'nfse_municipal', 'NFS-e municipal', 'rh_municipal_public:nfse_home', phase_f.NotaServicoMunicipal, 'rascunho(s)'),
    )
    for permission, module_code, label, route, model, unit_label in phase_f_definitions:
        if _phase_e_allowed(request.user, permission, module_code):
            rows = scoped_queryset(request.user, model.objects.filter(organization=current_organization()))
            phase_f_widgets.append({'label': label, 'url': reverse(route), 'count': rows.count(), 'unit_label': unit_label})
    if has_municipal_permission(request.user, 'patrimonio.view', module='patrimonio'):
        assets = scoped_queryset(request.user, phase_d.BemPatrimonial.objects.all())
        phase_d_summary['assets'] = assets.count()
        phase_d_summary['assets_maintenance'] = assets.filter(situacao=phase_d.BemPatrimonial.Situacao.MANUTENCAO).count()
        phase_d_summary['assets_unlocated'] = assets.filter(unidade__isnull=True).count()
        phase_d_summary['asset_inventories_pending'] = scoped_queryset(
            request.user, phase_d.InventarioPatrimonial.objects.filter(status__in=['ABERTO', 'CONFERENCIA']),
        ).count()
    if has_municipal_permission(request.user, 'almoxarifado.view', module='almoxarifado'):
        stock = scoped_queryset(request.user, phase_d.SaldoAlmoxarifadoMunicipal.objects.all())
        phase_d_summary['stock_items'] = stock.count()
        phase_d_summary['stock_critical'] = stock.filter(quantidade__lte=0).count()
        phase_d_summary['material_requests'] = scoped_queryset(
            request.user, phase_d.SolicitacaoMaterialMunicipal.objects.filter(status='PENDENTE'),
        ).count()
    if has_municipal_permission(request.user, 'frotas.view', module='frotas'):
        fleet = scoped_queryset(request.user, phase_d.VeiculoMunicipal.objects.all())
        phase_d_summary['vehicles'] = fleet.count()
        phase_d_summary['vehicles_available'] = fleet.filter(situacao=phase_d.VeiculoMunicipal.Situacao.DISPONIVEL).count()
        phase_d_summary['vehicles_maintenance'] = fleet.filter(situacao=phase_d.VeiculoMunicipal.Situacao.MANUTENCAO).count()
        today = timezone.localdate()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)
        fuel = scoped_queryset(request.user, phase_d.AbastecimentoMunicipal.objects.filter(veiculo__in=fleet))
        maintenance = scoped_queryset(request.user, phase_d.ManutencaoVeiculoMunicipal.objects.filter(veiculo__in=fleet))
        trips = scoped_queryset(request.user, phase_d.ViagemMunicipal.objects.filter(
            veiculo__in=fleet, status=phase_d.ViagemMunicipal.Status.CONCLUIDA,
            retorno_em__isnull=False,
        ))
        fuel_total = ExpressionWrapper(F('quantidade_litros') * F('valor_unitario'), output_field=DecimalField(max_digits=22, decimal_places=2))
        km_total = ExpressionWrapper(F('quilometragem_final') - F('quilometragem_inicial'), output_field=DecimalField(max_digits=20, decimal_places=0))
        def cost_summary(start):
            fuel_cost = fuel.filter(data__date__gte=start).aggregate(value=Sum(fuel_total))['value'] or 0
            repair_cost = maintenance.filter(iniciada_em__gte=start).aggregate(value=Sum('valor'))['value'] or 0
            distance = trips.filter(retorno_em__date__gte=start).aggregate(value=Sum(km_total))['value'] or 0
            total = fuel_cost + repair_cost
            return {
                'fuel': fuel_cost, 'maintenance': repair_cost, 'total': total,
                'km': distance, 'per_km': (total / distance) if distance else None,
            }
        phase_d_summary['fleet_month'] = cost_summary(month_start)
        phase_d_summary['fleet_year'] = cost_summary(year_start)
        phase_d_summary['fleet_docs_expiring'] = scoped_queryset(request.user, phase_d.DocumentoFrotaMunicipal.objects.filter(
            vence_em__range=(timezone.localdate(), timezone.localdate() + timedelta(days=30)),
        )).count()
    if has_municipal_permission(request.user, 'compras.view', module='compras_publicas'):
        purchase_scope = scoped_queryset(request.user, procurement.SolicitacaoCompra.objects.all())
        procurement_summary['pending_requests'] = purchase_scope.filter(status__in=[
            procurement.SolicitacaoCompra.Status.ENVIADA,
            procurement.SolicitacaoCompra.Status.EM_ANALISE,
        ]).count()
    if has_municipal_permission(request.user, 'licitacao.view', module='licitacoes_publicas'):
        process_scope = scoped_queryset(request.user, procurement.ProcessoContratacaoMunicipal.objects.all())
        procurement_summary['active_processes'] = process_scope.exclude(status__in=[
            procurement.ProcessoContratacaoMunicipal.Status.CONCLUIDO,
            procurement.ProcessoContratacaoMunicipal.Status.CANCELADO,
            procurement.ProcessoContratacaoMunicipal.Status.REVOGADO,
            procurement.ProcessoContratacaoMunicipal.Status.FRACASSADO,
        ]).count()
        procurement_summary['published_licitations'] = scoped_queryset(
            request.user, procurement.LicitacaoMunicipal.objects.all(),
        ).count()
    if has_municipal_permission(request.user, 'price_registry.view', module='registro_precos'):
        registry_scope = scoped_queryset(request.user, procurement.AtaRegistroPrecosMunicipal.objects.all())
        procurement_summary['active_atas'] = registry_scope.filter(status=procurement.AtaRegistroPrecosMunicipal.Status.VIGENTE).count()
        procurement_summary['atas_expiring'] = registry_scope.filter(
            status=procurement.AtaRegistroPrecosMunicipal.Status.VIGENTE,
            fim_vigencia__range=(timezone.localdate(), timezone.localdate() + timedelta(days=60)),
        ).count()
    if has_municipal_permission(request.user, 'contract.view', module='contratos_publicos'):
        contract_scope = scoped_queryset(request.user, procurement.ContratoPublicoMunicipal.objects.all())
        procurement_summary['contracts'] = contract_scope.count()
        procurement_summary['contracts_expiring'] = contract_scope.filter(
            status=procurement.ContratoPublicoMunicipal.Status.VIGENTE,
            fim_vigencia__range=(timezone.localdate(), timezone.localdate() + timedelta(days=60)),
        ).count()
        procurement_summary['contracted_value'] = contract_scope.aggregate(total=Sum('valor'))['total'] or 0
        procurement_summary['executed_value'] = scoped_queryset(
            request.user, procurement.ExecucaoContratoPublico.objects.filter(contrato__in=contract_scope),
        ).aggregate(total=Sum('valor'))['total'] or 0
    return render(request, 'rh_municipal/public_home.html', _context(
        request, cards=cards, charts=chart_groups, analytics_level=level,
        modules=module_rows, pending_invites=pending_invites, accesses=accesses,
        phase_widgets=phase_widgets, procurement_widgets=procurement_widgets,
        procurement_summary=procurement_summary,
        phase_d_widgets=phase_d_widgets, phase_d_summary=phase_d_summary,
        phase_e_widgets=phase_e_widgets,
        phase_f_widgets=phase_f_widgets,
    ))


def _can_create_structure(accesses, kind, parent=None):
    for access in accesses:
        if access.papel == AcessoMunicipal.Papel.ADMIN_PREFEITURA:
            return True
        if kind == 'departamento' and access.escopo == AcessoMunicipal.Escopo.SECRETARIA and parent and parent.pk == access.secretaria_id:
            return True
        if kind == 'setor' and access.escopo == AcessoMunicipal.Escopo.DEPARTAMENTO and parent and parent.pk == access.departamento_id:
            return True
        if kind == 'unidade' and access.escopo == AcessoMunicipal.Escopo.SETOR and parent and parent.pk == access.setor_id:
            return True
    return False


@login_required
@require_http_methods(['GET', 'POST'])
def structure(request):
    require_municipal_permission(request.user, 'structure.view')
    org = current_organization()
    kinds = ('secretaria', 'departamento', 'setor', 'unidade')
    actor_accesses = list(accesses_for(request.user))
    can_manage = has_municipal_permission(request.user, 'structure.manage')
    available_kinds = []
    if can_manage:
        if any(row.papel == AcessoMunicipal.Papel.ADMIN_PREFEITURA for row in actor_accesses):
            available_kinds = list(kinds)
        else:
            if any(row.escopo == AcessoMunicipal.Escopo.SECRETARIA for row in actor_accesses):
                available_kinds.append('departamento')
            if any(row.escopo == AcessoMunicipal.Escopo.DEPARTAMENTO for row in actor_accesses):
                available_kinds.append('setor')
            if any(row.escopo == AcessoMunicipal.Escopo.SETOR for row in actor_accesses):
                available_kinds.append('unidade')
    requested_kind = request.GET.get('tipo', request.POST.get('tipo', ''))
    kind = requested_kind if requested_kind in kinds else (available_kinds[0] if available_kinds else 'secretaria')
    if kind not in kinds:
        raise Http404
    can_manage_catalog = can_manage and any(
        row.papel == AcessoMunicipal.Papel.ADMIN_PREFEITURA for row in actor_accesses
    )
    edit_form = None
    catalog_action = request.POST.get('acao', '') if request.method == 'POST' else ''
    if request.method == 'POST' and catalog_action:
        require_municipal_permission(request.user, 'structure.manage')
        if catalog_action in {'editar_item', 'alternar_item'}:
            target_kind = request.POST.get('item_tipo', '')
            model_map = {
                'departamento': DepartamentoMunicipal, 'setor': SetorMunicipal,
                'unidade': UnidadeMunicipal,
            }
            if target_kind not in model_map:
                raise Http404
            try:
                target_id = int(request.POST.get('item_id', ''))
            except (TypeError, ValueError):
                raise Http404
            target = get_object_or_404(model_map[target_kind].objects, pk=target_id)
            parent = {
                'departamento': target.secretaria,
                'setor': target.departamento,
                'unidade': target.setor,
            }[target_kind]
            if not _can_create_structure(actor_accesses, target_kind, parent):
                raise PermissionDenied('O registro está fora do seu escopo municipal de administração.')
            if catalog_action == 'alternar_item':
                requested_active = request.POST.get('ativo')
                if requested_active not in {'true', 'false'}:
                    raise Http404
                active = requested_active == 'true'
                before = target.ativo
                if before != active:
                    with transaction.atomic():
                        target.ativo = active
                        target.save(update_fields=['ativo'])
                        audit_public(request.user, 'ESTRUTURA_MUNICIPAL_ATIVADA' if active else 'ESTRUTURA_MUNICIPAL_DESATIVADA', target, {
                            'tipo': target_kind, 'ativo_anterior': before, 'ativo_atual': active,
                        })
                messages.success(request, 'Registro ativado.' if active else 'Registro desativado. Histórico e vínculos foram preservados.')
                return redirect(f"{reverse('rh_municipal_public:structure')}?tipo={target_kind}&status=todos")
            edit_form = EstruturaItemEdicaoForm(
                request.POST, item=target, model=model_map[target_kind], actor=request.user,
                prefix=f'{target_kind}-{target.pk}',
            )
            if edit_form.is_valid():
                before = {'codigo': target.codigo, 'nome': target.nome, 'descricao': target.descricao, 'responsavel_id': target.responsavel_id}
                try:
                    with transaction.atomic():
                        target.codigo = edit_form.cleaned_data['codigo']
                        target.nome = edit_form.cleaned_data['nome']
                        target.descricao = edit_form.cleaned_data['descricao']
                        target.responsavel = edit_form.cleaned_data['responsavel']
                        target.save()
                        audit_public(request.user, 'ESTRUTURA_MUNICIPAL_ATUALIZADA', target, {
                            'tipo': target_kind, 'antes': before,
                            'depois': {'codigo': target.codigo, 'nome': target.nome, 'descricao': target.descricao, 'responsavel_id': target.responsavel_id},
                        })
                except ValidationError as exc:
                    edit_form.add_error(None, '; '.join(exc.messages))
                else:
                    messages.success(request, 'Registro atualizado com histórico preservado.')
                    return redirect(f"{reverse('rh_municipal_public:structure')}?tipo={target_kind}&status=todos")
            if target_kind == 'departamento':
                edit_form_map = {'departamento': edit_form}
            elif target_kind == 'setor':
                edit_form_map = {'setor': edit_form}
            else:
                edit_form_map = {'unidade': edit_form}
        else:
            edit_form_map = {}
        if catalog_action in {'editar_item', 'alternar_item'}:
            pass
        elif not can_manage_catalog:
            raise PermissionDenied('Somente o Administrador da Prefeitura pode administrar o catálogo de secretarias.')
        elif catalog_action == 'catalogo_inicial':
            created = initialize_secretary_catalog(request.user)
            messages.success(request, f'Catálogo pronto: {len(created)} secretaria(s) adicionada(s), todas desativadas. Registros anteriores foram preservados.')
            return redirect(f"{reverse('rh_municipal_public:structure')}?tipo=secretaria")
        elif catalog_action in {'renomear_secretaria', 'alternar_secretaria'}:
            try:
                secretary_id = int(request.POST.get('secretaria_id', ''))
            except (TypeError, ValueError):
                raise Http404
            row = get_object_or_404(
                Secretaria.objects,
                pk=secretary_id,
            )
            if catalog_action == 'renomear_secretaria':
                edit_form = SecretariaEdicaoForm(
                    request.POST, instance=row,
                    prefix=f'secretaria-{row.pk}',
                )
                if edit_form.is_valid():
                    before = {'codigo': row.codigo, 'nome': row.nome, 'descricao': row.descricao}
                    try:
                        with transaction.atomic():
                            updated = edit_form.save()
                            audit_public(request.user, 'SECRETARIA_ATUALIZADA', updated, {
                                'antes': before,
                                'depois': {'codigo': updated.codigo, 'nome': updated.nome, 'descricao': updated.descricao},
                            })
                    except ValidationError as exc:
                        edit_form.add_error(None, '; '.join(exc.messages))
                    else:
                        messages.success(request, 'Secretaria atualizada. O histórico e os vínculos existentes foram preservados.')
                        return redirect(f"{reverse('rh_municipal_public:structure')}?tipo=secretaria")
            elif catalog_action == 'alternar_secretaria':
                requested_active = request.POST.get('ativo')
                if requested_active not in {'true', 'false'}:
                    raise Http404
                active = requested_active == 'true'
                before = row.ativo
                if before != active:
                    with transaction.atomic():
                        row.ativo = active
                        row.save(update_fields=['ativo'])
                        audit_public(request.user, 'SECRETARIA_ATIVADA' if active else 'SECRETARIA_DESATIVADA', row, {
                            'ativo_anterior': before, 'ativo_atual': active,
                        })
                messages.success(request, 'Secretaria ativada.' if active else 'Secretaria desativada. Seus vínculos e histórico foram preservados.')
                return redirect(f"{reverse('rh_municipal_public:structure')}?tipo=secretaria")
        elif catalog_action not in {'editar_item', 'alternar_item'}:
            raise Http404

    initial = {}
    parent_query = {
        'departamento': ('secretaria_id', 'secretaria'),
        'setor': ('departamento_id', 'departamento'),
        'unidade': ('setor_id', 'setor'),
    }.get(kind)
    if parent_query:
        query_param, field_name = parent_query
        requested_parent = request.GET.get(query_param)
        if requested_parent:
            try:
                initial[field_name] = int(requested_parent)
            except (TypeError, ValueError):
                pass
    form = EstruturaPublicaForm(
        request.POST if request.method == 'POST' and not catalog_action else None,
        actor=request.user, kind=kind, initial=initial,
    ) if kind in available_kinds else None
    if request.method == 'POST':
        if not catalog_action:
            require_municipal_permission(request.user, 'structure.manage')
            if kind not in available_kinds:
                raise PermissionDenied('Seu papel municipal não pode criar esse nível da estrutura.')
        if not catalog_action and form and form.is_valid():
            data = form.cleaned_data
            secretaria = data.get('secretaria')
            departamento = data.get('departamento')
            setor = data.get('setor')
            parent = {'departamento': secretaria, 'setor': departamento, 'unidade': setor}.get(kind)
            if not _can_create_structure(list(accesses_for(request.user)), kind, parent):
                raise PermissionDenied('Você não pode criar registros fora do seu escopo municipal.')
            model_map = {
                'secretaria': Secretaria,
                'departamento': DepartamentoMunicipal,
                'setor': SetorMunicipal,
                'unidade': UnidadeMunicipal,
            }
            parent_field = {'departamento': 'secretaria', 'setor': 'departamento', 'unidade': 'setor'}.get(kind)
            kwargs = {
                'organization': org, 'codigo': data['codigo'], 'nome': data['nome'],
                'descricao': data['descricao'], 'responsavel': data.get('responsavel'),
            }
            if parent_field:
                kwargs[parent_field] = data[parent_field]
            try:
                row = model_map[kind](**kwargs)
                row.save()
                audit_public(request.user, 'ESTRUTURA_MUNICIPAL_CRIADA', row, {'tipo': kind, 'codigo': row.codigo})
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
            else:
                messages.success(request, 'Registro da estrutura municipal criado e auditado.')
                return redirect(f"{reverse('rh_municipal_public:structure')}?tipo={kind}")
    query_text = request.GET.get('q', '').strip()[:100]
    status_filter = request.GET.get('status', 'ativos')
    if status_filter not in {'ativos', 'inativos', 'todos'}:
        status_filter = 'ativos'
    if can_manage_catalog:
        secretary_queryset = Secretaria.objects.all()
    else:
        secretary_queryset = Secretaria.objects.filter(ativo=True)
    if status_filter == 'ativos':
        secretary_queryset = secretary_queryset.filter(ativo=True)
    elif status_filter == 'inativos':
        secretary_queryset = secretary_queryset.filter(ativo=False)
    if query_text:
        secretary_queryset = secretary_queryset.filter(Q(nome__icontains=query_text) | Q(codigo__icontains=query_text) | Q(descricao__icontains=query_text))
    secretaries = list(scoped_queryset(request.user, secretary_queryset))
    departments_qs = DepartamentoMunicipal.objects.filter(ativo=True, secretaria__ativo=True)
    sectors_qs = SetorMunicipal.objects.filter(ativo=True, departamento__ativo=True, departamento__secretaria__ativo=True)
    units_qs = UnidadeMunicipal.objects.filter(ativo=True, setor__ativo=True, setor__departamento__ativo=True, setor__departamento__secretaria__ativo=True)
    if status_filter == 'inativos':
        departments_qs = DepartamentoMunicipal.objects.filter(ativo=False)
        sectors_qs = SetorMunicipal.objects.filter(ativo=False)
        units_qs = UnidadeMunicipal.objects.filter(ativo=False)
    elif status_filter == 'todos':
        departments_qs = DepartamentoMunicipal.objects.all()
        sectors_qs = SetorMunicipal.objects.all()
        units_qs = UnidadeMunicipal.objects.all()
    if query_text:
        departments_qs = departments_qs.filter(Q(nome__icontains=query_text) | Q(codigo__icontains=query_text) | Q(descricao__icontains=query_text))
        sectors_qs = sectors_qs.filter(Q(nome__icontains=query_text) | Q(codigo__icontains=query_text) | Q(descricao__icontains=query_text))
        units_qs = units_qs.filter(Q(nome__icontains=query_text) | Q(codigo__icontains=query_text) | Q(descricao__icontains=query_text))
    departments = list(scoped_queryset(request.user, departments_qs).select_related('secretaria', 'responsavel'))
    sectors = list(scoped_queryset(request.user, sectors_qs).select_related('departamento__secretaria', 'responsavel'))
    units = list(scoped_queryset(request.user, units_qs).select_related('setor__departamento__secretaria', 'responsavel'))
    professionals = scoped_queryset(request.user, Servidor.objects.filter(
        ativo=True, secretaria__ativo=True, departamento__ativo=True,
        setor__ativo=True, unidade__ativo=True,
    )).count()
    secretary_rows = [
        {
            'item': secretary,
            'department_count': sum(row.secretaria_id == secretary.pk for row in departments),
            'edit_form': edit_form if edit_form and edit_form.instance.pk == secretary.pk
            else SecretariaEdicaoForm(instance=secretary, prefix=f'secretaria-{secretary.pk}'),
        }
        for secretary in secretaries
    ]
    item_edit_form_map = locals().get('edit_form_map', {})
    department_rows = [
        {'item': row, 'edit_form': item_edit_form_map.get('departamento') if item_edit_form_map.get('departamento') and item_edit_form_map['departamento'].item.pk == row.pk else EstruturaItemEdicaoForm(item=row, model=DepartamentoMunicipal, actor=request.user, prefix=f'departamento-{row.pk}')}
        for row in departments
    ]
    sector_rows = [
        {'item': row, 'edit_form': item_edit_form_map.get('setor') if item_edit_form_map.get('setor') and item_edit_form_map['setor'].item.pk == row.pk else EstruturaItemEdicaoForm(item=row, model=SetorMunicipal, actor=request.user, prefix=f'setor-{row.pk}')}
        for row in sectors
    ]
    unit_rows = [
        {'item': row, 'edit_form': item_edit_form_map.get('unidade') if item_edit_form_map.get('unidade') and item_edit_form_map['unidade'].item.pk == row.pk else EstruturaItemEdicaoForm(item=row, model=UnidadeMunicipal, actor=request.user, prefix=f'unidade-{row.pk}')}
        for row in units
    ]
    existing_codes = {row.codigo.casefold() for row in secretaries}
    existing_names = {' '.join(row.nome.casefold().split()) for row in secretaries}
    missing_catalog_count = sum(
        code.casefold() not in existing_codes and ' '.join(name.casefold().split()) not in existing_names
        for code, name in INITIAL_SECRETARY_CATALOG
    )
    return render(request, 'rh_municipal/public_structure.html', _context(request,
        kind=kind, kinds=kinds, form=form, secretaries=secretary_rows, departments=department_rows,
        sectors=sector_rows, units=unit_rows, available_kinds=available_kinds,
        can_manage_structure=can_manage, can_manage_catalog=can_manage_catalog,
        missing_catalog_count=missing_catalog_count,
        active_secretaries_count=sum(row.ativo for row in secretaries),
        professionals_count=professionals,
        search_query=query_text, status_filter=status_filter,
    ))


@login_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    require_municipal_permission(request.user, 'profile.manage')
    org = current_organization()
    instance = PerfilPrefeitura.objects.filter(organization=org).first() or PerfilPrefeitura(organization=org)
    form = PerfilPrefeituraForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        row = form.save(commit=False)
        row.organization = org
        row.save()
        audit_public(request.user, 'PERFIL_PREFEITURA_ATUALIZADO', row,
                     {'nome_institucional': row.nome_institucional, 'codigo_ibge': row.codigo_ibge, 'ativo': row.ativo})
        messages.success(request, 'Perfil institucional salvo.')
        return redirect('rh_municipal_public:profile')
    return render(request, 'rh_municipal/public_profile.html', _context(request, form=form))


@login_required
@require_http_methods(['GET', 'POST'])
def accesses(request):
    require_municipal_permission(request.user, 'access.view')
    initial = {}
    requested_secretary = request.GET.get('secretaria_id')
    if requested_secretary and has_municipal_permission(request.user, 'access.manage'):
        try:
            secretary_id = int(requested_secretary)
        except (TypeError, ValueError):
            secretary_id = None
        if secretary_id:
            secretary = scoped_queryset(
                request.user, Secretaria.objects.filter(ativo=True),
            ).filter(pk=secretary_id).first()
            if secretary:
                initial.update(secretaria=secretary.pk, escopo=AcessoMunicipal.Escopo.SECRETARIA)
    form = AcessoMunicipalForm(request.POST or None, actor=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            assign_municipal_access(
                request.user, membership=form.cleaned_data['membership'], papel=form.cleaned_data['papel'],
                escopo=form.cleaned_data['escopo'], secretaria=form.cleaned_data.get('secretaria'),
                departamento=form.cleaned_data.get('departamento'), setor=form.cleaned_data.get('setor'),
                unidade=form.cleaned_data.get('unidade'), funcao=form.cleaned_data.get('funcao'),
                permissions=form.cleaned_data.get('permissoes') or (),
            )
        except (PermissionDenied, ValidationError) as exc:
            form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
        else:
            messages.success(request, 'Acesso municipal configurado e auditado.')
            return redirect('rh_municipal_public:accesses')
    rows = AcessoMunicipal.objects.filter(ativo=True).select_related(
        'membership__user', 'secretaria', 'departamento', 'setor', 'unidade', 'funcao',
    ).prefetch_related('permissoes')
    visible = [row for row in rows if any(scope_allows(access, row) for access in accesses_for(request.user))]
    return render(request, 'rh_municipal/public_accesses.html', _context(request, form=form, rows=visible,
        permission_labels=PUBLIC_PERMISSION_LABELS))


@login_required
@require_POST
def access_revoke(request, pk):
    require_municipal_permission(request.user, 'access.manage')
    row = get_object_or_404(AcessoMunicipal.objects.select_related('membership', 'secretaria', 'departamento', 'setor', 'unidade'), pk=pk)
    if not any(scope_allows(access, row) for access in accesses_for(request.user)):
        raise PermissionDenied('Acesso está fora do seu escopo municipal.')
    row.ativo = False
    row.save(update_fields=['ativo'])
    audit_public(request.user, 'ACESSO_MUNICIPAL_REVOGADO', row, {'membership': row.membership_id, 'papel': row.papel})
    messages.success(request, 'Acesso municipal desativado; histórico preservado.')
    return redirect('rh_municipal_public:accesses')


@login_required
@require_http_methods(['GET', 'POST'])
def invites(request):
    can_create = has_municipal_permission(request.user, 'invite.create')
    can_revoke = has_municipal_permission(request.user, 'invite.revoke')
    if not can_create and not can_revoke:
        raise PermissionDenied('Acesso municipal não autorizado para consultar convites.')
    if request.method == 'POST' and not can_create:
        raise PermissionDenied('Seu acesso não pode gerar convites.')
    form = ConviteMunicipalForm(request.POST or None, actor=request.user) if can_create else None
    invite_url = None
    if request.method == 'POST' and form.is_valid():
        try:
            invite, raw = create_municipal_invite(request.user, data=form.cleaned_data)
            invite_url = request.build_absolute_uri(reverse('rh_municipal_public:invite_accept', args=[raw]))
            form = ConviteMunicipalForm(actor=request.user)
        except (PermissionDenied, ValidationError) as exc:
            form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
    rows = ConviteMunicipal.objects.order_by('-criado_em')
    visible = [row for row in rows if any(scope_allows(access, row) for access in accesses_for(request.user))]
    return render(request, 'rh_municipal/public_invites.html', _context(request,
        form=form, rows=visible, invite_url=invite_url, permission_labels=PUBLIC_PERMISSION_LABELS,
        can_invite=can_create, can_revoke_invites=can_revoke))


@login_required
@require_POST
def invite_revoke(request, pk):
    require_municipal_permission(request.user, 'invite.revoke')
    row = get_object_or_404(ConviteMunicipal.objects.select_related('secretaria', 'departamento', 'setor', 'unidade'), pk=pk)
    if not row.valido:
        messages.info(request, 'O convite já foi usado, expirou ou foi revogado.')
        return redirect('rh_municipal_public:invites')
    if not any(scope_allows(access, row) for access in accesses_for(request.user)):
        raise PermissionDenied('Convite está fora do seu escopo municipal.')
    row.revogado_em = timezone.now()
    row.revogado_por = request.user
    row.save(update_fields=['revogado_em', 'revogado_por'])
    audit_public(request.user, 'CONVITE_MUNICIPAL_REVOGADO', row, {'email': row.email})
    messages.success(request, 'Convite revogado.')
    return redirect('rh_municipal_public:invites')


def invite_accept(request, token):
    digest = ConviteMunicipal.digest(token)
    invite = ConviteMunicipal.all_objects.select_related(
        'organization', 'secretaria', 'departamento', 'setor', 'unidade', 'funcao', 'criado_por',
    ).filter(token_digest=digest).first()
    if not invite or not invite.valido:
        raise Http404('Convite municipal inexistente, expirado, utilizado ou revogado.')
    with tenant_context(invite.organization):
        if invite.organization.status != Organization.Status.ACTIVE:
            raise Http404
        if not module_enabled('gestao_publica'):
            raise PermissionDenied('Gestão Pública não está incluída no contrato desta Prefeitura.')
        from .models import product_enabled
        if not product_enabled(invite.organization_id):
            raise PermissionDenied('ERP Gestão Pública não está habilitado nesta Prefeitura.')
        User = get_user_model()
        matching = list(User.objects.filter(email__iexact=invite.email)[:2])
        if any(not candidate.is_active for candidate in matching):
            return render(request, 'rh_municipal/invite_error.html', {
                'message': 'Já existe uma conta inativa com este e-mail. Solicite a reativação ao administrador antes de aceitar o convite.'
            }, status=409)
        if len(matching) > 1:
            return render(request, 'rh_municipal/invite_error.html', {'message': 'O e-mail está associado a mais de uma conta. O suporte administrativo precisa resolver a duplicidade.'}, status=409)
        existing_user = matching[0] if matching else None
        if request.user.is_authenticated and request.user.email.lower() != invite.email.lower():
            raise PermissionDenied('Entre com a conta do e-mail convidado para aceitar este acesso.')
        if existing_user and not request.user.is_authenticated:
            login_url = reverse('contas:login') + '?next=' + reverse('rh_municipal_public:invite_accept', args=[token])
            return render(request, 'rh_municipal/invite_existing.html', {
                'invite': invite, 'login_url': login_url,
            })
        if existing_user:
            form = None
            if request.user.pk != existing_user.pk:
                raise PermissionDenied('A sessão ativa não corresponde ao e-mail convidado.')
            if request.method != 'POST':
                return render(request, 'rh_municipal/invite_existing_accept.html', {'invite': invite})
        else:
            if request.user.is_authenticated:
                raise PermissionDenied('Encerre a sessão atual antes de aceitar um convite para uma nova conta.')
            form = ConviteAceiteForm(request.POST or None, initial={'email': invite.email})
            if request.method != 'POST' or not form.is_valid():
                return render(request, 'rh_municipal/invite_accept.html', {'invite': invite, 'form': form})

        try:
            with transaction.atomic():
                locked = ConviteMunicipal.all_objects.select_for_update().get(pk=invite.pk)
                if not locked.valido:
                    raise ValidationError('O convite já foi usado, expirou ou foi revogado.')
                user = existing_user
                if user is None:
                    data = form.cleaned_data
                    user = User.objects.create_user(
                        username=data['username'], email=locked.email,
                        first_name=data['first_name'], last_name=data['last_name'],
                        password=data['password1'], perfil='SERVIDOR_PUBLICO', is_active=True,
                    )
                membership = OrganizationMembership.objects.filter(user=user, organization=locked.organization).first()
                if membership and membership.status != OrganizationMembership.Status.ACTIVE:
                    raise ValidationError('O vínculo existente com esta Prefeitura está inativo. Solicite a reativação ao administrador municipal.')
                if membership is None:
                    membership = OrganizationMembership.objects.create(
                        user=user, organization=locked.organization, role='SERVIDOR_PUBLICO',
                        status=OrganizationMembership.Status.ACTIVE,
                    )
                erp_link = MembershipERP.objects.filter(membership=membership, erp__code=PRODUCT_CODE).select_related('erp').first()
                if erp_link and (not erp_link.enabled or not erp_link.erp.active):
                    raise ValidationError('O acesso desta conta ao ERP Gestão Pública está desativado.')
                if not erp_link:
                    MembershipERP.objects.create(membership=membership,
                        erp=ERPCatalog.objects.get(code=PRODUCT_CODE), enabled=True)
                if AcessoMunicipal.objects.filter(
                    membership=membership, papel=locked.papel, escopo=locked.escopo,
                    secretaria=locked.secretaria, departamento=locked.departamento,
                    setor=locked.setor, unidade=locked.unidade, funcao=locked.funcao, ativo=True,
                ).exists():
                    raise ValidationError('Esta conta já possui o acesso municipal indicado no convite.')
                access = AcessoMunicipal(
                    membership=membership, papel=locked.papel, escopo=locked.escopo,
                    secretaria=locked.secretaria, departamento=locked.departamento,
                    setor=locked.setor, unidade=locked.unidade, funcao=locked.funcao,
                    atribuido_por=locked.criado_por,
                )
                access.save()
                for capability in sorted(set(locked.permissoes)):
                    PermissaoMunicipal.objects.create(acesso=access, capacidade=capability)
                locked.usado_em = timezone.now()
                locked.aceito_por = user
                locked.save(update_fields=['usado_em', 'aceito_por'])
                PlatformAudit.objects.create(organization=locked.organization,
                    erp=ERPCatalog.objects.get(code=PRODUCT_CODE),
                    user=user, action='CONVITE_MUNICIPAL_ACEITO',
                    record=f'{locked._meta.label}:{locked.pk}',
                    changes={'papel': locked.papel, 'escopo': locked.escopo, 'email': locked.email})
        except (ValidationError, IntegrityError) as exc:
            message = '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Não foi possível concluir o aceite; verifique se a conta já existe.'
            return render(request, 'rh_municipal/invite_error.html', {'message': message}, status=400)
        if request.user.is_authenticated:
            request.session['organization_id'] = locked.organization_id
            messages.success(request, 'Acesso municipal ativado. Você já pode acessar a Gestão Pública.')
            return redirect('rh_municipal_public:home')
        login_url = reverse('contas:login') + '?next=' + reverse('rh_municipal_public:home')
        return render(request, 'rh_municipal/invite_complete.html', {'login_url': login_url, 'organization': locked.organization})


def manifest(request):
    from django.http import JsonResponse
    response = JsonResponse({
        'id': '/gestao-publica/', 'name': 'VERTYX Gestão Pública', 'short_name': 'VERTYX Público',
        'lang': 'pt-BR', 'start_url': '/gestao-publica/', 'scope': '/gestao-publica/',
        'display': 'standalone', 'background_color': '#f4f7fa', 'theme_color': '#123b67',
        'description': 'ERP Gestão Pública VERTYX',
        'icons': [
            {'src': '/static/pwa/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
            {'src': '/static/pwa/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
        ],
    }, content_type='application/manifest+json')
    response['Cache-Control'] = 'no-cache'
    return response


def worker(request):
    from pathlib import Path
    from django.conf import settings
    from django.http import HttpResponse
    response = HttpResponse((Path(settings.BASE_DIR) / 'static/pwa/gestao-publica-sw.js').read_text(encoding='utf-8'), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/gestao-publica/'
    response['Cache-Control'] = 'no-cache'
    return response
