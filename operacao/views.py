"""Telas complementares do ERP, sempre sob o contexto da organização selecionada."""
import mimetypes
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from platform_core.access import effective_role, require_erp
from platform_core.audit import previous_values, record_write
from gestao import models as g, forms as gf
from gestao.views import value, page_query
from . import models as m, forms, services, permissions

RESOURCES = {
    'conhecimento': (m.ArtigoConhecimento, forms.ConhecimentoForm, 'operacional', 'operacional', 'Base de conhecimento', ['titulo', 'fabricante', 'modelo', 'ativo']),
    'deposito': (m.Deposito, forms.DepositoForm, 'compras', 'compras', 'Depósitos', ['nome', 'endereco', 'ativo']),
    'categoria': (m.CategoriaPeca, forms.CategoriaPecaForm, 'compras', 'compras', 'Categorias de peças', ['nome', 'ativo']),
    'chamado': (m.Chamado, forms.ChamadoForm, 'operacional', 'gestao', 'Chamados', ['titulo', 'cliente', 'equipamento', 'prioridade', 'status']),
    'checklist': (m.ModeloChecklist, forms.ChecklistForm, 'gestao', 'gestao', 'Modelos de checklist', ['nome', 'ativo']),
    'plano': (m.PlanoPreventivo, forms.PlanoForm, 'operacional', 'gestao', 'Planos preventivos', ['nome', 'cliente', 'periodicidade', 'proxima_execucao', 'ultima_execucao', 'ativo']),
    'compra': (m.Compra, forms.CompraForm, 'compras', 'compras', 'Compras', ['id', 'fornecedor', 'deposito', 'status', 'total', 'vencimento']),
    'venda': (m.Venda, forms.VendaForm, 'gestao', 'gestao', 'Vendas e loja', ['id', 'cliente', 'vendedor', 'status', 'total', 'vencimento']),
    'banco': (m.ContaBancaria, forms.ContaBancariaForm, 'financeiro', 'financeiro_escrever', 'Bancos e caixa', ['nome', 'tipo', 'saldo', 'ativo']),
    'extrato': (m.ExtratoBancario, forms.ExtratoForm, 'financeiro', 'financeiro_escrever', 'Conciliação bancária', ['conta', 'data', 'identificador', 'valor', 'movimento']),
    'fiscal': (m.DocumentoFiscal, forms.FiscalForm, 'financeiro', 'financeiro_escrever', 'Documentos fiscais', ['tipo', 'cliente', 'status', 'numero', 'ambiente', 'valor']),
    'documento': (m.Documento, forms.DocumentoForm, None, None, 'Central de documentos', ['titulo', 'tipo', 'cliente', 'equipamento', 'criado_em']),
    'portal_acesso': (m.PortalCliente, forms.PortalForm, 'gestao', 'gestao', 'Acessos ao portal', ['usuario', 'cliente', 'ativo']),
}

def config(resource):
    if resource not in RESOURCES:
        raise Http404()
    return RESOURCES[resource]

def permitted(user, capability):
    if capability:
        from platform_core.modules import has_capability
        return has_capability(user,capability,permissions.ROLES.get(capability,()))
    return effective_role(user) in ('ADMIN','GESTOR','TECNICO','ESTOQUE','FINANCEIRO','CONTABILIDADE','RH','PDV','VENDEDOR','COMPRAS')

def access(user, capability):
    if capability:
        permissions.require(user, capability)
    else:
        require_erp(user, roles=['ADMIN', 'GESTOR', 'TECNICO', 'ESTOQUE', 'FINANCEIRO', 'CONTABILIDADE','RH','PDV','VENDEDOR','COMPRAS'])

def queryset(user, resource):
    model = config(resource)[0]
    if resource == 'documento':
        return permissions.documents(user)
    qs = model.objects.all()
    if effective_role(user) == 'TECNICO':
        if resource == 'plano':
            qs = qs.filter(Q(tecnico__usuario=user) | Q(equipe__usuario=user)).distinct()
        if resource == 'chamado':
            from .technician_access import calls_for
            qs = calls_for(user)
        if resource == 'conhecimento':
            from ordens.services import visiveis
            qs = qs.filter(Q(ordem__isnull=True) | Q(ordem__in=visiveis(user)))
    return qs

def editable(resource, obj):
    if resource in ['compra', 'venda', 'fiscal']:
        return obj.status == 'RASCUNHO'
    if resource == 'chamado':
        return not obj.ordem_id and obj.status not in ['CANCELADO', 'CONCLUIDO']
    return resource != 'documento' and (resource != 'extrato' or not obj.movimento_id)

def field_label(model, name):
    try:
        return str(model._meta.get_field(name).verbose_name).capitalize()
    except Exception:
        return name.replace('_', ' ').capitalize()

@login_required
def lista(request, resource):
    model, _, read, write, title, cols = config(resource)
    access(request.user, read)
    qs = queryset(request.user, resource)
    if resource in ['compra','venda'] and request.GET.get('status') in ['RASCUNHO','APROVADA','PEDIDO','RECEBIDA','CONFIRMADA','CANCELADA']:
        qs=qs.filter(status=request.GET['status'])
    if resource=='compra' and request.GET.get('cotacoes')=='1':
        qs=qs.filter(cotacoes__isnull=False).distinct()
    search = request.GET.get('q', '').strip()
    field = 'titulo' if resource in ['chamado', 'documento', 'conhecimento'] else 'descricao' if resource in ['fiscal', 'extrato'] else 'cliente__nome_razao_social' if resource == 'venda' else 'fornecedor__nome' if resource == 'compra' else 'usuario__username' if resource == 'portal_acesso' else 'nome'
    if search:
        if resource == 'conhecimento':
            query = Q()
            for name in ['titulo', 'fabricante', 'modelo', 'sintoma', 'defeito', 'solucao', 'procedimento', 'observacoes']:
                query |= Q(**{name + '__icontains': search})
            qs = qs.filter(query)
        else:
            qs = qs.filter(**{field + '__icontains': search})
    page = Paginator(qs.order_by('-pk'), 25).get_page(request.GET.get('page'))
    rows = [{'cells': [value(obj, col) for col in cols], 'url': reverse('operacao:' + resource + '_detalhe', args=[obj.pk])} for obj in page]
    return render(request, 'gestao/lista.html', {'titulo': title, 'headers': [field_label(model, col) for col in cols], 'rows': rows, 'page_obj': page, 'query': page_query(request), 'q': search, 'new_url': reverse('operacao:' + resource + '_novo') if permitted(request.user, write) else ''})

@login_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def editar(request, resource, pk=None):
    model, cls, _, write, title, _ = config(resource)
    access(request.user, write)
    obj = get_object_or_404(queryset(request.user, resource).select_for_update(), pk=pk) if pk else model()
    if pk and not editable(resource, obj):
        return HttpResponse('Registro confirmado/histórico preservado; edição indisponível.', status=400)
    if not pk and hasattr(obj, 'criado_por_id'):
        obj.criado_por = request.user
    initial = {name: request.GET[name] for name in ['cliente', 'unidade', 'equipamento', 'ordem', 'contrato', 'orcamento', 'fiscal', 'lancamento', 'venda', 'chamado', 'tecnico', 'fornecedor'] if name in request.GET}
    form = cls(request.POST if request.method == 'POST' else None, request.FILES or None, instance=obj, initial=initial)
    if resource == 'documento' and effective_role(request.user) == 'TECNICO':
        from ordens.services import visiveis
        from .technician_access import scoped_records
        for field in ['cliente','unidade','equipamento']:
            form.fields[field].queryset=scoped_records(request.user,form.fields[field].queryset,field)
        form.fields['ordem'].queryset = visiveis(request.user)
        for field in ['fiscal', 'contrato', 'orcamento', 'fornecedor']:
            form.fields[field].queryset = form.fields[field].queryset.none()
        for field in ['funcionario','compra','venda']:
            form.fields[field].queryset=form.fields[field].queryset.none()
        form.fields['disponivel_portal'].disabled = True
        form.fields['tecnico'].queryset = form.fields['tecnico'].queryset.filter(usuario=request.user)
        form.fields['chamado'].queryset = queryset(request.user, 'chamado')
    if resource=='documento' and effective_role(request.user)=='RH':
        for field in ['cliente','unidade','equipamento','tecnico','fornecedor','chamado','ordem','contrato','orcamento','fiscal','peca','compra','venda']:
            form.fields[field].queryset=form.fields[field].queryset.none()
        form.fields['disponivel_portal'].disabled=True
    if resource=='documento' and effective_role(request.user) in ['PDV','VENDEDOR']:
        for field in ['funcionario','compra','fiscal','contrato','orcamento','fornecedor','tecnico','chamado','ordem','equipamento','unidade']:
            form.fields[field].queryset=form.fields[field].queryset.none()
        form.fields['venda'].queryset=form.fields['venda'].queryset.filter(Q(criado_por=request.user)|Q(vendedor=request.user))
    if resource == 'conhecimento':
        from ordens.services import visiveis
        form.fields['ordem'].queryset = visiveis(request.user)
        form.fields['manual'].queryset = permissions.documents(request.user)
    if request.method == 'POST' and form.is_valid():
        before = previous_values(form)
        try:
            with transaction.atomic():
                if resource == 'plano':
                    obj = services.salvar_plano(request.user, form)
                elif resource == 'documento':
                    obj = services.documento_salvar(request.user, form)
                elif resource == 'chamado':
                    obj = services.salvar_chamado(request.user, form, form.cleaned_data.get('request_id'))
                else:
                    obj = form.save()
                record_write(request, obj, before)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        except OSError:
            form.add_error(None, 'Armazenamento indisponível; tente novamente.')
        else:
            messages.success(request, 'Registro salvo na organização selecionada.')
            return redirect('operacao:' + resource + '_detalhe', pk=obj.pk)
    return render(request, 'operacao/form.html', {'titulo': ('Editar ' if pk else 'Cadastrar ') + title, 'form': form, 'back_url': reverse('operacao:' + resource + '_lista')}, status=400 if request.method == 'POST' else 200)

@login_required
def detalhe(request, resource, pk):
    model, cls, read, write, title, _ = config(resource)
    access(request.user, read)
    obj = get_object_or_404(queryset(request.user, resource), pk=pk)
    fields = [(field_label(model, name), ' · '.join(tech.nome for tech in obj.equipe.all()) if name == 'equipe' else value(obj, name)) for name in cls.Meta.fields if name not in ['arquivo', 'equipamentos', 'itens']]
    ctx = {'titulo': f'{title} · {obj}', 'object': obj, 'resource': resource, 'fields': fields, 'can_write': permitted(request.user, write), 'edit_url': reverse('operacao:' + resource + '_editar', args=[pk]) if editable(resource, obj) and permitted(request.user, write) else '', 'back_url': reverse('operacao:' + resource + '_lista'), 'tecnico_form': gf.TecnicoForm()}
    if resource in ['compra', 'venda']:
        ctx['itens'] = obj.itens.select_related('peca')
        if resource == 'compra':
            ctx['cotacoes'] = obj.cotacoes.select_related('fornecedor')
            ctx['recebimentos'] = obj.recebimentos.prefetch_related('itens__item__peca', 'itens__movimentacao')
    if resource == 'banco':
        ctx['movimentos'] = obj.movimentos.all()[:100]
    if resource == 'deposito':
        ctx['saldos'] = m.SaldoDeposito.objects.filter(deposito=obj).select_related('peca')
    if resource == 'plano':
        ctx['ocorrencias'] = obj.ocorrencias.select_related('equipamento', 'ordem').order_by('data')[:200]
        ctx['equipamentos'] = obj.equipamentos.all()
    if resource == 'extrato':
        ctx['conciliacao_form'] = forms.ConciliacaoForm(conta=obj.conta)
    return render(request, 'operacao/detalhe.html', ctx)

@login_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def item(request, resource, pk, item_id=None, kind='item'):
    access(request.user, 'compras' if resource == 'compra' else 'gestao')
    parent = get_object_or_404(m.Compra.objects.select_for_update() if resource == 'compra' else m.Venda.objects.select_for_update(), pk=pk)
    if parent.status != 'RASCUNHO':
        return HttpResponse('Itens/cotações só podem mudar em rascunho.', status=400)
    cls = forms.CotacaoCompraForm if kind == 'cotacao' else forms.ItemCompraForm if resource == 'compra' else forms.ItemVendaForm
    name = 'compra' if resource == 'compra' else 'venda'
    model = cls.Meta.model
    obj = get_object_or_404(model, pk=item_id, **{name: parent}) if item_id else model(**{name: parent})
    form = cls(request.POST if request.method == 'POST' else None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        before = previous_values(form)
        obj = form.save(commit=False)
        if resource == 'venda':
            obj.custo_unitario = obj.peca.custo_aquisicao
        obj.save()
        record_write(request, obj, before)
        return redirect('operacao:' + resource + '_detalhe', pk=pk)
    return render(request, 'operacao/form.html', {'titulo': f'{kind.capitalize()} · {parent}', 'form': form, 'back_url': reverse('operacao:' + resource + '_detalhe', args=[pk])}, status=400 if request.method == 'POST' else 200)

@login_required
@require_POST
@transaction.atomic
def item_remover(request, resource, pk, item_id, kind='item'):
    access(request.user, 'compras' if resource == 'compra' else 'gestao')
    parent = get_object_or_404(m.Compra.objects.select_for_update() if resource == 'compra' else m.Venda.objects.select_for_update(), pk=pk)
    if parent.status != 'RASCUNHO':
        return HttpResponse('Itens confirmados são preservados.', status=400)
    qs = parent.cotacoes if kind == 'cotacao' else parent.itens
    obj = get_object_or_404(qs, pk=item_id)
    from gestao.services import audit
    audit(request.user, 'ITEM_REMOVIDO', obj, {'anterior': str(obj)})
    obj.delete()
    return redirect('operacao:' + resource + '_detalhe', pk=pk)

@login_required
@require_POST
def acao(request, resource, pk, action):
    access(request.user, config(resource)[3])
    obj = get_object_or_404(queryset(request.user, resource), pk=pk)
    try:
        if resource == 'chamado' and action != 'gerar':
            services.chamado_status(request.user, pk, action, request.POST.get('justificativa', ''))
            return redirect('operacao:chamado_detalhe', pk=pk)
        if resource in ['chamado', 'plano']:
            form = gf.TecnicoForm(request.POST)
            if not form.is_valid():
                return HttpResponse('Escolha um técnico ativo da organização.', status=400)
            target = services.chamado_os(request.user, pk, form.cleaned_data['tecnico'].pk) if resource == 'chamado' else services.preventiva_os(request.user, pk, form.cleaned_data['tecnico'].pk)
            return redirect('ordens:detalhe', pk=target.pk)
        if resource == 'compra':
            quotation = request.POST.get('cotacao')
            if quotation and not obj.cotacoes.filter(pk=quotation).exists():
                raise Http404()
            services.compra_acao(request.user, pk, action, quotation)
        elif resource == 'venda' and action == 'confirmar':
            services.venda_confirmar(request.user, pk)
        elif resource == 'fiscal':
            from fiscal.services import executar
            executar(request.user, pk, action, request.POST.get('justificativa', ''))
        else:
            return HttpResponse('Ação inválida.', status=400)
    except (ValidationError, ValueError) as exc:
        return HttpResponse('; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Dados inválidos.', status=400)
    messages.success(request, 'Operação registrada.')
    return redirect('operacao:' + resource + '_detalhe', pk=pk)

@login_required
@require_http_methods(['GET', 'POST'])
def compra_receber(request, pk):
    permissions.require(request.user, 'compras')
    purchase = get_object_or_404(m.Compra, pk=pk)
    if purchase.status != 'PEDIDO':
        return HttpResponse('Compra deve estar em pedido.', status=400)
    form = forms.RecebimentoCompraForm(request.POST if request.method == 'POST' else None, compra=purchase)
    if request.method == 'POST' and form.is_valid():
        try:
            services.receber_compra(request.user, pk, form.cleaned_data['linhas'], form.cleaned_data['request_id'], deposito_id=form.cleaned_data['deposito'].pk, documento=form.cleaned_data['documento'])
        except (ValidationError, ValueError) as exc:
            form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Dados inválidos.')
        else:
            return redirect('operacao:compra_detalhe', pk=pk)
    return render(request, 'operacao/form.html', {'titulo': f'Recebimento parcial / final · {purchase}', 'form': form, 'back_url': reverse('operacao:compra_detalhe', args=[pk])}, status=400 if request.method == 'POST' else 200)

@login_required
@require_POST
def preventiva_gerar(request, pk):
    access(request.user, 'gestao')
    get_object_or_404(m.PreventivaProgramada, pk=pk)
    form = gf.TecnicoForm(request.POST)
    if not form.is_valid():
        return HttpResponse('Selecione técnico ativo.', status=400)
    try:
        order = services.preventiva_os(request.user, pk, form.cleaned_data['tecnico'].pk)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('ordens:detalhe', pk=order.pk)

@login_required
def documento_arquivo(request, pk):
    require_erp(request.user)
    document = get_object_or_404(permissions.documents(request.user), pk=pk)
    if not permissions.document_allowed(request.user, document):
        raise Http404()
    try:
        response = FileResponse(document.arquivo.open('rb'), as_attachment=True, filename=document.titulo + '.' + document.arquivo.name.rsplit('.', 1)[-1], content_type=mimetypes.guess_type(document.arquivo.name)[0] or 'application/octet-stream')
    except OSError:
        return HttpResponse('Arquivo indisponível; tente novamente.', status=503)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

@login_required
@require_http_methods(['GET', 'POST'])
def financeiro_acao(request, action, pk=None):
    access(request.user, 'financeiro_escrever')
    entry = get_object_or_404(g.Lancamento, pk=pk) if pk and action in ['pagar', 'parcelar'] else None
    row = get_object_or_404(m.ExtratoBancario, pk=pk) if action == 'conciliar' else None
    classes = {'pagar': forms.PagamentoForm, 'parcelar': forms.ParcelasForm, 'caixa': forms.CaixaForm, 'transferir': forms.TransferenciaForm, 'conciliar': forms.ConciliacaoForm}
    if action not in classes:
        raise Http404()
    form = classes[action](request.POST if request.method == 'POST' else None, **({'conta': row.conta} if row else {'initial': {'valor': entry.saldo}} if entry and action == 'pagar' else {}))
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            if action == 'pagar':
                services.pagar(request.user, pk, data['valor'], data['data'], data['observacao'], data['conta'].pk if data['conta'] else None, data['request_id'])
            elif action == 'parcelar':
                services.parcelar(request.user, pk, data['quantidade'], data['primeiro_vencimento'])
            elif action == 'caixa':
                services.caixa(request.user, data['conta'].pk, data['tipo'], data['valor'], data['data'], data['descricao'], data['request_id'])
            elif action == 'transferir':
                services.transferir_banco(request.user, data['conta'].pk, data['destino'].pk, data['valor'], data['data'], data['request_id'])
            else:
                services.conciliar(request.user, pk, data['movimento'].pk)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            messages.success(request, 'Operação financeira registrada.')
            return redirect('gestao:lancamento_detalhe', pk=pk) if entry else redirect('operacao:banco_lista')
    return render(request, 'operacao/form.html', {'titulo': {'pagar': 'Pagamento / recebimento parcial', 'parcelar': 'Parcelar conta', 'caixa': 'Movimentar caixa', 'transferir': 'Transferir entre contas', 'conciliar': 'Conciliar extrato'}[action], 'form': form, 'back_url': reverse('operacao:banco_lista')}, status=400 if request.method == 'POST' else 200)

@login_required
def sugestoes(request):
    access(request.user, 'compras')
    from .stock import metrics
    config = m.Configuracao.objects.first() or m.Configuracao()
    rows = [metrics(part,config) for part in g.Peca.objects.filter(ativo=True)]
    rows = [row for row in rows if row['disponivel'] <= row['minimo'] or row['sugerido'] > 0]
    return render(request, 'operacao/sugestoes.html', {'rows': rows})

@login_required
@require_POST
def os_acao(request, pk, action):
    from ordens.views import ordem_permitida
    ordem_permitida(request, pk)
    try:
        if action == 'checklist':
            services.checklist_salvar(request.user, pk, request.POST.getlist('concluido'), {key[5:]: val for key, val in request.POST.items() if key.startswith('nota_')}, {key[9:]: val for key, val in request.POST.items() if key.startswith('resposta_')})
        else:
            services.transicao_os(request.user, pk, action, request.POST.get('justificativa', ''))
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('ordens:detalhe', pk=pk)

@login_required
@require_http_methods(['GET', 'POST'])
def os_necessidade(request, pk):
    from ordens.views import ordem_permitida
    order = ordem_permitida(request, pk)
    form = forms.NecessidadePecaForm(request.POST if request.method == 'POST' else None, instance=m.NecessidadePecaOS(ordem=order, usuario=request.user))
    if request.method == 'POST' and form.is_valid():
        try:
            services.necessidade_peca(request.user, pk, form)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            return redirect('ordens:detalhe', pk=pk)
    return render(request, 'operacao/form.html', {'titulo': f'Peça necessária · {order.numero}', 'form': form, 'back_url': reverse('ordens:detalhe', args=[pk])}, status=400 if request.method == 'POST' else 200)

@login_required
@require_POST
def necessidade_compra(request, pk):
    permissions.require(request.user, 'compras')
    get_object_or_404(m.NecessidadePecaOS, pk=pk)
    try:
        purchase = services.comprar_necessidade(request.user, pk)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('operacao:compra_detalhe', pk=purchase.pk)

@login_required
def necessidades(request):
    require_erp(request.user, roles=['ADMIN', 'GESTOR', 'ESTOQUE', 'TECNICO'])
    rows = m.NecessidadePecaOS.objects.select_related('ordem', 'peca', 'deposito', 'compra').filter(resolvida_em__isnull=True).exclude(ordem__status__in=m.ENCERRADAS)
    if effective_role(request.user) == 'TECNICO':
        from ordens.services import visiveis
        rows = rows.filter(ordem__in=visiveis(request.user))
    from .stock import need_remaining
    data = [{'need': row, 'pendente': need_remaining(row)} for row in rows.order_by('criado_em')]
    return render(request, 'operacao/necessidades.html', {'rows': data, 'can_buy': effective_role(request.user) in ['ADMIN', 'GESTOR', 'ESTOQUE']})

@login_required
@require_POST
def necessidade_resolver(request, pk):
    permissions.require(request.user, 'compras')
    get_object_or_404(m.NecessidadePecaOS, pk=pk)
    try:
        services.resolver_necessidade(request.user, pk, request.POST.get('motivo', ''))
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=400)
    return redirect('operacao:necessidades')

@login_required
def pesquisa(request):
    from clientes.models import Cliente, Unidade
    from equipamentos.models import Equipamento
    from ordens.services import visiveis
    from gestao.permissions import allowed
    require_erp(request.user, roles=['ADMIN', 'GESTOR', 'TECNICO', 'ESTOQUE', 'FINANCEIRO', 'CONTABILIDADE', 'PLANEJADOR', 'ATENDIMENTO','PDV','VENDEDOR','COMPRAS'])
    text = request.GET.get('q', '').strip()[:100]
    sections = []
    if len(text) >= 2:
        sources = [('Clientes', Cliente.objects.filter(nome_razao_social__icontains=text), 'clientes:cliente_detail'), ('Unidades', Unidade.objects.filter(nome__icontains=text), 'clientes:unidade_detail'),
                   ('Equipamentos', Equipamento.objects.filter(Q(nome__icontains=text) | Q(patrimonio__icontains=text) | Q(codigo_interno__icontains=text) | Q(numero_serie__icontains=text)), 'equipamentos:equipamento_detail'),
                   ('Ordens de serviço', visiveis(request.user).filter(Q(numero_personalizado__icontains=text) | Q(defeito__icontains=text)), 'ordens:detalhe')]
        sources[1] = ('Unidades', sources[1][1], 'clientes:cliente_detail')
        commercial_role=effective_role(request.user) in ['PDV','VENDEDOR','COMPRAS']
        if commercial_role: sources=sources[:1]
        if effective_role(request.user) in ['ADMIN', 'GESTOR', 'TECNICO']:
            calls = queryset(request.user, 'chamado').filter(Q(titulo__icontains=text) | Q(descricao__icontains=text))
            number = text.upper().removeprefix('CH-')
            if number.isdigit():
                calls = calls | queryset(request.user, 'chamado').filter(pk=int(number))
            sources.append(('Chamados', calls, 'operacao:chamado_detalhe'))
        os_number = text.upper().removeprefix('OS-')
        if os_number.isdigit() and not commercial_role:
            sources[3] = ('Ordens de serviço', sources[3][1] | visiveis(request.user).filter(pk=int(os_number)), 'ordens:detalhe')
        if allowed(request.user, 'contratos'):
            sources.append(('Contratos', g.Contrato.objects.filter(numero__icontains=text), 'gestao:contrato_detalhe'))
        if allowed(request.user,'estoque'):
            sources.append(('Produtos',g.Peca.objects.filter(Q(sku__icontains=text)|Q(descricao__icontains=text)|Q(gtin=text)|Q(codigo_barras=text)|Q(codigos_alternativos__codigo=text)), 'gestao:peca_detalhe'))
        if allowed(request.user,'compras'):
            sources.append(('Fornecedores',g.Fornecedor.objects.filter(Q(nome__icontains=text)|Q(documento__icontains=text)),'gestao:fornecedor_detalhe'))
            buys=m.Compra.objects.filter(Q(fornecedor__nome__icontains=text)|Q(necessidade__icontains=text))
            number=text.upper().removeprefix('COMP-')
            if number.isdigit(): buys=buys|m.Compra.objects.filter(pk=int(number))
            sources.append(('Compras',buys,'operacao:compra_detalhe'))
        if allowed(request.user,'pdv'):
            sales=m.Venda.objects.filter(Q(cliente__nome_razao_social__icontains=text)|Q(observacoes__icontains=text))
            number=text.upper().removeprefix('VENDA-')
            if number.isdigit(): sales=sales|m.Venda.objects.filter(pk=int(number))
            if effective_role(request.user) in ['PDV','VENDEDOR']:
                sales=sales.filter(Q(criado_por=request.user)|Q(vendedor=request.user))
            sections.append({'titulo':'Vendas PDV','rows':[{'label':str(sale),'url':reverse('operacao:pdv_sale',args=[sale.public_id])} for sale in sales.exclude(public_id__isnull=True).distinct()[:25]]})
        for label, rows, route in sources:
            sections.append({'titulo': label, 'rows': [{'label': str(row), 'url': reverse(route, args=[row.cliente_id if label == 'Unidades' else row.pk])} for row in rows.distinct()[:25]]})
    return render(request, 'operacao/pesquisa.html', {'q': text, 'sections': sections})
