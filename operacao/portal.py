"""Portal limitado aos clientes explicitamente vinculados ao usuário, inclusive na mesma empresa."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, FileResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone
from clientes.models import Cliente, Unidade
from equipamentos.models import Equipamento
from ordens.models import OrdemServico, Assinatura, Foto
from gestao import models as g, services as gs, reporting
from . import models as m, forms
from .permissions import portal_clients, documents
from .views import documento_arquivo

def customers(request):
    return list(portal_clients(request.user))

@login_required
def home(request):
    ids = customers(request)
    return render(request, 'operacao/portal.html', {'clientes': Cliente.objects.filter(pk__in=ids), 'chamados': m.Chamado.objects.filter(cliente_id__in=ids)[:50], 'ordens': OrdemServico.objects.filter(cliente_id__in=ids).select_related('equipamento')[:50], 'equipamentos': Equipamento.objects.filter(cliente_id__in=ids), 'contratos': g.Contrato.objects.filter(cliente_id__in=ids), 'orcamentos': g.Orcamento.objects.filter(cliente_id__in=ids), 'documentos': documents(request.user), 'notas': m.DocumentoFiscal.objects.filter(cliente_id__in=ids).exclude(status='RASCUNHO'), 'financeiro': g.Lancamento.objects.filter(cliente_id__in=ids, tipo='RECEBER').exclude(status='CANCELADO')})

@login_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def chamado(request):
    ids = customers(request)
    obj = m.Chamado(criado_por=request.user)
    form = forms.ChamadoForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=obj)
    for name in ['origem', 'tecnico', 'agendada_para', 'agendada_ate', 'prazo', 'observacoes_internas']:
        form.fields.pop(name)
    for name, qs in {'cliente': Cliente.objects.filter(pk__in=ids), 'unidade': Unidade.objects.filter(cliente_id__in=ids), 'equipamento': Equipamento.objects.filter(cliente_id__in=ids), 'contrato': g.Contrato.objects.filter(cliente_id__in=ids)}.items():
        form.fields[name].queryset = qs
    if request.method == 'POST' and form.is_valid():
        from .services import salvar_chamado
        try:
            obj = salvar_chamado(request.user, form, form.cleaned_data.get('request_id'), portal=True)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
            return render(request, 'operacao/form.html', {'titulo': 'Abrir chamado', 'form': form, 'back_url': '/portal/'}, status=400)
        gs.audit(request.user, 'CHAMADO_PORTAL_CRIADO', obj, {'posterior': {'titulo': obj.titulo, 'cliente': obj.cliente_id}})
        from .notifications import deliver
        deliver(f'chamado:{obj.pk}', 'Novo chamado do cliente', str(obj), ['ADMIN', 'GESTOR'], f'/chamados/{obj.pk}/')
        return redirect('operacao:portal')
    return render(request, 'operacao/form.html', {'titulo': 'Abrir chamado', 'form': form, 'back_url': '/portal/'}, status=400 if request.method == 'POST' else 200)

@login_required
def ordem(request, pk):
    row = get_object_or_404(OrdemServico.objects.filter(cliente_id__in=customers(request)), pk=pk)
    return render(request, 'operacao/portal_os.html', {'ordem': row, 'assinaturas': row.assinaturas.all(), 'fotos': row.fotos.all()})

@login_required
def equipamento(request, codigo_publico):
    row = get_object_or_404(Equipamento.objects.filter(cliente_id__in=customers(request)), codigo_publico=codigo_publico)
    from .history import equipment_timeline
    return render(request, 'operacao/portal_equipamento.html', {'equipamento': row, 'timeline': equipment_timeline(request.user, row, portal=True)})

@login_required
def chamado_detalhe(request, pk):
    row = get_object_or_404(m.Chamado.objects.filter(cliente_id__in=customers(request)), pk=pk)
    docs = documents(request.user).filter(chamado=row)
    return render(request, 'operacao/portal_chamado.html', {'chamado': row, 'documentos': docs})

@login_required
def arquivo_os(request, pk, item_id, kind):
    row = get_object_or_404(OrdemServico.objects.filter(cliente_id__in=customers(request)), pk=pk)
    if kind == 'pdf':
        from ordens.reports import gerar_pdf
        signature = get_object_or_404(Assinatura, pk=item_id, ordem=row)
        try:
            response = HttpResponse(gerar_pdf(signature), content_type='application/pdf')
        except (ValidationError, OSError):
            return HttpResponse('Comprovante indisponível; verifique os arquivos do atendimento.', status=409)
        response['Content-Disposition'] = f'attachment; filename="{row.numero}.pdf"'
    else:
        photo = get_object_or_404(Foto, pk=item_id, ordem=row)
        try:
            response = FileResponse(photo.arquivo.open('rb'), content_type='image/jpeg')
        except OSError:
            return HttpResponse('Arquivo indisponível.', status=503)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

@login_required
@require_POST
@transaction.atomic
def aprovar(request, pk, action):
    quote = get_object_or_404(g.Orcamento.objects.select_for_update().filter(cliente_id__in=customers(request)), pk=pk)
    if action not in ['aprovar', 'recusar'] or quote.status != 'ENVIADO' or quote.validade < timezone.localdate() or quote.total <= 0:
        return HttpResponse('Orçamento não pode receber essa decisão.', status=400)
    old = quote.status
    quote.status = 'APROVADO' if action == 'aprovar' else 'RECUSADO'
    gs.write(quote)
    if quote.status == 'APROVADO' and quote.gerar_recebivel:
        gs.gerar_do_orcamento(request.user, quote)
    gs.audit(request.user, 'ORCAMENTO_' + quote.status, quote, {'status': {'anterior': old, 'posterior': quote.status}, 'canal': 'PORTAL_AUTENTICADO'})
    return redirect('operacao:portal')

@login_required
def orcamento_pdf(request, pk):
    quote = get_object_or_404(g.Orcamento.objects.filter(cliente_id__in=customers(request)), pk=pk)
    rows = [[item.get_tipo_display(), item.descricao, item.quantidade, item.valor_unitario, item.desconto, item.subtotal] for item in quote.itens.all()]
    return HttpResponse(reporting.pdf_bytes(quote.numero, request.organization, ['Tipo', 'Descrição', 'Quantidade', 'Unitário', 'Desconto', 'Subtotal'], rows, details=[('Cliente', quote.cliente), ('Validade', quote.validade), ('Total', quote.total), ('Condições', quote.condicoes_pagamento), ('Serviços', quote.servicos)]), content_type='application/pdf')

@login_required
def relatorio(request):
    ids = customers(request)
    headers = ['Descrição', 'Vencimento', 'Valor', 'Saldo', 'Situação']
    rows = [[row.descricao, str(row.vencimento), str(row.valor), str(row.saldo), row.situacao] for row in g.Lancamento.objects.filter(cliente_id__in=ids, tipo='RECEBER').exclude(status='CANCELADO')]
    fmt = request.GET.get('formato', 'csv')
    if fmt == 'pdf':
        return HttpResponse(reporting.pdf_bytes('Financeiro do cliente', request.organization, headers, rows), content_type='application/pdf')
    if fmt == 'xlsx':
        return HttpResponse(reporting.xlsx_bytes(headers, rows), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return HttpResponse(reporting.csv_bytes(headers, rows), content_type='text/csv; charset=utf-8')
