import uuid
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from platform_core.context import current_organization
from platform_core.models import PlatformAudit, ERPCatalog
from ordens.models import OrdemServico, Status
from ordens import services as os_services
from . import models as m
from .permissions import require, allowed


def audit(user, action, instance, changes=None):
    PlatformAudit.objects.create(organization=current_organization(), erp=ERPCatalog.objects.get(code='assistencia'), user=user, action=action, record=f'{instance._meta.label}:{instance.pk}', changes=changes or {})
    from operacao.notifications import event
    event(user, action, instance)


def write(instance):
    instance._service_write = True
    try:
        instance.save()
    finally:
        instance._service_write = False
    return instance


@transaction.atomic
def movimentar(user, peca_id, tipo, quantidade, observacao='', ordem_id=None, request_id=None, origem_id=None, destino_id=None, lote_data=None, lote_id=None, venda_id=None):
    from operacao.commerce_scope import _authorized
    commerce = _authorized(user,'stock',sale_id=venda_id,part_id=peca_id,kind=tipo,depot_id=origem_id)
    from operacao.purchase_scope import _authorized as purchase_authorized
    commerce = commerce or purchase_authorized(user,peca_id,tipo,Decimal(quantidade),destino_id,lote_data)
    if not commerce:
        require(user, 'estoque')
    quantity = Decimal(quantidade)
    if not quantity.is_finite() or quantity < 0 or quantity == 0 and tipo not in ['AJUSTE','INVENTARIO'] or quantity.as_tuple().exponent < -3:
        raise ValidationError('Quantidade inválida. Use até três casas decimais.')
    if tipo not in set(m.Movimentacao.Tipo.values) | {m.Movimentacao.TIPO_PERDA}:
        raise ValidationError('Tipo de movimentação inválido.')
    order = OrdemServico.objects.select_for_update().get(pk=ordem_id) if ordem_id else None
    if order and tipo in ['OS', 'DEVOLUCAO']:
        from operacao.contract_workday import link_order
        link_order(user, order)
    from platform_core.access import effective_role
    if not commerce and (effective_role(user) == 'TECNICO' or not allowed(user, 'estoque_escrever')):
        if tipo not in ['OS', 'DEVOLUCAO'] or order is None:
            raise PermissionDenied('Técnico registra somente utilização/devolução em suas OS.')
        os_services.autorizar(user, order)
    if tipo == 'OS' and order is None:
        raise ValidationError('Utilização exige OS relacionada.')
    if order and order.status in [Status.FINALIZADA, Status.APROVADA, Status.FATURADA, Status.CANCELADA]:
        raise ValidationError('OS finalizada é imutável; reabra pelo fluxo auditado.')
    if tipo == 'AJUSTE' and not observacao.strip():
        raise ValidationError('Ajuste exige justificativa.')
    if tipo == m.Movimentacao.TIPO_PERDA and (not observacao.strip() or not lote_id):
        raise ValidationError('Perda exige motivo e seleção explícita do lote para rastreabilidade.')
    part = m.Peca.objects.select_for_update().get(pk=peca_id)
    if not part.fracionavel and quantity != quantity.to_integral_value():
        raise ValidationError('Produto não fracionável exige quantidade base inteira.')
    inventory_lot=None
    if tipo=='INVENTARIO':
        from operacao.inventory import authorized_count
        from operacao.models import LoteEstoque
        if not authorized_count(user,part.pk,lote_id,quantity):
            raise PermissionDenied('Ajuste de inventário exige aprovação da contagem.')
        inventory_lot=LoteEstoque.objects.select_for_update().get(pk=lote_id,peca=part)
        if (origem_id or destino_id)!=inventory_lot.deposito_id:
            raise ValidationError('Lote não pertence ao depósito do inventário.')
    if tipo == 'TRANSFER' and ordem_id:
        raise ValidationError('Transferência física não representa utilização em OS.')
    token = request_id or uuid.uuid4()
    from operacao.stock import movement_parameters
    parameters = movement_parameters(lote_data, lote_id, venda_id)
    previous = m.Movimentacao.objects.filter(request_id=token).first()
    if previous:
        if (previous.peca_id, previous.tipo, previous.quantidade, previous.ordem_id, previous.usuario_id) != (part.pk, tipo, quantity, ordem_id, user.pk):
            raise ValidationError('Identificador de operação já usado com outros dados.')
        if origem_id is not None and previous.origem_id != int(origem_id) or destino_id is not None and previous.destino_id != int(destino_id):
            raise ValidationError('Identificador já usado para outros depósitos.')
        if previous.detalhamento != parameters:
            raise ValidationError('Identificador já usado para outro lote/origem de estoque.')
        return previous
    if not part.ativo:
        raise ValidationError('Peça inativa não pode ser movimentada.')
    if tipo == 'DEVOLUCAO' and order:
        used = -(m.Movimentacao.objects.filter(peca=part, ordem=order, tipo__in=['OS', 'DEVOLUCAO']).aggregate(total=Sum('variacao'))['total'] or m.ZERO)
        if quantity > used:
            raise ValidationError('Devolução excede a quantidade utilizada nessa OS.')
    if tipo == 'TRANSFER' and (not origem_id or not destino_id):
        raise ValidationError('Transferência exige origem e destino.')
    from operacao.services import saldo_movimentar
    from operacao.stock import ensure_lots, move_lots
    ensure_lots(part)
    if tipo == 'AJUSTE' and (origem_id or destino_id):
        raise ValidationError('Ajuste global usa o depósito Principal. Para redistribuir, use transferência.')
    delta = quantity - part.quantidade_atual if tipo == 'AJUSTE' else m.ZERO if tipo == 'TRANSFER' else -quantity if tipo in ['SAIDA', 'OS', m.Movimentacao.TIPO_PERDA] else quantity
    if inventory_lot is not None:
        delta=quantity-inventory_lot.quantidade
    balance = part.quantidade_atual + delta
    if balance < 0:
        raise ValidationError('Estoque insuficiente; saldo negativo não é permitido.')
    source, target = saldo_movimentar(part, delta, origem_id, destino_id, tipo == 'TRANSFER', quantity)
    before_balance = part.quantidade_atual
    part.quantidade_atual = balance
    part._stock_write = True
    part.save()
    movement = m.Movimentacao(peca=part, origem=source, destino=target, tipo=tipo, quantidade=quantity, variacao=delta, saldo_apos=balance, custo_unitario=Decimal(lote_data['custo_unitario']) if lote_data and 'custo_unitario' in lote_data else part.custo_aquisicao, preco_unitario=part.preco_venda, ordem=order, usuario=user, observacao=observacao, request_id=token, detalhamento=parameters)
    from operacao.stock import planned_cost
    movement.custo_total = planned_cost(part, movement, lote_data, lote_id, venda_id)
    cost_quantity = quantity if tipo == 'TRANSFER' else abs(delta)
    if cost_quantity:
        movement.custo_unitario = (movement.custo_total / cost_quantity).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    movement = write(movement)
    move_lots(user, part, movement, lote_data, lote_id, venda_id)
    details = movement.lotes_movimentados.all()
    if tipo == 'TRANSFER':
        details = details.filter(variacao__lt=0)
    if sum((row.custo_total for row in details), m.ZERO) != movement.custo_total:
        raise ValidationError('Custo dos lotes diverge do planejamento; operação revertida.')
    if order:
        order.revisao += 1
        order.save()
        os_services.auditar(order, user, 'MOVIMENTACAO_ESTOQUE', {'movimentacao': movement.pk, 'sku': part.sku, 'quantidade': str(quantity), 'variacao': str(delta)})
    audit(user, 'ESTOQUE_MOVIMENTADO', movement, {'quantidade': str(quantity), 'variacao': str(delta), 'saldo': {'anterior': str(before_balance), 'posterior': str(balance)}})
    return movement


def pecas_snapshot(ordem):
    return [{'sku': mov.peca.sku, 'descricao': mov.peca.descricao, 'tipo': mov.tipo, 'quantidade': str(mov.quantidade), 'variacao': str(mov.variacao), 'movimentacao': mov.pk, 'custo_total':str(mov.valor_custo), 'custo_legado_estimado':mov.custo_total is None, 'lotes':[{'id':row.lote_id,'numero':row.lote.numero,'quantidade':str(abs(row.variacao)),'custo_unitario':str(row.custo_unitario) if row.custo_unitario is not None else None,'custo_total':str(row.custo_total) if row.custo_total is not None else None} for row in mov.lotes_movimentados.all()]} for mov in m.Movimentacao.objects.filter(ordem=ordem, tipo__in=['OS', 'DEVOLUCAO']).select_related('peca').prefetch_related('lotes_movimentados__lote').order_by('pk')]


@transaction.atomic
def status_orcamento(user, pk, action):
    require(user, 'orcamentos')
    quote = m.Orcamento.objects.select_for_update().get(pk=pk)
    transitions = {'enviar': ('RASCUNHO', 'ENVIADO'), 'aprovar': ('ENVIADO', 'APROVADO'), 'recusar': ('ENVIADO', 'RECUSADO'), 'revisar': ('ENVIADO', 'RASCUNHO'), 'vencer': ('ENVIADO', 'VENCIDO'), 'cancelar': ('ENVIADO', 'CANCELADO')}
    if action not in transitions:
        raise ValidationError('Transição inválida.')
    source, target = transitions[action]
    if quote.status != source:
        raise ValidationError('Status não permite esta operação.')
    if action in ['enviar', 'aprovar']:
        if quote.situacao == 'VENCIDO' or not quote.itens.exists() or quote.total <= 0:
            raise ValidationError('Revise validade, itens e desconto antes de enviar/aprovar.')
    if action == 'vencer' and quote.validade >= timezone.localdate():
        raise ValidationError('Validade ainda não venceu.')
    quote.status = target
    write(quote)
    if target == 'APROVADO' and quote.gerar_recebivel:
        gerar_do_orcamento(user, quote)
    audit(user, 'ORCAMENTO_' + target, quote)
    return quote


@transaction.atomic
def salvar_item(user, form, quote_id):
    require(user, 'orcamentos')
    quote = m.Orcamento.objects.select_for_update().get(pk=quote_id)
    if quote.status != 'RASCUNHO':
        raise ValidationError('Somente orçamento rascunho aceita alteração de itens.')
    form.instance.orcamento = quote
    item = form.save()
    audit(user, 'ITEM_ORCAMENTO_SALVO', item)
    return item


@transaction.atomic
def remover_item(user, pk):
    require(user, 'orcamentos')
    item = m.ItemOrcamento.objects.get(pk=pk)
    quote = m.Orcamento.objects.select_for_update().get(pk=item.orcamento_id)
    if quote.status != 'RASCUNHO':
        raise ValidationError('Somente orçamento rascunho aceita remoção de itens.')
    audit(user, 'ITEM_ORCAMENTO_REMOVIDO', item, {'descricao': item.descricao})
    item.delete()


@transaction.atomic
def converter_orcamento(user, pk, tecnico_id):
    from contas.models import Tecnico
    require(user, 'orcamentos')
    quote = m.Orcamento.objects.select_for_update().get(pk=pk)
    from operacao.models import Venda
    if Venda.objects.filter(orcamento_origem=quote).exists():
        raise ValidationError('Orçamento já convertido em venda; não pode gerar outra operação.')
    if quote.status == 'CONVERTIDO' and quote.ordem_convertida_id:
        return quote.ordem_convertida
    if quote.status != 'APROVADO' or not quote.equipamento_id:
        raise ValidationError('Conversão exige orçamento aprovado com equipamento.')
    tech = Tecnico.objects.get(pk=tecnico_id, ativo=True)
    items = list(quote.itens.all())
    service_text = '\n'.join([quote.servicos] + [f'{i.descricao} ({i.quantidade})' for i in items if i.tipo == 'SERVICO']).strip()
    parts_text = '\n'.join(f'{i.descricao} ({i.quantidade})' for i in items if i.tipo == 'PECA')
    billed = quote.lancamentos.filter(tipo='RECEBER').exists()
    value = m.ZERO if billed else quote.total
    if quote.ordem_id:
        order = OrdemServico.objects.select_for_update().get(pk=quote.ordem_id)
        if order.status in ['FINALIZADA','APROVADA','FATURADA','CANCELADA']:
            raise ValidationError('OS vinculada já foi finalizada.')
        order.tecnico = tech
        order.diagnostico = quote.diagnostico or order.diagnostico
        order.servico_executado = service_text or order.servico_executado
        order.pecas = parts_text or order.pecas
        order.valor_cobranca = value
        order.revisao += 1
        order.save()
    else:
        order = OrdemServico.objects.create(cliente=quote.cliente, unidade=quote.unidade, equipamento=quote.equipamento, tecnico=tech, defeito=quote.diagnostico or f'Atendimento conforme {quote.numero}', diagnostico=quote.diagnostico, servico_executado=service_text, pecas=parts_text, observacoes=quote.observacoes, valor_cobranca=value, vencimento_cobranca=quote.validade)
        os_services.auditar(order, user, 'CRIACAO', os_services.snapshot(order))
    os_services.auditar(order, user, 'ORCAMENTO_CONVERTIDO', {'orcamento': quote.pk, 'total': str(quote.total)})
    quote.status, quote.ordem_convertida = 'CONVERTIDO', order
    write(quote)
    audit(user, 'ORCAMENTO_CONVERTIDO', quote, {'ordem': order.pk})
    return order


def datas_periodicas(inicio, fim, meses, limite=None):
    index = 0
    while True:
        date = inicio + relativedelta(months=index * meses)
        if date > fim or limite and index >= limite:
            return
        if index >= 1200:
            raise ValidationError('Período excede 1200 ocorrências; divida em contratos menores.')
        yield date
        index += 1


@transaction.atomic
def salvar_contrato(user, form):
    require(user, 'contratos')
    contract = form.save(commit=False)
    contract.save()
    for model, key, selected in [(m.ContratoUnidade, 'unidade', form.cleaned_data['unidades']), (m.ContratoEquipamento, 'equipamento', form.cleaned_data['equipamentos'])]:
        wanted = {obj.pk for obj in selected}
        links = model.objects.filter(contrato=contract)
        for link in list(links):
            if getattr(link, key + '_id') not in wanted:
                if key == 'equipamento' and contract.agenda.filter(equipamento_id=getattr(link, key + '_id')).exists():
                    raise ValidationError('Equipamento com planejamento registrado deve ser preservado no contrato.')
                link.delete()
        for obj in selected:
            model.objects.get_or_create(contrato=contract, **{key: obj})
    if contract.status not in ['SUSPENSO', 'ENCERRADO']:
        gerar_cobrancas(user, contract.pk)
        gerar_planejamento(user, contract.pk)
    audit(user, 'CONTRATO_SALVO', contract)
    return contract


@transaction.atomic
def gerar_planejamento(user, pk):
    require(user, 'contratos')
    contract = m.Contrato.objects.select_for_update().get(pk=pk)
    if contract.status in ['SUSPENSO', 'ENCERRADO']:
        raise ValidationError('Contrato suspenso/encerrado não gera planejamento.')
    dates = list(datas_periodicas(contract.data_inicial, contract.data_final, contract.periodicidade_preventiva_meses, contract.quantidade_visitas or None))
    for equipment in contract.equipamentos.all():
        for date in dates:
            m.AgendaPreventiva.objects.get_or_create(contrato=contract, equipamento=equipment, data_prevista=date)
    audit(user, 'PLANEJAMENTO_CONTRATO_GERADO', contract)


@transaction.atomic
def agendar_os(user, pk, tecnico_id):
    from contas.models import Tecnico
    require(user, 'contratos')
    agenda = m.AgendaPreventiva.objects.select_for_update().select_related('contrato', 'equipamento').get(pk=pk)
    if agenda.ordem_id:
        return agenda.ordem
    if agenda.situacao == 'CANCELADA':
        raise ValidationError('Planejamento cancelado/suspenso.')
    tech = Tecnico.objects.get(pk=tecnico_id, ativo=True)
    equipment = agenda.equipamento
    order = OrdemServico.objects.create(cliente=equipment.cliente, unidade=equipment.unidade, equipamento=equipment, tecnico=tech, tipo_atendimento='PREVENTIVA', defeito=f'Preventiva prevista em {agenda.data_prevista:%d/%m/%Y}, contrato {agenda.contrato.numero}', observacoes=agenda.contrato.observacoes)
    os_services.auditar(order, user, 'CRIACAO', os_services.snapshot(order))
    agenda.tecnico, agenda.ordem = tech, order
    agenda.save()
    audit(user, 'OS_PLANEJADA', agenda, {'ordem': order.pk})
    return order


def novo_recebivel(user, defaults, **origin):
    existing = m.Lancamento.objects.filter(tipo='RECEBER', **origin).first()
    if existing:
        return existing
    instance = write(m.Lancamento(tipo='RECEBER', criado_por=user, **defaults, **origin))
    audit(user, 'RECEBIVEL_AUTOMATICO', instance)
    return instance


def gerar_do_orcamento(user, quote):
    from operacao.models import Venda
    sale=Venda.objects.filter(orcamento_origem=quote).first()
    if sale:
        if sale.conta_id: return sale.conta
        raise ValidationError('Orçamento convertido em venda; recebível é gerado na finalização comercial.')
    if quote.ordem_id:
        order = OrdemServico.objects.select_for_update().get(pk=quote.ordem_id)
        if order.lancamentos.filter(tipo='RECEBER').exists():
            raise ValidationError('A OS vinculada já possui conta a receber; evite cobrança duplicada.')
    return novo_recebivel(user, {'descricao': quote.numero, 'cliente': quote.cliente, 'valor': quote.total, 'vencimento': quote.validade}, orcamento=quote)


@transaction.atomic
def gerar_da_os(user, ordem):
    # Chamado exclusivamente após autorizar/finalizar a OS pelo fluxo existente.
    os_services.autorizar(user, ordem)
    if ordem.status != Status.FINALIZADA or not ordem.valor_cobranca:
        return None
    if m.Orcamento.objects.filter(ordem_convertida=ordem, lancamentos__tipo='RECEBER').exists() or m.Orcamento.objects.filter(ordem=ordem, lancamentos__tipo='RECEBER').exists():
        return None
    return novo_recebivel(user, {'descricao': ordem.numero, 'cliente': ordem.cliente, 'valor': ordem.valor_cobranca, 'vencimento': ordem.vencimento_cobranca or timezone.localdate()}, ordem=ordem)


@transaction.atomic
def gerar_cobrancas(user, pk):
    require(user, 'contratos')
    contract = m.Contrato.objects.select_for_update().get(pk=pk)
    if contract.status in ['SUSPENSO', 'ENCERRADO']:
        raise ValidationError('Contrato suspenso/encerrado não gera cobranças.')
    if not contract.valor:
        return
    months = {'MENSAL': 1, 'TRIMESTRAL': 3, 'SEMESTRAL': 6, 'ANUAL': 12}
    dates = [contract.data_inicial] if contract.periodicidade_cobranca == 'UNICA' else list(datas_periodicas(contract.data_inicial, contract.data_final, months[contract.periodicidade_cobranca]))
    for date in dates:
        novo_recebivel(user, {'descricao': f'Contrato {contract.numero} · {date:%m/%Y}', 'cliente': contract.cliente, 'valor': contract.valor, 'vencimento': date}, contrato=contract, competencia=date)


@transaction.atomic
def liquidar(user, pk, data, observacao=''):
    from operacao.services import pagar
    entry = m.Lancamento.objects.select_for_update().get(pk=pk)
    pagar(user, pk, entry.saldo, data, observacao)
    return m.Lancamento.objects.get(pk=pk)


@transaction.atomic
def cancelar_lancamento(user, pk, observacao):
    require(user, 'financeiro_escrever')
    entry = m.Lancamento.objects.select_for_update().get(pk=pk)
    if entry.status not in ['PENDENTE', 'VENCIDO'] or not observacao.strip() or entry.pagamentos.exists():
        raise ValidationError('Cancelamento exige conta pendente e justificativa.')
    entry.status = 'CANCELADO'
    write(entry)
    write(m.EventoFinanceiro(lancamento=entry, tipo='CANCELAMENTO', valor=entry.valor, data=timezone.localdate(), usuario=user, observacao=observacao))
    audit(user, 'LANCAMENTO_CANCELADO', entry)
    return entry
