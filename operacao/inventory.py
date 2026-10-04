from contextvars import ContextVar
import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from platform_core.modules import require_capability
from gestao import models as g, services as gs, products
from . import models as m, stock
from .commerce import token

_approved_count=ContextVar('approved_inventory_count',default=None)

def authorized_count(user,part,lot,quantity):
    value=_approved_count.get()
    return bool(value and value==(user.pk,part,lot,quantity))

@transaction.atomic
def open_inventory(user,depot_id,reason):
    require_capability(user,'estoque_escrever')
    if not reason.strip(): raise ValidationError('Inventário exige motivo.')
    depot=m.Deposito.objects.get(pk=depot_id,ativo=True)
    part_ids=m.LoteEstoque.objects.filter(deposito=depot,quantidade__gt=0).values('peca_id')
    list(g.Peca.objects.select_for_update().filter(pk__in=part_ids).order_by('pk'))
    row=gs.write(m.Inventario(deposito=depot,motivo=reason.strip(),criado_por=user))
    for lot in m.LoteEstoque.objects.filter(deposito=depot,quantidade__gt=0).order_by('peca_id','pk'):
        gs.write(m.ItemInventario(inventario=row,lote=lot,esperado=lot.quantidade))
    gs.audit(user,'INVENTARIO_ABERTO',row,{'deposito':depot.pk,'motivo':reason})
    return row

@transaction.atomic
def count(user,public_id,item_id,quantity,request_id):
    require_capability(user,'estoque_escrever')
    inventory=m.Inventario.objects.select_for_update().get(public_id=public_id)
    if inventory.status=='APROVADO': raise ValidationError('Inventário já aprovado.')
    item=inventory.itens.get(pk=item_id)
    g.Peca.objects.select_for_update().get(pk=item.lote.peca_id)
    lot=m.LoteEstoque.objects.get(pk=item.lote_id)
    qty=products.number(quantity)
    if qty<0 or qty!=qty.quantize(Decimal('.001')): raise ValidationError('Contagem inválida; use até 3 decimais.')
    qty=qty.quantize(Decimal('.001'));key=token(request_id)
    old=m.ContagemInventario.objects.filter(request_id=key).first()
    if old:
        if (old.item_id,old.quantidade)!=(item.pk,qty): raise ValidationError('Token de contagem reutilizado.')
        return old
    last=g.Movimentacao.objects.filter(peca_id=lot.peca_id).order_by('-pk').values_list('pk',flat=True).first() or 0
    row=gs.write(m.ContagemInventario(item=item,quantidade=qty,saldo_no_momento=lot.quantidade,ultimo_movimento=last,usuario=user,request_id=key))
    gs.audit(user,'INVENTARIO_CONTADO',row,{'anterior':str(lot.quantidade),'contado':str(qty),'recontagem':item.contagens.count()>1})
    return row

@transaction.atomic
def approve_inventory(user,public_id):
    require_capability(user,'inventario_aprovar')
    require_capability(user,'estoque_escrever')
    inventory=m.Inventario.objects.select_for_update().get(public_id=public_id)
    if inventory.status=='APROVADO': return inventory
    items=list(inventory.itens.select_related('lote').order_by('lote__peca_id','pk'))
    if not items: raise ValidationError('Inventário sem lotes para contar.')
    list(g.Peca.objects.select_for_update().filter(pk__in=[i.lote.peca_id for i in items]).order_by('pk'))
    current=set(m.LoteEstoque.objects.filter(deposito=inventory.deposito,quantidade__gt=0).values_list('pk',flat=True))
    if current-set(i.lote_id for i in items): raise ValidationError('Novos lotes entraram no depósito; abra novo inventário completo.')
    plans=[]
    for item in items:
        counted=item.contagens.order_by('-pk').first()
        if not counted: raise ValidationError('Conte todos os lotes antes de aprovar.')
        lot=m.LoteEstoque.objects.select_for_update().get(pk=item.lote_id)
        latest=g.Movimentacao.objects.filter(peca_id=lot.peca_id).order_by('-pk').values_list('pk',flat=True).first() or 0
        if latest!=counted.ultimo_movimento or lot.quantidade!=counted.saldo_no_momento: raise ValidationError('Houve movimentação desde a contagem; recontagem obrigatória.')
        holds=stock.lot_holds(lot.peca,lot.deposito)
        if counted.quantidade<holds.get(lot.pk,0): raise ValidationError('Divergência compromete reservas; regularize os compromissos antes da aprovação.')
        plans.append((item,counted,lot))
    # Validate every count before any adjustment. Each official movement is atomic.
    for item,counted,lot in plans:
        move=None
        if counted.quantidade!=lot.quantidade:
            scope=_approved_count.set((user.pk,lot.peca_id,lot.pk,counted.quantidade))
            try:
                move=gs.movimentar(user,lot.peca_id,'INVENTARIO',counted.quantidade,inventory.motivo,origem_id=inventory.deposito_id if counted.quantidade<lot.quantidade else None,destino_id=inventory.deposito_id if counted.quantidade>lot.quantidade else None,lote_id=lot.pk,request_id=uuid.uuid5(inventory.public_id,'ajuste:'+str(item.pk)))
            finally: _approved_count.reset(scope)
        gs.write(m.AjusteInventario(item=item,contagem=counted,movimento=move))
    inventory.status='APROVADO';inventory.aprovado_por=user;inventory.aprovado_em=timezone.now();gs.write(inventory)
    gs.audit(user,'INVENTARIO_APROVADO',inventory,{'itens':len(items),'deposito':inventory.deposito_id})
    return inventory

@transaction.atomic
def create_transfer(user,part_id,source_id,target_id,quantity,reason,request_id,transit_id=None):
    require_capability(user,'estoque_escrever');key=token(request_id);qty=stock.amount(str(quantity))
    part=g.Peca.objects.select_for_update().get(pk=part_id,ativo=True)
    source=m.Deposito.objects.get(pk=source_id,ativo=True);target=m.Deposito.objects.get(pk=target_id,ativo=True);transit=m.Deposito.objects.get(pk=transit_id,ativo=True) if transit_id else None
    if not reason.strip(): raise ValidationError('Transferência exige motivo.')
    old=m.TransferenciaEstoque.objects.filter(request_id=key).first()
    if old:
        if (old.peca_id,old.origem_id,old.destino_id,old.transito_id,old.quantidade,old.motivo)!=(part.pk,source.pk,target.pk,transit.pk if transit else None,qty,reason.strip()): raise ValidationError('Token de transferência reutilizado.')
        return old
    row=gs.write(m.TransferenciaEstoque(peca=part,origem=source,destino=target,transito=transit,quantidade=qty,motivo=reason.strip(),request_id=key,criado_por=user))
    gs.audit(user,'TRANSFERENCIA_SOLICITADA',row,{'quantidade':str(qty),'origem':source.pk,'destino':target.pk,'transito':transit.pk if transit else None})
    return row

@transaction.atomic
def send_transfer(user,public_id):
    require_capability(user,'estoque_escrever')
    row=m.TransferenciaEstoque.objects.select_for_update().get(public_id=public_id)
    if row.status!='SOLICITADA': return row
    move=gs.movimentar(user,row.peca_id,'TRANSFER',row.quantidade,row.motivo,origem_id=row.origem_id,destino_id=row.transito_id or row.destino_id,request_id=uuid.uuid5(row.public_id,'envio'))
    gs.write(m.EtapaTransferencia(transferencia=row,etapa='ENVIADA' if row.transito_id else 'DIRETA',movimento=move))
    if row.transito_id:
        reserved=gs.write(m.ReservaEstoque(peca=row.peca,deposito=row.transito,quantidade=row.quantidade,motivo='Compromisso da transferência em trânsito',usuario=user,transferencia=row,request_id=uuid.uuid5(row.public_id,'reserva-transito')))
        for detail in move.lotes_movimentados.filter(variacao__gt=0):
            gs.write(m.AlocacaoReservaEstoque(reserva=reserved,lote=detail.lote,quantidade=detail.variacao,quantidade_inicial=detail.variacao))
        gs.audit(user,'ESTOQUE_RESERVADO',reserved,{'transferencia':row.pk,'deposito':row.transito_id,'quantidade':str(row.quantidade)})
    row.status='EM_TRANSITO' if row.transito_id else 'RECEBIDA';gs.write(row);gs.audit(user,'TRANSFERENCIA_'+row.status,row)
    return row

@transaction.atomic
def receive_transfer(user,public_id):
    require_capability(user,'estoque_escrever')
    row=m.TransferenciaEstoque.objects.select_for_update().get(public_id=public_id)
    if row.status=='RECEBIDA': return row
    if row.status!='EM_TRANSITO': raise ValidationError('Transferência não está em trânsito.')
    g.Peca.objects.select_for_update().get(pk=row.peca_id)
    for reservation in row.reservas.select_for_update().filter(status='ATIVA'):
        reservation.status='CONSUMIDA';reservation.quantidade=0;gs.write(reservation)
        for detail in reservation.alocacoes.all(): detail.quantidade=0;gs.write(detail)
        gs.audit(user,'RESERVA_CONSUMIDA',reservation,{'transferencia':row.pk,'motivo':'Recebimento da transferência no destino'})
    outbound=row.etapas.get(etapa='ENVIADA').movimento
    for detail in outbound.lotes_movimentados.filter(variacao__gt=0).order_by('lote_id'):
        move=gs.movimentar(user,row.peca_id,'TRANSFER',detail.variacao,row.motivo,origem_id=row.transito_id,destino_id=row.destino_id,lote_id=detail.lote_id,request_id=uuid.uuid5(row.public_id,'receber:'+str(detail.lote_id)))
        gs.write(m.EtapaTransferencia(transferencia=row,etapa='RECEBIDA',movimento=move))
    row.status='RECEBIDA';gs.write(row);gs.audit(user,'TRANSFERENCIA_RECEBIDA',row)
    return row
