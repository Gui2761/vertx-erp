"""Keyboard-friendly PDV over existing transactional services."""
import json
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.urls import reverse
from platform_core.modules import require_capability, has_capability
from gestao import models as g, services as gs
from gestao.forms import Estilizado
from clientes.models import Cliente
from . import models as m, commerce as c

class PDVConfigForm(Estilizado):
    class Meta:
        model=m.ConfiguracaoPDV
        fields=['limite_desconto_percentual','reservar_rascunho','reservar_orcamento']

@login_required
def products(request,public_id):
    require_capability(request.user,'pdv')
    with transaction.atomic():
        try: sale,session=c.lock_sale(request.user,public_id)
        except m.Venda.DoesNotExist: raise Http404
    query=request.GET.get('q','').strip()
    from django.db.models import Q
    rows=g.Peca.objects.filter(ativo=True).filter(Q(sku__icontains=query)|Q(descricao__icontains=query)|Q(gtin=query)|Q(codigo_barras=query)|Q(codigos_alternativos__codigo=query)).distinct()[:20] if query else []
    return render(request,'operacao/pdv_products.html',{'rows':rows,'sale':sale,'q':query,'back_url':reverse('operacao:pdv_sale',args=[public_id])})

@login_required
@transaction.atomic
def home(request):
    require_capability(request.user,'pdv')
    if request.GET.get('gestao') != '1':
        from .seller import terminal
        return terminal(request)
    require_capability(request.user,'caixa_supervisor')
    if request.method=='POST':
        try:
            session=c.open_cash(request.user,int(request.POST['conta']),request.POST['contado'],request.POST['request_id'])
        except (ValidationError,ValueError,KeyError,ObjectDoesNotExist) as exc: messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Revise os dados do caixa.')
        else: return redirect('operacao:pdv_cash',public_id=session.public_id)
    sessions=m.SessaoCaixa.objects.select_related('conta','operador').order_by('-aberto_em')
    if not has_capability(request.user,'caixa_supervisor'): sessions=sessions.filter(operador=request.user)
    return render(request,'operacao/pdv_home.html',{'sessions':sessions[:50],'contas':m.ContaBancaria.objects.filter(ativo=True,tipo='CAIXA'),'request_id':uuid.uuid4(),'back_url':reverse('platform_core:home')})

@login_required
@transaction.atomic
def cash(request,public_id):
    try: session=c.own_session(request.user,public_id,True)
    except m.SessaoCaixa.DoesNotExist: raise Http404
    from .seller_access import is_seller
    if is_seller(request.user) and request.method=='GET':
        return redirect('operacao:pdv_home')
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if action=='venda':
                sale=c.new_sale(request.user,public_id,int(request.POST['deposito']),request.POST.get('cliente') or None,request.POST.get('vendedor') or None,request.POST.get('filial') or None,request.POST.get('centro_custo') or None,request.POST.get('request_id'))
                return redirect('operacao:pdv_sale',public_id=sale.public_id)
            if action=='fechar': c.close_cash(request.user,public_id,request.POST['contado'],request.POST.get('motivo',''))
            elif action=='movimento': c.cash_operation(request.user,public_id,request.POST['tipo'],request.POST['valor'],request.POST.get('motivo',''),request.POST['request_id'])
            elif action=='converter':
                if is_seller(request.user):
                    from django.core.exceptions import PermissionDenied
                    raise PermissionDenied('Conversão de orçamento exige gestor.')
                sale=c.quote_to_sale(request.user,int(request.POST['orcamento']),public_id,int(request.POST['deposito']))
                return redirect('operacao:pdv_sale',public_id=sale.public_id)
            else: raise ValidationError('Operação inválida.')
            messages.success(request,'Operação registrada.');return redirect('operacao:pdv_cash',public_id=public_id)
        except (ValidationError,ValueError,KeyError,ObjectDoesNotExist) as exc: messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Revise os dados selecionados.')
    if is_seller(request.user):
        return redirect('operacao:pdv_home')
    from contas.models import Usuario
    from platform_core.context import current_organization
    from platform_core.models import FilialEmpresa
    return render(request,'operacao/pdv_cash.html',{'session':session,'expected':c.cash_expected(session),'events':session.eventos.select_related('movimento'),'sales':session.venda_set.select_related('cliente','vendedor'),'depositos':m.Deposito.objects.filter(ativo=True),'clientes':Cliente.objects.filter(ativo=True),'vendedores':Usuario.objects.filter(is_active=True,memberships__organization=current_organization(),memberships__status='ATIVO').distinct(),'filiais':FilialEmpresa.objects.filter(ativo=True),'centros':g.CentroCusto.objects.filter(ativo=True),'quotes':g.Orcamento.objects.filter(status='APROVADO'),'supervisor':has_capability(request.user,'caixa_supervisor'),'request_id':uuid.uuid4(),'back_url':reverse('operacao:pdv_home')})

@login_required
@transaction.atomic
def sale(request,public_id,receipt=False):
    try: sale,session=c.lock_sale(request.user,public_id)
    except m.Venda.DoesNotExist: raise Http404
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if action=='adicionar': c.add_item(request.user,public_id,request.POST['codigo'],request.POST['quantidade'],request.POST.get('unidade','venda'),request.POST.get('desconto') or 0,request.POST.get('motivo',''))
            elif action=='remover': c.remove_item(request.user,public_id,int(request.POST['item']))
            elif action=='editar': c.edit_item(request.user,public_id,int(request.POST['item']),request.POST['quantidade'],request.POST.get('desconto') or 0,request.POST.get('motivo',''))
            elif action=='observacao': c.sale_note(request.user,public_id,request.POST.get('observacoes',''))
            elif action=='preco': c.pricing(request.user,public_id,request.POST.get('desconto') or 0,request.POST.get('acrescimo') or 0,request.POST.get('motivo',''))
            elif action=='solicitar_desconto':
                from .seller_services import request_discount
                request_discount(request.user,public_id,request.POST.get('desconto') or 0,request.POST.get('motivo',''))
            elif action=='cliente':
                c.draft(sale,session)
                sale.cliente=Cliente.objects.get(pk=request.POST['cliente'],ativo=True) if request.POST.get('cliente') else None
                gs.write(sale);gs.audit(request.user,'PDV_CLIENTE_SELECIONADO',sale,{'cliente':sale.cliente_id})
            elif action=='finalizar': c.finalize(request.user,public_id,json.loads(request.POST['pagamentos']),request.POST['request_id'])
            elif action=='estado': c.sale_state(request.user,public_id,request.POST['estado'],request.POST.get('motivo',''))
            elif action=='devolver':
                from gestao.products import number
                rows=[{'item':key[5:],'quantidade':value} for key,value in request.POST.items() if key.startswith('item_') and value and number(value)>0]
                c.return_sale(request.user,public_id,rows,request.POST.get('motivo',''),request.POST['request_id'],account_id=int(request.POST['conta']) if request.POST.get('conta') else None,settle=request.POST.get('liquidar')=='on',session_id=session.public_id if session and not session.fechado_em else None,exchange_id=request.POST.get('troca') or None)
            else: raise ValidationError('Operação inválida.')
            messages.success(request,'Operação registrada.');return redirect('operacao:pdv_sale',public_id=public_id)
        except (ValidationError,ValueError,KeyError,TypeError,ObjectDoesNotExist) as exc: messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Revise os dados da operação.')
    from .seller_access import is_seller
    if not receipt and (is_seller(request.user) or sale.status=='RASCUNHO'):
        from .seller import sale_context
        return render(request,'operacao/seller_pdv.html',sale_context(request,sale,session))
    return render(request,'operacao/pdv_receipt.html' if receipt else 'operacao/pdv_sale.html',{'sale':sale,'session':session,'items':sale.itens.select_related('peca'),'forms':g.FormaPagamento.objects.filter(ativo=True).exclude(tipo_pdv=''),'contas':m.ContaBancaria.objects.filter(ativo=True) if not is_seller(request.user) else m.ContaBancaria.objects.none(),'can_return':has_capability(request.user,'devolucao'),'request_id':uuid.uuid4(),'back_url':reverse('operacao:pdv_cash',args=[session.public_id]) if session else reverse('operacao:pdv_home')})

@login_required
def config(request):
    require_capability(request.user,'config_empresa')
    instance=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
    form=PDVConfigForm(request.POST or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            row=form.save();gs.audit(request.user,'PDV_CONFIGURADO',row,{'campos':form.changed_data})
        return redirect('operacao:pdv_config')
    return render(request,'gestao/form.html',{'titulo':'Configuração PDV','form':form,'back_url':reverse('operacao:pdv_home')})


@login_required
def history(request):
    require_capability(request.user,'operar_pdv')
    rows=m.Venda.objects.select_related('cliente','vendedor','sessao_caixa').order_by('-pk')
    if not has_capability(request.user,'caixa_supervisor'):
        rows=rows.filter(sessao_caixa__operador=request.user)
    return render(request,'operacao/pdv_history.html',{'sales':rows[:100]})
