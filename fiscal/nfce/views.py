"""Private, tenant-scoped local readiness and NFC-e laboratory. No PDV UI edits."""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError,ObjectDoesNotExist,PermissionDenied
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
    from platform_core.access import effective_role
    try:
        preparation.authorize(request.user)
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))
    except ValidationError:
        if not request.user.is_authenticated or (effective_role(request.user) not in ('ADMIN', 'GESTOR') and not request.user.is_staff):
            return HttpResponseForbidden('Configuração restrita ao ADMIN desta organização.')

    # Se uma rota de proposta for solicitada, redireciona para a configuração operacional da organização
    if pk is not None:
        return redirect('operacao:fiscal_configuracao')

    # Visão Executiva Operacional do Tenant (/fiscal/configuracao/)
    from django.contrib import messages
    from django.utils import timezone
    org = current_organization()
    if not org and request.user.is_authenticated:
        from platform_core.models import OrganizationMembership
        membership = OrganizationMembership.objects.filter(user=request.user).first()
        if membership:
            org = membership.organization

    empresa = None
    if org:
        empresa, _ = ConfiguracaoEmpresa.objects.get_or_create(organization=org)

    filial = FilialEmpresa.objects.filter(organization=org, ativo=True).first() if org else None
    if org and not filial:
        filial, _ = FilialEmpresa.objects.get_or_create(
            organization=org,
            defaults={'nome': org.razao_social or org.nome_fantasia or 'Matriz', 'cnpj': org.cnpj or '', 'ativo': True}
        )

    nfce_params = (empresa.retencoes_informativas or {}).get('nfce', {}) if empresa else {}
    is_tecnolmed = org and ('tecnolmed' in (org.razao_social or '').lower() or '39966868' in (org.cnpj or ''))

    # Se for POST de atualização fiscal operacional
    if request.method == 'POST':
        csc_id = request.POST.get('csc_id', '').strip()
        csc_token = request.POST.get('csc_token', '').strip()
        ambiente = request.POST.get('ambiente', 'PRODUCAO').strip()
        serie = request.POST.get('serie', '1').strip() or '1'
        try:
            proximo_numero = max(1, int(request.POST.get('proximo_numero', '1')))
        except (ValueError, TypeError):
            proximo_numero = 1

        inscricao_estadual = request.POST.get('inscricao_estadual', '').strip()
        inscricao_municipal = request.POST.get('inscricao_municipal', '').strip()
        crt = request.POST.get('crt', '1').strip()
        natureza_operacao = request.POST.get('natureza_operacao', 'Venda a Consumidor Final').strip()

        cert_file = request.FILES.get('certificado')
        cert_password = request.POST.get('certificado_senha', '').strip()

        cert_info = nfce_params.get('certificado', {})
        if cert_file:
            import os
            pfx_bytes = cert_file.read()
            valid_until = None
            subject_cn = None
            cert_msg = "Certificado A1 carregado com sucesso"
            cert_dir = os.path.join(settings.BASE_DIR, 'private', 'certificates')
            os.makedirs(cert_dir, exist_ok=True)
            cert_path = os.path.join(cert_dir, f"cert_org_{org.pk}.pfx")
            cert_pem_path = os.path.join(cert_dir, f"cert_org_{org.pk}.pem")
            key_pem_path = os.path.join(cert_dir, f"key_org_{org.pk}.pem")
            with open(cert_path, 'wb') as cf:
                cf.write(pfx_bytes)

            try:
                from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
                p12 = pkcs12.load_key_and_certificates(pfx_bytes, cert_password.encode('utf-8') if cert_password else None)
                if p12 and p12.certificate:
                    valid_until = p12.certificate.not_valid_after_utc.strftime('%d/%m/%Y')
                    subject_cn = p12.certificate.subject.rfc4514_string()
                    cert_msg = f"Certificado A1 válido até {valid_until}"
                    with open(cert_pem_path, 'wb') as cp:
                        cp.write(p12.certificate.public_bytes(Encoding.PEM))
                    if p12.key:
                        with open(key_pem_path, 'wb') as kp:
                            kp.write(p12.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            except Exception as e:
                cert_msg = f"Certificado salvo (aviso senha: {str(e)[:40]})"

            cert_info = {
                'filename': cert_file.name,
                'path': cert_path,
                'cert_pem': cert_pem_path if valid_until else None,
                'key_pem': key_pem_path if valid_until else None,
                'valido_ate': valid_until,
                'subject': subject_cn,
                'status': cert_msg,
                'atualizado_em': timezone.now().strftime('%d/%m/%Y %H:%M')
            }

        if empresa:
            empresa.inscricao_estadual = inscricao_estadual
            empresa.inscricao_municipal = inscricao_municipal
            empresa.crt = crt
            empresa.natureza_operacao = natureza_operacao
            ret = empresa.retencoes_informativas or {}
            cfg = {
                'csc_id': csc_id,
                'csc_token': csc_token,
                'ambiente': ambiente,
                'serie': serie,
                'proximo_numero': proximo_numero,
                'natureza_operacao': natureza_operacao,
                'certificado': cert_info,
                'atualizado_em': timezone.now().strftime('%d/%m/%Y %H:%M')
            }
            ret['nfce'] = cfg
            ret['nfce_config'] = cfg
            empresa.retencoes_informativas = ret
            empresa.save()

        if filial:
            s_obj, _ = m.SerieFiscal.objects.get_or_create(
                estabelecimento=filial,
                tipo='NFCE',
                ambiente=ambiente,
                serie=serie,
                defaults={'proximo_numero': proximo_numero}
            )
            if s_obj.proximo_numero != proximo_numero:
                s_obj.proximo_numero = proximo_numero
                s_obj.save()

        messages.success(request, 'Configurações fiscais e Token CSC da NFC-e salvos com sucesso!')
        return redirect('operacao:fiscal_configuracao')

    # Dados consolidados para o formulário
    csc_id = nfce_params.get('csc_id') or ('2' if is_tecnolmed else '')
    csc_token = nfce_params.get('csc_token') or ('E79E83BB-4358-4A48-890D-46F971423857' if is_tecnolmed else '')
    ambiente = nfce_params.get('ambiente') or 'PRODUCAO'
    serie = nfce_params.get('serie') or '1'
    proximo_numero = nfce_params.get('proximo_numero') or 1
    ie = empresa.inscricao_estadual if empresa and empresa.inscricao_estadual else ('271732954' if is_tecnolmed else '')
    im = empresa.inscricao_municipal if empresa and empresa.inscricao_municipal else ('1000387' if is_tecnolmed else '')
    crt = empresa.crt if empresa and empresa.crt else '1'
    natureza_operacao = empresa.natureza_operacao if empresa and empresa.natureza_operacao else 'Venda a Consumidor Final'
    
    cert_a1 = (empresa.retencoes_informativas or {}).get('certificado_a1') if empresa else None
    cert_info = nfce_params.get('certificado', {})
    if cert_a1 and not cert_info.get('status'):
        cert_info = {
            'status': f"Certificado A1 Ativo (Válido até {cert_a1.get('valido_ate')})",
            'subject': cert_a1.get('titular') or cert_a1.get('emissor'),
            'filename': cert_a1.get('nome_arquivo'),
            'valido_ate': cert_a1.get('valido_ate')
        }

    return render(request, 'fiscal/nfce/configuration.html', {
        'config': None,
        'org': org,
        'empresa': empresa,
        'filial': filial,
        'csc_id': csc_id,
        'csc_token': csc_token,
        'ambiente': ambiente,
        'serie': serie,
        'proximo_numero': proximo_numero,
        'inscricao_estadual': ie,
        'inscricao_municipal': im,
        'crt': crt,
        'natureza_operacao': natureza_operacao,
        'cert_info': cert_info,
        'is_tecnolmed': is_tecnolmed,
    })


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
