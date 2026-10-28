from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.templatetags.static import static
from django.views.decorators.http import require_http_methods, require_GET
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from .catalog import FEATURES, money
from .models import PlanoComercial
from .forms import InteresseForm
from .services import form_token, register_interest
from platform_core.saas_forms import AdminInicialForm, DadosEmpresaForm
from platform_core.saas_models import PlanoSaaS, PrimeiroAcessoSaaS
from platform_core.saas_services import criar_cliente


def page(request,template,context=None,status=200):
    data={'canonical':request.build_absolute_uri(request.path),
          'social_image':request.build_absolute_uri(static('commercial/erp-preview.jpg'))}
    data.update(context or {})
    response=render(request,template,data,status=status)
    response['Cache-Control']='no-store'
    response['Referrer-Policy']='strict-origin-when-cross-origin'
    return response


def catalog(period):
    plans=list(PlanoComercial.objects.filter(ativo=True))
    annual_available=any(plan.valor_anual is not None for plan in plans)
    period='ANUAL' if period=='ANUAL' and annual_available else 'MENSAL'
    cards=[]
    for plan in plans:
        effective_period='ANUAL' if plan.periodicidade=='ANUAL' else period
        value=plan.valor_anual if effective_period=='ANUAL' else plan.preco
        offered=effective_period=='MENSAL' or plan.valor_anual is not None
        saas_plan=PlanoSaaS.objects.filter(
            plano_comercial=plan,ativo=True,publico_ativo=True,periodicidade=effective_period,
        ).first()
        if saas_plan and saas_plan.preco != value:
            saas_plan=None
        contracting_available=bool(saas_plan and value is not None)
        public_features=[(FEATURES[key][0],plan.recursos[key]) for key in FEATURES
                          if key != 'erp' and key in plan.recursos and plan.recursos[key]!='FUTURO']
        cards.append({'plan':plan,'price':money(value) if value is not None else '',
                      'period':'ano' if effective_period=='ANUAL' else 'mês',
                      'cta':(reverse('commercial:signup')+f'?plano={plan.slug}&periodo={effective_period}'
                             if contracting_available else reverse('commercial:demo')+f'?plano={plan.slug}&periodo={effective_period}'),
                      'contracting_available':contracting_available,
                      'period_code':effective_period,
                      'limit_users':saas_plan.limites.get('usuarios') if saas_plan else None,
                      'limit_branches':saas_plan.limites.get('filiais') if saas_plan else None,
                      'features':public_features,'preview_features':public_features[:3],
                      'annual_pending':not offered})
    state_labels={'INCLUIDO':'Incluído','NAO_INCLUIDO':'Não incluído',
                  'CONSULTA':'A definir na proposta','FUTURO':'Fora do escopo desta oferta'}
    rows=[{'label':label,'values':[{'value':state_labels.get(item['plan'].recursos.get(key,'CONSULTA'),'A definir na proposta')} for item in cards]} for key,(label,_,_) in FEATURES.items() if key not in ['erp','assistencia']]
    # Publish only quotas that are actually configured in the SaaS plan.
    # Legacy commercial fields remain authoritative only for technician caps;
    # users and branches come from the same plan that governs enforcement.
    for label, key in [('Filiais', 'limit_branches'), ('Usuários', 'limit_users')]:
        rows.insert(0, {'label': label, 'values': [
            {'value': item[key] if item[key] is not None else 'A definir na proposta'}
            for item in cards
        ]})
    rows.insert(2, {'label': 'Técnicos', 'values': [
        {'value': item['plan'].limite_tecnicos if item['plan'].limite_tecnicos is not None else 'A definir na proposta'}
        for item in cards
    ]})
    return {'plans':cards,'comparison':rows,'period':period,'annual_available':annual_available,
            'features':[{'key':key,'name':label,'description':description,'icon':icon} for key,(label,description,icon) in FEATURES.items()]}


@require_GET
def home(request):
    if request.user.is_authenticated:
        return redirect('platform_core:home')
    return page(request,'commercial/home.html',catalog(request.GET.get('periodo')))


@require_GET
def pricing(request):
    return page(request,'commercial/pricing.html',{**catalog(request.GET.get('periodo')),'pricing_page':True})


def _signup_plan(slug, period):
    """Resolve a public offer only when its separately configured SaaS plan exists."""
    if period not in (PlanoSaaS.Period.MONTH, PlanoSaaS.Period.YEAR):
        return None
    commercial=PlanoComercial.objects.filter(slug=slug,ativo=True).first()
    if not commercial:
        return None
    price=commercial.valor_anual if period==PlanoSaaS.Period.YEAR else commercial.preco
    if price is None:
        return None
    configured=PlanoSaaS.objects.filter(
        plano_comercial=commercial,periodicidade=period,ativo=True,publico_ativo=True,
    ).first()
    return configured if configured and configured.preco==price else None


@require_http_methods(['GET','POST'])
def signup(request):
    if request.user.is_authenticated:
        return redirect('platform_core:home')
    slug=(request.POST.get('plano') if request.method=='POST' else request.GET.get('plano','')).strip()
    period=(request.POST.get('periodo') if request.method=='POST' else request.GET.get('periodo','MENSAL')).strip().upper()
    plan=_signup_plan(slug,period)
    if plan is None:
        return page(request,'commercial/signup_unavailable.html',status=409)
    company=DadosEmpresaForm(request.POST or None)
    admin=AdminInicialForm(request.POST or None,prefix='admin')
    error=''
    if request.method=='POST' and company.is_valid() and admin.is_valid():
        try:
            result=criar_cliente(actor=None,company=company.cleaned_data,
                                 admin=admin.cleaned_data,plan_id=plan.pk)
        except (ValidationError,IntegrityError) as exc:
            if isinstance(exc,ValidationError):
                error='; '.join(exc.messages)
            else:
                error='Não foi possível concluir o cadastro. Confira se o CNPJ e o e-mail já estão em uso.'
        else:
            request.session['public_saas_pending_access']={
                'token':result['token'],'token_id':result['token_id'],
                'organization_id':result['organization'].pk,
                'user_id':result['user'].pk,'created_at':timezone.now().timestamp(),
            }
            return redirect('commercial:signup_confirmation')
    context={'plan':plan,'period':period,'company_form':company,'admin_form':admin,'signup_error':error}
    response=page(request,'commercial/signup.html',context,status=400 if request.method=='POST' else 200)
    response['Cache-Control']='private, no-store'
    return response


@require_GET
def signup_confirmation(request):
    pending=request.session.get('public_saas_pending_access')
    if not pending or timezone.now().timestamp()-pending.get('created_at',0)>=1200:
        request.session.pop('public_saas_pending_access',None)
        return redirect('commercial:pricing')
    row=PrimeiroAcessoSaaS.objects.filter(
        pk=pending.get('token_id'),organization_id=pending.get('organization_id'),
        user_id=pending.get('user_id'),usado_em__isnull=True,expira_em__gt=timezone.now(),
    ).select_related('organization','user').first()
    if not row:
        request.session.pop('public_saas_pending_access',None)
        return redirect('commercial:pricing')
    first_access_url=request.build_absolute_uri(reverse('platform_core:saas_first_access',args=[pending['token']]))
    response=page(request,'commercial/signup_confirmation.html',{
        'organization':row.organization,'admin_user':row.user,'first_access_url':first_access_url,
        'expires_at':row.expira_em,
    })
    response['Cache-Control']='private, no-store'
    response['Referrer-Policy']='no-referrer'
    return response


@require_GET
def signup_first_access(request):
    pending=request.session.get('public_saas_pending_access')
    if not pending or timezone.now().timestamp()-pending.get('created_at',0)>=1200:
        request.session.pop('public_saas_pending_access',None)
        return redirect('commercial:pricing')
    row=PrimeiroAcessoSaaS.objects.filter(
        pk=pending.get('token_id'),organization_id=pending.get('organization_id'),
        user_id=pending.get('user_id'),usado_em__isnull=True,expira_em__gt=timezone.now(),
    ).first()
    if not row:
        request.session.pop('public_saas_pending_access',None)
        return redirect('commercial:pricing')
    response=redirect('platform_core:saas_first_access',token=pending['token'])
    response['Cache-Control']='private, no-store'
    response['Referrer-Policy']='no-referrer'
    return response


@require_http_methods(['GET','POST'])
def demo(request):
    selected=request.GET.get('plano')
    initial={'periodicidade':request.GET.get('periodo','MENSAL'),'objetivo':request.GET.get('assunto','INTEGRADA')}
    if request.method=='GET':
        if selected:
            initial['plano']=get_object_or_404(PlanoComercial,slug=selected,ativo=True)
        initial['token']=form_token(request)
    form=InteresseForm(request.POST if request.method=='POST' else None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            register_interest(request,form)
        except (ValidationError,IntegrityError,PlanoComercial.DoesNotExist) as exc:
            message='Solicitação em processamento. Recarregue e tente novamente.' if not isinstance(exc,ValidationError) else '; '.join(exc.messages)
            form.add_error(None,message)
        else:
            request.session['commercial_received']=True
            return redirect('commercial:thanks')
    return page(request,'commercial/demo.html',{'form':form},status=400 if request.method=='POST' else 200)


@require_GET
def thanks(request):
    # Deliberately generic: no lead lookup or public personal information.
    if not request.session.get('commercial_received'):
        return redirect('commercial:demo')
    return page(request,'commercial/thanks.html')


@require_GET
def information(request,kind):
    return page(request,'commercial/information.html',{'kind':kind})


@require_GET
def robots(request):
    paths=['/vertyx/','/contas/','/admin/','/ordens/','/clientes/','/equipamentos/','/tecnico/','/pdv/','/financeiro/','/documentos/','/demonstracao/','/solicitacao-recebida/']
    return HttpResponse('User-agent: *\nAllow: /\n'+''.join('Disallow: '+path+'\n' for path in paths),content_type='text/plain')
