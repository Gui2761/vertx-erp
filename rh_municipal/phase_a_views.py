"""Tenant-safe dashboards and draft setup screens for Public Management Phase A."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from platform_core.context import current_organization

from . import phase_a_models as civic
from .models import PRODUCT_CODE
from .phase_a_forms import FORM_SPECS, foundation_form
from .public_services import (
    audit_public, has_municipal_permission, require_municipal_permission,
    scoped_queryset,
)


MODULES = {
    'planejamento': {
        'code': civic.MUNICIPAL_MODULES['planning'], 'permission': 'planning',
        'title': 'Planejamento Público', 'eyebrow': 'PLANEJAMENTO · PPA, LDO E LOA',
        'intro': 'Organize exercícios, instrumentos, programas, ações, metas e indicadores. A estrutura prepara o vínculo futuro com orçamento e execução, sem impor regras legais.',
        'sections': [
            ('Exercícios', civic.ExercicioMunicipal, lambda x: (x.ano, x.get_status_display(), x.descricao or '—')),
            ('PPA, LDO e LOA', civic.InstrumentoPlanejamentoMunicipal, lambda x: (x.get_tipo_display(), x.nome, f'{x.exercicio.ano} · {x.get_status_display()}')),
            ('Programas', civic.ProgramaPlanejamentoMunicipal, lambda x: (x.codigo, x.nome, x.exercicio.ano)),
            ('Projetos, atividades e operações especiais', civic.AcaoPlanejamentoMunicipal, lambda x: (x.codigo, x.nome, x.get_tipo_display())),
            ('Indicadores e metas', civic.IndicadorPlanejamentoMunicipal, lambda x: (x.codigo, x.nome, f'Meta: {x.meta if x.meta is not None else "A definir"} {x.unidade_medida}')),
        ],
    },
    'orcamento': {
        'code': civic.MUNICIPAL_MODULES['budget'], 'permission': 'budget',
        'title': 'Orçamento Público', 'eyebrow': 'ORÇAMENTO · QDD E DOTAÇÕES',
        'intro': 'Prepare exercícios, órgãos, unidades orçamentárias, classificações e dotações. Créditos adicionais são registros preparatórios; não alteram saldo contabilizado.',
        'sections': [
            ('Órgãos orçamentários', civic.OrgaoOrcamentarioMunicipal, lambda x: (x.codigo, x.nome, x.secretaria.nome if x.secretaria_id else 'Sem secretaria')),
            ('Unidades orçamentárias', civic.UnidadeOrcamentariaMunicipal, lambda x: (x.codigo, x.nome, x.orgao.nome)),
            ('Dotações / QDD', civic.DotacaoOrcamentariaMunicipal, lambda x: (x.codigo_qdd or '—', x.unidade_orcamentaria.nome, f'Programado: R$ {x.saldo_programado}')),
            ('Créditos adicionais', civic.CreditoAdicionalMunicipal, lambda x: (x.get_tipo_display(), x.dotacao_destino.codigo_qdd or x.dotacao_destino.descricao or 'Dotação', f'R$ {x.valor} · {x.get_status_display()}')),
        ],
    },
    'contabilidade': {
        'code': civic.MUNICIPAL_MODULES['accounting'], 'permission': 'accounting',
        'title': 'Contabilidade Pública · Fundação', 'eyebrow': 'CONTABILIDADE · BASE PARAMETRIZÁVEL',
        'intro': 'Estrutura preparatória para plano de contas, períodos, lançamentos, partidas, documentos e fechamento. Referências normativas são configuráveis; não há regras MCASP/TCE fixas nem contabilização automática.',
        'sections': [
            ('Planos de contas', civic.PlanoContasMunicipal, lambda x: (x.codigo, x.nome, f'{x.versao or "Versão a definir"} · {x.referencia_normativa or "Referência não informada"}')),
            ('Contas contábeis', civic.ContaContabilMunicipal, lambda x: (x.codigo, x.nome, x.get_classificacao_display())),
            ('Períodos', civic.PeriodoContabilMunicipal, lambda x: (f'{x.mes:02}/{x.exercicio.ano}', x.get_status_display(), '')),
            ('Lançamentos preparatórios', civic.LancamentoContabilMunicipal, lambda x: (x.data_referencia, x.historico, x.get_status_display())),
            ('Fechamentos', civic.FechamentoContabilMunicipal, lambda x: (x.periodo, x.get_status_display(), x.observacoes or '')),
        ],
    },
    'tesouraria': {
        'code': civic.MUNICIPAL_MODULES['treasury'], 'permission': 'treasury',
        'title': 'Tesouraria · Fundação', 'eyebrow': 'TESOURARIA · CONTAS E CONCILIAÇÃO',
        'intro': 'Cadastre referências de bancos e contas e prepare conciliação. As movimentações aqui são informativas/preparatórias e não realizam pagamentos, transferências ou integração contábil.',
        'sections': [
            ('Bancos', civic.BancoMunicipal, lambda x: (x.codigo or '—', x.nome, 'Ativo' if x.ativo else 'Inativo')),
            ('Contas bancárias', civic.ContaBancariaMunicipal, lambda x: (x.banco.nome, x.descricao, x.get_status_display())),
            ('Movimentações preparatórias', civic.MovimentacaoTesourariaMunicipal, lambda x: (x.data_referencia, x.descricao, f'{x.get_tipo_display()} · R$ {x.valor}')),
            ('Conciliações', civic.ConciliacaoBancariaMunicipal, lambda x: (f'{x.periodo_inicio} – {x.periodo_fim}', x.conta.descricao, x.get_status_display())),
        ],
    },
}


@login_required
@require_http_methods(['GET', 'POST'])
def foundation_home(request, family):
    config = MODULES.get(family)
    if config is None:
        raise PermissionDenied('Módulo municipal desconhecido.')
    view_capability = f"{config['permission']}.view"
    manage_capability = f"{config['permission']}.manage"
    module_code = config['code']
    require_municipal_permission(request.user, view_capability, module=module_code)
    can_manage = has_municipal_permission(request.user, manage_capability, module=module_code)
    org = current_organization()

    form = None
    selected_action = request.GET.get('novo') if request.method == 'GET' else request.POST.get('acao')
    forms_for_family = FORM_SPECS[family]
    if selected_action and selected_action in forms_for_family:
        if request.method == 'POST':
            require_municipal_permission(request.user, manage_capability, module=module_code)
        title, model, fields = forms_for_family[selected_action]
        form = foundation_form(
            model, fields, actor=request.user,
            data=request.POST if request.method == 'POST' else None,
        )
        if request.method == 'POST' and form.is_valid():
            with transaction.atomic():
                record = form.save(commit=False)
                record.organization = org
                for actor_field in ('criado_por', 'iniciado_por'):
                    if any(field.name == actor_field for field in record._meta.fields):
                        setattr(record, actor_field, request.user)
                record.save()
                audit_public(request.user, f'{family.upper()}_REGISTRO_CRIADO', record, {
                    'tipo': selected_action,
                    'identificador': str(getattr(record, 'codigo', getattr(record, 'ano', record.pk))),
                })
            messages.success(request, f'{title} salvo como registro preparatório e auditado.')
            return redirect(reverse(f'rh_municipal_public:{family}'))

    sections = []
    for title, model, formatter in config['sections']:
        queryset = scoped_queryset(request.user, model.objects.all()).order_by('-pk')[:30]
        rows = [{'primary': str(obj), 'cells': formatter(obj)} for obj in queryset]
        sections.append({'title': title, 'rows': rows, 'total': len(rows)})
    form_actions = [
        {'key': key, 'title': spec[0], 'url': f"{reverse(f'rh_municipal_public:{family}')}?novo={key}"}
        for key, spec in forms_for_family.items()
    ]
    return render(request, 'rh_municipal/phase_a_module.html', {
        **_public_context(request),
        'family': family, 'config': config, 'sections': sections,
        'form_actions': form_actions, 'selected_action': selected_action,
        'home_url': reverse(f'rh_municipal_public:{family}'),
        'form_title': forms_for_family.get(selected_action, ('',))[0] if selected_action in forms_for_family else '',
        'form': form, 'can_manage_module': can_manage,
    })


def _public_context(request):
    from .public_views import _context
    return _context(request)
