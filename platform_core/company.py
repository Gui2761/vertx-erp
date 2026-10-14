"""Company metadata and explicit audited module/capability configuration."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .forms import TenantModelForm
from .models import ConfiguracaoEmpresa, FilialEmpresa, Organization, ModuloOrganizacao, OrganizationMembership, PermissaoMembership
from .modules import CAPABILITIES, require_capability
from .context import current_organization

class EmpresaForm(TenantModelForm):
    class Meta:
        model = ConfiguracaoEmpresa
        # Commercial plan and quotas are platform-controlled SaaS entitlements.
        # Tenant administrators cannot raise them through the company settings API.
        fields = ['inscricao_estadual', 'inscricao_municipal', 'regime_tributario', 'crt', 'natureza_operacao', 'codigo_servico', 'iss_informativo', 'retencoes_informativas']

class FilialForm(TenantModelForm):
    class Meta:
        model = FilialEmpresa
        fields = ['codigo', 'nome', 'cnpj', 'endereco', 'inscricao_estadual', 'inscricao_municipal', 'ativo']

class PermissaoForm(TenantModelForm):
    capacidade = forms.ChoiceField(choices=[(key,key.replace('_',' ').capitalize()) for key in CAPABILITIES])
    class Meta:
        model = PermissaoMembership
        fields = ['membership', 'capacidade', 'permitido']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['membership'].queryset = OrganizationMembership.objects.filter(organization=current_organization(), status='ATIVO').select_related('user', 'organization')

class ModulosForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        existing = dict(ModuloOrganizacao.objects.values_list('codigo','habilitado'))
        for code,label in ModuloOrganizacao._meta.get_field('codigo').choices:
            self.fields[code] = forms.BooleanField(label=label,required=False,initial=existing.get(code,True))

@login_required
def configuration(request, kind='empresa', public_id=None):
    require_capability(request.user, 'config_empresa')
    from gestao.services import audit
    classes = {'empresa':(EmpresaForm, ConfiguracaoEmpresa, 'Empresa — dados fiscais e plano informativo'), 'filial':(FilialForm, FilialEmpresa, 'Filial da empresa'), 'permissao':(PermissaoForm, PermissaoMembership, 'Permissão por vínculo'), 'modulos':(ModulosForm, ModuloOrganizacao, 'Módulos da organização')}
    cls, model, title = classes[kind]
    if kind == 'empresa':
        instance = model.objects.first() or model()
    elif public_id:
        instance = get_object_or_404(model,public_id=public_id)
    else:
        instance = model()
    if kind == 'permissao' and request.method == 'POST':
        member = request.POST.get('membership', '')
        if member.isdigit():
            instance = model.objects.filter(membership_id=int(member), capacidade=request.POST.get('capacidade', '')).first() or instance
    before_values = {name: getattr(instance, name) for name in cls._meta.fields if name != 'membership'} if kind != 'modulos' else {}
    form = cls(request.POST or None, **({'instance':instance} if kind!='modulos' else {}))
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=current_organization().pk)
                if kind=='modulos':
                    before = dict(model.objects.values_list('codigo','habilitado'))
                    for code,enabled in form.cleaned_data.items():
                        row = model.objects.filter(codigo=code).first() or model(codigo=code)
                        row.habilitado=enabled; row.save()
                    audit(request.user,'MODULOS_CONFIGURADOS',current_organization(),{'antes':before,'depois':form.cleaned_data})
                else:
                    if kind == 'filial' and not instance.pk:
                        from .saas_services import verificar_limite
                        verificar_limite(current_organization(), 'filiais')
                    if kind=='permissao':
                        prior=model.objects.filter(membership=form.cleaned_data['membership'],capacidade=form.cleaned_data['capacidade']).first()
                        if prior:
                            prior.permitido=form.cleaned_data['permitido']; prior.save(); instance=prior
                        else:
                            instance=form.save()
                    else:
                        instance=form.save()
                    audit(request.user,'CONFIGURACAO_EMPRESA',instance,{'tipo':kind,'antes':{key:str(value) for key,value in before_values.items()},'depois':{key:str(getattr(instance,key)) for key in before_values},'membership':getattr(instance,'membership_id',None)})
        except ValidationError as exc:
            form.add_error(None,'; '.join(exc.messages))
        else:
            return redirect('platform_core:empresa')
    return render(request,'platform_core/company.html',{'titulo':title,'form':form,'filiais':FilialEmpresa.objects.all(),'back_url':reverse('platform_core:home')},status=400 if request.method=='POST' else 200)
