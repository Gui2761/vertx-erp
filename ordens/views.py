import base64
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from . import services
from .forms import OrdemForm, GeoForm, FotoForm, AssinaturaForm, ReabrirForm
from .models import OrdemServico, Foto, Conferencia, Assinatura, Status
from platform_core.logging_utils import operation_failure


def ordem_permitida(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    services.autorizar(request.user, ordem)
    return ordem


def erro(exc):
    return HttpResponseBadRequest('; '.join(exc.messages))


def token_conferencia(conferencia):
    return signing.dumps({'id': conferencia.pk, 'usuario': conferencia.usuario_id, 'ordem': conferencia.ordem_id}, salt='ordens.conferencia')


def ler_token(token, user, ordem):
    payload = signing.loads(token, salt='ordens.conferencia', max_age=1800)
    if payload['usuario'] != user.pk or payload['ordem'] != ordem.pk:
        raise signing.BadSignature()
    return payload['id']


@login_required
def lista(request):
    from django.core.paginator import Paginator
    qs = services.visiveis(request.user)
    if request.GET.get('status') in Status.values:
        qs = qs.filter(status=request.GET['status'])
    if request.GET.get('grupo') == 'abertas':
        qs = qs.filter(status__in=['ABERTA','AGENDADA'])
    if request.GET.get('grupo') == 'andamento':
        qs = qs.filter(status__in=['EXECUCAO','DESLOCAMENTO','AG_PECA','AG_CLIENTE','AG_APROVACAO'])
    if request.GET.get('atrasadas') == '1':
        qs = qs.filter(prazo__lt=timezone.now()).exclude(status__in=['FINALIZADA','APROVADA','FATURADA','CANCELADA'])
    page = Paginator(qs, 20).get_page(request.GET.get('page'))
    return render(request, 'ordens/lista.html', {'ordens': page, 'page_obj': page, 'gestor': services.gestor(request.user), 'status_choices': Status.choices})


@login_required
@require_http_methods(['GET', 'POST'])
def criar(request):
    services.autorizar(request.user, administrativo=True)
    form = OrdemForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            ordem = services.criar(request.user, form)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect('ordens:detalhe', pk=ordem.pk)
    return render(request, 'ordens/form.html', {'form': form, 'titulo': 'Nova Ordem de Serviço'})


@login_required
def detalhe(request, pk):
    ordem = ordem_permitida(request, pk)
    assinaturas = ordem.assinaturas.select_related('conferencia').order_by('-ciclo')
    assinatura = assinaturas.filter(ciclo=ordem.ciclo).first()
    dados = assinatura.conferencia.dados if assinatura else services.snapshot(ordem, ordem.localizacoes.filter(ciclo=ordem.ciclo, evento='FINAL').last())
    return render(request, 'ordens/detalhe.html', {'ordem': ordem, 'dados': dados, 'assinatura': assinatura, 'assinaturas': assinaturas, 'gestor': services.gestor(request.user), 'foto_form': FotoForm(), 'reabrir_form': ReabrirForm()})


@login_required
@require_http_methods(['GET', 'POST'])
def editar(request, pk):
    ordem = ordem_permitida(request, pk)
    if ordem.status in ['FINALIZADA', 'APROVADA', 'FATURADA', 'CANCELADA']:
        return HttpResponseBadRequest('Reabra a OS antes de editar.')
    form = OrdemForm(instance=ordem, operacional=not services.gestor(request.user))
    if request.method == 'POST':
        try:
            ordem, form = services.editar(request.user, pk, request.POST)
        except ValidationError as exc:
            return erro(exc)
        if form is None:
            return redirect('ordens:detalhe', pk=pk)
    return render(request, 'ordens/form.html', {'form': form, 'titulo': f'Editar {ordem.numero}', 'ordem': ordem})


@login_required
@require_POST
def iniciar(request, pk):
    ordem_permitida(request, pk)
    form = GeoForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest(form.errors.as_json())
    try:
        services.iniciar(request.user, pk, form.cleaned_data)
    except ValidationError as exc:
        return erro(exc)
    return redirect('ordens:detalhe', pk=pk)


@login_required
@require_POST
def foto_adicionar(request, pk):
    ordem = ordem_permitida(request, pk)
    form = FotoForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, 'ordens/form.html', {'form': form, 'titulo': 'Adicionar foto', 'ordem': ordem}, status=400)
    try:
        services.adicionar_foto(request.user, pk, form.cleaned_data)
    except ValidationError as exc:
        return erro(exc)
    except OSError as exc:
        operation_failure('photo_upload_failed', exc)
        return HttpResponse('Armazenamento indisponível. Tente novamente.', status=503)
    return redirect('ordens:detalhe', pk=pk)


@login_required
def foto(request, pk, foto_id):
    ordem = ordem_permitida(request, pk)
    item = get_object_or_404(Foto, pk=foto_id, ordem=ordem)
    try:
        response = FileResponse(item.arquivo.open('rb'), content_type='image/jpeg')
    except OSError as exc:
        operation_failure('photo_download_failed', exc)
        return HttpResponse('Arquivo indisponível. Tente novamente.', status=503)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def mostrar_conferencia(request, conferencia, form=None, status=200):
    token = token_conferencia(conferencia)
    form = form or AssinaturaForm(initial={'token': token})
    return render(request, 'ordens/conferencia.html', {'ordem': conferencia.ordem, 'dados': conferencia.dados, 'form': form}, status=status)


@login_required
@require_POST
def preparar(request, pk):
    ordem_permitida(request, pk)
    form = GeoForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest(form.errors.as_json())
    try:
        conferencia = services.preparar(request.user, pk, form.cleaned_data)
    except ValidationError as exc:
        return erro(exc)
    return redirect('ordens:conferencia', pk=pk, token=token_conferencia(conferencia))


@login_required
def conferencia(request, pk, token):
    ordem = ordem_permitida(request, pk)
    try:
        cid = ler_token(token, request.user, ordem)
    except signing.BadSignature:
        return HttpResponseBadRequest('Conferência inválida ou expirada. Volte à OS e tente novamente.')
    item = get_object_or_404(Conferencia, pk=cid, ordem=ordem, usuario=request.user)
    if ordem.status != Status.EXECUCAO or item.revisao != ordem.revisao or item.ciclo != ordem.ciclo:
        return HttpResponseBadRequest('A OS mudou. Faça uma nova conferência.')
    return mostrar_conferencia(request, item)


@login_required
@require_POST
def finalizar(request, pk):
    ordem = ordem_permitida(request, pk)
    form = AssinaturaForm(request.POST)
    try:
        cid = ler_token(request.POST.get('token', ''), request.user, ordem)
    except (signing.BadSignature, KeyError, TypeError):
        return HttpResponseBadRequest('Conferência inválida ou expirada.')
    item = get_object_or_404(Conferencia, pk=cid, ordem=ordem, usuario=request.user)
    if not form.is_valid():
        return mostrar_conferencia(request, item, form, status=400)
    try:
        services.finalizar(request.user, pk, cid, form.cleaned_data)
    except ValidationError as exc:
        return erro(exc)
    return redirect('ordens:detalhe', pk=pk)


@login_required
@require_POST
def reabrir(request, pk):
    ordem = ordem_permitida(request, pk)
    services.autorizar(request.user, ordem, administrativo=True)
    form = ReabrirForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest(form.errors.as_json())
    try:
        services.reabrir(request.user, pk, form.cleaned_data['justificativa'])
    except ValidationError as exc:
        return erro(exc)
    return redirect('ordens:detalhe', pk=pk)


@login_required
def assinatura_imagem(request, pk, assinatura_id):
    ordem = ordem_permitida(request, pk)
    assinatura = get_object_or_404(Assinatura, pk=assinatura_id, ordem=ordem)
    response = HttpResponse(base64.b64decode(assinatura.imagem), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def pdf(request, pk, assinatura_id):
    from .reports import gerar_pdf
    ordem = ordem_permitida(request, pk)
    assinatura = get_object_or_404(Assinatura.objects.select_related('conferencia'), pk=assinatura_id, ordem=ordem)
    try:
        conteudo = gerar_pdf(assinatura)
    except (ValidationError, OSError) as exc:
        operation_failure('pdf_generation_failed', exc)
        return HttpResponse('Não foi possível gerar o comprovante: verifique a integridade e a disponibilidade dos arquivos.', status=409)
    response = HttpResponse(conteudo, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{ordem.numero}-v{assinatura.ciclo}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    return response
