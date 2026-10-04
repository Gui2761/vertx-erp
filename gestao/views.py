from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from contas.permissions import perfis_requeridos
from platform_core.audit import record_write, previous_values
from . import models as m, forms, services, reporting
from .permissions import require, allowed, ROLES

RESOURCES = {
    'peca': (m.Peca, forms.PecaForm, 'estoque', 'estoque_escrever', 'Peças e Estoque', ['sku', 'descricao', 'quantidade_atual', 'estoque_minimo', 'unidade_medida', 'ativo']),
    'fornecedor': (m.Fornecedor, forms.FornecedorForm, 'estoque_escrever', 'estoque_escrever', 'Fornecedores', ['nome', 'documento', 'telefone', 'ativo']),
    'orcamento': (m.Orcamento, forms.OrcamentoForm, 'orcamentos', 'orcamentos', 'Orçamentos', ['numero', 'cliente', 'validade', 'situacao', 'total']),
    'contrato': (m.Contrato, forms.ContratoForm, 'contratos', 'contratos', 'Contratos', ['numero', 'cliente', 'data_final', 'situacao', 'valor']),
    'lancamento': (m.Lancamento, forms.LancamentoForm, 'financeiro', 'financeiro_escrever', 'Lançamentos financeiros', ['descricao', 'tipo', 'cliente', 'vencimento', 'valor', 'situacao']),
    'categoria_financeira': (m.CategoriaFinanceira, forms.CategoriaFinanceiraForm, 'financeiro', 'financeiro_escrever', 'Categorias financeiras', ['nome', 'ativo']),
    'centro_custo': (m.CentroCusto, forms.CentroCustoForm, 'financeiro', 'financeiro_escrever', 'Centros de custo', ['nome', 'ativo']),
    'forma_pagamento': (m.FormaPagamento, forms.FormaPagamentoForm, 'financeiro', 'financeiro_escrever', 'Formas de pagamento', ['nome', 'ativo']),
}
LABELS = {'numero': 'Número', 'situacao': 'Situação', 'total': 'Total', 'quantidade_atual': 'Saldo atual', 'estoque_minimo': 'Estoque mínimo'}
SITUATIONS = {'RASCUNHO': 'Rascunho', 'ENVIADO': 'Enviado', 'APROVADO': 'Aprovado', 'RECUSADO': 'Recusado', 'CONVERTIDO': 'Convertido em OS', 'ATIVO': 'Ativo', 'PROXIMO': 'Próximo do vencimento', 'VENCIDO': 'Vencido', 'SUSPENSO': 'Suspenso', 'ENCERRADO': 'Encerrado', 'PENDENTE': 'Pendente', 'LIQUIDADO': 'Pago / recebido', 'CANCELADO': 'Cancelado'}


def resource_config(resource):
    try:
        return RESOURCES[resource]
    except KeyError:
        raise Http404()


def page_query(request):
    query = request.GET.copy()
    query.pop('page', None)
    return query.urlencode()


def label(model, name):
    return LABELS.get(name) or str(model._meta.get_field(name).verbose_name).capitalize()


def value(obj, name):
    if name == 'situacao':
        return SITUATIONS.get(obj.situacao, obj.situacao)
    if hasattr(obj, 'get_' + name + '_display'):
        return getattr(obj, 'get_' + name + '_display')()
    result = getattr(obj, name)
    return 'Sim' if result is True else 'Não' if result is False else result if result is not None else ''


def can_edit(user, resource, obj=None):
    if not allowed(user, resource_config(resource)[3]):
        return False
    if resource == 'orcamento' and obj and obj.status != 'RASCUNHO':
        return False
    if resource == 'lancamento' and obj and obj.status not in ['PENDENTE', 'VENCIDO']:
        return False
    return True


@login_required
def lista(request, resource):
    model, _, permission, write, title, columns = resource_config(resource)
    require(request.user, permission)
    qs = model.objects.all()
    search = request.GET.get('q', '').strip()
    field = 'descricao' if resource in ['peca', 'lancamento'] else 'numero' if resource == 'contrato' else 'cliente__nome_razao_social' if resource == 'orcamento' else 'nome'
    if search:
        if resource == 'peca':
            from django.db.models import Q
            qs = qs.filter(Q(descricao__icontains=search) | Q(sku__icontains=search) | Q(gtin=search) | Q(codigo_barras=search) | Q(codigos_alternativos__codigo=search)).distinct()
        else:
            qs = qs.filter(**{field + '__icontains': search})
    if request.GET.get('status') in SITUATIONS and resource in ['orcamento', 'contrato', 'lancamento']:
        qs = reporting.situation(qs, request.GET['status'])
    stock_rows = None
    if resource == 'peca':
        from operacao.stock import metrics
        from operacao.models import Configuracao
        config = Configuracao.objects.first() or Configuracao()
        if request.GET.get('minimo') == '1':
            stock_rows = {obj.pk: metrics(obj, config) for obj in qs.filter(ativo=True)}
            qs = qs.filter(pk__in=[pk for pk, data in stock_rows.items() if data['disponivel'] <= data['minimo']])
    if resource == 'lancamento' and request.GET.get('tipo') in ['RECEBER', 'PAGAR']:
        qs = qs.filter(tipo=request.GET['tipo'])
    if resource == 'lancamento':
        from .financial_origin import origin_query, origin_type_query
        qs = qs.filter(origin_type_query(request.GET.get('origem')))
        for name in ['ordem', 'orcamento', 'contrato', 'venda_origem', 'compra_origem']:
            raw = request.GET.get(name)
            if raw:
                if not raw.isdigit():
                    return HttpResponse('Filtro de origem inválido.', status=400)
                qs = qs.filter(origin_query(**{name + '__pk': int(raw)}))
        from django.utils.dateparse import parse_date
        from django.db.models import Q
        dates = {}
        for key in ['vencimento_inicio','vencimento_fim','pagamento_inicio','pagamento_fim']:
            raw = request.GET.get(key)
            if raw:
                try:
                    dates[key] = parse_date(raw)
                except ValueError:
                    dates[key] = None
                if not dates[key]:
                    return HttpResponse('Filtro de data inválido.',status=400)
        for key,lookup in [('vencimento_inicio','gte'),('vencimento_fim','lte')]:
            if dates.get(key):
                qs = qs.filter(**{'vencimento__'+lookup:dates[key]})
        if dates.get('pagamento_inicio') and dates.get('pagamento_fim'):
            period=(dates['pagamento_inicio'],dates['pagamento_fim'])
            qs=qs.filter(Q(pagamentos__data__range=period) | (Q(status='LIQUIDADO',pagamentos__isnull=True,data_liquidacao__range=period) & ~Q(eventos__tipo='ABATIMENTO'))).distinct()
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    rows = [{'cells': [value(obj, col) for col in columns], 'url': reverse('gestao:' + resource + '_detalhe', args=[obj.pk])} for obj in page]
    headers = [label(model, col) for col in columns]
    if resource == 'peca':
        for obj, row in zip(page, rows):
            data = stock_rows[obj.pk] if stock_rows is not None else metrics(obj, config)
            row['cells'].extend(data[key] for key in ['reservado','disponivel','em_compra','ideal','sugerido','situacao'])
        headers.extend(['Reservado','Disponível válido','Em compra','Ideal / máximo','Sugestão de compra','Situação'])
    return render(request, 'gestao/lista.html', {'titulo': title, 'resource': resource, 'headers': headers, 'rows': rows, 'page_obj': page, 'query': page_query(request), 'new_url': reverse('gestao:' + resource + '_novo') if allowed(request.user, write) else '', 'can_write': allowed(request.user, write), 'q': search})


@login_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def editar(request, resource, pk=None):
    model, form_class, permission, write, title, _ = resource_config(resource)
    require(request.user, write)
    obj = get_object_or_404(model.objects.select_for_update(), pk=pk) if pk else model()
    if not can_edit(request.user, resource, obj if pk else None):
        return HttpResponse('Este registro tem condições/histórico preservados e não pode ser editado.', status=400)
    if not pk and hasattr(obj, 'criado_por_id'):
        obj.criado_por = request.user
    form = form_class(request.POST if request.method == 'POST' else None, instance=obj)
    if resource == 'contrato' and not pk and request.method == 'GET':
        from operacao.models import Configuracao
        from django.db.models import Max
        config = Configuracao.objects.first()
        if config:
            next_id = (m.Contrato.objects.aggregate(total=Max('pk'))['total'] or 0) + 1
            form.initial['numero'] = f'{config.prefixo_contrato}-{next_id:0{config.digitos_numero}d}'
            form.fields['numero'].help_text = 'Sugestão conforme parâmetros da organização; confirme a numeração única antes de salvar.'
    status = 200
    if request.method == 'POST' and form.is_valid():
        before = previous_values(form)
        try:
            with transaction.atomic():
                obj = services.salvar_contrato(request.user, form) if resource == 'contrato' else form.save()
                record_write(request, obj, before)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
            status = 400
        else:
            messages.success(request, 'Registro salvo na organização selecionada.')
            return redirect('gestao:' + resource + '_detalhe', pk=obj.pk)
    elif request.method == 'POST':
        status = 400
    return render(request, 'gestao/form.html', {'titulo': ('Editar ' if pk else 'Cadastrar ') + title, 'form': form, 'back_url': reverse('gestao:' + resource + '_lista')}, status=status)


@login_required
def detalhe(request, resource, pk):
    model, form_class, permission, _, title, _ = resource_config(resource)
    require(request.user, permission)
    obj = get_object_or_404(model, pk=pk)
    names = list(form_class.Meta.fields)
    if resource == 'peca':
        names.append('quantidade_atual')
        if not allowed(request.user, 'estoque_escrever'):
            names.remove('custo_aquisicao')
    fields = [(label(model, name), value(obj, name)) for name in names if name not in ['unidades', 'equipamentos']]
    ctx = {'titulo': f'{title} · {obj}', 'object': obj, 'resource': resource, 'fields': fields, 'can_write': allowed(request.user, resource_config(resource)[3]), 'can_edit': can_edit(request.user, resource, obj), 'back_url': reverse('gestao:' + resource + '_lista'), 'edit_url': reverse('gestao:' + resource + '_editar', args=[pk])}
    if resource == 'orcamento':
        ctx.update(itens=obj.itens.select_related('peca'), tecnico_form=forms.TecnicoForm())
    if resource == 'contrato':
        from .financial_origin import origin_query
        ctx.update(unidades=obj.unidades.all(), equipamentos=obj.equipamentos.all(), agendas=obj.agenda.select_related('equipamento', 'tecnico', 'ordem')[:30], cobrancas=m.Lancamento.objects.filter(origin_query(contrato=obj))[:30])
    if resource == 'lancamento':
        ctx.update(eventos=obj.eventos.select_related('usuario'), pagamentos=obj.pagamentos.select_related('conta','usuario'), operacao_form=forms.OperacaoFinanceiraForm(), origem=obj.origem_financeira)
    if resource == 'peca':
        from operacao.stock import metrics
        ctx['stock'] = metrics(obj)
        moves = obj.movimentacoes.select_related('usuario', 'ordem')
        if not allowed(request.user, 'estoque_escrever'):
            moves = moves.filter(ordem__tecnico__usuario=request.user)
        ctx['movimentacoes'] = moves[:30]
    return render(request, 'gestao/detalhe.html', ctx)


@perfis_requeridos(*ROLES['estoque'])
@require_http_methods(['GET', 'POST'])
def movimentar(request):
    form = forms.MovimentoForm(request.POST if request.method == 'POST' else None, user=request.user, initial={'ordem': request.GET.get('ordem'), 'peca': request.GET.get('peca'), 'tipo': 'OS' if request.GET.get('ordem') else 'ENTRADA'})
    status = 200
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            services.movimentar(request.user, data['peca'].pk, data['tipo'], data['quantidade'], data['observacao'], data['ordem'].pk if data['ordem'] else None, data['request_id'], data['origem'].pk if data['origem'] else None, data['destino'].pk if data['destino'] else None,lote_id=data['lote'].pk if data['lote'] else None)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
            status = 400
        else:
            messages.success(request, 'Movimentação registrada e saldo atualizado.')
            return redirect('gestao:peca_detalhe', pk=data['peca'].pk)
    elif request.method == 'POST':
        status = 400
    return render(request, 'gestao/form.html', {'titulo': 'Movimentação de estoque', 'form': form, 'back_url': reverse('gestao:peca_lista')}, status=status)


@perfis_requeridos(*ROLES['orcamentos'])
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def item(request, pk, item_id=None):
    quote = get_object_or_404(m.Orcamento.objects.select_for_update(), pk=pk)
    obj = get_object_or_404(m.ItemOrcamento, pk=item_id, orcamento=quote) if item_id else m.ItemOrcamento(orcamento=quote)
    if quote.status != 'RASCUNHO':
        return HttpResponse('Somente orçamento rascunho aceita edição.', status=400)
    form = forms.ItemOrcamentoForm(request.POST if request.method == 'POST' else None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        services.salvar_item(request.user, form, pk)
        return redirect('gestao:orcamento_detalhe', pk=pk)
    return render(request, 'gestao/form.html', {'titulo': f'Item de {quote.numero}', 'form': form, 'back_url': reverse('gestao:orcamento_detalhe', args=[pk])}, status=400 if request.method == 'POST' else 200)


@perfis_requeridos(*ROLES['orcamentos'])
@require_POST
def item_remover(request, pk, item_id):
    get_object_or_404(m.ItemOrcamento, pk=item_id, orcamento_id=pk)
    try:
        services.remover_item(request.user, item_id)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('gestao:orcamento_detalhe', pk=pk)


@perfis_requeridos(*ROLES['orcamentos'])
@require_POST
def orcamento_status(request, pk, action):
    get_object_or_404(m.Orcamento, pk=pk)
    try:
        services.status_orcamento(request.user, pk, action)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('gestao:orcamento_detalhe', pk=pk)


@perfis_requeridos(*ROLES['orcamentos'])
@require_POST
def converter(request, pk):
    get_object_or_404(m.Orcamento, pk=pk)
    form = forms.TecnicoForm(request.POST)
    if form.is_valid():
        try:
            order = services.converter_orcamento(request.user, pk, form.cleaned_data['tecnico'].pk)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            return redirect('ordens:detalhe', pk=order.pk)
    return render(request, 'gestao/form.html', {'titulo': 'Converter orçamento em OS', 'form': form, 'back_url': reverse('gestao:orcamento_detalhe', args=[pk])}, status=400)


@perfis_requeridos(*ROLES['orcamentos'])
def orcamento_pdf(request, pk):
    quote = get_object_or_404(m.Orcamento, pk=pk)
    rows = [[item.get_tipo_display(), item.descricao, item.quantidade, item.valor_unitario, item.desconto, item.subtotal] for item in quote.itens.all()]
    details = [('Cliente', str(quote.cliente)), ('Unidade', str(quote.unidade or '')), ('Equipamento', str(quote.equipamento or '')), ('Data / validade', f'{quote.data} / {quote.validade}'), ('Diagnóstico', quote.diagnostico), ('Serviços', quote.servicos), ('Condições de pagamento', quote.condicoes_pagamento), ('Prazo', quote.prazo_execucao), ('Observações', quote.observacoes), ('Subtotal / desconto / total (R$)', f'{quote.subtotal} / {quote.desconto} / {quote.total}')]
    try:
        content = reporting.pdf_bytes(quote.numero, request.organization, ['Tipo', 'Descrição', 'Quantidade', 'Unitário (R$)', 'Desconto (R$)', 'Subtotal (R$)'], rows, details=details)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return pdf_response(content, quote.numero)


@perfis_requeridos(*ROLES['contratos'])
@require_POST
def contrato_gerar(request, pk, action):
    get_object_or_404(m.Contrato, pk=pk)
    try:
        if action == 'planejamento':
            services.gerar_planejamento(request.user, pk)
        elif action == 'cobrancas':
            services.gerar_cobrancas(request.user, pk)
        else:
            raise Http404()
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('gestao:contrato_detalhe', pk=pk)


@perfis_requeridos(*ROLES['planejamento'])
def planejamento(request):
    qs = m.AgendaPreventiva.objects.select_related('contrato__cliente', 'equipamento', 'tecnico', 'ordem')
    if not allowed(request.user, 'contratos'):
        qs = qs.filter(tecnico__usuario=request.user)
    form = forms.FiltrosForm(request.GET, statuses=[(x, x.capitalize()) for x in ['PENDENTE', 'ATRASADA', 'AGENDADA', 'CONCLUIDA', 'CANCELADA']])
    if not form.is_valid():
        return render(request, 'gestao/planejamento.html', {'form': form}, status=400)
    qs = reporting.filter_query(qs, form.cleaned_data, {'cliente': 'contrato__cliente', 'unidade': 'equipamento__unidade', 'tecnico': 'tecnico', 'equipamento': 'equipamento'}, 'data_prevista')
    items = [x for x in qs if not form.cleaned_data.get('status') or x.situacao == form.cleaned_data['status']]
    page = Paginator(items, 25).get_page(request.GET.get('page'))
    data = form.cleaned_data
    legacy = [] if data.get('tecnico') else reporting.legacy_preventivas(data)
    today = timezone.localdate()
    legacy = [(equipment, due) for equipment, due in legacy if not data.get('status') or data['status'] == ('ATRASADA' if due < today else 'PENDENTE')]
    legacy_page = Paginator(legacy, 25).get_page(request.GET.get('legacy_page'))
    query = request.GET.copy()
    query.pop('legacy_page', None)
    return render(request, 'gestao/planejamento.html', {'form': form, 'page_obj': page, 'query': page_query(request), 'agendas': page, 'can_write': allowed(request.user, 'contratos'), 'legacy': legacy_page, 'legacy_query': query.urlencode(), 'tecnico_form': forms.TecnicoForm()})


@perfis_requeridos(*ROLES['contratos'])
@require_POST
def agenda_os(request, pk):
    get_object_or_404(m.AgendaPreventiva, pk=pk)
    form = forms.TecnicoForm(request.POST)
    if form.is_valid():
        try:
            order = services.agendar_os(request.user, pk, form.cleaned_data['tecnico'].pk)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            return redirect('ordens:detalhe', pk=order.pk)
    return render(request, 'gestao/form.html', {'titulo': 'Gerar OS preventiva', 'form': form, 'back_url': reverse('gestao:planejamento')}, status=400)


@perfis_requeridos(*ROLES['financeiro'])
def financeiro(request):
    form = forms.FinanceiroFiltrosForm(request.GET)
    if not form.is_valid():
        return render(request, 'gestao/financeiro.html', {'form': form}, status=400)
    today = timezone.localdate()
    inicio = form.cleaned_data.get('inicio') or today.replace(day=1)
    fim = form.cleaned_data.get('fim') or today
    if fim < inicio:
        form.add_error(None, 'Período inválido.')
        return render(request, 'gestao/financeiro.html', {'form': form}, status=400)
    return render(request, 'gestao/financeiro.html', {'form': form, 'totais': reporting.financial_dashboard(inicio, fim, form.cleaned_data), 'inicio': inicio, 'fim': fim, 'can_write': allowed(request.user, 'financeiro_escrever')})


@perfis_requeridos(*ROLES['financeiro_escrever'])
@require_POST
def financeiro_operacao(request, pk, action):
    get_object_or_404(m.Lancamento, pk=pk)
    form = forms.OperacaoFinanceiraForm(request.POST)
    if form.is_valid():
        try:
            if action == 'liquidar':
                if not form.cleaned_data['data']:
                    raise ValidationError('Informe a data de liquidação.')
                services.liquidar(request.user, pk, form.cleaned_data['data'], form.cleaned_data['observacao'])
            elif action == 'cancelar':
                services.cancelar_lancamento(request.user, pk, form.cleaned_data['observacao'])
            else:
                raise Http404()
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            return redirect('gestao:lancamento_detalhe', pk=pk)
    return render(request, 'gestao/form.html', {'titulo': 'Operação financeira', 'form': form, 'back_url': reverse('gestao:lancamento_detalhe', args=[pk])}, status=400)


@perfis_requeridos(*ROLES['relatorios'])
def relatorios(request):
    return render(request, 'gestao/relatorios.html', {'relatorios': [(key, title) for key, (title, _) in reporting.REPORTS.items() if reporting.report_allowed(request.user, key)]})


def pdf_response(content, name):
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{name}.pdf"'
    return response


@perfis_requeridos(*ROLES['relatorios'])
def relatorio(request, key):
    if key not in reporting.REPORTS:
        raise Http404()
    if not reporting.report_allowed(request.user, key):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Relatório não autorizado para este perfil.')
    from ordens.models import Status
    from equipamentos.models import SituacaoOperacional
    statuses = Status.choices if key.startswith('os_') or key == 'preventivas_realizadas' else SituacaoOperacional.choices if key.startswith('equipamentos_') else m.Movimentacao.Tipo.choices if key in ['pecas_utilizadas', 'movimentacao_estoque'] else m.Contrato._meta.get_field('status').choices if key.startswith('contratos_') else m.Lancamento._meta.get_field('status').choices if key in ['receitas', 'despesas'] else [(x, x.capitalize()) for x in ['PENDENTE', 'ATRASADA', 'AGENDADA']]
    form = forms.FiltrosForm(request.GET, statuses=statuses)
    if key.startswith('custos_'):
        form.fields['status'].choices = [('', 'Todos')] + list(Status.choices)
    if key in ['preventivas_previstas', 'preventivas_executadas', 'planos_preventivos']:
        form.fields['status'].choices = [('', 'Todos')] + [(code, code.capitalize()) for code in ['PENDENTE', 'ATRASADA', 'AGENDADA', 'CONCLUIDA', 'CANCELADA']]
    if key in reporting.ADDITIONAL_REPORTS:
        from operacao.reporting import REPORTS
        category = REPORTS[key][1]
        keep = ['inicio', 'fim'] if category == 'estoque' or key == 'fluxo_caixa' else ['inicio', 'fim', 'cliente'] if category in ['financeiro', 'orcamentos'] else list(form.fields)
        if key == 'compras_pendentes':
            keep.append('status')
            form.fields['status'].choices = [('', 'Todos')] + [('APROVADA', 'Aprovada'), ('PEDIDO', 'Pedido')]
        if key == 'orcamentos_conversao':
            keep.append('status')
            form.fields['status'].choices = [('', 'Todos')] + list(m.Orcamento._meta.get_field('status').choices)
        for name in list(form.fields):
            if name not in keep:
                form.fields.pop(name)
    if key.startswith('equipamentos_') or key.startswith('contratos_'):
        form.fields.pop('tecnico')
    if key == 'estoque_minimo':
        for name in list(form.fields):
            form.fields.pop(name)
    if not form.is_valid():
        return render(request, 'gestao/relatorio.html', {'form': form, 'titulo': reporting.REPORTS[key][0]}, status=400)
    headers, rows = reporting.report_data(request.user, key, form.cleaned_data)
    title = reporting.REPORTS[key][0]
    export = request.GET.get('export')
    if export == 'xlsx':
        try:
            content = reporting.xlsx_bytes(headers, rows)
        except ValidationError as exc:
            return HttpResponse('; '.join(exc.messages), status=400)
        response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{key}.xlsx"'
        return response
    if export == 'csv':
        if len(rows) > 10000:
            return HttpResponse('Reduza os filtros para exportar até 10.000 linhas.', status=400)
        response = HttpResponse(reporting.csv_bytes(headers, rows), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{key}.csv"'
        return response
    if export == 'pdf':
        try:
            content = reporting.pdf_bytes(title, request.organization, headers, rows)
        except ValidationError as exc:
            return HttpResponse('; '.join(exc.messages), status=400)
        return pdf_response(content, key)
    page = Paginator(rows, 50).get_page(request.GET.get('page'))
    query = request.GET.copy()
    query.pop('page', None)
    query.pop('export', None)
    return render(request, 'gestao/relatorio.html', {'form': form, 'titulo': title, 'headers': headers, 'rows': page, 'page_obj': page, 'total': len(rows), 'query': query.urlencode()})
