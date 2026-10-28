"""Responsive, permission-gated screens for municipal procurement Phase B."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from platform_core.context import current_organization

from . import phase_b_models as procurement
from .models import PRODUCT_CODE
from .procurement_forms import (
    AtaUsoForm, ContractExecutionForm, MODEL_ACTIONS,
    procurement_model_form,
)
from .procurement_services import (
    _history, create_process_from_request, price_comparison,
    STATUS_PROCESS_TRANSITIONS, STATUS_REQUEST_TRANSITIONS,
    register_contract_amendment, register_contract_execution,
    register_price_registry_usage, transition_procurement_process,
    transition_purchase_request,
)
from .public_services import audit_public, has_municipal_permission, require_municipal_permission, scoped_queryset


SCREENS = {
    'compras': {
        'route': 'compras_module',
        'module': 'compras_publicas', 'permission': 'compras.view',
        'title': 'Compras Públicas', 'eyebrow': 'SOLICITAÇÕES · COTAÇÕES · PROCESSOS',
        'intro': 'Registre demandas por secretaria, reúna itens e cotações e acompanhe aprovações com trilha de auditoria.',
        'actions': ('solicitacao', 'item_solicitacao', 'modalidade', 'pesquisa', 'cotacao', 'cotacao_item', 'documento_solicitacao'),
        'sections': (
            ('Solicitações de compra', procurement.SolicitacaoCompra, ('numero', 'exercicio', 'secretaria__nome', 'get_status_display')),
            ('Pesquisas de preço', procurement.PesquisaPrecoMunicipal, ('data_referencia', 'solicitacao__numero', 'processo__numero', 'observacoes')),
            ('Cotações de fornecedores', procurement.CotacaoFornecedorMunicipal, ('fornecedor__nome', 'data', 'fonte', 'documento_referencia')),
            ('Modalidades parametrizadas', procurement.ModalidadeContratacaoMunicipal, ('codigo', 'nome', 'fundamento_referencia', 'ativo')),
        ),
    },
    'licitacoes': {
        'route': 'licitacoes_module',
        'module': 'licitacoes_publicas', 'permission': 'licitacao.view',
        'title': 'Licitações e Processos', 'eyebrow': 'PROCESSO · EDITAL · PARTICIPAÇÃO · JULGAMENTO',
        'intro': 'Organize processos, itens, lotes, propostas, julgamento e histórico. Regras legais e modalidades são parametrizadas pela Prefeitura.',
        'actions': ('processo', 'lote', 'item_processo', 'licitacao', 'participante', 'proposta', 'proposta_item', 'documento_processo'),
        'sections': (
            ('Processos de contratação', procurement.ProcessoContratacaoMunicipal, ('numero', 'exercicio', 'objeto', 'get_status_display')),
            ('Editais / publicações', procurement.LicitacaoMunicipal, ('numero_edital', 'processo__numero', 'data_publicacao', 'meio_publicacao')),
            ('Itens dos processos', procurement.ItemContratacaoMunicipal, ('processo__numero', 'numero', 'descricao', 'situacao')),
            ('Fornecedores participantes', procurement.FornecedorProcessoMunicipal, ('processo__numero', 'fornecedor__nome', 'get_status_display', 'registrado_em')),
            ('Propostas', procurement.PropostaMunicipal, ('numero', 'fornecedor_processo__fornecedor__nome', 'fornecedor_processo__processo__numero', 'data_envio')),
        ),
    },
    'registro-precos': {
        'route': 'registro_precos_module',
        'module': 'registro_precos', 'permission': 'price_registry.view',
        'title': 'Registro de Preços', 'eyebrow': 'ATAS · ITENS · SALDO · UTILIZAÇÃO',
        'intro': 'Acompanhe atas, vigências e saldo registrado. Utilizações são transacionais, idempotentes por referência e não podem superar o saldo.',
        'actions': ('ata', 'ata_item', 'ata_uso', 'documento_contrato'),
        'sections': (
            ('Atas', procurement.AtaRegistroPrecosMunicipal, ('numero', 'exercicio', 'fornecedor__nome', 'get_status_display')),
            ('Itens e saldo', procurement.ItemAtaRegistroPrecosMunicipal, ('ata__numero', 'item_processo__descricao', 'quantidade_registrada', 'saldo')),
            ('Utilizações registradas', procurement.UtilizacaoAtaPrecosMunicipal, ('item_ata__ata__numero', 'quantidade', 'valor_total', 'referencia')),
        ),
    },
    'contratos': {
        'route': 'contratos_module',
        'module': 'contratos_publicos', 'permission': 'contract.view',
        'title': 'Contratos Públicos', 'eyebrow': 'CONTRATOS · ADITIVOS · EXECUÇÃO',
        'intro': 'Gerencie contratos, alterações auditadas, entregas, medições, ocorrências e fiscalização. Empenho e pagamento oficial ainda não são executados.',
        'actions': ('contrato', 'contrato_item', 'aditivo', 'execucao'),
        'sections': (
            ('Contratos', procurement.ContratoPublicoMunicipal, ('numero', 'exercicio', 'fornecedor__nome', 'get_status_display')),
            ('Itens e saldo contratual', procurement.ItemContratoPublicoMunicipal, ('contrato__numero', 'descricao', 'quantidade_contratada', 'saldo_quantidade')),
            ('Aditivos / apostilamentos', procurement.AditivoContratoPublico, ('contrato__numero', 'get_tipo_display', 'numero', 'criado_em')),
            ('Execução e fiscalização', procurement.ExecucaoContratoPublico, ('contrato__numero', 'get_tipo_display', 'data_referencia', 'descricao')),
            ('Documentos privados', procurement.DocumentoContratacaoMunicipal, ('documento__titulo', 'get_categoria_display', 'documento__criado_em', 'criado_em')),
        ),
    },
}


ACTION_MODULE_PERMISSION = {
    'solicitacao': ('compras_publicas', 'compras.manage'),
    'item_solicitacao': ('compras_publicas', 'compras.manage'),
    'modalidade': ('compras_publicas', 'compras.manage'),
    'pesquisa': ('compras_publicas', 'cotacao.manage'),
    'cotacao': ('compras_publicas', 'cotacao.manage'),
    'cotacao_item': ('compras_publicas', 'cotacao.manage'),
    'processo': ('licitacoes_publicas', 'licitacao.manage'),
    'lote': ('licitacoes_publicas', 'licitacao.manage'),
    'item_processo': ('licitacoes_publicas', 'licitacao.manage'),
    'licitacao': ('licitacoes_publicas', 'licitacao.manage'),
    'participante': ('licitacoes_publicas', 'licitacao.manage'),
    'proposta': ('licitacoes_publicas', 'licitacao.manage'),
    'proposta_item': ('licitacoes_publicas', 'licitacao.judge'),
    'ata': ('registro_precos', 'price_registry.manage'),
    'ata_item': ('registro_precos', 'price_registry.manage'),
    'ata_uso': ('registro_precos', 'price_registry.manage'),
    'contrato': ('contratos_publicos', 'contract.manage'),
    'contrato_item': ('contratos_publicos', 'contract.manage'),
    'aditivo': ('contratos_publicos', 'contract.approve'),
    'execucao': ('contratos_publicos', 'contract.execute'),
    'documento_solicitacao': ('compras_publicas', 'compras.manage'),
    'documento_processo': ('licitacoes_publicas', 'licitacao.manage'),
    'documento_contrato': ('contratos_publicos', 'contract.documents'),
}


def _format(value):
    if callable(value):
        value = value()
    return '—' if value in (None, '') else str(value)


def _searchable_path(model, path):
    current = model
    parts = path.split('__')
    for index, part in enumerate(parts):
        try:
            field = current._meta.get_field(part)
        except Exception:
            return False
        if index == len(parts) - 1:
            return field.get_internal_type() in {'CharField', 'TextField', 'SlugField'}
        if not field.is_relation or field.related_model is None:
            return False
        current = field.related_model
    return False


def _rows(actor, model, fields, search=''):
    queryset = scoped_queryset(actor, model.objects.all())
    if search:
        searchable = [field for field in fields if not field.startswith('get_') and _searchable_path(model, field)]
        query = Q(pk__in=[])
        for field in searchable:
            query |= Q(**{f'{field}__icontains': search})
        if searchable:
            queryset = queryset.filter(query)
    rows = []
    for obj in queryset.select_related()[:100]:
        cells = []
        for field in fields:
            if field == 'saldo':
                value = obj.saldo
            elif field == 'saldo_quantidade':
                value = obj.saldo_quantidade
            elif field.startswith('get_'):
                value = getattr(obj, field)()
            else:
                value = obj
                for segment in field.split('__'):
                    value = getattr(value, segment, None)
                    if value is None:
                        break
            cells.append(_format(value))
        rows.append({'cells': cells, 'object': obj})
    return rows


def _actor_fields(record, actor):
    names = {field.name for field in record._meta.fields}
    for name in ('criado_por', 'responsavel', 'gestor', 'enviado_por'):
        if name in names and not getattr(record, f'{name}_id', None):
            setattr(record, name, actor)


@login_required
@require_http_methods(['GET', 'POST'])
def procurement_screen(request, family):
    config = SCREENS.get(family)
    if config is None:
        raise PermissionDenied('Módulo público desconhecido.')
    module, view_permission = config['module'], config['permission']
    require_municipal_permission(request.user, view_permission, module=module)
    can_manage = any(has_municipal_permission(request.user, cap, module=module) for cap in (
        'compras.manage', 'cotacao.manage', 'licitacao.manage', 'price_registry.manage', 'contract.manage',
        'contract.approve', 'contract.execute', 'contract.documents',
    ))
    action = request.POST.get('acao') if request.method == 'POST' else request.GET.get('novo')
    form = None
    form_title = ''
    form_error = ''
    if action in ACTION_MODULE_PERMISSION:
        action_module, action_permission = ACTION_MODULE_PERMISSION[action]
        require_municipal_permission(request.user, action_permission, module=action_module)
        if action == 'ata_uso':
            form = AtaUsoForm(data=request.POST if request.method == 'POST' else None, actor=request.user)
            form_title = 'Registrar utilização da Ata'
        elif action == 'execucao':
            form = ContractExecutionForm(data=request.POST if request.method == 'POST' else None, actor=request.user)
            form_title = 'Registrar execução contratual'
        else:
            form_title, form = procurement_model_form(action, actor=request.user,
                data=request.POST if request.method == 'POST' else None,
                files=request.FILES if request.method == 'POST' else None)
        if request.method == 'POST' and form.is_valid():
            uploaded_document = None
            try:
                with transaction.atomic():
                    if action == 'processo':
                        process = create_process_from_request(
                            request.user, form.cleaned_data['solicitacao'].pk,
                            number=form.cleaned_data['numero'], exercise=form.cleaned_data['exercicio'],
                            modality=form.cleaned_data['modalidade'],
                        )
                        obj = process
                    elif action == 'ata_uso':
                        obj = register_price_registry_usage(
                            request.user, form.cleaned_data['item_ata'].pk,
                            quantity=form.cleaned_data['quantidade'], unit=form.cleaned_data['unidade'],
                            reference=form.cleaned_data['referencia'],
                        )
                    elif action == 'execucao':
                        obj = register_contract_execution(
                            request.user, form.cleaned_data['contrato'].pk,
                            item_id=form.cleaned_data['item_contrato'].pk if form.cleaned_data['item_contrato'] else None,
                            quantity=form.cleaned_data['quantidade'], value=form.cleaned_data['valor'],
                            description=form.cleaned_data['descricao'], kind=form.cleaned_data['tipo'],
                            reference=form.cleaned_data['referencia'],
                        )
                    elif action == 'aditivo':
                        obj = register_contract_amendment(
                            request.user, form.cleaned_data['contrato'].pk, data=form.cleaned_data,
                        )
                    elif action.startswith('documento_'):
                        import hashlib
                        from pathlib import PurePosixPath
                        from operacao.models import Documento
                        uploaded = form.cleaned_data['arquivo']
                        digest = hashlib.sha256()
                        for chunk in uploaded.chunks():
                            digest.update(chunk)
                        uploaded.seek(0)
                        extension = PurePosixPath(uploaded.name).suffix.lower()
                        document_type = {
                            '.pdf': 'PDF', '.png': 'IMAGEM', '.jpg': 'IMAGEM',
                            '.jpeg': 'IMAGEM', '.webp': 'IMAGEM', '.xml': 'FISCAL_XML',
                        }[extension]
                        category = 'CONTRATO' if form.cleaned_data['categoria'] in {'CONTRATO', 'ADITIVO', 'ATA'} else 'OUTRO'
                        document = Documento.objects.create(
                            organization=current_organization(), titulo=form.cleaned_data['titulo'],
                            tipo=document_type, arquivo=uploaded, categoria=category,
                            sha256=digest.hexdigest(), enviado_por=request.user,
                            disponivel_portal=False,
                        )
                        uploaded_document = document
                        target_field = {
                            'documento_solicitacao': 'solicitacao',
                            'documento_processo': 'processo',
                            'documento_contrato': 'contrato',
                        }[action]
                        obj = procurement.DocumentoContratacaoMunicipal(
                            organization=current_organization(), documento=document,
                            categoria=form.cleaned_data['categoria'],
                            **{target_field: form.cleaned_data['alvo']},
                        )
                        obj.save()
                        audit_public(request.user, 'COMPRAS_DOCUMENTO_ANEXADO', obj,
                                     {'documento': document.pk, 'categoria': obj.categoria})
                    else:
                        obj = form.save(commit=False)
                        obj.organization = current_organization()
                        _actor_fields(obj, request.user)
                        obj.save()
                        _history(request.user, 'REGISTRO_CRIADO', obj,
                                 after={'tipo': action, 'id': obj.pk})
                        audit_public(request.user, 'COMPRAS_REGISTRO_CRIADO', obj,
                                     {'tipo': action, 'identificador': str(obj.pk)})
                messages.success(request, f'{form_title} registrado com trilha de auditoria.')
                return redirect(reverse('rh_municipal_public:compras_module', kwargs={'family': family}))
            except (ValidationError, IntegrityError) as exc:
                if uploaded_document and uploaded_document.arquivo:
                    try:
                        uploaded_document.arquivo.delete(save=False)
                    except OSError:
                        pass
                form_error = '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Registro duplicado ou vínculo incompatível; confira os dados e tente novamente.'

    search = request.GET.get('q', '').strip()[:100]
    sections = []
    for title, model, fields in config['sections']:
        rows = _rows(request.user, model, fields, search=search)
        sections.append({'title': title, 'rows': rows, 'model': model})
    requests = scoped_queryset(request.user, procurement.SolicitacaoCompra.objects.all())
    processes = scoped_queryset(request.user, procurement.ProcessoContratacaoMunicipal.objects.all())
    contracts = scoped_queryset(request.user, procurement.ContratoPublicoMunicipal.objects.all())
    alerts = []
    today = __import__('django.utils.timezone', fromlist=['localdate']).localdate()
    if family == 'contratos':
        for contract in contracts.filter(status=procurement.ContratoPublicoMunicipal.Status.VIGENTE, fim_vigencia__isnull=False, fim_vigencia__lte=today + __import__('datetime').timedelta(days=60))[:20]:
            alerts.append({'label': f'Contrato {contract.numero} próximo do vencimento', 'date': contract.fim_vigencia})
    price_maps = []
    if family == 'compras':
        for research in scoped_queryset(request.user, procurement.PesquisaPrecoMunicipal.objects.all()).prefetch_related('cotacoes__itens')[:30]:
            price_maps.append({'research': research, 'items': price_comparison(research)})
    links = [
        {'title': title, 'url': f"{reverse(f'rh_municipal_public:{config['route']}')}?novo={key}"}
        for key in config['actions'] for title, model, fields in [MODEL_ACTIONS.get(key, {
            'ata_uso': ('Registrar utilização da Ata', None, ()),
            'execucao': ('Registrar execução contratual', None, ()),
        }.get(key, (key, None, ())))]
        if has_municipal_permission(request.user, ACTION_MODULE_PERMISSION[key][1], module=ACTION_MODULE_PERMISSION[key][0])
    ]
    request_actions = {}
    if family == 'compras':
        labels = {
            procurement.SolicitacaoCompra.Status.ENVIADA: ('Enviar para análise', 'compras.manage'),
            procurement.SolicitacaoCompra.Status.EM_ANALISE: ('Iniciar análise', 'compras.manage'),
            procurement.SolicitacaoCompra.Status.APROVADA: ('Aprovar', 'compras.approve'),
            procurement.SolicitacaoCompra.Status.REJEITADA: ('Rejeitar', 'compras.approve'),
            procurement.SolicitacaoCompra.Status.EM_CONTRATACAO: ('Encaminhar para contratação', 'compras.manage'),
            procurement.SolicitacaoCompra.Status.CONCLUIDA: ('Concluir', 'compras.manage'),
            procurement.SolicitacaoCompra.Status.CANCELADA: ('Cancelar', 'compras.manage'),
        }
        for purchase in requests[:60]:
            request_actions[purchase.pk] = [
                (target, labels[target][0])
                for target in STATUS_REQUEST_TRANSITIONS.get(purchase.status, set())
                if has_municipal_permission(
                    request.user, labels[target][1], module='compras_publicas', record=purchase,
                )
            ]
    process_actions = {}
    if family == 'licitacoes':
        labels = {
            procurement.ProcessoContratacaoMunicipal.Status.EM_PLANEJAMENTO: ('Planejar', 'licitacao.manage'),
            procurement.ProcessoContratacaoMunicipal.Status.PUBLICADO: ('Publicar', 'licitacao.manage'),
            procurement.ProcessoContratacaoMunicipal.Status.EM_DISPUTA: ('Abrir disputa', 'licitacao.manage'),
            procurement.ProcessoContratacaoMunicipal.Status.EM_JULGAMENTO: ('Iniciar julgamento', 'licitacao.judge'),
            procurement.ProcessoContratacaoMunicipal.Status.EM_HABILITACAO: ('Iniciar habilitação', 'licitacao.judge'),
            procurement.ProcessoContratacaoMunicipal.Status.EM_RECURSO: ('Abrir recurso', 'licitacao.judge'),
            procurement.ProcessoContratacaoMunicipal.Status.ADJUDICADO: ('Adjudicar', 'licitacao.homologate'),
            procurement.ProcessoContratacaoMunicipal.Status.HOMOLOGADO: ('Homologar', 'licitacao.homologate'),
            procurement.ProcessoContratacaoMunicipal.Status.FRACASSADO: ('Registrar fracasso', 'licitacao.manage'),
            procurement.ProcessoContratacaoMunicipal.Status.REVOGADO: ('Revogar', 'licitacao.manage'),
            procurement.ProcessoContratacaoMunicipal.Status.CANCELADO: ('Cancelar', 'licitacao.manage'),
        }
        for process in processes[:60]:
            process_actions[process.pk] = [
                (target, labels[target][0])
                for target in STATUS_PROCESS_TRANSITIONS.get(process.status, set())
                if has_municipal_permission(
                    request.user, labels[target][1], module='licitacoes_publicas', record=process,
                )
            ]
    request_rows = list(requests[:60])
    process_rows = list(processes[:60])
    for row in request_rows:
        row.available_actions = request_actions.get(row.pk, [])
    for row in process_rows:
        row.available_actions = process_actions.get(row.pk, [])
    from .phase_b_models import HistoricoContratacaoPublica
    history_query = Q(pk__in=[])
    for section in sections:
        visible_ids = [row['object'].pk for row in section['rows']]
        if visible_ids:
            history_query |= Q(entidade=section['model']._meta.label_lower, registro_id__in=visible_ids)
    history = list(scoped_queryset(
        request.user, HistoricoContratacaoPublica.objects.filter(history_query),
    ).select_related('usuario').order_by('-criado_em', '-pk')[:40])
    return render(request, 'rh_municipal/procurement_module.html', {
        **_public_context(request), 'family': family, 'config': config,
        'sections': sections, 'form': form, 'form_title': form_title,
        'form_error': form_error, 'home_url': reverse(f"rh_municipal_public:{config['route']}"),
        'links': links, 'can_manage': can_manage, 'requests': request_rows,
        'processes': process_rows, 'contracts': contracts[:60],
        'request_actions': request_actions, 'process_actions': process_actions,
        'price_maps': price_maps, 'alerts': alerts, 'history': history, 'search': search,
    })


@login_required
@require_http_methods(['POST'])
def procurement_transition(request, family, kind, pk):
    try:
        if family == 'compras' and kind == 'solicitacao':
            target = request.POST.get('status')
            row = transition_purchase_request(request.user, pk, target, reason=request.POST.get('motivo', ''))
        elif family == 'licitacoes' and kind == 'processo':
            target = request.POST.get('status')
            row = transition_procurement_process(request.user, pk, target, reason=request.POST.get('motivo', ''))
        else:
            raise PermissionDenied('Ação de workflow inválida.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        route = SCREENS[family]['route']
        return redirect(f'rh_municipal_public:{route}')
    messages.success(request, f'Etapa registrada: {row.get_status_display()}.')
    return redirect(f"rh_municipal_public:{SCREENS[family]['route']}")


@login_required
def procurement_document(request, pk):
    link = scoped_queryset(request.user, procurement.DocumentoContratacaoMunicipal.objects.select_related(
        'documento', 'solicitacao', 'processo', 'contrato',
    )).filter(pk=pk).first()
    if link is None:
        raise Http404
    if link.solicitacao_id:
        capability, module = 'compras.view', 'compras_publicas'
    elif link.processo_id:
        capability, module = 'licitacao.view', 'licitacoes_publicas'
    else:
        capability, module = 'contract.documents', 'contratos_publicos'
    require_municipal_permission(request.user, capability, module=module, record=link)
    try:
        stream = link.documento.arquivo.open('rb')
    except (OSError, ValueError):
        raise Http404
    response = FileResponse(stream, as_attachment=True, filename=link.documento.titulo)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


def _public_context(request):
    from .public_views import _context
    return _context(request)

