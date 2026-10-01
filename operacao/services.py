import copy
import hashlib
import uuid
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from contas.models import Tecnico
from ordens.models import OrdemServico, Status
from ordens import services as os_services
from gestao import models as g, services as gs
from gestao.permissions import require
from . import models as m

def positive(value):
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValidationError('Informe valor positivo com até dois decimais.')
    return amount

@transaction.atomic
def saldo_deposito(part):
    """Aloca o saldo legado sem gerar consumo/entrada fictícios."""
    principal, _ = m.Deposito.objects.get_or_create(nome='Principal')
    saldo = m.SaldoDeposito.objects.filter(deposito=principal, peca=part).first()
    if saldo is None:
        other = m.SaldoDeposito.objects.filter(peca=part).aggregate(total=Sum('quantidade'))['total'] or g.ZERO
        saldo = gs.write(m.SaldoDeposito(deposito=principal, peca=part, quantidade=part.quantidade_atual - other))
    return principal

def saldo_movimentar(part, delta, origem=None, destino=None, transferencia=False, quantidade=None):
    default = saldo_deposito(part)
    source = m.Deposito.objects.get(pk=origem, ativo=True) if origem else default
    target = m.Deposito.objects.get(pk=destino, ativo=True) if destino else default
    if transferencia:
        if not origem or not destino or source.pk == target.pk:
            raise ValidationError('Transferência exige dois depósitos ativos diferentes.')
        changes = [(source, -quantidade), (target, quantidade)]
    else:
        selected = source if delta < 0 else target
        changes = [(selected, delta)]
    for deposit, change in sorted(changes, key=lambda item: item[0].pk):
        balance = m.SaldoDeposito.objects.select_for_update().filter(deposito=deposit, peca=part).first()
        if not balance:
            balance = gs.write(m.SaldoDeposito(deposito=deposit, peca=part))
        if balance.quantidade + change < 0:
            raise ValidationError('Saldo insuficiente no depósito de origem.')
        balance.quantidade += change
        gs.write(balance)
    return (source if delta < 0 or transferencia else None, target if delta >= 0 or transferencia else None)

@transaction.atomic
def chamado_os(user, pk, tecnico_id):
    require(user, 'contratos')
    call = m.Chamado.objects.select_for_update().get(pk=pk)
    if call.ordem_id:
        return call.ordem
    if call.status != 'ABERTO' or not call.equipamento_id:
        raise ValidationError('Chamado aberto precisa de equipamento para gerar OS.')
    tech = Tecnico.objects.get(pk=tecnico_id, ativo=True)
    order = OrdemServico.objects.create(cliente=call.cliente, unidade=call.unidade, equipamento=call.equipamento, tecnico=tech, contrato=call.contrato, prioridade=call.prioridade, defeito=call.descricao)
    os_services.auditar(order, user, 'CRIACAO', os_services.snapshot(order))
    call.ordem, call.status = order, 'CONVERTIDO'
    call.save()
    gs.audit(user, 'CHAMADO_CONVERTIDO', call, {'ordem': order.pk})
    return order

def datas_plano(plan):
    days = {'DIARIO': 1, 'SEMANAL': 7, 'QUINZENAL': 15, 'PERSONALIZADA': plan.intervalo_dias}
    months = {'MENSAL': 1, 'BIMESTRAL': 2, 'TRIMESTRAL': 3, 'SEMESTRAL': 6, 'ANUAL': 12}
    for index in range(1201):
        date = plan.inicio + (timezone.timedelta(days=index * days[plan.periodicidade]) if plan.periodicidade in days else relativedelta(months=index * months[plan.periodicidade]))
        if date > plan.fim:
            return
        if index == 1200:
            raise ValidationError('Divida planos com mais de 1200 ocorrências por equipamento.')
        yield date

@transaction.atomic
def salvar_plano(user, form):
    require(user, 'contratos')
    plan = form.save(commit=False)
    plan.save()
    wanted = {x.pk for x in form.cleaned_data['equipamentos']}
    for link in plan.planoequipamento_set.all():
        if link.equipamento_id not in wanted:
            if plan.ocorrencias.filter(equipamento_id=link.equipamento_id).exists():
                raise ValidationError('Equipamento com agenda gerada deve ser preservado; desative o plano.')
            link.delete()
    for equipment in form.cleaned_data['equipamentos']:
        m.PlanoEquipamento.objects.get_or_create(plano=plan, equipamento=equipment)
    gerar_plano(user, plan.pk)
    gs.audit(user, 'PLANO_SALVO', plan)
    return plan

@transaction.atomic
def gerar_plano(user, pk):
    require(user, 'contratos')
    plan = m.PlanoPreventivo.objects.select_for_update().get(pk=pk)
    if not plan.ativo:
        return
    dates = list(datas_plano(plan))
    if len(dates) * plan.equipamentos.count() > 10000:
        raise ValidationError('Divida planos com mais de 10.000 ocorrências.')
    for equipment in plan.equipamentos.all():
        for date in dates:
            m.PreventivaProgramada.objects.get_or_create(plano=plan, equipamento=equipment, data=date)

@transaction.atomic
def preventiva_os(user, pk, tecnico_id):
    require(user, 'contratos')
    item = m.PreventivaProgramada.objects.select_for_update().get(pk=pk)
    if item.ordem_id:
        return item.ordem
    if item.situacao == 'CANCELADA':
        raise ValidationError('Plano/ocorrência desativados.')
    tech = Tecnico.objects.get(pk=tecnico_id, ativo=True)
    equipment, plan = item.equipamento, item.plano
    checklist = copy.deepcopy(plan.checklist.itens) if plan.checklist_id else []
    for row in checklist:
        row['concluido'] = False
    order = OrdemServico.objects.create(cliente=equipment.cliente, unidade=equipment.unidade, equipamento=equipment, tecnico=tech, contrato=plan.contrato, tipo_atendimento='PREVENTIVA', defeito=f'Plano {plan.nome} · {item.data:%d/%m/%Y}', agendada_para=timezone.make_aware(timezone.datetime.combine(item.data, timezone.datetime.min.time()).replace(hour=8)), checklist=checklist, observacoes=plan.observacoes)
    os_services.auditar(order, user, 'CRIACAO', os_services.snapshot(order))
    item.ordem = order
    item.save()
    gs.audit(user, 'PREVENTIVA_OS_GERADA', item, {'ordem': order.pk})
    return order

@transaction.atomic
def checklist_salvar(user, pk, concluded, observations):
    order = OrdemServico.objects.select_for_update().get(pk=pk)
    os_services.autorizar(user, order)
    if order.status in m.ENCERRADAS:
        raise ValidationError('Atendimento encerrado é imutável.')
    old = copy.deepcopy(order.checklist)
    for index, row in enumerate(order.checklist):
        row['concluido'] = str(index) in concluded
        row['observacao'] = observations.get(str(index), '')[:1000]
    order.revisao += 1
    order.save()
    os_services.auditar(order, user, 'CHECKLIST', {'anterior': old, 'posterior': order.checklist})

@transaction.atomic
def transicao_os(user, pk, action, reason=''):
    order = OrdemServico.objects.select_for_update().get(pk=pk)
    os_services.autorizar(user, order)
    old = order.status
    transitions = {'agendar': (['ABERTA'], 'AGENDADA'), 'aguardar_peca': (['EXECUCAO'], 'AG_PECA'), 'aguardar_cliente': (['EXECUCAO'], 'AG_CLIENTE'), 'retomar': (['AG_PECA', 'AG_CLIENTE'], 'EXECUCAO'), 'aprovar': (['FINALIZADA'], 'APROVADA'), 'faturar': (['APROVADA'], 'FATURADA')}
    if action == 'cancelar':
        os_services.autorizar(user, order, administrativo=True)
        if old == 'CANCELADA' or not reason.strip():
            raise ValidationError('Cancelamento exige justificativa e OS não cancelada.')
        if m.DocumentoFiscal.objects.filter(ordem=order, status='AUTORIZADA').exists():
            raise ValidationError('Regularize a nota fiscal no provedor antes de cancelar.')
        for entry in order.lancamentos.all():
            if entry.status == 'LIQUIDADO' or entry.pagamentos.exists():
                raise ValidationError('OS tem recebimento; regularize o financeiro antes de cancelar.')
            if entry.status != 'CANCELADO':
                gs.cancelar_lancamento(user, entry.pk, reason)
        target = 'CANCELADA'
    else:
        if action not in transitions or old not in transitions[action][0]:
            raise ValidationError('Transição não permitida neste estado.')
        target = transitions[action][1]
        if action in ['agendar', 'aprovar', 'faturar']:
            os_services.autorizar(user, order, administrativo=True)
        if action == 'agendar' and not order.agendada_para:
            raise ValidationError('Informe a data/hora agendada ao editar a OS.')
        if action == 'faturar' and not order.lancamentos.exists() and not g.Orcamento.objects.filter(ordem_convertida=order, lancamentos__isnull=False).exists():
            raise ValidationError('OS sem conta a receber não pode ser faturada.')
    order.status = target
    order.revisao += 1
    os_services.salvar_transicao(order)
    os_services.auditar(order, user, 'STATUS_' + target, {'status': {'anterior': old, 'posterior': target}}, reason)
    return order

@transaction.atomic
def compra_acao(user, pk, action, quotation_id=None):
    require(user, 'estoque_escrever')
    purchase = m.Compra.objects.select_for_update().get(pk=pk)
    if action == 'receber' and purchase.status == 'RECEBIDA':
        return purchase
    old = purchase.status
    if action == 'aprovar':
        if old != 'RASCUNHO' or not purchase.itens.exists() or purchase.total <= 0:
            raise ValidationError('Solicitação precisa de itens/valor e estar em rascunho.')
        if quotation_id:
            quotation = purchase.cotacoes.get(pk=quotation_id)
            if quotation.validade < timezone.localdate() or quotation.valor != purchase.total:
                raise ValidationError('Revise validade e preços dos itens para coincidir com a cotação escolhida.')
            purchase.fornecedor = quotation.fornecedor
        if not purchase.fornecedor_id:
            raise ValidationError('Selecione o fornecedor/cotação antes da aprovação.')
        purchase.status = 'APROVADA'
    elif action == 'pedir' and old == 'APROVADA':
        purchase.status = 'PEDIDO'
    elif action == 'receber' and old == 'PEDIDO':
        for item in purchase.itens.select_related('peca').order_by('peca_id'):
            gs.movimentar(user, item.peca_id, 'ENTRADA', item.quantidade, f'Recebimento {purchase}', destino_id=purchase.deposito_id,
                lote_data={'numero':item.lote,'fabricacao':item.fabricacao,'validade':item.validade,'documento_entrada':item.documento_entrada,'item_compra':item,'fornecedor':purchase.fornecedor,'custo_unitario':item.custo_unitario})
        purchase.conta = gs.write(g.Lancamento(tipo='PAGAR', descricao=str(purchase), fornecedor=purchase.fornecedor, valor=purchase.total, vencimento=purchase.vencimento, criado_por=user))
        purchase.status = 'RECEBIDA'
    elif action == 'cancelar' and old in ['RASCUNHO', 'APROVADA', 'PEDIDO']:
        purchase.status = 'CANCELADA'
    else:
        raise ValidationError('Transição de compra inválida.')
    gs.write(purchase)
    gs.audit(user, 'COMPRA_' + purchase.status, purchase, {'status': {'anterior': old, 'posterior': purchase.status}})
    return purchase

@transaction.atomic
def venda_confirmar(user, pk):
    require(user, 'contratos')
    sale = m.Venda.objects.select_for_update().get(pk=pk)
    if sale.status == 'CONFIRMADA':
        return sale
    if sale.status != 'RASCUNHO' or not sale.itens.exists() or sale.total <= 0:
        raise ValidationError('Venda exige itens, total positivo e rascunho.')
    for item in sale.itens.select_related('peca').order_by('peca_id'):
        gs.movimentar(user, item.peca_id, 'SAIDA', item.quantidade, str(sale), origem_id=sale.deposito_id, venda_id=sale.pk)
    sale.conta = gs.write(g.Lancamento(tipo='RECEBER', descricao=str(sale), cliente=sale.cliente, valor=sale.total, vencimento=sale.vencimento, criado_por=user))
    sale.status = 'CONFIRMADA'
    gs.write(sale)
    gs.audit(user, 'VENDA_CONFIRMADA', sale, {'total': str(sale.total), 'lancamento': sale.conta_id})
    return sale

@transaction.atomic
def caixa(user, conta_id, tipo, valor, date, description, reference=None):
    require(user, 'financeiro_escrever')
    account = m.ContaBancaria.objects.select_for_update().get(pk=conta_id, ativo=True)
    amount = positive(valor)
    if tipo not in ['ENTRADA', 'SAIDA'] or date > timezone.localdate() or not description.strip():
        raise ValidationError('Tipo/data/descrição inválidos.')
    ref = reference or uuid.uuid4()
    existing = account.movimentos.filter(referencia=ref).first()
    if existing:
        if (existing.tipo, existing.valor, existing.data, existing.descricao) != (tipo, amount, date, description):
            raise ValidationError('Identificador de caixa já utilizado com outros dados.')
        return existing
    if tipo == 'SAIDA' and not account.permite_saldo_negativo and amount > account.saldo:
        raise ValidationError('Saldo bancário insuficiente; limite negativo não habilitado.')
    movement = gs.write(m.MovimentoCaixa(conta=account, tipo=tipo, valor=amount, data=date, descricao=description, referencia=ref, usuario=user))
    gs.audit(user, 'CAIXA_MOVIMENTADO', movement, {'tipo': tipo, 'valor': str(amount)})
    return movement

@transaction.atomic
def transferir_banco(user, origem, destino, amount, date, reference):
    require(user, 'financeiro_escrever')
    if origem == destino:
        raise ValidationError('Contas de origem/destino devem ser diferentes.')
    list(m.ContaBancaria.objects.select_for_update().filter(pk__in=[origem, destino]).order_by('pk'))
    caixa(user, origem, 'SAIDA', amount, date, 'Transferência entre contas', reference)
    caixa(user, destino, 'ENTRADA', amount, date, 'Transferência entre contas', reference)

@transaction.atomic
def pagar(user, pk, amount, date, observation='', account_id=None, request_id=None):
    require(user, 'financeiro_escrever')
    entry = g.Lancamento.objects.select_for_update().get(pk=pk)
    token = request_id or uuid.uuid4()
    previous = m.Pagamento.objects.filter(request_id=token).first()
    if previous:
        if (previous.lancamento_id, previous.valor, previous.data, previous.conta_id) != (pk, Decimal(amount), date, account_id):
            raise ValidationError('Identificador de pagamento já usado com outros dados.')
        return previous
    amount = positive(amount)
    if entry.status not in ['PENDENTE', 'VENCIDO'] or amount > entry.saldo or date > timezone.localdate() or date < entry.data_emissao:
        raise ValidationError('Revise estado, saldo pendente e data do pagamento.')
    if account_id:
        account = m.ContaBancaria.objects.get(pk=account_id, ativo=True)
        caixa(user, account.pk, 'ENTRADA' if entry.tipo == 'RECEBER' else 'SAIDA', amount, date, entry.descricao, token)
    else:
        account = None
    payment = gs.write(m.Pagamento(lancamento=entry, valor=amount, data=date, conta=account, usuario=user, observacoes=observation, request_id=token))
    gs.write(g.EventoFinanceiro(lancamento=entry, tipo='LIQUIDACAO', valor=amount, data=date, usuario=user, observacao=observation))
    if entry.saldo == 0:
        entry.status, entry.data_liquidacao = 'LIQUIDADO', date
        gs.write(entry)
    gs.audit(user, 'LANCAMENTO_LIQUIDADO' if entry.status == 'LIQUIDADO' else 'PAGAMENTO_PARCIAL', entry, {'valor': str(amount), 'saldo': str(entry.saldo), 'data': date.isoformat()})
    return payment

@transaction.atomic
def parcelar(user, pk, quantity, first_date):
    require(user, 'financeiro_escrever')
    entry = g.Lancamento.objects.select_for_update().get(pk=pk)
    if entry.parcelas.exists():
        return list(entry.parcelas.all())
    if entry.status != 'PENDENTE' or entry.pagamentos.exists() or not 2 <= quantity <= 60:
        raise ValidationError('Parcelamento exige conta pendente sem pagamentos e 2 a 60 parcelas.')
    portion = (entry.valor / quantity).quantize(Decimal('.01'))
    if portion < Decimal('.01'):
        raise ValidationError('Valor insuficiente para a quantidade de parcelas.')
    result = []
    for index in range(quantity):
        amount = portion if index < quantity - 1 else entry.valor - portion * (quantity - 1)
        part = gs.write(g.Lancamento(tipo=entry.tipo, descricao=f'{entry.descricao} · {index + 1}/{quantity}', cliente=entry.cliente, fornecedor=entry.fornecedor, categoria=entry.categoria, centro_custo=entry.centro_custo, forma_pagamento=entry.forma_pagamento, valor=amount, vencimento=first_date + relativedelta(months=index), criado_por=user))
        result.append(m.Parcela.objects.create(origem=entry, lancamento=part, numero=index + 1))
    gs.cancelar_lancamento(user, entry.pk, 'Substituído por parcelas vinculadas, sem baixa de caixa.')
    gs.audit(user, 'LANCAMENTO_PARCELADO', entry, {'parcelas': quantity, 'valor': str(entry.valor)})
    return result

@transaction.atomic
def conciliar(user, pk, movement_id):
    require(user, 'financeiro_escrever')
    row = m.ExtratoBancario.objects.select_for_update().get(pk=pk)
    movement = m.MovimentoCaixa.objects.get(pk=movement_id, conta=row.conta)
    expected = movement.valor if movement.tipo == 'ENTRADA' else -movement.valor
    if row.movimento_id or expected != row.valor or movement.data != row.data:
        raise ValidationError('Extrato já conciliado ou valor/data divergentes.')
    row.movimento = movement
    row.save()
    gs.audit(user, 'EXTRATO_CONCILIADO', row, {'movimento': movement.pk})

@transaction.atomic
def documento_salvar(user, form):
    from .permissions import document_allowed
    document = form.save(commit=False)
    document.enviado_por = user
    document.clean()
    if not document_allowed(user, document, writing=True):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Documento fora da função/OS atribuída.')
    document.sha256 = hashlib.sha256(document.arquivo.read()).hexdigest()
    document.arquivo.seek(0)
    document.save()
    gs.audit(user, 'DOCUMENTO_ENVIADO', document, {'sha256': document.sha256})
    return document
