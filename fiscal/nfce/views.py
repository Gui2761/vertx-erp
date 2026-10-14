"""Private, tenant-scoped local readiness and NFC-e laboratory. No PDV UI edits."""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError,ObjectDoesNotExist
from django.http import Http404,HttpResponseBadRequest,HttpResponseForbidden
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from platform_core.modules import require_capability
from platform_core.models import ConfiguracaoEmpresa,FilialEmpresa
from platform_core.context import current_organization
from fiscal.views import check_fields
from operacao import models as m
from . import services as s,forms
from . import configuration as preparation


@login_required
@never_cache
def configuracao(request, pk=None):
    try:
        preparation.authorize(request.user)
    except ValidationError:
        return HttpResponseForbidden('Configuração desta etapa disponível somente no ambiente local de homologação.')
    proposals = m.ConfiguracaoFiscal.objects.exclude(proposta_documental={}).filter(tipo='NFCE', ambiente='HOMOLOGACAO').select_related('estabelecimento', 'configuracao_confirmada__estabelecimento')
    config = get_object_or_404(proposals, pk=pk) if pk is not None else proposals.order_by('-pk').first()
    if config is None:
        return render(request, 'fiscal/nfce/configuration.html', {'config': None})
    form = preparation.PreparacaoForm(request.POST if request.method == 'POST' else None, initial=preparation.initial(config))
    if request.method == 'POST':
        try:
            check_fields(request, [*form.fields, 'acao'])
            if request.POST.get('acao') not in ('salvar', 'confirmar'):
                raise ValidationError('Ação não permitida; emissão bloqueada nesta etapa.')
            if form.is_valid():
                payload = request.POST.dict()
                payload.pop('csrfmiddlewaretoken', None); payload.pop('acao', None)
                preparation.save_preparation(request.user, config.pk, payload, confirm=request.POST['acao'] == 'confirmar')
                from django.contrib import messages
                messages.success(request, 'Preparação salva com auditoria. Emissão permanece bloqueada.')
                return redirect('operacao:fiscal_configuracao_detalhe', pk=config.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    rows, product = preparation.readiness(config)
    fields = []
    if product:
        fields = [('Descrição', product.descricao), ('Código', product.sku), ('EAN/GTIN', product.gtin), ('NCM', product.ncm), ('CEST', product.cest), ('Unidade', product.unidade_medida), ('Origem', product.origem_fiscal), ('CFOP', product.cfop), ('CST/CSOSN', product.csosn or product.cst or product.cst_csosn)]
    return render(request, 'fiscal/nfce/configuration.html', {'config': config, 'form': form, 'checklist': rows,
        'sections': [(label, [form[name] for name in names]) for label, names in preparation.SECTIONS],
        'product_fields': fields, 'proposals': proposals, 'pending_count': sum(not done for _, done in rows),
        'responsavel_checklist': preparation.pendencias_responsavel(config, product)})


@login_required
@never_cache
def home(request):
    require_capability(request.user,'fiscal_consultar')
    org=current_organization();company=ConfiguracaoEmpresa.objects.first()
    state=[('CNPJ da organização',bool(org.cnpj)),('Razão social',bool(org.razao_social)),('Estabelecimento fiscal',FilialEmpresa.objects.exists()),('CRT',bool(company and company.crt)),('Regime tributário',bool(company and company.regime_tributario)),('Perfil de estabelecimento/SE',m.PerfilFiscalEstabelecimento.objects.filter(uf='SE').exists()),('Série NFC-e homologação',m.SerieFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO').exists()),('Configuração NFC-e homologação',m.ConfiguracaoNFCe.objects.exists())]
    proposals=m.ConfiguracaoFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO').exclude(proposta_documental={}).select_related('estabelecimento')
    return render(request,'fiscal/nfce/home.html',{'readiness':state,'proposals':proposals,'cadastros':forms.CADASTROS,'local_enabled':getattr(settings,'FISCAL_NFCE_LOCAL_ENABLED',False),
        'docs':m.DocumentoFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO',configuracao_fiscal__motor='NFCE_SVRS_HOM').order_by('-pk')})


@login_required
@never_cache
def cadastro(request,kind):
    if kind not in forms.CADASTROS:raise Http404()
    model,formclass=forms.CADASTROS[kind]
    require_capability(request.user,'fiscal_gerenciar_credenciais' if kind in ('referencia','vinculo') else 'fiscal_configurar')
    form=formclass(request.POST if request.method=='POST' else None)
    if request.method=='POST':
        try:
            check_fields(request,form.fields)
            if form.is_valid():
                values=dict(form.cleaned_data)
                if kind=='referencia':values['referencia']='cofre://'+str(values.pop('identificador'))
                s.cadastrar_local(request.user,model,**values)
                return redirect('operacao:nfce_home')
        except ValidationError as exc:form.add_error(None,exc)
    return render(request,'fiscal/nfce/form.html',{'form':form,'titulo':'Laboratório NFC-e: '+kind})


@login_required
@never_cache
def preparar(request):
    require_capability(request.user,'fiscal_emitir');form=forms.PrepararForm(request.POST if request.method=='POST' else None)
    if request.method=='POST':
        try:
            check_fields(request,form.fields)
            if form.is_valid():
                d=form.cleaned_data;doc=s.preparar(request.user,d['venda'].pk,d['configuracao'].pk,d['serie'].pk,d['credencial'].pk,d['regra'].pk)
                return redirect('operacao:nfce_detalhe',pk=doc.pk)
        except (ValidationError,ObjectDoesNotExist) as exc:
            form.add_error(None,exc if isinstance(exc,ValidationError) else 'Dados não pertencem à organização selecionada.')
    return render(request,'fiscal/nfce/form.html',{'form':form,'titulo':'Preparar NFC-e de venda finalizada'})


@login_required
@never_cache
def detalhe(request,pk):
    require_capability(request.user,'fiscal_consultar')
    doc=get_object_or_404(m.DocumentoFiscal,pk=pk,tipo='NFCE',ambiente='HOMOLOGACAO',configuracao_fiscal__motor='NFCE_SVRS_HOM')
    from .workflow import estado
    last=doc.solicitacoes_fiscais.order_by('-pk').first()
    return render(request,'fiscal/nfce/detail.html',{'doc':doc,'estado_operacional':estado(doc,last),'retorno_fiscal':s.resumo_retorno(request.user,last.pk) if last else None,'emitir_form':forms.SolicitarForm(),'cancelar_form':forms.CancelarForm(),
        'requests':doc.solicitacoes_fiscais.all(),'eventos':doc.eventos_fiscais.all(),'arquivos':m.Documento.objects.filter(fiscal=doc)})


@login_required
@never_cache
@require_POST
def solicitar(request,pk,operation):
    if operation not in ('EMITIR','CANCELAR'):raise Http404()
    require_capability(request.user,'fiscal_cancelar' if operation=='CANCELAR' else 'fiscal_emitir')
    doc=get_object_or_404(m.DocumentoFiscal,pk=pk,tipo='NFCE',ambiente='HOMOLOGACAO',configuracao_fiscal__motor='NFCE_SVRS_HOM')
    form=(forms.CancelarForm if operation=='CANCELAR' else forms.SolicitarForm)(request.POST)
    try:
        check_fields(request,form.fields)
        if not form.is_valid():return HttpResponseBadRequest('Solicitação inválida.')
        req=s.solicitar(request.user,doc.pk,form.cleaned_data['request_id'],operation,form.cleaned_data.get('motivo',''));s.processar(request.user,req.pk)
    except ValidationError as exc:return HttpResponseBadRequest('; '.join(exc.messages))
    return redirect('operacao:nfce_detalhe',pk=doc.pk)


@login_required
@never_cache
@require_POST
def reconciliar(request,pk):
    req=get_object_or_404(m.SolicitacaoFiscal,pk=pk,documento__ambiente='HOMOLOGACAO',documento__tipo='NFCE')
    require_capability(request.user,'fiscal_cancelar' if req.operacao=='CANCELAR' else 'fiscal_emitir')
    try:check_fields(request,[]);s.processar(request.user,req.pk)
    except ValidationError as exc:return HttpResponseBadRequest('; '.join(exc.messages))
    return redirect('operacao:nfce_detalhe',pk=req.documento_id)


@login_required
@never_cache
@require_POST
def danfe(request,pk):
    require_capability(request.user,'fiscal_consultar')
    get_object_or_404(m.DocumentoFiscal,pk=pk,tipo='NFCE',ambiente='HOMOLOGACAO',configuracao_fiscal__motor='NFCE_SVRS_HOM')
    from .danfe import gerar
    try:check_fields(request,[]);file=gerar(request.user,pk)
    except ValidationError as exc:return HttpResponseBadRequest('; '.join(exc.messages))
    return redirect('operacao:documento_arquivo',pk=file.pk)
