from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
import uuid

from platform_core.context import current_organization
from platform_core.models import OrganizationMembership

from .forms import AcessoRHForm, ServidorForm
from .models import (
    AcessoRH, AfastamentoServidor, CargoMunicipal, DepartamentoMunicipal, FuncaoMunicipal,
    FeriasServidor, Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal, VinculoFuncional,
)
from .forms import DecisaoSolicitacaoForm, EstruturaMunicipalForm, JornadaMunicipalForm, SolicitacaoServidorForm
from .services import ADMIN_ROLES, MANAGE_ROLES, create_request, create_server, decide_request, grant_access, mark_point, require_roles, roles_for, audit


def _base_context(request, **extra):
    return {'organization': current_organization(), 'roles': roles_for(request.user), **extra}


@login_required
def home(request):
    roles = roles_for(request.user)
    if AcessoRH.Papel.SERVIDOR in roles and not roles.intersection(MANAGE_ROLES):
        return redirect('rh_municipal:portal')
    require_roles(request.user, MANAGE_ROLES | {AcessoRH.Papel.CHEFIA})
    return render(request, 'rh_municipal/home.html', _base_context(request, totals={
        'servidores': Servidor.objects.filter(ativo=True).count(),
        'secretarias': Secretaria.objects.filter(ativo=True).count(),
        'departamentos': DepartamentoMunicipal.objects.filter(ativo=True).count(),
        'unidades': UnidadeMunicipal.objects.filter(ativo=True).count(),
        'ferias_pendentes': FeriasServidor.objects.filter(status='SOLICITADA').count(),
        'afastamentos_pendentes': AfastamentoServidor.objects.filter(status='SOLICITADO').count(),
    }))


@login_required
@require_http_methods(['GET', 'POST'])
def servidores(request):
    require_roles(request.user, MANAGE_ROLES)
    form = ServidorForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            try:
                row = create_server(request.user, form)
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
            else:
                messages.success(request, 'Servidor cadastrado no RH Municipal.')
                return redirect('rh_municipal:servidor', public_id=row.public_id)
    rows = Servidor.objects.select_related('secretaria', 'departamento', 'setor', 'unidade', 'cargo', 'vinculo').order_by('nome')[:200]
    return render(request, 'rh_municipal/servidores.html', _base_context(request, rows=rows, form=form))


@login_required
def servidor(request, public_id):
    member, roles = require_roles(request.user, MANAGE_ROLES | {AcessoRH.Papel.SERVIDOR})
    row = get_object_or_404(Servidor.objects.select_related(
        'secretaria', 'departamento', 'setor', 'unidade', 'cargo', 'funcao', 'vinculo', 'jornada',
    ), public_id=public_id)
    if AcessoRH.Papel.SERVIDOR in roles and not roles.intersection(MANAGE_ROLES) and row.usuario_id != request.user.pk:
        raise PermissionDenied('Servidor só pode acessar a própria ficha.')
    return render(request, 'rh_municipal/servidor.html', _base_context(request, row=row, history=row.historico.order_by('-criado_em')[:50]))


@login_required
def estrutura(request):
    require_roles(request.user, MANAGE_ROLES | {AcessoRH.Papel.CHEFIA})
    return render(request, 'rh_municipal/estrutura.html', _base_context(request,
        secretarias=Secretaria.objects.prefetch_related('departamentos__setores__unidades'),
        cargos=CargoMunicipal.objects.filter(ativo=True),
        kinds=[('secretaria','Secretaria'),('departamento','Departamento'),('setor','Setor'),('unidade','Unidade'),('cargo','Cargo'),('funcao','Função'),('vinculo','Vínculo')],
    ))


ESTRUTURA_MODELS = {
    'secretaria': Secretaria,
    'departamento': DepartamentoMunicipal,
    'setor': SetorMunicipal,
    'unidade': UnidadeMunicipal,
    'cargo': CargoMunicipal,
    'funcao': FuncaoMunicipal,
    'vinculo': VinculoFuncional,
}


@login_required
@require_http_methods(['GET', 'POST'])
def estrutura_novo(request, kind):
    require_roles(request.user, MANAGE_ROLES)
    model = ESTRUTURA_MODELS.get(kind)
    if model is None:
        from django.http import Http404
        raise Http404
    form = EstruturaMunicipalForm(request.POST or None, kind=kind)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        kwargs = {'organization': current_organization(), 'codigo': data['codigo'], 'nome': data['nome'], 'descricao': data['descricao']}
        if kind == 'departamento': kwargs['secretaria'] = data['secretaria']
        elif kind == 'setor': kwargs['departamento'] = data['departamento']
        elif kind == 'unidade': kwargs['setor'] = data['setor']
        elif kind == 'cargo': kwargs['carga_horaria_semanal'] = data.get('carga_horaria_semanal')
        try:
            row = model(**kwargs)
            row.save()
            audit(request.user, 'RH_MUNICIPAL_ESTRUTURA_CRIADA', row, {'tipo': kind, 'codigo': row.codigo})
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            messages.success(request, 'Item da estrutura municipal cadastrado.')
            return redirect('rh_municipal:estrutura')
    return render(request, 'rh_municipal/estrutura_form.html', _base_context(request, form=form, kind=kind))


@login_required
@require_http_methods(['GET', 'POST'])
def jornada_nova(request):
    require_roles(request.user, MANAGE_ROLES)
    form = JornadaMunicipalForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        row = form.save(commit=False)
        try:
            row.save()
            audit(request.user, 'RH_MUNICIPAL_JORNADA_CRIADA', row, {'nome': row.nome})
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            messages.success(request, 'Jornada municipal cadastrada como parâmetro informativo.')
            return redirect('rh_municipal:estrutura')
    return render(request, 'rh_municipal/jornada_form.html', _base_context(request, form=form))


@login_required
@require_http_methods(['GET', 'POST'])
def acessos(request):
    require_roles(request.user, ADMIN_ROLES)
    form = AcessoRHForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            grant_access(request.user, form.cleaned_data['membership'], form.cleaned_data['papel'])
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
        else:
            messages.success(request, 'Papel municipal atribuído e auditado.')
            return redirect('rh_municipal:acessos')
    rows = AcessoRH.objects.select_related('membership__user').order_by('membership__user__username', 'papel')
    return render(request, 'rh_municipal/acessos.html', _base_context(request, form=form, rows=rows))


@login_required
@require_http_methods(['GET', 'POST'])
def solicitacoes(request):
    require_roles(request.user, MANAGE_ROLES)
    form = DecisaoSolicitacaoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            decide_request(request.user, form.cleaned_data['public_id'], form.cleaned_data['aprovada'], form.cleaned_data['motivo'])
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
        else:
            messages.success(request, 'Decisão registrada no histórico municipal.')
            return redirect('rh_municipal:solicitacoes')
    from .models import SolicitacaoServidor
    rows = SolicitacaoServidor.objects.select_related('servidor', 'decisao').order_by('-criado_em')[:200]
    return render(request, 'rh_municipal/solicitacoes.html', _base_context(request, form=form, rows=rows))


@login_required
def portal(request):
    require_roles(request.user, {AcessoRH.Papel.SERVIDOR})
    row = get_object_or_404(Servidor.objects.select_related('secretaria', 'departamento', 'unidade', 'cargo'), usuario=request.user)
    form = SolicitacaoServidorForm(request.POST or None)
    if request.method == 'POST':
        try:
            if request.POST.get('acao') == 'ponto':
                mark_point(request.user, request.POST.get('tipo', ''), request.POST.get('request_id', ''))
                messages.success(request, 'Marcação de ponto registrada e auditada.')
            elif request.POST.get('acao') == 'solicitacao' and form.is_valid():
                create_request(request.user, form.cleaned_data['tipo'], form.cleaned_data['descricao'], request_id=request.POST.get('request_id'))
                messages.success(request, 'Solicitação enviada para análise municipal.')
            else:
                raise ValidationError('Ação inválida ou formulário incompleto.')
            return redirect('rh_municipal:portal')
        except (ValidationError, PermissionDenied, ValueError) as exc:
            messages.error(request, '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))
    return render(request, 'rh_municipal/portal.html', _base_context(request, row=row,
        ferias=row.ferias.order_by('-inicio')[:20], afastamentos=row.afastamentos.order_by('-inicio')[:20],
        solicitacoes=row.solicitacoes.select_related('decisao').order_by('-criado_em')[:20],
        pontos=row.marcacoes_ponto.order_by('-data_hora')[:30], form=form,
        request_id=uuid.uuid4(), punches=[
            ('ENTRADA', 'Entrada', uuid.uuid4()), ('SAIDA_INTERVALO', 'Iniciar intervalo', uuid.uuid4()),
            ('RETORNO_INTERVALO', 'Retornar do intervalo', uuid.uuid4()), ('SAIDA', 'Saída', uuid.uuid4()),
        ]))
