import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from platform_core.modules import require_capability, has_capability
from gestao.models import Peca
from . import models as m, inventory as service

@login_required
def inventories(request,public_id=None):
    require_capability(request.user,'estoque_escrever')
    row=get_object_or_404(m.Inventario,public_id=public_id) if public_id else None
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if row and action=='contar': service.count(request.user,public_id,int(request.POST['item']),request.POST['quantidade'],request.POST['request_id'])
            elif row and action=='aprovar': service.approve_inventory(request.user,public_id)
            elif not row and action=='abrir':
                row=service.open_inventory(request.user,int(request.POST['deposito']),request.POST.get('motivo',''))
            else: raise ValidationError('Operação inválida.')
            return redirect('operacao:inventory_detail',public_id=row.public_id)
        except (ValidationError,ValueError,KeyError,ObjectDoesNotExist) as exc: messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Dados inválidos.')
    lines=[]
    if row:
        for item in row.itens.select_related('lote__peca').prefetch_related('contagens'):
            counts=list(item.contagens.all());latest=max(counts,key=lambda entry:entry.pk) if counts else None
            lines.append({'item':item,'count':latest,'rounds':len(counts),'request_id':uuid.uuid4()})
    return render(request,'operacao/inventory.html',{'inventory':row,'lines':lines,'inventories':m.Inventario.objects.select_related('deposito').order_by('-criado_em')[:50],'depositos':m.Deposito.objects.filter(ativo=True),'can_approve':has_capability(request.user,'inventario_aprovar'),'back_url':reverse('operacao:inventory_list')})

@login_required
def transfers(request):
    require_capability(request.user,'estoque_escrever')
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if action=='criar': service.create_transfer(request.user,int(request.POST['peca']),int(request.POST['origem']),int(request.POST['destino']),request.POST['quantidade'],request.POST.get('motivo',''),request.POST['request_id'],int(request.POST['transito']) if request.POST.get('transito') else None)
            elif action=='enviar': service.send_transfer(request.user,request.POST['transferencia'])
            elif action=='receber': service.receive_transfer(request.user,request.POST['transferencia'])
            else: raise ValidationError('Operação inválida.')
            return redirect('operacao:transfer_list')
        except (ValidationError,ValueError,KeyError,ObjectDoesNotExist) as exc: messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Dados inválidos.')
    return render(request,'operacao/transfers.html',{'rows':m.TransferenciaEstoque.objects.select_related('peca','origem','destino','transito').order_by('-criado_em')[:100],'depositos':m.Deposito.objects.filter(ativo=True),'products':Peca.objects.filter(ativo=True),'request_id':uuid.uuid4(),'back_url':reverse('gestao:peca_lista')})
