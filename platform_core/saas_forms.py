from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .models import Organization, ModuloOrganizacao
from .saas_models import MODULES, PlanoSaaS
from .validators import normalize_cnpj, validate_cnpj


class DadosEmpresaForm(forms.Form):
    razao_social = forms.CharField(label='Razão social', max_length=255)
    nome_fantasia = forms.CharField(label='Nome fantasia', max_length=150, required=False)
    cnpj = forms.CharField(label='CNPJ', max_length=18, validators=[validate_cnpj])
    email = forms.EmailField(label='E-mail da empresa')
    telefone = forms.CharField(label='Telefone / WhatsApp', max_length=30)
    endereco = forms.CharField(label='Endereço', max_length=255)
    cidade = forms.CharField(label='Cidade', max_length=100)
    uf = forms.CharField(label='UF', max_length=2, min_length=2)

    def clean_cnpj(self):
        value = normalize_cnpj(self.cleaned_data['cnpj'])
        if Organization.objects.filter(cnpj=value).exists():
            raise ValidationError('Já existe uma organização com este CNPJ.')
        return value

    def clean_uf(self):
        return self.cleaned_data['uf'].strip().upper()


class AdminInicialForm(forms.Form):
    nome = forms.CharField(label='Nome do administrador', max_length=150)
    email = forms.EmailField(label='E-mail de acesso')
    whatsapp = forms.CharField(label='WhatsApp do administrador', max_length=20)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().casefold()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise ValidationError('Este e-mail já possui uma conta. Use um e-mail exclusivo para o administrador inicial.')
        return email


class PlanoSaaSForm(forms.ModelForm):
    modulos = forms.MultipleChoiceField(
        label='Módulos incluídos', required=False,
        choices=[(value, label) for value, label in ModuloOrganizacao._meta.get_field('codigo').choices],
        widget=forms.CheckboxSelectMultiple,
    )
    limite_usuarios = forms.IntegerField(label='Limite de usuários', min_value=1, required=False, help_text='Deixe vazio para A definir.')
    limite_filiais = forms.IntegerField(label='Limite de filiais', min_value=0, required=False, help_text='Deixe vazio para A definir.')
    limite_armazenamento_mb = forms.IntegerField(label='Armazenamento (MB)', min_value=0, required=False, help_text='Deixe vazio para A definir.')
    limite_vendas_mes = forms.IntegerField(label='Vendas por mês', min_value=0, required=False, help_text='Considera vendas confirmadas/finalizadas no mês; vazio = A definir.')
    limite_ordens_mes = forms.IntegerField(label='Ordens de serviço por mês', min_value=0, required=False, help_text='Considera OS formalizadas no mês, inclusive canceladas; vazio = A definir.')

    class Meta:
        model = PlanoSaaS
        fields = ['slug', 'nome', 'descricao', 'preco', 'periodicidade', 'ativo']
        widgets = {'descricao': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['modulos'] = self.instance.modulos
            for key in ('usuarios', 'filiais', 'armazenamento_mb', 'vendas_mes', 'ordens_mes'):
                self.initial[f'limite_{key}'] = self.instance.limites.get(key)

    def clean_slug(self):
        return slugify(self.cleaned_data['slug'])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('limite_usuarios') == 0:
            self.add_error('limite_usuarios', 'O plano precisa comportar pelo menos o administrador inicial.')
        if cleaned.get('modulos'):
            cleaned['modulos'] = list(dict.fromkeys(cleaned['modulos']))
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.modulos = list(self.cleaned_data.get('modulos', []))
        instance.limites = {
            'usuarios': self.cleaned_data.get('limite_usuarios'),
            'filiais': self.cleaned_data.get('limite_filiais'),
            'armazenamento_mb': self.cleaned_data.get('limite_armazenamento_mb'),
            'vendas_mes': self.cleaned_data.get('limite_vendas_mes'),
            'ordens_mes': self.cleaned_data.get('limite_ordens_mes'),
        }
        if commit:
            instance.save()
        return instance


class EditarClienteForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['razao_social', 'nome_fantasia', 'cnpj', 'email', 'telefone', 'endereco', 'cidade', 'uf']


class AlterarPlanoForm(forms.Form):
    plano = forms.ModelChoiceField(label='Novo plano', queryset=PlanoSaaS.objects.none())
    motivo = forms.CharField(label='Motivo (opcional)', required=False, max_length=300, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plano'].queryset = PlanoSaaS.objects.filter(ativo=True)
