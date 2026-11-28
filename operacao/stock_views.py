from decimal import Decimal, DecimalException
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, F, Sum, DecimalField, ExpressionWrapper
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from django.utils.dateparse import parse_date
from django.utils import timezone
from platform_core.access import require_erp
from platform_core.audit import record_write, previous_values
from gestao import models as g, services as gs, reporting
from gestao.permissions import require, allowed
from . import models as m, stock, stock_forms as forms


@login_required
def dashboard(request):
    """Resumo do estoque da organização ativa, com filtros sobre os produtos."""
    require(request.user, 'estoque')
    from django.utils import timezone
    from platform_core.context import current_organization, get_org_cache_dict
    org_cache = get_org_cache_dict(current_organization())
    cache_key = ('stock_dashboard_ctx', request.GET.urlencode())
    if org_cache is not None and cache_key in org_cache:
        return render(request, 'operacao/stock_dashboard.html', org_cache[cache_key])

    today = timezone.localdate()
    config = m.Configuracao.objects.first() or m.Configuracao()
    lots = m.LoteEstoque.objects.filter(quantidade__gt=0).select_related('peca', 'deposito', 'fornecedor')
    movements = g.Movimentacao.objects.select_related('peca', 'origem', 'destino', 'usuario').order_by('-criado_em', '-pk')

    near_cutoff = today + timezone.timedelta(days=max(config.dias_alerta_validade))
    near_lots = lots.filter(validade__gte=today, validade__lte=near_cutoff)
    value_expr = ExpressionWrapper(F('quantidade') * F('custo_unitario'), output_field=DecimalField(max_digits=30, decimal_places=5))
    value = lots.aggregate(total=Sum(value_expr))['total'] or Decimal('0')

    # Base QuerySet de produtos ativos
    parts_qs = g.Peca.objects.filter(ativo=True).select_related('categoria', 'fornecedor').order_by('sku')

    # KPIs organizacionais globais calculados de forma instantânea em 1 única agregação SQL
    from django.db.models import Count
    kpis = parts_qs.aggregate(
        total=Count('pk'),
        com_estoque=Count('pk', filter=Q(quantidade_atual__gt=0)),
        sem_estoque=Count('pk', filter=Q(quantidade_atual__lte=0)),
        estoque_baixo=Count('pk', filter=Q(quantidade_atual__gt=0, quantidade_atual__lte=F('estoque_minimo'))),
    )
    total_parts = kpis['total']
    com_estoque = kpis['com_estoque']
    sem_estoque = kpis['sem_estoque']
    estoque_baixo = kpis['estoque_baixo']

    summary = {
        'produtos': total_parts,
        'com_estoque': com_estoque,
        'sem_estoque': sem_estoque,
        'estoque_baixo': estoque_baixo,
        'lotes_vencendo': near_lots.count(),
        'valor': value,
    }

    depot_id = request.GET.get('deposito', '').strip()
    category_id = request.GET.get('categoria', '').strip()
    supplier_id = request.GET.get('fornecedor', '').strip()
    situation = request.GET.get('situacao', '').strip().upper()
    lot_query = request.GET.get('lote', '').strip()
    validity_from = parse_date(request.GET.get('validade_de', '') or '')
    validity_to = parse_date(request.GET.get('validade_ate', '') or '')

    scoped_depots = m.Deposito.objects.filter(ativo=True)
    depot = None
    if depot_id and scoped_depots.filter(pk=depot_id).exists():
        depot = scoped_depots.filter(pk=depot_id).first()
        lots = lots.filter(deposito_id=depot_id)
        movements = movements.filter(Q(origem_id=depot_id) | Q(destino_id=depot_id))
        parts_qs = parts_qs.filter(lotes__deposito_id=depot_id).distinct()
    else:
        depot_id = ''

    if category_id and m.CategoriaPeca.objects.filter(pk=category_id).exists():
        parts_qs = parts_qs.filter(categoria_id=category_id)
    else:
        category_id = ''

    if supplier_id and g.Fornecedor.objects.filter(pk=supplier_id).exists():
        parts_qs = parts_qs.filter(fornecedor_id=supplier_id)
    else:
        supplier_id = ''

    if lot_query:
        lots = lots.filter(numero__icontains=lot_query)
    if validity_from:
        lots = lots.filter(validade__gte=validity_from)
    if validity_to:
        lots = lots.filter(validade__lte=validity_to)

    if lot_query or validity_from or validity_to:
        matching_ids = lots.values_list('peca_id', flat=True)
        parts_qs = parts_qs.filter(pk__in=matching_ids)
        movements = movements.filter(peca_id__in=matching_ids)

    if situation == 'ZERADO':
        parts_qs = parts_qs.filter(quantidade_atual__lte=0)
    elif situation == 'BAIXO':
        parts_qs = parts_qs.filter(quantidade_atual__gt=0, quantidade_atual__lte=F('estoque_minimo'))
    elif situation == 'VENCIDO':
        parts_qs = parts_qs.filter(lotes__validade__lt=today).distinct()
    elif situation == 'VENCENDO':
        parts_qs = parts_qs.filter(lotes__validade__gte=today, lotes__validade__lte=near_cutoff).distinct()
    elif situation == 'EXCESSO':
        parts_qs = parts_qs.filter(estoque_maximo__isnull=False, quantidade_atual__gt=F('estoque_maximo'))
    elif situation == 'NORMAL':
        parts_qs = parts_qs.filter(quantidade_atual__gt=F('estoque_minimo'))

    # Paginação em nível de banco de dados
    paginator = Paginator(parts_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Enriquecimento em lote APENAS para os 25 itens da página atual
    page_parts = list(page_obj.object_list)
    batch_metrics = stock.metrics_batch(page_parts, config, today)
    rows = []
    for part in page_parts:
        data = batch_metrics[part.pk]
        if depot or lot_query or validity_from or validity_to:
            selected_lots = lots.filter(peca=part)
            selected_ids = set(selected_lots.values_list('pk', flat=True))
            valid_lot_rows = stock.valid_lots(part, depot, today)
            if lot_query or validity_from or validity_to:
                valid_lot_rows = valid_lot_rows.filter(pk__in=selected_ids)
            valid_qty = stock.total(valid_lot_rows)
            physical_qty = stock.total(selected_lots)
            held = stock.lot_holds(part, depot)
            reserved_qty = sum((quantity for lot_id, quantity in held.items() if lot_id in set(valid_lot_rows.values_list('pk', flat=True))), Decimal('0'))
            available_qty = max(Decimal('0'), valid_qty - reserved_qty)
            situation_label = 'ZERADO' if available_qty == 0 else 'ESTOQUE BAIXO' if available_qty <= part.estoque_minimo else 'NORMAL'
            data = {**data, 'fisico': physical_qty,
                    'valido': valid_qty, 'reservado': reserved_qty,
                    'disponivel': available_qty, 'situacao': situation_label}
        rows.append({'peca': part, 'stock': data})

    page_obj.object_list = rows

    movement_rows = [{'movement': row, 'quantity': row.quantidade if row.tipo == 'TRANSFER' else row.variacao} for row in movements[:10]]
    ctx = {
        'summary': summary,
        'page_obj': page_obj,
        'depositos': list(scoped_depots.order_by('nome')),
        'categorias': list(m.CategoriaPeca.objects.order_by('nome')),
        'fornecedores': list(g.Fornecedor.objects.filter(ativo=True).order_by('nome')),
        'movimentos': movement_rows,
        'today': today,
        'validity_end': near_cutoff,
        'situation_choices': [
            ('ZERADO', 'Sem estoque disponível'),
            ('BAIXO', 'Abaixo do mínimo'),
            ('NORMAL', 'Normal'),
            ('VENCIDO', 'Possui lote vencido'),
            ('VENCENDO', 'Possui lote vencendo'),
            ('EXCESSO', 'Acima do ideal/máximo'),
        ],
        'filters': {
            'deposito': depot_id,
            'categoria': category_id,
            'fornecedor': supplier_id,
            'situacao': situation,
            'lote': lot_query,
            'validade_de': request.GET.get('validade_de', ''),
            'validade_ate': request.GET.get('validade_ate', ''),
        },
    }
    if org_cache is not None:
        org_cache[cache_key] = ctx
    return render(request, 'operacao/stock_dashboard.html', ctx)

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
    from .stock_scheduler import tick
    try:
        config_obj = m.Configuracao.objects.first()
        now = timezone.now()
        should_tick = False
        if not config_obj or not config_obj.ultima_verificacao_estoque:
            should_tick = True
        elif now >= config_obj.ultima_verificacao_estoque + timezone.timedelta(minutes=config_obj.intervalo_alertas_minutos):
            should_tick = True
        elif not m.OcorrenciaEstoque.objects.filter(resolvida_em__isnull=True).exists():
            should_tick = True
        if should_tick:
            tick(request.user, now)
    except Exception:
        pass
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
    counts = {
        'abertas': m.OcorrenciaEstoque.objects.filter(resolvida_em__isnull=True).count(),
        'reposicao': m.OcorrenciaEstoque.objects.filter(tipo='REPOSICAO', resolvida_em__isnull=True).count(),
        'resolvidas': m.OcorrenciaEstoque.objects.filter(resolvida_em__isnull=False).count(),
    }
    filtro_ativo = 'historico' if request.GET.get('historico')=='1' else ('reposicao' if request.GET.get('tipo')=='REPOSICAO' else 'abertas')
    return render(request,'operacao/stock_occurrences.html',{
        'rows':rows,
        'page_obj':page,
        'query':query.urlencode(),
        'counts':counts,
        'filtro_ativo':filtro_ativo,
        'notifications':m.Notificacao.objects.filter(usuario=request.user,ocorrencia_estoque__isnull=False,resolvida_em__isnull=True)[:100]
    })

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
    from decimal import Decimal, DecimalException
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


@login_required
@require_http_methods(['GET', 'POST'])
def initial_balance(request):
    """
    Levantamento Inicial / Balanço de Estoque.
    Permite a conferência física e o lançamento do saldo inicial para produtos
    recém-importados ou em implantação de inventário.
    """
    require(request.user, 'estoque_escrever')
    
    # Processamento de formulário individual ou em lote
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'salvar_individual':
            peca_id = request.POST.get('peca_id')
            raw_qty = request.POST.get('quantidade', '').strip().replace(',', '.')
            lote_num = request.POST.get('lote', '').strip() or 'INICIAL'
            validade_str = request.POST.get('validade', '').strip()
            validade = parse_date(validade_str) if validade_str else None
            
            try:
                peca = get_object_or_404(g.Peca, pk=peca_id)
                new_qty = Decimal(raw_qty)
                if new_qty < 0:
                    raise ValidationError('Quantidade não pode ser negativa.')
                
                if new_qty != peca.quantidade_atual:
                    lote_data = {'numero': lote_num}
                    if validade:
                        lote_data['validade'] = validade
                    elif peca.validade:
                        lote_data['validade'] = peca.validade
                    
                    with transaction.atomic():
                        gs.movimentar(
                            request.user,
                            peca.pk,
                            'AJUSTE',
                            new_qty,
                            observacao=f"Levantamento Inicial (Balanço): {peca.sku}",
                            lote_data=lote_data if new_qty > peca.quantidade_atual else None
                        )
                    messages.success(request, f'Saldo do produto "{peca.descricao}" ajustado para {new_qty}.')
                else:
                    messages.info(request, f'Saldo do produto "{peca.descricao}" já era {new_qty}. Nenhuma alteração necessária.')
            except (ValidationError, ValueError, DecimalException) as exc:
                messages.error(request, f'Erro ao ajustar produto: {exc}')
            
            query_string = request.POST.get('query_string', '')
            return redirect(f"{reverse('operacao:stock_initial_balance')}?{query_string}")

        elif action == 'salvar_lote':
            pks = request.POST.getlist('peca_pks')
            updated_count = 0
            errors = []
            
            for pk_str in pks:
                raw_qty = request.POST.get(f'qty_{pk_str}', '').strip().replace(',', '.')
                if not raw_qty:
                    continue
                try:
                    new_qty = Decimal(raw_qty)
                    if new_qty < 0:
                        continue
                    peca = g.Peca.objects.filter(pk=pk_str).first()
                    if not peca:
                        continue
                    
                    if new_qty != peca.quantidade_atual:
                        lote_num = request.POST.get(f'lote_{pk_str}', '').strip() or 'INICIAL'
                        validade_str = request.POST.get(f'validade_{pk_str}', '').strip()
                        validade = parse_date(validade_str) if validade_str else None
                        
                        lote_data = {'numero': lote_num}
                        if validade:
                            lote_data['validade'] = validade
                        elif peca.validade:
                            lote_data['validade'] = peca.validade
                        
                        with transaction.atomic():
                            gs.movimentar(
                                request.user,
                                peca.pk,
                                'AJUSTE',
                                new_qty,
                                observacao=f"Levantamento Inicial (Balanço em lote): {peca.sku}",
                                lote_data=lote_data if new_qty > peca.quantidade_atual else None
                            )
                        updated_count += 1
                except Exception as exc:
                    errors.append(f"Produto {pk_str}: {exc}")
            
            if updated_count > 0:
                messages.success(request, f'{updated_count} produto(s) atualizado(s) com sucesso no Levantamento Inicial!')
            else:
                messages.info(request, 'Nenhum saldo foi modificado.')
            if errors:
                messages.warning(request, f'Alguns itens tiveram inconsistências: {"; ".join(errors[:3])}')
            
            query_string = request.POST.get('query_string', '')
            return redirect(f"{reverse('operacao:stock_initial_balance')}?{query_string}")

    # Consulta e Filtros (GET)
    q = request.GET.get('q', '').strip()
    situacao = request.GET.get('situacao', 'ZERADOS').strip()
    categoria_id = request.GET.get('categoria', '').strip()
    
    parts_qs = g.Peca.objects.filter(ativo=True).select_related('categoria').order_by('descricao')
    
    from django.db.models import Count
    kpis = parts_qs.aggregate(
        total=Count('pk'),
        zerados=Count('pk', filter=Q(quantidade_atual__lte=0)),
        com_estoque=Count('pk', filter=Q(quantidade_atual__gt=0)),
    )
    
    if q:
        parts_qs = parts_qs.filter(
            Q(sku__icontains=q) |
            Q(descricao__icontains=q) |
            Q(codigo_barras__icontains=q) |
            Q(gtin__icontains=q)
        )
    
    if situacao == 'ZERADOS':
        parts_qs = parts_qs.filter(quantidade_atual__lte=0)
    elif situacao == 'COM_ESTOQUE':
        parts_qs = parts_qs.filter(quantidade_atual__gt=0)
        
    if categoria_id:
        parts_qs = parts_qs.filter(categoria_id=categoria_id)
        
    paginator = Paginator(parts_qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    categorias = m.CategoriaPeca.objects.filter(ativo=True).order_by('nome')
    depositos = m.Deposito.objects.filter(ativo=True).order_by('nome')
    
    context = {
        'page_obj': page_obj,
        'kpis': kpis,
        'categorias': categorias,
        'depositos': depositos,
        'filters': {
            'q': q,
            'situacao': situacao,
            'categoria': categoria_id,
        },
        'query_string': request.GET.urlencode(),
    }
    return render(request, 'operacao/stock_initial_balance.html', context)


@login_required
def initial_balance_template(request):
    """Gera planilha CSV modelo pré-populada com todos os produtos da organização para levantamento de estoque."""
    require(request.user, 'estoque_escrever')
    import csv
    
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="levantamento_inicial_estoque.csv"'
    response.write('\ufeff')
    
    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'CODIGO_SKU',
        'DESCRICAO',
        'SALDO_ATUAL_SISTEMA',
        'QUANTIDADE_FISICA_CONFERIDA',
        'NUMERO_LOTE',
        'DATA_VALIDADE'
    ])
    
    for peca in g.Peca.objects.filter(ativo=True).order_by('descricao'):
        writer.writerow([
            peca.sku,
            peca.descricao,
            str(peca.quantidade_atual).replace('.', ','),
            '',
            peca.lote or 'INICIAL',
            peca.validade.strftime('%d/%m/%Y') if peca.validade else ''
        ])
    return response


@login_required
@require_POST
def initial_balance_import(request):
    """
    Importa planilha (CSV ou XLSX) com a contagem física do levantamento inicial.
    Atualiza o estoque dos produtos correspondentes por SKU ou código de barras.
    """
    require(request.user, 'estoque_escrever')
    uploaded_file = request.FILES.get('arquivo')
    if not uploaded_file:
        messages.error(request, 'Nenhum arquivo foi selecionado.')
        return redirect('operacao:stock_initial_balance')
        
    filename = uploaded_file.name.lower()
    rows = []
    
    try:
        if filename.endswith('.csv') or filename.endswith('.txt'):
            import csv
            content = uploaded_file.read().decode('utf-8-sig', errors='replace')
            sample = content[:2048]
            delimiter = ';' if ';' in sample else (',' if ',' in sample else '\t')
            reader = csv.reader(content.splitlines(), delimiter=delimiter)
            rows = [r for r in reader if any(cell.strip() for cell in r)]
        elif filename.endswith(('.xlsx', '.xlsm')):
            import openpyxl
            wb = openpyxl.load_workbook(uploaded_file, data_only=True)
            sheet = wb.active
            for r in sheet.iter_rows(values_only=True):
                if any(cell is not None for cell in r):
                    rows.append([str(c) if c is not None else '' for c in r])
        else:
            messages.error(request, 'Formato inválido. Por favor, envie uma planilha .csv ou .xlsx.')
            return redirect('operacao:stock_initial_balance')
    except Exception as exc:
        messages.error(request, f'Erro ao ler o arquivo: {exc}')
        return redirect('operacao:stock_initial_balance')
        
    if not rows or len(rows) < 2:
        messages.error(request, 'A planilha está vazia ou não possui cabeçalho.')
        return redirect('operacao:stock_initial_balance')
        
    header = [h.strip().upper().replace(' ', '_') for h in rows[0]]
    sku_idx = None
    qty_idx = None
    lote_idx = None
    validade_idx = None
    
    for i, col in enumerate(header):
        if col in ['CODIGO_SKU', 'SKU', 'CODIGO', 'COD_PROD', 'CODIGO_PRODUTO', 'ITEM']:
            sku_idx = i
        elif col in ['QUANTIDADE_FISICA_CONFERIDA', 'QUANTIDADE', 'SALDO', 'QUANTIDADE_FISICA', 'QTD', 'ESTOQUE', 'CONTAGEM']:
            qty_idx = i
        elif col in ['NUMERO_LOTE', 'LOTE', 'NUM_LOTE']:
            lote_idx = i
        elif col in ['DATA_VALIDADE', 'VALIDADE', 'VENCIMENTO']:
            validade_idx = i
            
    if sku_idx is None or qty_idx is None:
        messages.error(request, 'Não foi possível identificar as colunas obrigatórias: "CODIGO_SKU" e "QUANTIDADE" (ou QUANTIDADE_FISICA_CONFERIDA). Baixe o modelo oficial.')
        return redirect('operacao:stock_initial_balance')
        
    updated = 0
    not_found = []
    errors = []
    
    for row_num, row in enumerate(rows[1:], start=2):
        if len(row) <= max(sku_idx, qty_idx):
            continue
        raw_sku = row[sku_idx].strip()
        raw_qty = row[qty_idx].strip().replace(',', '.')
        if not raw_sku or not raw_qty:
            continue
            
        try:
            qty = Decimal(raw_qty)
            if qty < 0:
                continue
        except (ValueError, DecimalException):
            continue
            
        peca = g.Peca.objects.filter(ativo=True).filter(
            Q(sku__iexact=raw_sku) | Q(codigo_barras__iexact=raw_sku) | Q(gtin__iexact=raw_sku)
        ).first()
        
        if not peca:
            not_found.append(raw_sku)
            continue
            
        if qty != peca.quantidade_atual:
            lote_num = 'INICIAL'
            if lote_idx is not None and len(row) > lote_idx and row[lote_idx].strip():
                lote_num = row[lote_idx].strip()
                
            lote_data = {'numero': lote_num}
            if validade_idx is not None and len(row) > validade_idx and row[validade_idx].strip():
                val_parsed = parse_date(row[validade_idx].strip())
                if val_parsed:
                    lote_data['validade'] = val_parsed
            elif peca.validade:
                lote_data['validade'] = peca.validade
                
            try:
                with transaction.atomic():
                    gs.movimentar(
                        request.user,
                        peca.pk,
                        'AJUSTE',
                        qty,
                        observacao=f"Levantamento Inicial (Importação de Planilha)",
                        lote_data=lote_data if qty > peca.quantidade_atual else None
                    )
                updated += 1
            except Exception as exc:
                errors.append(f"{peca.sku}: {exc}")
                
    if updated > 0:
        messages.success(request, f'Sucesso! {updated} produto(s) tiveram seu saldo físico inicial lançado com sucesso!')
    else:
        messages.info(request, 'Nenhum saldo foi alterado (as quantidades informadas já coincidiam com o saldo atual ou as linhas estavam vazias).')
        
    if not_found:
        messages.warning(request, f'{len(not_found)} código(s) não foram encontrados no cadastro de produtos: {", ".join(not_found[:5])}{"..." if len(not_found) > 5 else ""}')
        
    if errors:
        messages.error(request, f'Alguns produtos apresentaram erro: {"; ".join(errors[:3])}')
        
    return redirect('operacao:stock_initial_balance')


@login_required
@require_http_methods(['GET', 'POST'])
def barcode_labels(request):
    """
    Gerador e impressor de etiquetas de código de barras para produtos.
    Suporta bobina térmica (Zebra, Argox, Elgin) e folhas A4 (Pimaco).
    """
    require(request.user, 'estoque')
    from .barcode_generator import generate_code128_svg
    from platform_core.context import current_organization
    
    q = request.GET.get('q', '').strip()
    categoria_id = request.GET.get('categoria', '').strip()
    peca_id = request.GET.get('peca', '').strip()
    layout = request.GET.get('layout', 'a4_30').strip()
    show_price = request.GET.get('show_price', '1') == '1'
    show_org = request.GET.get('show_org', '1') == '1'
    show_sku = request.GET.get('show_sku', '1') == '1'
    
    parts_qs = g.Peca.objects.filter(ativo=True).select_related('categoria').order_by('descricao')
    if peca_id:
        parts_qs = parts_qs.filter(pk=peca_id)
    if q:
        parts_qs = parts_qs.filter(
            Q(sku__icontains=q) | Q(descricao__icontains=q) | Q(codigo_barras__icontains=q) | Q(gtin__icontains=q)
        )
    if categoria_id:
        parts_qs = parts_qs.filter(categoria_id=categoria_id)
        
    if request.method == 'POST':
        pks = request.POST.getlist('selected_pks')
        layout = request.POST.get('layout', layout)
        show_price = request.POST.get('show_price') == '1'
        show_org = request.POST.get('show_org') == '1'
        show_sku = request.POST.get('show_sku') == '1'
        
        selected_items = []
        for pk in pks:
            try:
                qty = int(request.POST.get(f'copies_{pk}', 1) or 1)
            except (ValueError, TypeError):
                qty = 1
            peca = g.Peca.objects.filter(pk=pk).first()
            if peca and qty > 0:
                barcode_val = peca.codigo_barras or peca.gtin or peca.sku
                svg = generate_code128_svg(barcode_val, height=35, module_width=1.3, include_text=True)
                for _ in range(min(qty, 100)):
                    selected_items.append({
                        'peca': peca,
                        'barcode_val': barcode_val,
                        'svg': svg,
                    })
        return render(request, 'operacao/barcode_labels_print.html', {
            'items': selected_items,
            'layout': layout,
            'show_price': show_price,
            'show_org': show_org,
            'show_sku': show_sku,
            'org_name': current_organization().display_name if current_organization() else 'VERTYX',
        })

    categorias = m.CategoriaPeca.objects.filter(ativo=True).order_by('nome')
    products = list(parts_qs[:150])
    
    context = {
        'products': products,
        'categorias': categorias,
        'filters': {'q': q, 'categoria': categoria_id, 'peca': peca_id},
        'layout': layout,
        'show_price': show_price,
        'show_org': show_org,
        'show_sku': show_sku,
    }
    return render(request, 'operacao/barcode_labels.html', context)
