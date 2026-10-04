from django import forms
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404,render,redirect
from django.urls import reverse
from . import models as m, services as gs
from .forms import Estilizado
from .permissions import require

class CodeForm(Estilizado):
    class Meta:
        model=m.CodigoProduto
        fields=['codigo']
class SupplierForm(Estilizado):
    class Meta:
        model=m.FornecedorProduto
        fields=['fornecedor','referencia','ultimo_custo']

@login_required
def relationships(request,pk):
    require(request.user,'estoque_escrever')
    part=get_object_or_404(m.Peca,pk=pk)
    kind=request.POST.get('tipo','codigo')
    model,cls=(m.FornecedorProduto,SupplierForm) if kind=='fornecedor' else (m.CodigoProduto,CodeForm)
    form=cls(request.POST or None,instance=model(peca=part))
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            row=form.save();gs.audit(request.user,'PRODUTO_VINCULO_ADICIONADO',row,{'produto':part.pk,'tipo':kind})
        return redirect('gestao:produto_vinculos',pk=part.pk)
    return render(request,'gestao/product_links.html',{'part':part,'form':form if request.method=='POST' else None,'code_form':CodeForm(instance=m.CodigoProduto(peca=part)),'supplier_form':SupplierForm(instance=m.FornecedorProduto(peca=part)),'codes':part.codigos_alternativos.all(),'suppliers':part.fornecedores_comerciais.select_related('fornecedor'),'back_url':reverse('gestao:peca_detalhe',args=[pk])})
