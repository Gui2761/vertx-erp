"""PDV transactions using Venda, FEFO, Lancamento, Pagamento and MovimentoCaixa."""
import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from platform_core.modules import require_capability, has_capability, module_enabled
from platform_core.context import current_organization
from gestao import models as g, services as gs, products
from . import models as m, services as finance, stock
from .commerce_scope import _execution

ZERO=Decimal('0'); CENT=Decimal('.01')

def money(value, zero=False):
    value=products.number(value)
    if value < 0 or value > Decimal('999999999999.99') or not zero and value==0 or value != value.quantize(CENT):
        raise ValidationError('Informe valor monetário exato em centavos.')
    return value

def token(value):
    try: return uuid.UUID(str(value))
    except (ValueError,TypeError,AttributeError): raise ValidationError('Identificador da operação inválido.')

def own_session(user, public_id, closed=False):
    require_capability(user,'pdv')
    row=m.SessaoCaixa.objects.select_for_update().get(public_id=public_id)
    if row.operador_id!=user.pk and not has_capability(user,'caixa_supervisor'):
        raise PermissionDenied('Caixa pertence a outro operador.')
    if row.fechado_em and not closed:
        raise ValidationError('Caixa já fechado.')
    return row

@transaction.atomic
def open_cash(user,account_id,counted,request_id):
    require_capability(user,'pdv')
    if not module_enabled('financeiro'): raise PermissionDenied('Financeiro desabilitado.')
    amount=money(counted,True); key=token(request_id)
    try:
        account=m.ContaBancaria.objects.select_for_update(of=('self',)).select_related('deposito_padrao').get(pk=account_id,ativo=True,tipo='CAIXA')
    except m.ContaBancaria.DoesNotExist:
        # Do not reveal whether an out-of-tenant ID exists; make stale or
        # unavailable selections actionable for the operator.
        raise ValidationError('O caixa selecionado não está disponível nesta organização. Atualize a página e confira o cadastro do caixa.') from None
    if not account.deposito_padrao_id or not account.deposito_padrao.ativo or account.deposito_padrao.organization_id!=current_organization().pk:
        raise ValidationError('Configure um depósito padrão ativo no cadastro do caixa antes de abrir a sessão.')
    old=m.SessaoCaixa.objects.filter(abertura_id=key).first()
    if old:
        if (old.conta_id,old.operador_id,old.saldo_abertura)!=(account.pk,user.pk,amount): raise ValidationError('Token de abertura reutilizado com outros dados.')
        return old
    if m.SessaoCaixa.objects.filter(conta=account,fechado_em__isnull=True).exists(): raise ValidationError('Conta já possui caixa aberto.')
    row=gs.write(m.SessaoCaixa(conta=account,operador=user,saldo_abertura=amount,abertura_id=key))
    gs.audit(user,'CAIXA_ABERTO',row,{'contagem':str(amount),'saldo_ledger':str(account.saldo),'sem_movimento_financeiro':True})
    return row

def cash_expected(session):
    events=session.eventos.select_related('movimento')
    return session.saldo_abertura+sum((event.movimento.valor if event.movimento.tipo=='ENTRADA' else -event.movimento.valor for event in events),ZERO)

@transaction.atomic
def close_cash(user,public_id,counted,reason=''):
    session=own_session(user,public_id,True); amount=money(counted,True)
    if session.fechado_em:
        if session.contado!=amount or session.justificativa!=reason.strip(): raise ValidationError('Fechamento já registrado com outros dados.')
        return session
    expected=cash_expected(session); difference=amount-expected
    if difference and not reason.strip(): raise ValidationError('Diferença de caixa exige justificativa.')
    session.esperado,session.contado,session.diferenca=expected,amount,difference
    session.justificativa=reason.strip();session.fechado_em=timezone.now();session.fechado_por=user
    gs.write(session);gs.audit(user,'CAIXA_FECHADO',session,{'esperado':str(expected),'contado':str(amount),'diferenca':str(difference),'justificativa':reason.strip()})
    return session

@transaction.atomic
def cash_operation(user,public_id,kind,amount,reason,request_id):
    session=own_session(user,public_id)
    account=m.ContaBancaria.objects.select_for_update(of=('self',)).select_related('deposito_padrao').get(pk=session.conta_id)
    if not account.deposito_padrao_id or not account.deposito_padrao.ativo or account.deposito_padrao.organization_id!=current_organization().pk:
        raise ValidationError('Configure um depósito padrão ativo no caixa antes de movimentá-lo.')
    require_capability(user,'caixa_supervisor')
    if kind not in ('SUPRIMENTO','SANGRIA','RETIRADA','AJUSTE_ENTRADA','AJUSTE_SAIDA') or not reason.strip(): raise ValidationError('Operação/motivo inválidos.')
    direction='ENTRADA' if kind in ('SUPRIMENTO','AJUSTE_ENTRADA') else 'SAIDA'
    with _execution(user,session=session):
        move=finance.caixa(user,session.conta_id,direction,money(amount),timezone.localdate(),kind+': '+reason.strip(),token(request_id))
    prior=m.EventoCaixa.objects.filter(movimento=move).first()
    if prior:
        if prior.sessao_id!=session.pk: raise ValidationError('Movimento já pertence a outro caixa.')
        return prior
    event=gs.write(m.EventoCaixa(sessao=session,movimento=move,tipo='AJUSTE' if kind.startswith('AJUSTE') else kind))
    gs.audit(user,'OPERACAO_CAIXA',event,{'motivo':reason,'valor':str(move.valor)})
    return event

@transaction.atomic
def new_sale(user,session_id,depot_id=None,customer_id=None,seller_id=None,branch_id=None,center_id=None,request_id=None):
    session=own_session(user,session_id)
    account=m.ContaBancaria.objects.select_related('deposito_padrao').get(pk=session.conta_id)
    depot=account.deposito_padrao
    if not depot or not depot.ativo or depot.organization_id!=current_organization().pk:
        raise ValidationError('O caixa não possui depósito padrão ativo configurado.')
    # Compatibility for internal callers during migration: any supplied depot must
    # match the account configuration; the browser never chooses this value.
    if depot_id not in (None, '') and int(depot_id)!=depot.pk:
        raise ValidationError('O depósito da venda é definido pelo caixa e não pode ser alterado pelo operador.')
    from .seller_access import is_seller
    if is_seller(user) and seller_id and int(seller_id)!=user.pk:
        raise PermissionDenied('Vendedor não pode atribuir vendas a outra pessoa.')
    key=token(request_id) if request_id else uuid.uuid4()
    intent={'caixa':session.pk,'deposito':depot.pk,'cliente':int(customer_id) if customer_id else None,'vendedor':int(seller_id or user.pk),'filial':int(branch_id) if branch_id else None,'centro':int(center_id) if center_id else None,'usuario':user.pk}
    prior=m.Venda.objects.filter(criacao_id=key).first()
    if prior:
        if prior.dados_criacao!=intent: raise ValidationError('Token de abertura de venda reutilizado com outros dados.')
        return prior
    from clientes.models import Cliente
    from contas.models import Usuario
    from platform_core.models import FilialEmpresa
    customer=Cliente.objects.get(pk=customer_id,ativo=True) if customer_id else None
    seller=Usuario.objects.get(pk=seller_id or user.pk,is_active=True)
    if not seller.memberships.filter(organization=current_organization(),status='ATIVO').exists(): raise ValidationError('Vendedor fora da organização.')
    sale=m.Venda.objects.create(sessao_caixa=session,deposito=depot,cliente=customer,vendedor=seller,vencimento=timezone.localdate(),criado_por=user,criacao_id=key,dados_criacao=intent,filial=FilialEmpresa.objects.get(pk=branch_id,ativo=True) if branch_id else None,centro_custo=g.CentroCusto.objects.get(pk=center_id,ativo=True) if center_id else None)
    gs.audit(user,'VENDA_ABERTA',sale,{'caixa':session.pk,'vendedor':seller.pk})
    return sale

@transaction.atomic
def sale_state(user,public_id,state,reason=''):
    sale,session=lock_sale(user,public_id)
    if state=='CANCELADA':
        if sale.status=='CANCELADA': return sale
        if sale.status not in ('RASCUNHO','ORCAMENTO','AG_PAGAMENTO') or not reason.strip(): raise ValidationError('Cancelamento exige venda aberta e motivo; venda finalizada usa devolução.')
        for reservation in sale.reservas_estoque.select_for_update().filter(status='ATIVA'):
            reservation.status='LIBERADA';gs.write(reservation)
            gs.audit(user,'RESERVA_LIBERADA',reservation,{'motivo':reason,'venda':sale.pk})
    elif state in ('ORCAMENTO','AG_PAGAMENTO'):
        draft(sale,session)
        if not sale.itens.exists(): raise ValidationError('Venda sem itens.')
        config=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
        if state=='ORCAMENTO' and config.reservar_orcamento:
            for item in sale.itens.order_by('peca_id','pk'):
                held=stock.total(sale.reservas_estoque.filter(peca=item.peca,status='ATIVA'))
                needed=stock.total(sale.itens.filter(peca=item.peca))-held
                if needed>0:
                    with _execution(user,sale=sale,session=session): stock.reserve(user,item.peca_id,sale.deposito_id,needed,'Reserva orçamento comercial',sale_id=sale.pk,request_id=uuid.uuid5(sale.public_id,'orcamento:'+str(item.peca_id)))
    elif state=='RASCUNHO':
        if sale.status not in ('ORCAMENTO','AG_PAGAMENTO') or not session or session.fechado_em: raise ValidationError('Venda não pode ser reaberta.')
    else: raise ValidationError('Estado comercial inválido.')
    sale.status=state;gs.write(sale);gs.audit(user,'VENDA_'+state,sale,{'motivo':reason})
    return sale

@transaction.atomic
def quote_to_sale(user,quote_id,session_id,depot_id=None):
    session=own_session(user,session_id)
    quote=g.Orcamento.objects.select_for_update().get(pk=quote_id)
    prior=m.Venda.objects.filter(orcamento_origem=quote).first()
    if prior: return prior
    if quote.status!='APROVADO' or quote.ordem_convertida_id: raise ValidationError('Orçamento precisa estar aprovado e não convertido em OS.')
    items=list(quote.itens.select_related('peca'))
    if not items or any(i.tipo!='PECA' or not i.peca_id for i in items): raise ValidationError('Conversão comercial exige somente produtos; serviços permanecem no fluxo de OS.')
    receivable=quote.lancamentos.filter(tipo='RECEBER').first()
    if receivable and (receivable.status=='CANCELADO' or receivable.parcelas.exists()): raise ValidationError('Recebível parcelado/cancelado exige revisão no financeiro.')
    sale=new_sale(user,session_id,depot_id,quote.cliente_id)
    sale.orcamento_origem=quote;sale.conta=receivable;sale.desconto_global=quote.desconto;sale.acrescimo=quote.deslocamento+quote.impostos;sale.vencimento=quote.validade;gs.write(sale)
    for item in items: m.ItemVenda.objects.create(venda=sale,peca=item.peca,quantidade=item.quantidade,valor_unitario=item.valor_unitario,desconto=item.desconto)
    # Retain the approved quote and its immutable terms; the unique link tracks conversion.
    gs.audit(user,'ORCAMENTO_CONVERTIDO_VENDA',sale,{'orcamento':quote.pk,'recebivel_reutilizado':receivable.pk if receivable else None})
    return sale

@transaction.atomic
def return_sale(user,public_id,rows,reason,request_id,account_id=None,settle=False,session_id=None,exchange_id=None):
    require_capability(user,'devolucao');require_capability(user,'estoque_escrever');require_capability(user,'financeiro_escrever')
    sale,original_session=lock_sale(user,public_id);key=token(request_id)
    if not reason.strip() or not isinstance(rows,list) or not rows: raise ValidationError('Devolução exige motivo e itens.')
    selection=sorted([{'item':int(row['item']),'quantidade':str(stock.amount(str(row['quantidade'])))} for row in rows],key=lambda row:row['item'])
    if len({row['item'] for row in selection})!=len(selection): raise ValidationError('Item duplicado na devolução.')
    data={'itens':selection,'motivo':reason.strip(),'conta':account_id,'liquidar':bool(settle),'caixa':str(session_id) if session_id else None,'troca':str(exchange_id) if exchange_id else None}
    old=m.DevolucaoVenda.objects.filter(request_id=key).first()
    if old:
        if old.venda_id!=sale.pk or old.dados!=data: raise ValidationError('Token de devolução reutilizado com outros dados.')
        return old
    if sale.status not in ('FINALIZADA','PARCIALMENTE_DEVOLVIDA') or not sale.snapshot or not sale.conta_id: raise ValidationError('Devolução exige venda finalizada com rastreabilidade por item/lote.')
    entry=g.Lancamento.objects.select_for_update().get(pk=sale.conta_id)
    if entry.parcelas.exists() or entry.status=='CANCELADO': raise ValidationError('Recebível parcelado/cancelado requer revisão no financeiro antes da devolução.')
    snapshot={row['item']:row for row in sale.snapshot['itens']}
    planned=[];total=ZERO
    for row in selection:
        item=sale.itens.get(pk=row['item']);qty=Decimal(row['quantidade'])
        previous=item.devolucoes.aggregate(quantity=Sum('quantidade'),value=Sum('valor'))
        used=previous['quantity'] or ZERO;paid=(previous['value'] or ZERO).quantize(CENT,rounding=ROUND_HALF_UP)
        if used+qty>item.quantidade or not item.movimento_id: raise ValidationError('Quantidade excede a venda ou movimento original indisponível.')
        net=Decimal(snapshot[item.pk]['valor_liquido'])
        value=(((used+qty)*net/item.quantidade).quantize(CENT,rounding=ROUND_HALF_UP)-paid).quantize(CENT,rounding=ROUND_HALF_UP)
        planned.append((item,qty,value));total+=value
    list(g.Peca.objects.select_for_update().filter(pk__in=[item.peca_id for item,_,_ in planned]).order_by('pk'))
    total=total.quantize(CENT,rounding=ROUND_HALF_UP)
    abatement=min(total,entry.saldo.quantize(CENT,rounding=ROUND_HALF_UP));refund=(total-abatement).quantize(CENT,rounding=ROUND_HALF_UP)
    replacement=m.Venda.objects.get(public_id=exchange_id) if exchange_id else None
    if replacement and replacement.pk==sale.pk: raise ValidationError('Troca deve apontar para uma nova venda.')
    refund_entry=gs.write(g.Lancamento(tipo='PAGAR',descricao=f'Devolução {sale}',cliente=sale.cliente,centro_custo=sale.centro_custo,valor=refund,vencimento=timezone.localdate(),criado_por=user)) if refund else None
    returned=gs.write(m.DevolucaoVenda(venda=sale,request_id=key,motivo=reason.strip(),usuario=user,valor=total,reembolso=refund_entry,dados=data,troca_por=replacement))
    for item,qty,value in planned:
        move=gs.movimentar(user,item.peca_id,'DEVOLUCAO',qty,reason.strip(),destino_id=sale.deposito_id,venda_id=sale.pk,lote_data={'devolucao_item':item.pk},request_id=uuid.uuid5(key,'item:'+str(item.pk)))
        gs.write(m.ItemDevolucaoVenda(devolucao=returned,item=item,quantidade=qty,valor=value,movimento=move))
    if abatement:
        gs.write(g.EventoFinanceiro(lancamento=entry,tipo='ABATIMENTO',valor=abatement,data=timezone.localdate(),usuario=user,observacao=f'Devolução {returned.public_id}: {reason}'))
        if entry.saldo==0: entry.status='LIQUIDADO';entry.data_liquidacao=timezone.localdate();gs.write(entry)
    if refund_entry and settle:
        session=own_session(user,session_id) if session_id else None
        if account_id and m.ContaBancaria.objects.get(pk=account_id).tipo=='CAIXA' and (not session or session.conta_id!=account_id): raise ValidationError('Reembolso em caixa exige sessão aberta correspondente.')
        payment=finance.pagar(user,refund_entry.pk,refund,timezone.localdate(),reason.strip(),account_id,uuid.uuid5(key,'reembolso'))
        if session and account_id==session.conta_id:
            gs.write(m.EventoCaixa(sessao=session,movimento=m.MovimentoCaixa.objects.get(conta_id=account_id,referencia=payment.request_id),tipo='DEVOLUCAO'))
    complete=all((item.devolucoes.aggregate(total=Sum('quantidade'))['total'] or ZERO)==item.quantidade for item in sale.itens.all())
    sale.status='DEVOLVIDA' if complete else 'PARCIALMENTE_DEVOLVIDA';gs.write(sale)
    gs.audit(user,'VENDA_DEVOLVIDA',returned,{'venda':sale.pk,'valor':str(total),'abatimento':str(abatement),'reembolso':str(refund),'liquidado':bool(settle),'motivo':reason})
    return returned

def lock_sale(user,public_id):
    require_capability(user,'pdv')
    candidate=m.Venda.objects.get(public_id=public_id)
    from .seller_access import is_seller
    if is_seller(user) and candidate.vendedor_id != user.pk:
        raise PermissionDenied('Venda pertence a outro vendedor.')
    session=own_session(user,candidate.sessao_caixa.public_id,True) if candidate.sessao_caixa_id else None
    sale=m.Venda.objects.select_for_update().get(pk=candidate.pk)
    if not session and not has_capability(user,'caixa_supervisor'): raise PermissionDenied('Venda legada exige supervisor.')
    return sale,session

def draft(sale,session):
    if sale.status!='RASCUNHO' or not session or session.fechado_em: raise ValidationError('Operação exige venda em rascunho e caixa aberto.')

@transaction.atomic
def add_item(user,public_id,code,quantity,mode='venda',discount=0,reason=''):
    sale,session=lock_sale(user,public_id);draft(sale,session)
    if mode not in ('base','venda'): raise ValidationError('PDV usa somente unidade base ou unidade de venda configurada.')
    part=products.lookup(code)
    unit_price=part.preco_venda*(part.fator_venda if mode=='venda' else 1)
    conversion=products.convert(part,quantity,mode,unit_price)
    value=money(discount,True)
    config=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
    gross=(conversion['quantidade_base']*conversion['valor_base']).quantize(CENT,rounding=ROUND_HALF_UP)
    if value>gross: raise ValidationError('Desconto excede o item.')
    if value and (not reason.strip() or value*100>gross*config.limite_desconto_percentual and not has_capability(user,'desconto_supervisor')): raise PermissionDenied('Desconto exige motivo e limite/autorização.')
    item=m.ItemVenda.objects.create(venda=sale,peca=part,quantidade=conversion['quantidade_base'],valor_unitario=conversion['valor_base'],desconto=value,conversao={k:str(v) for k,v in conversion.items()})
    if config.reservar_rascunho:
        with _execution(user,sale=sale,session=session): stock.reserve(user,part.pk,sale.deposito_id,item.quantidade,'Reserva PDV',sale_id=sale.pk,request_id=uuid.uuid5(sale.public_id,'reserva:'+str(item.pk)))
    gs.audit(user,'VENDA_ITEM_ADICIONADO',item,{'conversao':item.conversao,'desconto':str(value),'motivo':reason})
    from .seller_services import validate_discount
    validate_discount(user,sale)
    return item

@transaction.atomic
def edit_item(user,public_id,item_id,quantity,discount=0,reason=''):
    sale,session=lock_sale(user,public_id);draft(sale,session)
    item=sale.itens.select_for_update().get(pk=item_id)
    part=g.Peca.objects.select_for_update().get(pk=item.peca_id)
    qty=products.convert(part,quantity,'base')['quantidade_base'];value=money(discount,True)
    config=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
    if value>qty*item.valor_unitario: raise ValidationError('Desconto excede subtotal.')
    if value and (not reason.strip() or value>qty*item.valor_unitario*config.limite_desconto_percentual/100 and not has_capability(user,'desconto_supervisor')): raise PermissionDenied('Desconto exige motivo e autorização acima do limite.')
    before={'quantidade':str(item.quantidade),'desconto':str(item.desconto)}
    held=list(sale.reservas_estoque.select_for_update().filter(peca=part,status='ATIVA'))
    for row in held:
        row.status='LIBERADA';gs.write(row);gs.audit(user,'RESERVA_LIBERADA',row,{'motivo':'Alteração auditada do carrinho'})
    item.quantidade=qty;item.desconto=value
    item.conversao={**item.conversao,'quantidade_base':str(qty),'quantidade_comercial':str(qty/Decimal(item.conversao.get('fator','1')))}
    gs.write(item)
    if held or config.reservar_rascunho:
        needed=stock.total(sale.itens.filter(peca=part))
        with _execution(user,sale=sale,session=session): stock.reserve(user,part.pk,sale.deposito_id,needed,'Carrinho atualizado',sale_id=sale.pk,request_id=uuid.uuid4())
    gs.audit(user,'VENDA_ITEM_ALTERADO',item,{'antes':before,'depois':{'quantidade':str(qty),'desconto':str(value)},'motivo':reason})
    from .seller_services import validate_discount
    validate_discount(user,sale)
    return item

@transaction.atomic
def sale_note(user,public_id,note):
    sale,session=lock_sale(user,public_id);draft(sale,session)
    before=sale.observacoes;sale.observacoes=note.strip();gs.write(sale)
    gs.audit(user,'VENDA_OBSERVACAO',sale,{'antes':before,'depois':sale.observacoes})
    return sale

@transaction.atomic
def remove_item(user,public_id,item_id):
    sale,session=lock_sale(user,public_id);draft(sale,session)
    item=sale.itens.get(pk=item_id)
    part=g.Peca.objects.select_for_update().get(pk=item.peca_id)
    held=list(sale.reservas_estoque.select_for_update().filter(peca=part,status='ATIVA'))
    for row in held:
        row.status='LIBERADA';gs.write(row);gs.audit(user,'RESERVA_LIBERADA',row,{'motivo':'Remoção auditada de item do carrinho'})
    gs.audit(user,'VENDA_ITEM_REMOVIDO',item,{'quantidade':str(item.quantidade)});item.delete()
    needed=stock.total(sale.itens.filter(peca=part))
    if held and needed:
        with _execution(user,sale=sale,session=session): stock.reserve(user,part.pk,sale.deposito_id,needed,'Carrinho após remoção',sale_id=sale.pk,request_id=uuid.uuid4())
    from .seller_services import validate_discount
    validate_discount(user,sale)

@transaction.atomic
def pricing(user,public_id,discount,addition,reason='',record_approval=True):
    sale,session=lock_sale(user,public_id);draft(sale,session)
    discount,addition=money(discount,True),money(addition,True)
    gross=sum((item.total for item in sale.itens.all()),ZERO)
    config=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
    if discount>gross: raise ValidationError('Desconto excede total.')
    if (discount or addition) and not reason.strip(): raise ValidationError('Alteração de preço exige motivo.')
    if discount*100>gross*config.limite_desconto_percentual and not has_capability(user,'desconto_supervisor'): raise PermissionDenied('Desconto requer supervisor.')
    before={'desconto':str(sale.desconto_global),'acrescimo':str(sale.acrescimo)}
    sale.desconto_global=discount;sale.acrescimo=addition;gs.write(sale)
    gs.audit(user,'VENDA_PRECO_ALTERADO',sale,{'antes':before,'depois':{'desconto':str(discount),'acrescimo':str(addition)},'motivo':reason})
    from .seller_services import cart_hash, validate_discount
    if record_approval and has_capability(user,'desconto_supervisor') and (discount or addition):
        gs.write(m.SolicitacaoDescontoPDV(venda=sale,solicitado_por=user,valor=discount,motivo=reason.strip(),carrinho_hash=cart_hash(sale),status='APROVADO',decidido_por=user,decidido_em=timezone.now(),decisao_motivo=reason.strip()))
    validate_discount(user,sale)
    return sale

def normalize_payments(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=20: raise ValidationError('Informe de 1 a 20 pagamentos.')
    result=[]
    for row in rows:
        try:
            form=g.FormaPagamento.objects.get(pk=int(row['forma']),ativo=True)
        except (g.FormaPagamento.DoesNotExist,TypeError,ValueError,KeyError):
            raise ValidationError('A forma de pagamento selecionada não está ativa nesta organização.') from None
        if not form.tipo_pdv: raise ValidationError('Forma precisa ser configurada para o PDV.')
        if form.tipo_pdv in {'PIX','DEBITO','CREDITO','TRANSFERENCIA','OUTRO'}:
            organization = current_organization()
            if not form.conta_pdv_id or not organization:
                raise ValidationError('Configure uma conta financeira ativa desta organização nesta forma de pagamento antes de utilizá-la.')
            try:
                account = m.ContaBancaria.objects.get(pk=form.conta_pdv_id, ativo=True)
            except (m.ContaBancaria.DoesNotExist, PermissionDenied):
                # A forma pode ter sido gravada de maneira inconsistente por um
                # caminho legado. A consulta tenant-scoped deve continuar
                # negando a conta estrangeira, com erro de validação previsível.
                raise ValidationError('Configure uma conta financeira ativa desta organização nesta forma de pagamento antes de utilizá-la.') from None
            if account.organization_id != organization.pk:
                raise ValidationError('Configure uma conta financeira ativa desta organização nesta forma de pagamento antes de utilizá-la.')
        value=money(row['valor']);received=money(row.get('recebido',value))
        if received<value or received!=value and form.tipo_pdv!='DINHEIRO': raise ValidationError('Troco permitido somente para dinheiro.')
        normalized={'forma':form.pk,'valor':str(value),'recebido':str(received)}
        if form.tipo_pdv=='CREDITO':
            try: installments=int(row.get('parcelas',1))
            except (TypeError,ValueError): raise ValidationError('Informe parcelas inteiras de 1 a 12 para cartão de crédito.') from None
            if not 1<=installments<=12: raise ValidationError('Cartão de crédito aceita de 1 a 12 parcelas.')
            if installments>1: normalized['parcelas']=installments
        elif row.get('parcelas') not in (None,'',1,'1'):
            raise ValidationError('Parcelamento está disponível somente para cartão de crédito.')
        result.append(normalized)
    return result

@transaction.atomic
def finalize(user,public_id,payments,request_id):
    sale,session=lock_sale(user,public_id)
    key=token(request_id);rows=normalize_payments(payments)
    if sale.finalizacao_id:
        if sale.finalizacao_id!=key or sale.finalizacao_dados!=rows: raise ValidationError('Venda já finalizada com outra operação.')
        return sale
    draft(sale,session)
    from platform_core.saas_services import verificar_limite
    verificar_limite(current_organization(), 'vendas_mes', erp_code='assistencia')
    items=list(sale.itens.select_related('peca').order_by('peca_id','pk'))
    from .seller_services import validate_discount
    validate_discount(user,sale)
    total=sale.total
    if not items or total<=0: raise ValidationError('Venda exige itens e total positivo.')
    # One stable lock order across all sales, including multiple products/accounts.
    list(g.Peca.objects.select_for_update().filter(pk__in=[i.peca_id for i in items]).order_by('pk'))
    if sale.conta_id:
        entry=g.Lancamento.objects.select_for_update().get(pk=sale.conta_id)
        if entry.valor!=total or entry.status=='CANCELADO' or entry.parcelas.exists(): raise ValidationError('Recebível do orçamento incompatível; revisar no financeiro.')
    else:
        entry=gs.write(g.Lancamento(tipo='RECEBER',descricao=str(sale),cliente=sale.cliente,centro_custo=sale.centro_custo,valor=total,vencimento=sale.vencimento,criado_por=user))
    if sum((Decimal(row['valor']) for row in rows),ZERO)!=entry.saldo: raise ValidationError('Pagamentos devem corresponder exatamente ao saldo da venda.')
    deferred=sum((Decimal(row['valor']) for row in rows if g.FormaPagamento.objects.get(pk=row['forma']).tipo_pdv in ('BOLETO','CREDIARIO')),ZERO)
    if deferred:
        from clientes.models import Cliente
        if not sale.cliente_id: raise ValidationError('Venda a prazo exige cliente identificado.')
        customer=Cliente.objects.select_for_update().get(pk=sale.cliente_id)
        outstanding=sum((item.saldo for item in g.Lancamento.objects.filter(cliente=customer,tipo='RECEBER',status__in=['PENDENTE','VENCIDO']).exclude(pk=entry.pk)),ZERO)
        if customer.limite_credito is None or customer.limite_credito<0 or outstanding+deferred>customer.limite_credito: raise ValidationError('Limite de crédito não configurado ou insuficiente.')
    sale.conta=entry
    allocated=[];subtotal=sum((i.total for i in items),ZERO)
    if subtotal<=0: raise ValidationError('Subtotal deve ser positivo.')
    exact=[i.total*total*100/subtotal for i in items]
    cents=[int(value) for value in exact]
    for index in sorted(range(len(items)),key=lambda i:exact[i]-cents[i],reverse=True)[:int(total*100)-sum(cents)]: cents[index]+=1
    for index,item in enumerate(items):
        net=Decimal(cents[index])/100
        with _execution(user,sale=sale,session=session,entry=entry):
            move=gs.movimentar(user,item.peca_id,'SAIDA',item.quantidade,str(sale),origem_id=sale.deposito_id,venda_id=sale.pk,request_id=uuid.uuid5(key,'item:'+str(item.pk)))
        item.custo_total=move.valor_custo;item.custo_unitario=(item.custo_total/item.quantidade).quantize(CENT,rounding=ROUND_HALF_UP);item.movimento=move;gs.write(item)
        allocated.append({'item':item.pk,'sku':item.peca.sku,'descricao':item.peca.descricao,'quantidade':str(item.quantidade),'valor_unitario':str(item.valor_unitario),'desconto':str(item.desconto),'valor_liquido':str(net),'custo_total':str(item.custo_total),'movimento':move.pk,'conversao':item.conversao,'lotes':[{'id':detail.lote_id,'numero':detail.lote.numero,'validade':detail.lote.validade.isoformat() if detail.lote.validade else None,'quantidade':str(-detail.variacao),'custo_unitario':str(detail.custo_unitario),'custo_total':str(detail.custo_total)} for detail in move.lotes_movimentados.select_related('lote')]})
    accounts=sorted(set([session.conta_id]+[f.conta_pdv_id for f in g.FormaPagamento.objects.filter(pk__in=[r['forma'] for r in rows]) if f.conta_pdv_id]))
    list(m.ContaBancaria.objects.select_for_update().filter(pk__in=accounts).order_by('pk'))
    for index,row in enumerate(rows):
        form=g.FormaPagamento.objects.get(pk=row['forma']);amount=Decimal(row['valor']);received=Decimal(row['recebido'])
        payment=None
        if form.tipo_pdv not in ('BOLETO','CREDIARIO'):
            account_id=session.conta_id if form.tipo_pdv=='DINHEIRO' else form.conta_pdv_id
            with _execution(user,sale=sale,session=session,entry=entry,account_ids=[form.conta_pdv_id] if form.conta_pdv_id else []):
                payment=finance.pagar(user,entry.pk,amount,timezone.localdate(),f'PDV: {form.nome}',account_id,uuid.uuid5(key,'pagamento:'+str(index)))
            if account_id==session.conta_id:
                move=m.MovimentoCaixa.objects.get(conta_id=account_id,referencia=payment.request_id)
                gs.write(m.EventoCaixa(sessao=session,movimento=move,tipo='VENDA'))
        gs.write(m.PagamentoVenda(venda=sale,forma=form,valor=amount,recebido=received,troco=received-amount,pagamento=payment,parcelas=row.get('parcelas',1)))
    sale.status='FINALIZADA';sale.finalizacao_id=key;sale.finalizacao_dados=rows;sale.finalizada_em=timezone.now()
    sale.snapshot={'numero':str(sale),'organization':str(current_organization().display_name),'cliente':str(sale.cliente) if sale.cliente_id else 'Consumidor não identificado','vendedor':str(sale.vendedor),'total':str(total),'desconto_global':str(sale.desconto_global),'acrescimo':str(sale.acrescimo),'itens':allocated,'pagamentos':rows,'saldo_pendente':str(entry.saldo),'finalizada_em':timezone.now().isoformat(),'fiscal':'Comprovante não fiscal'}
    gs.write(sale);gs.audit(user,'VENDA_FINALIZADA',sale,{'total':str(total),'lancamento':entry.pk,'caixa':session.pk,'request_id':str(key)})
    return sale
