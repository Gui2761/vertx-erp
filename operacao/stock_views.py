from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from platform_core.access import require_erp
from platform_core.audit import record_write, previous_values
from gestao import models as g, services as gs, reporting
from gestao.permissions import require, allowed
from . import models as m, stock, stock_forms as forms

@login_required
def lots(request):
    require(request.user,'estoque')
    qs=m.LoteEstoque.objects.select_related('peca','deposito','fornecedor').order_by('peca__sku','validade','pk')
    if request.GET.get('peca'):
        try:
            part_id=int(request.GET['peca'])
        except ValueError:
            raise Http404()
        part=get_object_or_404(g.Peca,pk=part_id)
        qs=qs.filter(peca=part)
    if request.GET.get('q'):
        qs=qs.filter(peca__sku__icontains=request.GET['q'])
    from django.utils import timezone
    if request.GET.get('situacao')=='vencido':
        qs=qs.filter(validade__lt=timezone.localdate(),quantidade__gt=0)
    if request.GET.get('situacao')=='vencendo':
        qs=qs.filter(validade__range=(timezone.localdate(),timezone.localdate()+timezone.timedelta(days=90)),quantidade__gt=0)
    return render(request,'operacao/stock_lots.html',{'page_obj':Paginator(qs,30).get_page(request.GET.get('page')),'can_write':allowed(request.user,'estoque_escrever')})

@login_required
@require_http_methods(['GET','POST'])
def lot_entry(request):
    require(request.user,'estoque_escrever')
    form=forms.EntradaLoteForm(request.POST if request.method=='POST' else None,initial={'peca':request.GET.get('peca')})
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            gs.movimentar(request.user,d['peca'].pk,'ENTRADA',d['quantidade'],d['motivo'],destino_id=d['deposito'].pk,request_id=d['request_id'],lote_data={key:d[key] for key in ['numero','fabricacao','validade','fornecedor','custo_unitario','localizacao','documento_entrada']})
        except ValidationError as exc:
            form.add_error(None,'; '.join(exc.messages))
        else:
            messages.success(request,'Entrada por lote registrada no estoque existente.')
            return redirect('operacao:stock_lots')
    return render(request,'operacao/form.html',{'titulo':'Entrada por lote','form':form,'back_url':reverse('operacao:stock_lots')},status=400 if request.method=='POST' else 200)

@login_required
@require_http_methods(['GET','POST'])
def reservations(request):
    require(request.user,'estoque_escrever')
    form=forms.ReservaForm(request.POST if request.method=='POST' else None,initial={'peca':request.GET.get('peca'),'ordem':request.GET.get('ordem'),'venda':request.GET.get('venda')})
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            stock.reserve(request.user,d['peca'].pk,d['deposito'].pk,d['quantidade'],d['motivo'],d['ordem'].pk if d['ordem'] else None,d['venda'].pk if d['venda'] else None, request_id=d.get('request_id'), lot_id=d['lote'].pk if d.get('lote') else None)
        except ValidationError as exc:
            form.add_error(None,'; '.join(exc.messages))
        else:
            return redirect('operacao:stock_reservations')
    rows=m.ReservaEstoque.objects.select_related('peca','deposito','ordem','venda').order_by('-pk')
    return render(request,'operacao/stock_reservations.html',{'form':form,'page_obj':Paginator(rows,25).get_page(request.GET.get('page'))},status=400 if request.method=='POST' else 200)

@login_required
@require_POST
def release(request,pk):
    require(request.user,'estoque_escrever')
    get_object_or_404(m.ReservaEstoque,pk=pk)
    try:
        stock.release(request.user,pk,request.POST.get('motivo',''))
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages),status=400)
    return redirect('operacao:stock_reservations')

@login_required
def occurrences(request):
    require(request.user,'estoque_escrever')
    qs=m.OcorrenciaEstoque.objects.select_related('peca','lote').order_by('peca__sku','-aberta_em')
    qs=qs.filter(resolvida_em__isnull=request.GET.get('historico')!='1')
    if request.GET.get('tipo'):
        qs=qs.filter(tipo=request.GET['tipo'])
    page=Paginator(qs,50).get_page(request.GET.get('page'))
    config=m.Configuracao.objects.first() or m.Configuracao()
    cache={}
    rows=[]
    for row in page:
        if row.peca_id not in cache:
            cache[row.peca_id]=stock.metrics(row.peca,config)
        rows.append({'occurrence':row,'stock':cache[row.peca_id]})
    query=request.GET.copy();query.pop('page',None)
    return render(request,'operacao/stock_occurrences.html',{'rows':rows,'page_obj':page,'query':query.urlencode(),'notifications':m.Notificacao.objects.filter(usuario=request.user,ocorrencia_estoque__isnull=False,resolvida_em__isnull=True)[:100]})

@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def config(request):
    require_erp(request.user,roles=['ADMIN'])
    obj=m.Configuracao.objects.select_for_update().first() or m.Configuracao()
    form=forms.ConfigEstoqueForm(request.POST if request.method=='POST' else None,instance=obj)
    if request.method=='POST' and form.is_valid():
        before=previous_values(form)
        row=form.save()
        record_write(request,row,before)
        messages.success(request,'Configurações de estoque e compras salvas.')
        return redirect('operacao:stock_config')
    return render(request,'operacao/stock_config.html',{'form':form},status=400 if request.method=='POST' else 200)

@login_required
@require_http_methods(['GET','POST'])
def reports(request):
    require(request.user,'estoque_escrever')
    if request.method=='POST':
        report=stock.generate_report(request.user,automatic=False)
        return redirect('operacao:stock_report',pk=report.pk)
    return render(request,'operacao/stock_reports.html',{'page_obj':Paginator(m.RelatorioEstoque.objects.all(),25).get_page(request.GET.get('page'))})

REPORT_FIELDS=[('produto','Produto'),('sku','Código/SKU'),('categoria','Categoria'),('fisico','Estoque físico'),('reservado','Reservado'),('disponivel','Disponível'),('minimo','Mínimo'),('ideal','Ideal/máximo'),('consumo_medio','Consumo médio/dia'),('vencendo','Quantidade vencendo'),('em_compra','Em compra'),('sugerido','Sugerido'),('fornecedor','Último fornecedor'),('custo','Último custo'),('valor_estimado','Valor estimado')]
NUMERIC_FIELDS={'fisico','reservado','disponivel','minimo','ideal','consumo_medio','vencendo','em_compra','sugerido','custo','valor_estimado'}

def report_value(row,key):
    from decimal import Decimal
    return Decimal(row.dados[key]) if key in NUMERIC_FIELDS else row.dados[key]

@login_required
@require_http_methods(['GET','POST'])
def report(request,pk):
    require(request.user,'estoque_escrever')
    obj=get_object_or_404(m.RelatorioEstoque,pk=pk)
    rows=list(obj.itens.select_related('peca'))
    export=request.GET.get('export')
    if export in ['pdf','xlsx']:
        data=[[report_value(row,key) for key,_ in REPORT_FIELDS] for row in rows]
        headers=[label for _,label in REPORT_FIELDS]
        if export=='pdf':
            # 15 colunas em um único quadro seriam ilegíveis; manter todos os
            # dados em fichas de produto, com paginação do renderer existente.
            data=[]
            for row in rows:
                from django.utils.formats import number_format
                data.append(['Produto',row.dados['produto']])
                data.extend([[label,number_format(report_value(row,key),decimal_pos=2 if key in ['custo','valor_estimado'] else 6 if key=='consumo_medio' else 3,use_l10n=True) if key in NUMERIC_FIELDS else str(row.dados[key])] for key,label in REPORT_FIELDS if key!='produto'])
            try:
                content=reporting.pdf_bytes(str(obj),request.organization,['Informação','Valor'],data,max_rows=50000)
            except ValidationError as exc:
                return HttpResponse('; '.join(exc.messages),status=400)
            mime='application/pdf'
        else:
            try:
                content=reporting.xlsx_bytes(headers,data,numeric_columns=[index for index,(key,_) in enumerate(REPORT_FIELDS) if key in NUMERIC_FIELDS])
            except ValidationError as exc:
                return HttpResponse('; '.join(exc.messages),status=400)
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response=HttpResponse(content,content_type=mime)
        response['Content-Disposition']=f'attachment; filename="necessidade-compras-{obj.pk}.{export}"'
        return response
    form=forms.CompraRelatorioForm(request.POST if request.method=='POST' else None,rows=rows)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            purchase=stock.report_purchase(request.user,pk,d['selecao'],d['deposito'].pk,d['vencimento'],d['request_id'],d['justificativa'])
        except ValidationError as exc:
            form.add_error(None,'; '.join(exc.messages))
        else:
            return redirect('operacao:compra_detalhe',pk=purchase.pk)
    items=[{'item':row,'cells':[report_value(row,key) for key,_ in REPORT_FIELDS],'select':form[f'selecionar_{row.pk}'],'quantity':form[f'quantidade_{row.pk}']} for row in rows]
    return render(request,'operacao/stock_report.html',{'object':obj,'form':form,'headers':[label for _,label in REPORT_FIELDS],'items':items,'compras':m.Compra.objects.filter(relatorio_estoque=obj)},status=400 if request.method=='POST' else 200)

@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def receipt(request,pk,item_id):
    require(request.user,'estoque_escrever')
    purchase=get_object_or_404(m.Compra.objects.select_for_update(),pk=pk,status='PEDIDO')
    row=get_object_or_404(m.ItemCompra,pk=item_id,compra=purchase)
    row._receiving_write=True
    form=forms.RecebimentoLoteForm(request.POST if request.method=='POST' else None,instance=row)
    if request.method=='POST' and form.is_valid():
        before=previous_values(form)
        saved=form.save()
        record_write(request,saved,before)
        return redirect('operacao:compra_detalhe',pk=pk)
    return render(request,'operacao/form.html',{'titulo':'Identificar lote do recebimento','form':form,'back_url':reverse('operacao:compra_detalhe',args=[pk])},status=400 if request.method=='POST' else 200)
