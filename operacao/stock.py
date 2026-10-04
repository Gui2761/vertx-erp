"""Lotes, disponibilidade e reposição integrados a Peca/Movimentacao/Compra."""
import uuid
from decimal import Decimal, ROUND_CEILING
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Q, F
from django.utils import timezone
from gestao import models as g, services as gs
from gestao.permissions import require
from . import models as m

ZERO = g.ZERO
THREE = Decimal('.001')

def amount(value):
    quantity = Decimal(value)
    if not quantity.is_finite() or quantity <= 0 or quantity.as_tuple().exponent < -3:
        raise ValidationError('Informe quantidade positiva com até três decimais.')
    return quantity

def movement_parameters(data, lot_id, sale_id):
    result = {}
    if data:
        result['entrada'] = {key:(value.pk if hasattr(value,'pk') else value.isoformat() if hasattr(value,'isoformat') else str(value) if isinstance(value,Decimal) else value) for key,value in data.items()}
    if lot_id:
        result['lote_id'] = int(lot_id)
    if sale_id:
        result['venda_id'] = int(sale_id)
    return result

def active_reservations(part, depot=None):
    qs = m.ReservaEstoque.objects.filter(peca=part, status='ATIVA', quantidade__gt=0).exclude(ordem__status__in=m.ENCERRADAS).exclude(venda__status__in=['CONFIRMADA','FINALIZADA','PARCIALMENTE_DEVOLVIDA','DEVOLVIDA','CANCELADA'])
    return qs.filter(deposito=depot) if depot else qs

def total(qs, field='quantidade'):
    return qs.aggregate(total=Sum(field))['total'] or ZERO

def valid_lots(part, depot=None, today=None):
    today = today or timezone.localdate()
    qs = m.LoteEstoque.objects.filter(peca=part, quantidade__gt=0).filter(Q(validade__isnull=True) | Q(validade__gte=today))
    # Compatibilidade de entradas antigas sem metadados: uma validade global
    # vencida nunca libera consumo de lote legado cuja validade é desconhecida.
    # Lotes identificados por entrada têm validade própria e não usam esse campo.
    qs = qs.exclude(legado=True,validade__isnull=True,peca__validade__lt=today)
    if depot:
        qs = qs.filter(deposito=depot)
    return qs.order_by(F('validade').asc(nulls_last=True), 'entrada_em', 'pk')

def ensure_lots(part):
    """Compatibilidade defensiva; saldo legado é detalhado, nunca duplicado."""
    from .services import saldo_deposito
    saldo_deposito(part)
    for balance in m.SaldoDeposito.objects.filter(peca=part).order_by('deposito_id'):
        detailed = total(m.LoteEstoque.objects.filter(peca=part, deposito=balance.deposito))
        missing = balance.quantidade - detailed
        if missing < 0:
            raise ValidationError('Detalhamento de lotes divergente do saldo; regularize por movimentação auditada.')
        if missing:
            gs.write(m.LoteEstoque(peca=part, deposito=balance.deposito, numero=part.lote or f'LEGADO-{part.pk}', validade=part.validade, quantidade=missing, fornecedor=part.fornecedor, custo_unitario=part.custo_aquisicao, localizacao=part.localizacao, legado=True))

def lot_change(user, movement, lot, delta, cost=None):
    before = lot.quantidade
    lot.quantidade += delta
    if lot.quantidade < 0:
        raise ValidationError('Saldo do lote insuficiente.')
    gs.write(lot)
    cost = lot.custo_unitario if cost is None else cost
    detail = gs.write(m.MovimentacaoLote(movimentacao=movement, lote=lot, quantidade_anterior=before, variacao=delta, quantidade_posterior=lot.quantidade, custo_unitario=cost, custo_total=abs(delta) * cost))
    gs.audit(user, 'LOTE_MOVIMENTADO', detail, {'produto':lot.peca_id, 'lote':lot.pk, 'numero':lot.numero, 'deposito':lot.deposito_id, 'quantidade_anterior':str(before), 'movimentacao':movement.pk, 'variacao':str(delta), 'quantidade_posterior':str(lot.quantidade), 'custo_unitario':str(cost), 'custo_total':str(detail.custo_total), 'motivo':movement.observacao, 'origem':{'tipo':movement.tipo,'os':movement.ordem_id,'compra':lot.item_compra.compra_id if lot.item_compra_id else None}})

def incoming_lot(part, movement, data):
    data = dict(data or {})
    explicit = bool(data)
    if part.exige_lote and not data.get('numero'):
        raise ValidationError('Produto exige número do lote na entrada.')
    if part.controla_validade and (not data.get('numero') or not data.get('validade')):
        raise ValidationError('Produto exige número de lote e validade no recebimento.')
    supplier = data.pop('fornecedor', None)
    if supplier is not None and not isinstance(supplier, g.Fornecedor):
        supplier = g.Fornecedor.objects.get(pk=supplier)
    if supplier and supplier.organization_id != part.organization_id:
        raise ValidationError('Fornecedor pertence a outra organização.')
    return gs.write(m.LoteEstoque(peca=part, deposito=movement.destino, numero=data.pop('numero', '') or f'ENTRADA-{movement.pk}', validade=data.pop('validade', None) if explicit else part.validade,
        fabricacao=data.pop('fabricacao', None), fornecedor=supplier or part.fornecedor,
        custo_unitario=data.pop('custo_unitario', movement.custo_unitario), localizacao=data.pop('localizacao', part.localizacao), documento_entrada=data.pop('documento_entrada', ''), item_compra=data.pop('item_compra', None), legado=not explicit))

def own_reservations(part, depot, order_id=None, sale_id=None):
    qs = active_reservations(part, depot)
    if order_id:
        return qs.filter(ordem_id=order_id)
    if sale_id:
        return qs.filter(venda_id=sale_id)
    return qs.none()


def lot_holds(part, depot, excluded=()):
    """Existing aggregate reservations remain effective without fabricated history."""
    lots = list(valid_lots(part, depot))
    used = {}
    result = {}
    legacy = []
    for reservation in active_reservations(part, depot).prefetch_related('alocacoes').order_by('pk'):
        details = list(reservation.alocacoes.all())
        if not details:
            legacy.append(reservation)
        for detail in details:
            used[detail.lote_id] = used.get(detail.lote_id, ZERO) + detail.quantidade
            if reservation.pk not in excluded:
                result[detail.lote_id] = result.get(detail.lote_id, ZERO) + detail.quantidade
    for reservation in legacy:
        remaining = reservation.quantidade
        for lot in lots:
            quantity = min(remaining, max(ZERO, lot.quantidade - used.get(lot.pk, ZERO)))
            used[lot.pk] = used.get(lot.pk, ZERO) + quantity
            if reservation.pk not in excluded:
                result[lot.pk] = result.get(lot.pk, ZERO) + quantity
            remaining -= quantity
            if not remaining:
                break
    return result

def consume_reservations(user, qs, quantity):
    remaining = quantity
    for row in qs.select_for_update(of=('self',)).order_by('pk'):
        used = min(row.quantidade, remaining)
        old = row.quantidade
        row.quantidade -= used
        if not row.quantidade:
            row.status = 'CONSUMIDA'
        gs.write(row)
        allocated = used
        for detail in row.alocacoes.select_for_update().order_by('lote__validade', 'pk'):
            released = min(allocated, detail.quantidade)
            if released:
                detail.quantidade -= released
                gs.write(detail)
                gs.audit(user, 'RESERVA_LOTE_LIBERADA_POR_CONSUMO', detail, {'quantidade': str(released), 'saldo': str(detail.quantidade), 'motivo': 'Liberação do compromisso; os lotes efetivamente consumidos constam em MovimentacaoLote.'})
                allocated -= released
            if not allocated:
                break
        gs.audit(user, 'RESERVA_CONSUMIDA', row, {'anterior':str(old),'posterior':str(row.quantidade)})
        remaining -= used
        if not remaining:
            break

def return_allocation(part, movement):
    remaining = movement.variacao
    result = []
    sale_id=movement.detalhamento.get('venda_id')
    if sale_id:
        item_id=movement.detalhamento.get('entrada',{}).get('devolucao_item')
        try:
            item=m.ItemVenda.objects.get(pk=int(item_id),venda_id=sale_id,peca=part,movimento__isnull=False)
        except (TypeError,ValueError,m.ItemVenda.DoesNotExist):
            raise ValidationError('Devolução exige item e movimento original da venda.')
        for original in item.movimento.lotes_movimentados.select_related('lote').order_by('pk'):
            if original.lote.deposito_id!=movement.destino_id: raise ValidationError('Devolução deve retornar ao depósito/lote original.')
            returned=m.MovimentacaoLote.objects.filter(lote_id=original.lote_id,movimentacao__tipo='DEVOLUCAO',movimentacao__detalhamento__venda_id=sale_id,movimentacao__detalhamento__entrada__devolucao_item=item.pk).aggregate(total=Sum('variacao'))['total'] or ZERO
            quantity=min(remaining,max(ZERO,-original.variacao-returned))
            if quantity:
                lot=m.LoteEstoque.objects.select_for_update().get(pk=original.lote_id)
                result.append((lot,quantity,original.custo_unitario))
                remaining-=quantity
            if not remaining: break
        if remaining: raise ValidationError('Devolução excede lotes consumidos na venda.')
        return result
    used = m.MovimentacaoLote.objects.filter(movimentacao__peca=part, movimentacao__ordem_id=movement.ordem_id, movimentacao__tipo__in=['OS','DEVOLUCAO'], lote__deposito_id=movement.destino_id).values('lote_id').annotate(net=Sum('variacao')).order_by('lote_id')
    for row in used:
        if row['net'] >= 0:
            continue
        lot = m.LoteEstoque.objects.select_for_update().get(pk=row['lote_id'])
        original = lot.movimentos.filter(movimentacao__ordem_id=movement.ordem_id, movimentacao__tipo='OS').order_by('pk').first()
        # Reverte o custo documentado da saída; não reprecifica o histórico legado.
        cost = (original.custo_unitario if original.custo_unitario is not None else original.movimentacao.custo_unitario) if original else lot.custo_unitario
        quantity = min(remaining, -row['net'])
        result.append((lot, quantity, cost))
        remaining -= quantity
        if not remaining:
            break
    if remaining:
        if m.MovimentacaoLote.objects.filter(movimentacao__peca=part, movimentacao__ordem_id=movement.ordem_id, movimentacao__tipo='OS').exists():
            raise ValidationError('Devolução excede consumo por lote/depósito.')
        result.append((None, remaining, movement.custo_unitario))
    return result


def outgoing_allocation(part, movement, lot_id=None, sale_id=None):
    quantity = movement.quantidade if movement.tipo == 'TRANSFER' else -movement.variacao
    source = movement.origem
    qs = valid_lots(part, source)
    expired_disposal = False
    if lot_id:
        try:
            lot = m.LoteEstoque.objects.get(pk=lot_id, peca=part, deposito=source)
        except m.LoteEstoque.DoesNotExist:
            raise ValidationError('Lote não corresponde ao produto/depósito de origem.')
        expired_disposal = bool(lot.validade and lot.validade < timezone.localdate())
        if expired_disposal and movement.tipo not in ['AJUSTE','TRANSFER']:
            raise ValidationError('Lote vencido não pode ser utilizado ou vendido.')
        qs = m.LoteEstoque.objects.filter(pk=lot_id)
    own = own_reservations(part, source, movement.ordem_id, sale_id)
    other = active_reservations(part, source).exclude(pk__in=own.values('pk'))
    if not expired_disposal and quantity > total(valid_lots(part, source)) - total(other):
        raise ValidationError('Estoque válido disponível insuficiente; lotes vencidos e reservas não podem ser consumidos.')
    remaining = quantity
    allocation = []
    held = lot_holds(part, source, set(own.values_list('pk', flat=True)))
    for lot in qs.select_for_update():
        used = min(max(ZERO, lot.quantidade - held.get(lot.pk, ZERO)), remaining)
        if used:
            allocation.append((lot, used, lot.custo_unitario))
            remaining -= used
        if not remaining:
            break
    if remaining:
        raise ValidationError('Quantidade insuficiente nos lotes selecionados.')
    return allocation, own, expired_disposal


def planned_cost(part, movement, data=None, lot_id=None, sale_id=None):
    if movement.tipo=='INVENTARIO':
        return abs(movement.variacao)*m.LoteEstoque.objects.get(pk=lot_id,peca=part).custo_unitario
    if movement.tipo == 'DEVOLUCAO' and (movement.ordem_id or sale_id):
        allocation = return_allocation(part, movement)
    elif movement.variacao > 0:
        return movement.variacao * movement.custo_unitario
    elif movement.variacao < 0 or movement.tipo == 'TRANSFER':
        allocation, _, _ = outgoing_allocation(part, movement, lot_id, sale_id)
    else:
        return ZERO
    return sum((quantity * cost for _, quantity, cost in allocation), ZERO)


def move_lots(user, part, movement, data=None, lot_id=None, sale_id=None):
    delta = movement.variacao
    if movement.tipo=='INVENTARIO':
        lot=m.LoteEstoque.objects.select_for_update().get(pk=lot_id,peca=part)
        lot_change(user,movement,lot,delta)
        return
    if lot_id and (delta > 0 or movement.tipo == 'DEVOLUCAO'):
        raise ValidationError('Entradas usam metadados de um novo lote; devoluções recuperam o lote original automaticamente.')
    if movement.tipo == 'DEVOLUCAO' and (movement.ordem_id or sale_id):
        for lot, quantity, cost in return_allocation(part, movement):
            lot = lot or incoming_lot(part, movement, data)
            lot_change(user, movement, lot, quantity, cost)
        return
    if delta > 0:
        lot = incoming_lot(part, movement, data)
        lot_change(user, movement, lot, delta)
        return
    quantity = movement.quantidade if movement.tipo == 'TRANSFER' else -delta
    if not quantity:
        return
    allocation, own, expired_disposal = outgoing_allocation(part, movement, lot_id, sale_id)
    for lot, used, cost in allocation:
        lot_change(user, movement, lot, -used, cost)
        if movement.tipo == 'TRANSFER':
            target = m.LoteEstoque.objects.filter(grupo=lot.grupo, deposito=movement.destino).first()
            if not target:
                target = gs.write(m.LoteEstoque(peca=part, deposito=movement.destino, grupo=lot.grupo, numero=lot.numero, fabricacao=lot.fabricacao, validade=lot.validade, fornecedor=lot.fornecedor, custo_unitario=lot.custo_unitario, entrada_em=lot.entrada_em, localizacao=movement.destino.endereco, documento_entrada=lot.documento_entrada, item_compra=lot.item_compra, legado=lot.legado))
            lot_change(user, movement, target, used)
    if movement.tipo != 'TRANSFER' and not expired_disposal:
        consume_reservations(user, own, quantity)

@transaction.atomic
def reserve(user, part_id, depot_id, quantity, reason, order_id=None, sale_id=None, request_id=None, lot_id=None):
    from .commerce_scope import _authorized
    if not _authorized(user,'reserve',sale_id=sale_id,part_id=part_id,depot_id=depot_id):
        require(user, 'estoque_escrever')
    order = None
    if order_id:
        from ordens.models import OrdemServico
        order = OrdemServico.objects.select_for_update().get(pk=order_id)
        if order.status in m.ENCERRADAS:
            raise ValidationError('OS encerrada não aceita reserva.')
    part = g.Peca.objects.select_for_update().get(pk=part_id, ativo=True)
    depot = m.Deposito.objects.get(pk=depot_id, ativo=True)
    quantity = amount(quantity)
    if not reason.strip() or order_id and sale_id:
        raise ValidationError('Informe motivo e apenas uma origem para a reserva.')
    previous = m.ReservaEstoque.objects.filter(request_id=request_id).first() if request_id else None
    if previous:
        initial = total(previous.alocacoes.all(), 'quantidade_inicial') or previous.quantidade
        if (previous.peca_id, previous.deposito_id, previous.ordem_id, previous.venda_id, initial, previous.motivo) != (part_id, depot_id, order_id, sale_id, quantity, reason):
            raise ValidationError('Identificador de reserva já utilizado com outros dados.')
        if lot_id and not previous.alocacoes.filter(lote_id=lot_id).exists():
            raise ValidationError('Identificador de reserva corresponde a outro lote.')
        return previous
    sale = None
    if sale_id:
        sale = m.Venda.objects.filter(pk=sale_id, status='RASCUNHO', deposito=depot).first()
        if not sale:
            raise ValidationError('Venda deve estar em rascunho e usar o depósito da reserva.')
        ordered=total(sale.itens.filter(peca=part))
        pledged=total(active_reservations(part,depot).filter(venda=sale))
        if quantity+pledged > ordered:
            raise ValidationError('Reserva excede a quantidade deste produto na venda.')
    ensure_lots(part)
    if quantity > total(valid_lots(part, depot)) - total(active_reservations(part, depot)):
        raise ValidationError('Quantidade excede estoque válido disponível.')
    held = lot_holds(part, depot)
    lots = valid_lots(part, depot)
    if lot_id:
        lots = lots.filter(pk=lot_id)
    allocations = []
    remaining = quantity
    for lot in lots.select_for_update():
        allocated = min(remaining, max(ZERO, lot.quantidade - held.get(lot.pk, ZERO)))
        if allocated:
            allocations.append((lot, allocated))
            remaining -= allocated
        if not remaining:
            break
    if remaining:
        raise ValidationError('Lotes válidos disponíveis insuficientes para reserva.')
    row = gs.write(m.ReservaEstoque(peca=part, deposito=depot, quantidade=quantity, motivo=reason, ordem=order, venda=sale, usuario=user, request_id=request_id))
    for lot, allocated in allocations:
        gs.write(m.AlocacaoReservaEstoque(reserva=row, lote=lot, quantidade=allocated, quantidade_inicial=allocated))
    gs.audit(user, 'ESTOQUE_RESERVADO', row, {'produto':part.pk,'deposito':depot.pk,'quantidade':str(quantity),'os':order_id,'venda':sale_id,'motivo':reason})
    return row

@transaction.atomic
def release(user, pk, reason):
    require(user, 'estoque_escrever')
    row = m.ReservaEstoque.objects.get(pk=pk)
    if row.transferencia_id:
        raise ValidationError('Reserva de trânsito é liberada somente ao receber a transferência.')
    g.Peca.objects.select_for_update().get(pk=row.peca_id)
    row = m.ReservaEstoque.objects.select_for_update().get(pk=pk)
    if not reason.strip():
        raise ValidationError('Liberação exige justificativa.')
    if row.status == 'ATIVA':
        row.status = 'LIBERADA'
        gs.write(row)
        gs.audit(user, 'RESERVA_LIBERADA', row, {'quantidade':str(row.quantidade),'motivo':reason})
    return row

def metrics(part, config=None, today=None):
    part.refresh_from_db()
    config = config or m.Configuracao.objects.first() or m.Configuracao()
    today = today or timezone.localdate()
    valid = list(valid_lots(part, today=today))
    valid_quantity = sum((lot.quantidade for lot in valid), ZERO)
    reserved = total(active_reservations(part))
    available = max(ZERO, valid_quantity - reserved)
    expired = total(part.lotes.filter(validade__lt=today))
    pending = sum((item.quantidade_pendente for item in m.ItemCompra.objects.filter(peca=part, compra__status__in=['APROVADA','PEDIDO']).select_related('compra')), ZERO)
    drafts = total(m.ItemCompra.objects.filter(peca=part, compra__status='RASCUNHO'))
    since = today - timezone.timedelta(days=config.consumo_historico_dias - 1)
    history = part.movimentacoes.filter(tipo__in=['SAIDA','OS','DEVOLUCAO'], criado_em__date__range=(since,today))
    first = part.movimentacoes.filter(tipo__in=['SAIDA','OS']).order_by('criado_em').first()
    daily = max(ZERO, -total(history, 'variacao')) / config.consumo_historico_dias if first and first.criado_em.date() <= today - timezone.timedelta(days=30) else ZERO
    horizon = max(config.dias_alerta_validade)
    expiring = sum((lot.quantidade for lot in valid if lot.validade and lot.validade <= today + timezone.timedelta(days=horizon)), ZERO)
    # FEFO prospectivo: reservas consomem primeiro; histórico médio é uma estimativa.
    committed, used_forecast, replacement = reserved, ZERO, ZERO
    for lot in valid:
        pledged = min(lot.quantidade, committed)
        committed -= pledged
        left = lot.quantidade - pledged
        if not lot.validade or lot.validade > today + timezone.timedelta(days=horizon):
            continue
        demand = max(ZERO, daily * max(0, (lot.validade - today).days) - used_forecast)
        projected = min(left, demand)
        used_forecast += projected
        replacement += left - projected
    ideal = max(part.estoque_minimo, part.estoque_maximo or part.estoque_minimo, daily * config.reposicao_dias)
    effective = available - replacement
    need_quantity = sum((need_remaining(need) for need in m.NecessidadePecaOS.objects.filter(peca=part, resolvida_em__isnull=True).exclude(ordem__status__in=m.ENCERRADAS).select_related('ordem')), ZERO)
    sales=m.ItemVenda.objects.filter(peca=part,venda__status='AG_PAGAMENTO').values('venda_id').annotate(demand=Sum('quantidade'))
    pledged={row['venda_id']:row['held'] for row in active_reservations(part).filter(venda__isnull=False).values('venda_id').annotate(held=Sum('quantidade'))}
    commercial=sum((max(ZERO,row['demand']-pledged.get(row['venda_id'],ZERO)) for row in sales),ZERO)
    required = max(ZERO, max(ideal, need_quantity) + commercial - effective - pending) if effective <= part.estoque_minimo or need_quantity+commercial > available else ZERO
    suggested = required.quantize(THREE, rounding=ROUND_CEILING)
    last = part.lotes.order_by('-entrada_em','-pk').first()
    supplier = last.fornecedor if last and last.fornecedor_id else part.fornecedor
    cost = last.custo_unitario if last else part.custo_aquisicao
    return {'peca':part, 'produto':part.descricao, 'sku':part.sku, 'categoria':str(part.categoria or ''), 'fisico':part.quantidade_atual, 'valido':valid_quantity, 'vencido':expired, 'reservado':reserved, 'disponivel':available, 'minimo':part.estoque_minimo, 'ideal':ideal.quantize(THREE, rounding=ROUND_CEILING), 'consumo_medio':daily.quantize(Decimal('.000001')), 'vencendo':expiring, 'substituir':replacement, 'em_compra':pending, 'em_solicitacao':drafts, 'sugerido':suggested, 'fornecedor':str(supplier or ''), 'fornecedor_id':supplier.pk if supplier else None, 'custo':cost, 'valor_estimado':(suggested * cost).quantize(Decimal('.01')), 'situacao':'ZERADO' if available == 0 else 'ESTOQUE BAIXO' if available <= part.estoque_minimo else 'REPOSIÇÃO POR VALIDADE' if replacement and effective <= part.estoque_minimo else 'NORMAL'}

def need_remaining(need):
    movements = g.Movimentacao.objects.filter(ordem=need.ordem, peca_id=need.peca_id, criado_em__gte=need.criado_em, tipo__in=['OS', 'DEVOLUCAO']).filter(Q(tipo='OS', origem_id=need.deposito_id) | Q(tipo='DEVOLUCAO', destino_id=need.deposito_id))
    consumed = max(ZERO, -total(movements, 'variacao'))
    reserved = total(active_reservations(need.peca, need.deposito).filter(ordem=need.ordem))
    return max(ZERO, need.quantidade - consumed - reserved)

def snapshot(data):
    return {key:str(value) if isinstance(value, Decimal) else value for key,value in data.items() if key != 'peca'}

@transaction.atomic
def scan_stock(user, now=None):
    require(user, 'estoque_escrever')
    now = now or timezone.now()
    config, _ = m.Configuracao.objects.get_or_create()
    config = m.Configuracao.objects.select_for_update().get(pk=config.pk)
    today = timezone.localdate(now)
    wanted = set()
    for part in g.Peca.objects.filter(ativo=True).select_related('categoria','fornecedor'):
        # Encerramento libera compromissos sem restaurar consumo físico já lançado.
        for reservation in part.reservas.filter(status='ATIVA').filter(Q(ordem__status__in=m.ENCERRADAS) | Q(venda__status__in=['CONFIRMADA','CANCELADA'])):
            release(user, reservation.pk, 'Origem encerrada; liberação automática do compromisso restante.')
        data = metrics(part, config, today)
        conditions = []
        if data['disponivel'] <= part.estoque_minimo:
            conditions.append((f'produto:{part.pk}:reposicao',None,'REPOSICAO',data['situacao']))
        if part.quantidade_atual > 0 and not part.movimentacoes.filter(criado_em__date__gte=today-timezone.timedelta(days=90)).exists():
            conditions.append((f'produto:{part.pk}:sem-movimento',None,'SEM_MOVIMENTO','SEM MOVIMENTO HÁ 90 DIAS'))
        for lot in part.lotes.filter(quantidade__gt=0, validade__isnull=False):
            days = (lot.validade-today).days
            if days < 0:
                conditions.append((f'lote:{lot.pk}:validade',lot,'VENCIDO','VENCIDO'))
            elif days <= max(config.dias_alerta_validade):
                threshold = min(limit for limit in config.dias_alerta_validade if days <= limit)
                conditions.append((f'lote:{lot.pk}:validade',lot,'VALIDADE',f'VENCE EM ATÉ {threshold} DIAS'))
        for key, lot, kind, state in conditions:
            wanted.add(key)
            occurrence, created = m.OcorrenciaEstoque.objects.get_or_create(chave=key, resolvida_em__isnull=True, defaults={'peca':part,'lote':lot,'tipo':kind,'situacao':state,'dados':snapshot(data),'aberta_em':now,'atualizada_em':now})
            occurrence.tipo, occurrence.situacao, occurrence.dados, occurrence.atualizada_em = kind, state, snapshot(data), now
            occurrence.save()
            from .notifications import deliver
            deliver(f'ocorrencia-estoque:{occurrence.pk}',state,f'{part.sku} · {part.descricao} · disponível {data["disponivel"]}', ['ADMIN','GESTOR','ESTOQUE'], '/estoque/ocorrencias/', occurrence=occurrence)
            if created:
                gs.audit(user,'ESTOQUE_OCORRENCIA_ABERTA',occurrence,{'produto':part.pk,'lote':lot.pk if lot else None,'situacao':state})
    for occurrence in m.OcorrenciaEstoque.objects.filter(resolvida_em__isnull=True).exclude(chave__in=wanted):
        occurrence.resolvida_em = occurrence.atualizada_em = now
        occurrence.save()
        for notice in m.Notificacao.objects.filter(ocorrencia_estoque=occurrence):
            notice.resolvida_em=now
            notice.save()
        gs.audit(user,'ESTOQUE_OCORRENCIA_RESOLVIDA',occurrence,{'produto':occurrence.peca_id,'lote':occurrence.lote_id})
    return len(wanted)

@transaction.atomic
def generate_report(user, week=None, automatic=True, now=None):
    require(user, 'estoque_escrever')
    config, _ = m.Configuracao.objects.get_or_create()
    config = m.Configuracao.objects.select_for_update().get(pk=config.pk)
    now = now or timezone.now()
    today = timezone.localdate(now)
    week = week or today-timezone.timedelta(days=today.weekday())
    if automatic:
        previous = m.RelatorioEstoque.objects.filter(semana=week,automatico=True).first()
        if previous:
            return previous
    report = gs.write(m.RelatorioEstoque(semana=week,automatico=automatic,usuario=user,gerado_em=now,parametros={'dias_validade':config.dias_alerta_validade,'historico_dias':config.consumo_historico_dias,'reposicao_dias':config.reposicao_dias}))
    parts = list(g.Peca.objects.select_for_update().filter(ativo=True).order_by('pk'))
    for part in parts:
        data = metrics(part, config, today)
        if data['disponivel'] <= part.estoque_minimo or data['vencido'] or data['substituir'] or data['sugerido']:
            gs.write(m.ItemRelatorioEstoque(relatorio=report,peca=part,dados=snapshot(data)))
    gs.audit(user,'RELATORIO_ESTOQUE_GERADO',report,{'semana':week.isoformat(),'automatico':automatic,'itens':report.itens.count()})
    from .notifications import deliver
    deliver(f'relatorio-estoque:{report.pk}','Relatório de necessidade de compras',f'{report.itens.count()} produtos para análise.', ['ADMIN','GESTOR','ESTOQUE'], f'/estoque/relatorios/{report.pk}/')
    return report

@transaction.atomic
def report_purchase(user, report_id, selection, depot_id, due, request_id, reason=''):
    require(user, 'estoque_escrever')
    report = m.RelatorioEstoque.objects.select_for_update().get(pk=report_id)
    depot = m.Deposito.objects.get(pk=depot_id, ativo=True)
    normalized = {str(int(key)):str(amount(value).quantize(THREE)) for key,value in selection.items()}
    if not normalized:
        raise ValidationError('Selecione pelo menos um produto.')
    previous = m.Compra.objects.filter(pedido_relatorio_id=request_id).first()
    if previous:
        if previous.relatorio_estoque_id != report.pk or previous.selecao_relatorio != normalized or previous.deposito_id != depot.pk or previous.vencimento != due:
            raise ValidationError('Identificador já usado com outra solicitação.')
        return previous
    rows = list(report.itens.filter(pk__in=normalized).select_related('peca').order_by('peca_id'))
    if len(rows) != len(normalized):
        raise ValidationError('Produtos não pertencem ao relatório desta organização.')
    list(g.Peca.objects.select_for_update().filter(pk__in=[row.peca_id for row in rows]).order_by('pk'))
    for row in rows:
        current = metrics(row.peca)
        if Decimal(normalized[str(row.pk)]) > current['sugerido'] and not reason.strip():
            raise ValidationError('Necessidade mudou ou quantidade excede recomendação; informe justificativa para a alteração.')
    purchase = m.Compra.objects.create(relatorio_estoque=report,pedido_relatorio_id=request_id,selecao_relatorio=normalized,deposito=depot,necessidade=f'Reposição por relatório {report.pk}',vencimento=due,observacoes=reason,criado_por=user)
    for row in rows:
        m.ItemCompra.objects.create(compra=purchase,peca=row.peca,quantidade=Decimal(normalized[str(row.pk)]),custo_unitario=Decimal(row.dados['custo']),relatorio_item=row)
    gs.audit(user,'COMPRA_GERADA_RELATORIO',purchase,{'relatorio':report.pk,'selecao':normalized,'justificativa':reason})
    return purchase
