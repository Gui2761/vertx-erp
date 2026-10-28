"""Audited, tenant-scoped services for public procurement workflows."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from platform_core.context import current_organization

from .phase_b_models import (
    AditivoContratoPublico, AtaRegistroPrecosMunicipal, ContratoPublicoMunicipal,
    ExecucaoContratoPublico, HistoricoContratacaoPublica,
    ItemAtaRegistroPrecosMunicipal, ItemContratoPublicoMunicipal,
    ItemContratacaoMunicipal, ItemSolicitacaoCompra,
    ProcessoContratacaoMunicipal, SolicitacaoCompra,
    UtilizacaoAtaPrecosMunicipal,
)
from .public_services import audit_public, require_municipal_permission, scoped_queryset


STATUS_REQUEST_TRANSITIONS = {
    SolicitacaoCompra.Status.RASCUNHO: {SolicitacaoCompra.Status.ENVIADA, SolicitacaoCompra.Status.CANCELADA},
    SolicitacaoCompra.Status.ENVIADA: {SolicitacaoCompra.Status.EM_ANALISE, SolicitacaoCompra.Status.CANCELADA},
    SolicitacaoCompra.Status.EM_ANALISE: {SolicitacaoCompra.Status.APROVADA, SolicitacaoCompra.Status.REJEITADA},
    SolicitacaoCompra.Status.APROVADA: {SolicitacaoCompra.Status.EM_CONTRATACAO, SolicitacaoCompra.Status.CANCELADA},
    SolicitacaoCompra.Status.REJEITADA: set(),
    SolicitacaoCompra.Status.EM_CONTRATACAO: {SolicitacaoCompra.Status.CONCLUIDA, SolicitacaoCompra.Status.CANCELADA},
    SolicitacaoCompra.Status.CONCLUIDA: set(),
    SolicitacaoCompra.Status.CANCELADA: set(),
}

STATUS_PROCESS_TRANSITIONS = {
    ProcessoContratacaoMunicipal.Status.RASCUNHO: {ProcessoContratacaoMunicipal.Status.EM_PLANEJAMENTO, ProcessoContratacaoMunicipal.Status.CANCELADO},
    ProcessoContratacaoMunicipal.Status.EM_PLANEJAMENTO: {ProcessoContratacaoMunicipal.Status.PUBLICADO, ProcessoContratacaoMunicipal.Status.CANCELADO},
    ProcessoContratacaoMunicipal.Status.PUBLICADO: {ProcessoContratacaoMunicipal.Status.EM_DISPUTA, ProcessoContratacaoMunicipal.Status.REVOGADO},
    ProcessoContratacaoMunicipal.Status.EM_DISPUTA: {ProcessoContratacaoMunicipal.Status.EM_JULGAMENTO, ProcessoContratacaoMunicipal.Status.FRACASSADO},
    ProcessoContratacaoMunicipal.Status.EM_JULGAMENTO: {ProcessoContratacaoMunicipal.Status.EM_HABILITACAO, ProcessoContratacaoMunicipal.Status.EM_RECURSO, ProcessoContratacaoMunicipal.Status.FRACASSADO},
    ProcessoContratacaoMunicipal.Status.EM_HABILITACAO: {ProcessoContratacaoMunicipal.Status.EM_RECURSO, ProcessoContratacaoMunicipal.Status.ADJUDICADO, ProcessoContratacaoMunicipal.Status.FRACASSADO},
    ProcessoContratacaoMunicipal.Status.EM_RECURSO: {ProcessoContratacaoMunicipal.Status.EM_JULGAMENTO, ProcessoContratacaoMunicipal.Status.ADJUDICADO},
    ProcessoContratacaoMunicipal.Status.ADJUDICADO: {ProcessoContratacaoMunicipal.Status.HOMOLOGADO},
    ProcessoContratacaoMunicipal.Status.HOMOLOGADO: {ProcessoContratacaoMunicipal.Status.CONCLUIDO},
    ProcessoContratacaoMunicipal.Status.FRACASSADO: set(),
    ProcessoContratacaoMunicipal.Status.REVOGADO: set(),
    ProcessoContratacaoMunicipal.Status.CONCLUIDO: set(),
    ProcessoContratacaoMunicipal.Status.CANCELADO: set(),
}


def _history(actor, event, record, *, before=None, after=None, reason=''):
    row = HistoricoContratacaoPublica(
        entidade=record._meta.label_lower, registro_id=record.pk, evento=event,
        antes=before or {}, depois=after or {}, justificativa=reason,
        usuario=actor, organization=current_organization(),
    )
    row._service_write = True
    row.save()
    audit_public(actor, f'COMPRAS_{event}', record, {'status_antes': before or {}, 'status_depois': after or {}})
    return row


@transaction.atomic
def transition_purchase_request(actor, public_id, target, *, reason=''):
    qs = scoped_queryset(actor, SolicitacaoCompra.objects.select_for_update())
    try:
        request = qs.get(public_id=public_id)
    except (SolicitacaoCompra.DoesNotExist, AttributeError):
        # Older schemas may not expose public_id; the fallback still remains
        # inside the active tenant and authorization scope.
        try:
            request = qs.get(pk=public_id)
        except SolicitacaoCompra.DoesNotExist as exc:
            raise ValidationError('Solicitação não encontrada no seu escopo.') from exc
    if target in {SolicitacaoCompra.Status.APROVADA, SolicitacaoCompra.Status.REJEITADA}:
        require_municipal_permission(actor, 'compras.approve', module='compras_publicas', record=request)
        if not reason.strip():
            raise ValidationError('Informe a justificativa da aprovação ou rejeição.')
    else:
        require_municipal_permission(actor, 'compras.manage', module='compras_publicas', record=request)
    if target not in STATUS_REQUEST_TRANSITIONS.get(request.status, set()):
        raise ValidationError('A transição solicitada não é permitida para a situação atual.')
    old = request.status
    request.status = target
    if target == SolicitacaoCompra.Status.ENVIADA:
        request.enviado_em = timezone.now()
    if target in {SolicitacaoCompra.Status.APROVADA, SolicitacaoCompra.Status.REJEITADA}:
        request.decidido_por = actor
        request.decidido_em = timezone.now()
        request.motivo_decisao = reason.strip()
    request.save()
    _history(actor, f'SOLICITACAO_{target}', request, before={'status': old}, after={'status': target}, reason=reason)
    return request


@transaction.atomic
def create_process_from_request(actor, request_id, *, number, exercise, modality, responsible=None):
    require_municipal_permission(actor, 'licitacao.manage', module='licitacoes_publicas')
    request = scoped_queryset(actor, SolicitacaoCompra.objects.select_for_update()).get(pk=request_id)
    if request.status != SolicitacaoCompra.Status.APROVADA:
        raise ValidationError('Somente solicitações aprovadas podem gerar processo de contratação.')
    items = list(ItemSolicitacaoCompra.objects.filter(solicitacao=request).order_by('pk'))
    if not items:
        raise ValidationError('Inclua ao menos um item antes de gerar o processo.')
    process = ProcessoContratacaoMunicipal(
        organization=request.organization, numero=number, exercicio=exercise,
        solicitacao=request, secretaria=request.secretaria, unidade=request.unidade,
        objeto='; '.join(item.descricao for item in items)[:400],
        justificativa=request.justificativa, modalidade=modality,
        unidade_orcamentaria=request.unidade_orcamentaria, dotacao=request.dotacao,
        fonte_recurso=request.fonte_recurso,
        valor_estimado=sum((item.estimativa_total or Decimal('0')) for item in items),
        responsavel=responsible or actor, criado_por=actor,
    )
    process.save()
    for number_index, item in enumerate(items, start=1):
        ItemContratacaoMunicipal(
            organization=request.organization, processo=process, solicitacao_item=item,
            numero=number_index, descricao=item.descricao, especificacao=item.especificacao,
            quantidade=item.quantidade, unidade_medida=item.unidade_medida,
            valor_estimado_unitario=item.estimativa_unitaria or Decimal('0'),
        ).save()
    previous_status = request.status
    request.status = SolicitacaoCompra.Status.EM_CONTRATACAO
    request.save(update_fields=['status', 'atualizado_em'])
    _history(actor, 'SOLICITACAO_EM_CONTRATACAO', request,
             before={'status': previous_status}, after={'status': request.status},
             reason=f'Processo {number}/{exercise} criado a partir da solicitação.')
    _history(actor, 'PROCESSO_CRIADO', process, after={'solicitacao': request.pk, 'numero': number})
    return process


@transaction.atomic
def transition_procurement_process(actor, process_id, target, *, reason=''):
    process = scoped_queryset(actor, ProcessoContratacaoMunicipal.objects.select_for_update()).get(pk=process_id)
    if target in {ProcessoContratacaoMunicipal.Status.ADJUDICADO, ProcessoContratacaoMunicipal.Status.HOMOLOGADO}:
        require_municipal_permission(actor, 'licitacao.homologate', module='licitacoes_publicas', record=process)
    elif target in {ProcessoContratacaoMunicipal.Status.EM_JULGAMENTO, ProcessoContratacaoMunicipal.Status.EM_HABILITACAO, ProcessoContratacaoMunicipal.Status.EM_RECURSO}:
        require_municipal_permission(actor, 'licitacao.judge', module='licitacoes_publicas', record=process)
    else:
        require_municipal_permission(actor, 'licitacao.manage', module='licitacoes_publicas', record=process)
    if target not in STATUS_PROCESS_TRANSITIONS.get(process.status, set()):
        raise ValidationError('Etapa incompatível com o estado atual do processo.')
    if not reason.strip():
        raise ValidationError('Informe a justificativa da mudança de etapa para registro da trilha.')
    old = process.status
    process.status = target
    process.save(update_fields=['status'])
    _history(actor, f'PROCESSO_{target}', process, before={'status': old}, after={'status': target}, reason=reason)
    return process


@transaction.atomic
def register_contract_amendment(actor, contract_id, *, data):
    contract = scoped_queryset(actor, ContratoPublicoMunicipal.objects.select_for_update()).get(pk=contract_id)
    require_municipal_permission(actor, 'contract.approve', module='contratos_publicos', record=contract)
    if contract.status in {ContratoPublicoMunicipal.Status.ENCERRADO, ContratoPublicoMunicipal.Status.RESCINDIDO}:
        raise ValidationError('Contrato encerrado ou rescindido não aceita novos aditivos.')
    amendment = AditivoContratoPublico(
        organization=current_organization(), contrato=contract,
        tipo=data['tipo'], numero=data['numero'],
        valor_anterior=contract.valor, valor_novo=data.get('valor_novo'),
        fim_vigencia_anterior=contract.fim_vigencia, fim_vigencia_novo=data.get('fim_vigencia_novo'),
        fundamento=data.get('fundamento', ''), observacoes=data.get('observacoes', ''),
        criado_por=actor,
    )
    amendment._service_write = True
    amendment.save()
    before = {'valor': str(contract.valor), 'fim_vigencia': str(contract.fim_vigencia or '')}
    fields = []
    if amendment.valor_novo is not None and amendment.tipo in {
        AditivoContratoPublico.Tipo.ADITIVO, AditivoContratoPublico.Tipo.REAJUSTE,
        AditivoContratoPublico.Tipo.REPACTUACAO,
    }:
        contract.valor = amendment.valor_novo
        fields.append('valor')
    if amendment.fim_vigencia_novo is not None and amendment.tipo == AditivoContratoPublico.Tipo.PRORROGACAO:
        if contract.fim_vigencia and amendment.fim_vigencia_novo < contract.fim_vigencia:
            raise ValidationError('A prorrogação não pode reduzir a vigência atual.')
        contract.fim_vigencia = amendment.fim_vigencia_novo
        fields.append('fim_vigencia')
    if amendment.tipo in {AditivoContratoPublico.Tipo.ENCERRAMENTO, AditivoContratoPublico.Tipo.RESCISAO}:
        contract.status = (ContratoPublicoMunicipal.Status.ENCERRADO if amendment.tipo == AditivoContratoPublico.Tipo.ENCERRAMENTO
                           else ContratoPublicoMunicipal.Status.RESCINDIDO)
        fields.append('status')
    if fields:
        contract.save(update_fields=fields)
    _history(actor, f'CONTRATO_{amendment.tipo}', contract, before=before,
             after={'valor': str(contract.valor), 'fim_vigencia': str(contract.fim_vigencia or ''), 'status': contract.status},
             reason=amendment.fundamento)
    return amendment


def price_comparison(research):
    """Return descriptive quote statistics; the result is not a legal award."""
    grouped = {}
    for line in research.cotacoes.select_related('fornecedor').prefetch_related('itens'):
        for item in line.itens.all():
            key = (item.descricao, item.unidade_medida, item.quantidade)
            grouped.setdefault(key, []).append({
                'supplier': line.fornecedor.nome,
                'unit_price': item.preco_unitario,
                'total': item.preco_total,
                'source': line.fonte or line.documento_referencia,
                'date': line.data,
            })
    result = []
    for (description, unit, quantity), values in grouped.items():
        prices = sorted(row['unit_price'] for row in values)
        n = len(prices)
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
        result.append({
            'description': description, 'unit': unit, 'quantity': quantity,
            'quotes': values, 'minimum': prices[0], 'maximum': prices[-1],
            'mean': sum(prices) / Decimal(n), 'median': median,
        })
    return result


@transaction.atomic
def register_price_registry_usage(actor, item_id, *, quantity, unit, reference=''):
    require_municipal_permission(actor, 'price_registry.manage', module='registro_precos')
    item = scoped_queryset(actor, ItemAtaRegistroPrecosMunicipal.objects.select_for_update().select_related('ata')).get(pk=item_id)
    require_municipal_permission(actor, 'price_registry.manage', module='registro_precos', record=item)
    if reference:
        existing = UtilizacaoAtaPrecosMunicipal.objects.filter(
            organization=current_organization(), referencia=reference,
        ).first()
        if existing:
            if existing.item_ata_id != item.pk or existing.quantidade != quantity:
                raise ValidationError('Referência de utilização já usada em outra operação.')
            return existing
    ata = item.ata
    today = timezone.localdate()
    if ata.status != AtaRegistroPrecosMunicipal.Status.VIGENTE or not (ata.inicio_vigencia <= today <= ata.fim_vigencia):
        raise ValidationError('A Ata não está vigente na data atual.')
    if unit and unit.organization_id != current_organization().pk:
        raise PermissionDenied('Unidade de outra Prefeitura.')
    if quantity <= 0 or quantity > item.saldo:
        raise ValidationError('Quantidade solicitada excede o saldo disponível da Ata.')
    amount = (quantity * item.valor_unitario).quantize(Decimal('0.01'))
    usage = UtilizacaoAtaPrecosMunicipal(
        organization=current_organization(), item_ata=item, unidade=unit,
        quantidade=quantity, valor_total=amount, referencia=reference,
        criado_por=actor,
    )
    usage._service_write = True
    usage.save()
    item.quantidade_utilizada += quantity
    item.save(update_fields=['quantidade_utilizada'])
    _history(actor, 'ATA_UTILIZADA', item, before={'saldo': str(item.saldo + quantity)}, after={'saldo': str(item.saldo)})
    return usage


@transaction.atomic
def register_contract_execution(actor, contract_id, *, item_id=None, quantity, value, description, kind, reference=''):
    require_municipal_permission(actor, 'contract.execute', module='contratos_publicos')
    contract = scoped_queryset(actor, ContratoPublicoMunicipal.objects.select_for_update()).get(pk=contract_id)
    require_municipal_permission(actor, 'contract.execute', module='contratos_publicos', record=contract)
    item = None
    if item_id:
        item = ItemContratoPublicoMunicipal.objects.select_for_update().select_related('contrato').get(pk=item_id)
        if item.contrato_id != contract.pk:
            raise ValidationError('O item selecionado pertence a outro contrato.')
        require_municipal_permission(actor, 'contract.execute', module='contratos_publicos', record=item)
    if contract.status != ContratoPublicoMunicipal.Status.VIGENTE:
        raise ValidationError('Somente contrato vigente aceita registro de execução.')
    if reference and ExecucaoContratoPublico.objects.filter(contrato=contract, referencia=reference).exists():
        raise ValidationError('Referência de execução já registrada.')
    if item and quantity is not None and (quantity <= 0 or quantity > item.saldo_quantidade):
        raise ValidationError('A quantidade excede o saldo contratual do item.')
    if value is not None:
        already_executed = ExecucaoContratoPublico.objects.filter(contrato=contract).aggregate(
            total=Sum('valor'),
        )['total'] or Decimal('0.00')
        if already_executed + value > contract.valor:
            raise ValidationError('O valor da execução excede o saldo financeiro do contrato.')
    row = ExecucaoContratoPublico(
        organization=current_organization(), contrato=contract, item_contrato=item,
        tipo=kind, referencia=reference, quantidade=quantity, valor=value,
        descricao=description, criado_por=actor,
    )
    row._service_write = True
    row.save()
    if item and quantity is not None:
        item.quantidade_utilizada += quantity
        item.save(update_fields=['quantidade_utilizada'])
    _history(actor, 'EXECUCAO_REGISTRADA', contract, after={'item': item.pk if item else None, 'quantidade': str(quantity), 'valor': str(value)})
    return row

