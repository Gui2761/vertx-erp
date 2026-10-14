"""Views' calculations and approvals over the official Venda/PDV services."""
import calendar
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from platform_core.modules import require_capability
from platform_core.access import effective_role
from gestao import services as gs
from . import models as m, commerce as c, stock
from .seller_access import is_seller

ZERO = Decimal('0')

def own_sales(user):
    require_capability(user, 'central_vendedor')
    return m.Venda.objects.filter(vendedor=user).select_related('cliente').prefetch_related('itens','devolucoes','pagamentos_pdv__forma')

def net_sale(sale):
    return max(ZERO, sale.total - sum((row.valor for row in sale.devolucoes.all()), ZERO))

def indicators(user, today=None):
    today = today or timezone.localdate()
    month = today.replace(day=1)
    next_month = (month.replace(day=28) + timezone.timedelta(days=4)).replace(day=1)
    week = today - timezone.timedelta(days=today.weekday())
    sales = list(own_sales(user).filter(finalizada_em__date__gte=min(month,week), finalizada_em__date__lt=next_month, status__in=['FINALIZADA','PARCIALMENTE_DEVOLVIDA','DEVOLVIDA']))
    month_rows = [row for row in sales if timezone.localdate(row.finalizada_em) >= month]
    total = sum((net_sale(row) for row in month_rows), ZERO)
    daily = sum((net_sale(row) for row in sales if timezone.localdate(row.finalizada_em)==today), ZERO)
    weekly = sum((net_sale(row) for row in sales if week <= timezone.localdate(row.finalizada_em) <= today), ZERO)
    goal = m.MetaVendedor.objects.filter(vendedor=user, competencia=month).first()
    missing = max(ZERO,goal.valor-total) if goal else None
    percent = (total*100/goal.valor).quantize(Decimal('.1'), rounding=ROUND_HALF_UP) if goal and goal.valor else None
    pace = (missing/Decimal(calendar.monthrange(today.year,today.month)[1]-today.day+1)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if missing is not None else None
    motivation = 'Configure sua meta com o responsável comercial.'
    if percent is not None:
        motivation = ('Meta atingida! Continue acompanhando suas vendas.' if percent>=100 else f'Você atingiu {percent}% da sua meta. Cada venda conta.')
    return {'today_total':daily,'week_total':weekly,'month_total':total,'ticket':(total/len(month_rows)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if month_rows else ZERO,'goal':goal,'remaining':missing,'percent':percent,'daily_needed':pace,'motivation':motivation,'count':len(month_rows)}

def availability(part, depot, sale=None):
    # Read only: do not materialize legacy lots or change a stock balance here.
    valid = stock.total(stock.valid_lots(part,depot))
    balances = stock.total(m.SaldoDeposito.objects.filter(peca=part,deposito=depot))
    detailed = stock.total(m.LoteEstoque.objects.filter(peca=part,deposito=depot))
    legacy = max(ZERO,balances-detailed)
    if part.validade and part.validade < timezone.localdate():
        legacy = ZERO
    reserved = stock.active_reservations(part,depot)
    if sale:
        reserved = reserved.exclude(venda=sale)
    return max(ZERO,valid+legacy-stock.total(reserved))

def cart_hash(sale):
    rows = list(sale.itens.order_by('pk').values('pk','peca_id','quantidade','valor_unitario','desconto'))
    raw = json.dumps({'venda':sale.pk,'deposito':sale.deposito_id,'acrescimo':format(sale.acrescimo,'.2f'),'itens':rows},sort_keys=True,default=str)
    return hashlib.sha256(raw.encode()).hexdigest()

def validate_discount(user, sale):
    if not is_seller(user):
        return
    items = list(sale.itens.all())
    gross = sum(((row.quantidade*row.valor_unitario).quantize(c.CENT) for row in items),ZERO)
    discounts = sum((row.desconto for row in items),ZERO)+sale.desconto_global
    limit = (m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()).limite_desconto_percentual
    if discounts*100 <= gross*limit:
        return
    approved = sale.solicitacoes_desconto.filter(status='APROVADO',valor=sale.desconto_global,carrinho_hash=cart_hash(sale)).exists()
    if not approved:
        raise PermissionDenied('Desconto total acima do limite. Solicite autorização do responsável.')

@transaction.atomic
def request_discount(user, public_id, value, reason):
    sale, session = c.lock_sale(user,public_id);c.draft(sale,session)
    value = c.money(value,True)
    if not reason.strip() or not sale.itens.exists() or value > sum((row.total for row in sale.itens.all()),ZERO):
        raise ValidationError('Informe desconto válido e motivo para o carrinho atual.')
    fingerprint = cart_hash(sale)
    existing = sale.solicitacoes_desconto.filter(status='PENDENTE').first()
    if existing:
        if (existing.valor,existing.carrinho_hash,existing.motivo)!=(value,fingerprint,reason.strip()):
            raise ValidationError('Já existe uma solicitação pendente. Aguarde a decisão do responsável.')
        return existing
    row = gs.write(m.SolicitacaoDescontoPDV(venda=sale,solicitado_por=user,valor=value,motivo=reason.strip(),carrinho_hash=fingerprint))
    gs.audit(user,'PDV_DESCONTO_SOLICITADO',row,{'venda':sale.pk,'valor':str(value),'motivo':reason.strip()})
    from .notifications import deliver
    deliver(f'pdv-desconto:{row.pk}','Autorização de desconto',f'{sale} solicita R$ {value}.',['ADMIN','GESTOR'],'/vendedor/gestao/')
    return row

def require_supervisor(user):
    require_capability(user,'desconto_supervisor')
    if effective_role(user) not in {'ADMIN','GESTOR'}:
        raise PermissionDenied('A decisão exige ADMIN/GESTOR.')

@transaction.atomic
def decide_discount(user, pk, approve, reason):
    require_supervisor(user)
    candidate = m.SolicitacaoDescontoPDV.objects.get(pk=pk)
    sale, session = c.lock_sale(user,candidate.venda.public_id)
    row = m.SolicitacaoDescontoPDV.objects.select_for_update().get(pk=pk)
    if row.status!='PENDENTE':
        raise ValidationError('Solicitação já decidida.')
    if not reason.strip():
        raise ValidationError('A decisão exige justificativa.')
    c.draft(sale,session)
    if approve and row.carrinho_hash!=cart_hash(sale):
        raise ValidationError('Carrinho alterado: recuse esta solicitação e peça uma nova.')
    if approve:
        # Use the same pricing service and the authenticated supervisor.
        c.pricing(user,sale.public_id,row.valor,sale.acrescimo,reason,record_approval=False)
    row.status='APROVADO' if approve else 'RECUSADO'
    row.decidido_por=user;row.decidido_em=timezone.now();row.decisao_motivo=reason.strip();gs.write(row)
    gs.audit(user,'PDV_DESCONTO_DECIDIDO',row,{'venda':sale.pk,'valor':str(row.valor),'aprovado':approve,'motivo':reason.strip(),'solicitante':row.solicitado_por_id})
    gs.write(m.Notificacao(usuario=row.solicitado_por,chave=f'pdv-desconto-decisao:{row.pk}',titulo='Solicitação de desconto decidida',mensagem=f'{sale}: {row.status.lower()}.',link=f'/pdv/vendas/{sale.public_id}/'))
    return row
