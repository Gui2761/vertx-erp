"""Seller experience over official PDV, personnel and notification records."""
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from platform_core.context import current_organization
from platform_core.modules import require_capability, has_capability
from contas.models import Usuario
from clientes.models import Cliente
from gestao import models as g, services as gs
from . import models as m, commerce as c, seller_services as s


class CustomerForm(forms.ModelForm):
    class Meta:
        model=Cliente
        fields=['nome_razao_social','tipo_pessoa','cpf_cnpj','telefone','email']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in self.fields.values():
            field.widget.attrs['class']='form-control'

class GoalForm(forms.ModelForm):
    class Meta:
        model=m.MetaVendedor
        fields=['vendedor','competencia','valor']
        widgets={'competencia':forms.DateInput(attrs={'type':'date'})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['vendedor'].queryset=Usuario.objects.filter(is_active=True,memberships__organization=current_organization(),memberships__status='ATIVO',memberships__role__in=['VENDEDOR','PDV']).distinct()
        for field in self.fields.values(): field.widget.attrs['class']='form-control'

def date_range(request):
    today=timezone.localdate()
    period=request.GET.get('periodo','hoje')
    if period=='ontem': return today-timezone.timedelta(days=1),today-timezone.timedelta(days=1)
    if period=='mes': return today.replace(day=1),today
    if period=='personalizado':
        from datetime import date
        try:
            start,end=date.fromisoformat(request.GET.get('inicio','')),date.fromisoformat(request.GET.get('fim',''))
        except ValueError: raise ValidationError('Informe início e fim válidos.')
        if start>end or (end-start).days>366: raise ValidationError('O período deve ser de até 366 dias.')
        return start,end
    return today,today

@login_required
def home(request):
    require_capability(request.user,'pdv')
    return render(request,'operacao/seller_home.html',s.indicators(request.user))

@login_required
def sales(request):
    require_capability(request.user,'pdv')
    try: start,end=date_range(request)
    except ValidationError as exc:
        messages.error(request,'; '.join(exc.messages));start=end=timezone.localdate()
    rows=s.own_sales(request.user).filter(Q(finalizada_em__date__range=(start,end))|Q(finalizada_em__isnull=True,criado_em__date__range=(start,end))).order_by('-pk')
    return render(request,'operacao/seller_sales.html',{'sales':rows[:100],'start':start,'end':end,'period':request.GET.get('periodo','hoje')})

@login_required
def goal(request):
    require_capability(request.user,'pdv')
    return render(request,'operacao/seller_goal.html',s.indicators(request.user))

@login_required
def commission(request):
    require_capability(request.user,'pdv')
    # No percentage, accrual or payout is fabricated. Rule configuration is later.
    return render(request,'operacao/seller_commission.html',s.indicators(request.user))

@login_required
def alerts(request):
    require_capability(request.user,'pdv')
    return render(request,'operacao/seller_alerts.html',{'notices':m.Notificacao.objects.filter(usuario=request.user)[:100]})

@login_required
def notice_read(request,pk):
    require_capability(request.user,'pdv')
    if request.method!='POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    row=get_object_or_404(m.Notificacao,pk=pk,usuario=request.user)
    row.lida_em=timezone.now();gs.write(row)
    return redirect('operacao:seller_alerts')

@login_required
@transaction.atomic
def customer(request):
    require_capability(request.user,'pdv_cliente_cadastrar')
    try:
        sale,session=c.lock_sale(request.user,request.GET.get('venda') or request.POST.get('venda'))
    except (ObjectDoesNotExist,ValidationError,ValueError):
        raise Http404('Venda indisponível.')
    c.draft(sale,session)
    form=CustomerForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        obj=form.save();sale.cliente=obj;gs.write(sale)
        gs.audit(request.user,'PDV_CLIENTE_CADASTRADO',obj,{'venda':sale.pk,'campos':list(form.fields)})
        return redirect('operacao:pdv_sale',public_id=sale.public_id)
    return render(request,'operacao/seller_customer.html',{'form':form,'sale':sale},status=400 if request.method=='POST' else 200)

@login_required
@transaction.atomic
def terminal(request):
    require_capability(request.user,'pdv')
    if request.method=='POST':
        try:
            if request.POST.get('action')=='abrir':
                c.open_cash(request.user,int(request.POST['conta']),request.POST['contado'],request.POST['request_id'])
                return redirect('operacao:pdv_home')
            if request.POST.get('action')=='venda':
                sale=c.new_sale(request.user,request.POST['caixa'],int(request.POST['deposito']),request_id=request.POST['request_id'])
                return redirect('operacao:pdv_sale',public_id=sale.public_id)
            raise ValidationError('Operação inválida.')
        except (ValidationError,ValueError,KeyError,ObjectDoesNotExist) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Revise os dados da operação.')
    sessions=m.SessaoCaixa.objects.filter(operador=request.user,fechado_em__isnull=True).select_related('conta')
    return render(request,'operacao/seller_terminal.html',{'sessions':sessions,'contas':m.ContaBancaria.objects.filter(ativo=True,tipo='CAIXA'),'depositos':m.Deposito.objects.filter(ativo=True),'request_id':uuid.uuid4(),'drafts':s.own_sales(request.user).filter(status='RASCUNHO',sessao_caixa__fechado_em__isnull=True).order_by('-pk')[:10]})

def sale_context(request,sale,session):
    query=request.GET.get('q','').strip()[:100]
    parts=g.Peca.objects.filter(ativo=True)
    if query:
        parts=parts.filter(Q(descricao__icontains=query)|Q(sku__icontains=query)|Q(referencia__icontains=query)|Q(gtin=query)|Q(codigo_barras=query)|Q(codigos_alternativos__codigo=query)).distinct()
    else:
        parts=parts.none()
    products=[{'part':part,'available':s.availability(part,sale.deposito,sale),'price':part.preco_venda*part.fator_venda} for part in parts[:20]]
    customer_q=request.GET.get('cliente_q','').strip()[:100]
    customers=Cliente.objects.filter(ativo=True).filter(Q(nome_razao_social__icontains=customer_q)|Q(cpf_cnpj__icontains=customer_q))[:20] if customer_q else Cliente.objects.none()
    config=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
    items=list(sale.itens.select_related('peca'))
    sold=s.own_sales(request.user).filter(sessao_caixa=session,status__in=['FINALIZADA','PARCIALMENTE_DEVOLVIDA','DEVOLVIDA'])
    events=session.eventos.select_related('movimento') if session else []
    summary={'sold':sum((s.net_sale(row) for row in sold),c.ZERO),'methods':m.PagamentoVenda.objects.filter(venda__in=sold).values('forma__nome').annotate(total=Sum('valor')),'supplies':sum((row.movimento.valor for row in events if row.tipo=='SUPRIMENTO'),c.ZERO),'withdrawals':sum((row.movimento.valor for row in events if row.tipo in ['SANGRIA','RETIRADA']),c.ZERO),'expected':c.cash_expected(session) if session else c.ZERO}
    return {'sale':sale,'session':session,'items':items,'products':products,'q':query,'customers':customers,'customer_q':customer_q,'forms':g.FormaPagamento.objects.filter(ativo=True).exclude(tipo_pdv=''),'request_id':uuid.uuid4(),'discount_limit':config.limite_desconto_percentual,'gross':sum(((i.quantidade*i.valor_unitario).quantize(c.CENT) for i in items),c.ZERO),'items_discount':sum((i.desconto for i in items),c.ZERO),'total_discount':sum((i.desconto for i in items),c.ZERO)+sale.desconto_global,'cash_summary':summary,'discount_requests':sale.solicitacoes_desconto.order_by('-pk')[:5],'can_customer':has_capability(request.user,'pdv_cliente_cadastrar')}

@login_required
@transaction.atomic
def management(request):
    s.require_supervisor(request.user)
    data=request.POST if request.POST.get('action')=='meta' else None
    instance=None
    if data:
        try:
            from datetime import date
            instance=m.MetaVendedor.objects.filter(vendedor_id=int(data.get('vendedor','')),competencia=date.fromisoformat(data.get('competencia',''))).first()
        except (ValueError,TypeError):
            pass
    form=GoalForm(data,instance=instance)
    sellers=GoalForm().fields['vendedor'].queryset
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if action=='meta' and form.is_valid():
                data=form.cleaned_data
                old=m.MetaVendedor.objects.filter(vendedor=data['vendedor'],competencia=data['competencia']).first()
                before={'valor':str(old.valor)} if old else {}
                obj,_=m.MetaVendedor.objects.update_or_create(vendedor=data['vendedor'],competencia=data['competencia'],defaults={'valor':data['valor']})
                gs.audit(request.user,'META_VENDEDOR_CONFIGURADA',obj,{'antes':before,'valor':str(obj.valor)})
            elif action=='desconto':
                s.decide_discount(request.user,int(request.POST['solicitacao']),request.POST.get('aprovar')=='sim',request.POST.get('motivo',''))
            elif action=='mensagem':
                recipient=get_object_or_404(sellers,pk=request.POST.get('vendedor'))
                body=request.POST.get('mensagem','').strip()
                if not body or len(body)>2000: raise ValidationError('Informe mensagem de até 2000 caracteres.')
                notice=gs.write(m.Notificacao(usuario=recipient,chave='seller-message:'+uuid.uuid4().hex,titulo='Mensagem da gestão',mensagem=body,link='/vendedor/alertas/'))
                gs.audit(request.user,'VENDEDOR_MENSAGEM',notice,{'destinatario':recipient.pk})
            else: raise ValidationError('Revise os dados da configuração.')
        except (ValidationError,KeyError,ValueError,ObjectDoesNotExist) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Registro indisponível.')
        else:
            messages.success(request,'Operação comercial registrada.');return redirect('operacao:seller_management')
    return render(request,'operacao/seller_management.html',{'form':form,'sellers':sellers,'requests':m.SolicitacaoDescontoPDV.objects.filter(status='PENDENTE').select_related('venda','solicitado_por'),'goals':m.MetaVendedor.objects.select_related('vendedor').order_by('-competencia')[:50]})
