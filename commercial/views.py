from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.templatetags.static import static
from django.views.decorators.http import require_http_methods, require_GET
from .catalog import FEATURES, money
from .models import PlanoComercial
from .forms import InteresseForm
from .services import form_token, register_interest


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
        public_features=[(FEATURES[key][0],plan.recursos[key]) for key in FEATURES if key in plan.recursos and plan.recursos[key]!='FUTURO']
        cards.append({'plan':plan,'price':money(value) if value is not None else '',
                      'period':'ano' if effective_period=='ANUAL' else 'mês',
                      'cta':reverse('commercial:demo')+f'?plano={plan.slug}&periodo={effective_period}',
                      'features':public_features,'preview_features':public_features[:3],
                      'annual_pending':not offered})
    rows=[{'label':label,'values':[{'value':('Incluído' if item['plan'].recursos.get(key)=='INCLUIDO' else 'A definir na proposta')} for item in cards]} for key,(label,_,_) in FEATURES.items() if key not in ['erp','assistencia']]
    for key,label in reversed([('limite_usuarios','Usuários'),('limite_tecnicos','Técnicos')]):
        rows.insert(0,{'label':label,'values':[{'value':getattr(item['plan'],key) if getattr(item['plan'],key) is not None else 'A definir na proposta'} for item in cards]})
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
