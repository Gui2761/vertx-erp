from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from platform_core.context import current_organization
from platform_core.models import MembershipERP, OrganizationMembership

from .models import (
    AcessoMunicipal, CargoMunicipal, DepartamentoMunicipal, FuncaoMunicipal,
    PerfilPrefeitura, Secretaria, SetorMunicipal, UnidadeMunicipal,
)
from .public_services import PUBLIC_PERMISSION_LABELS
from .public_services import accesses_for, has_municipal_permission, scoped_queryset
from .models import Servidor


class PerfilPrefeituraForm(forms.ModelForm):
    class Meta:
        model = PerfilPrefeitura
        fields = ('nome_institucional', 'codigo_ibge', 'ativo')
        widgets = {'nome_institucional': forms.TextInput(attrs={'placeholder': 'Nome oficial, se diferente do cadastro da organização'}),
                   'codigo_ibge': forms.TextInput(attrs={'inputmode': 'numeric', 'maxlength': 7})}


class EstruturaPublicaForm(forms.Form):
    codigo = forms.CharField(max_length=30, label='Código')
    nome = forms.CharField(max_length=150, label='Nome')
    descricao = forms.CharField(required=False, label='Descrição', widget=forms.Textarea(attrs={'rows': 3}))
    responsavel = forms.ModelChoiceField(queryset=Servidor.objects.none(), required=False, label='Responsável')
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False, label='Secretaria')
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False, label='Departamento')
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False, label='Setor')

    def __init__(self, *args, actor=None, kind='secretaria', **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.kind = kind
        self.fields['responsavel'].queryset = Servidor.objects.filter(organization=org, ativo=True).select_related('secretaria', 'departamento', 'unidade')
        self.fields['secretaria'].queryset = Secretaria.objects.filter(organization=org, ativo=True)
        self.fields['departamento'].queryset = DepartamentoMunicipal.objects.filter(organization=org, ativo=True)
        self.fields['setor'].queryset = SetorMunicipal.objects.filter(organization=org, ativo=True)
        for name in ('secretaria', 'departamento', 'setor', 'responsavel'):
            self.fields[name].widget.attrs.update({'class': 'gp-select'})
        self.fields['codigo'].widget.attrs.update({'placeholder': 'Ex.: SEC-ADM'})
        self.fields['nome'].widget.attrs.update({'placeholder': 'Nome da unidade organizacional'})
        self.fields['descricao'].widget.attrs.update({'placeholder': 'Descrição opcional'})
        if actor is not None:
            for name in ('secretaria', 'departamento', 'setor', 'responsavel'):
                self.fields[name].queryset = scoped_queryset(actor, self.fields[name].queryset)
        relevant = {
            'secretaria': ('responsavel',), 'departamento': ('secretaria', 'responsavel'),
            'setor': ('departamento',), 'unidade': ('setor',),
        }.get(kind)
        if relevant is None:
            raise ValidationError('Tipo de estrutura municipal inválido.')
        for name in ('secretaria', 'departamento', 'setor'):
            if name not in relevant:
                self.fields.pop(name)
        if kind == 'unidade':
            self.fields['setor'].label = 'Setor'


class SecretariaEdicaoForm(forms.ModelForm):
    class Meta:
        model = Secretaria
        fields = ('codigo', 'nome', 'descricao', 'responsavel')
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'gp-input', 'maxlength': 30}),
            'nome': forms.TextInput(attrs={'class': 'gp-input', 'maxlength': 150}),
            'descricao': forms.Textarea(attrs={'class': 'gp-input', 'rows': 2}),
            'responsavel': forms.Select(attrs={'class': 'gp-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsavel'].queryset = Servidor.objects.filter(
            organization=current_organization(), ativo=True,
        ).select_related('secretaria')

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        duplicate = Secretaria.all_objects.filter(
            organization=current_organization(), codigo=codigo,
        ).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise ValidationError('Este código já está sendo usado por outra secretaria desta Prefeitura.')
        return codigo


class EstruturaItemEdicaoForm(forms.Form):
    codigo = forms.CharField(max_length=30, label='Código')
    nome = forms.CharField(max_length=150, label='Nome')
    descricao = forms.CharField(required=False, label='Descrição', widget=forms.Textarea(attrs={'rows': 2}))
    responsavel = forms.ModelChoiceField(queryset=Servidor.objects.none(), required=False, label='Responsável')

    def __init__(self, *args, item, model, actor, **kwargs):
        self.item = item
        self.model = model
        self.actor = actor
        super().__init__(*args, initial={
            'codigo': item.codigo, 'nome': item.nome, 'descricao': item.descricao,
            'responsavel': item.responsavel_id,
        }, **kwargs)
        self.fields['responsavel'].queryset = scoped_queryset(
            actor,
            Servidor.objects.filter(organization=current_organization(), ativo=True),
        )
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                field.widget.attrs['class'] = 'gp-select'
            else:
                field.widget.attrs['class'] = 'gp-input'

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        duplicate = self.model.all_objects.filter(
            organization=current_organization(), codigo=codigo,
        ).exclude(pk=self.item.pk)
        if duplicate.exists():
            raise ValidationError('Este código já está sendo usado nesta Prefeitura.')
        return codigo


class AcessoMunicipalForm(forms.Form):
    membership = forms.ModelChoiceField(queryset=OrganizationMembership.objects.none(), label='Usuário com acesso à Prefeitura')
    papel = forms.ChoiceField(choices=AcessoMunicipal.Papel.choices, label='Papel municipal')
    escopo = forms.ChoiceField(choices=AcessoMunicipal.Escopo.choices, label='Escopo')
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)
    funcao = forms.ModelChoiceField(queryset=FuncaoMunicipal.objects.none(), required=False, label='Função municipal')
    permissoes = forms.MultipleChoiceField(choices=sorted(PUBLIC_PERMISSION_LABELS.items()), required=False,
        widget=forms.CheckboxSelectMultiple, label='Permissões específicas')

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        erp_membership_ids = MembershipERP.objects.filter(erp__code='gestao-publica', erp__active=True, enabled=True).values_list('membership_id', flat=True)
        self.fields['membership'].queryset = OrganizationMembership.objects.filter(
            organization=org, status=OrganizationMembership.Status.ACTIVE, pk__in=erp_membership_ids,
        ).select_related('user').order_by('user__last_name', 'user__first_name', 'user__username')
        self.fields['membership'].label_from_instance = lambda row: f'{row.user.get_full_name() or row.user.username} · {row.get_role_display()}'
        self.fields['secretaria'].queryset = Secretaria.objects.filter(organization=org, ativo=True)
        self.fields['departamento'].queryset = DepartamentoMunicipal.objects.filter(organization=org, ativo=True).select_related('secretaria')
        self.fields['setor'].queryset = SetorMunicipal.objects.filter(organization=org, ativo=True).select_related('departamento')
        self.fields['unidade'].queryset = UnidadeMunicipal.objects.filter(organization=org, ativo=True).select_related('setor')
        self.fields['funcao'].queryset = FuncaoMunicipal.objects.filter(organization=org, ativo=True)
        if actor is not None and not has_municipal_permission(actor, 'access.manage'):
            self.fields['membership'].queryset = OrganizationMembership.objects.none()
        elif actor is not None and not any(row.papel == AcessoMunicipal.Papel.ADMIN_PREFEITURA for row in accesses_for(actor)):
            membership_ids = scoped_queryset(actor, Servidor.objects.filter(
                ativo=True, usuario__isnull=False,
            )).values_list('usuario__memberships__pk', flat=True)
            visible_membership_ids = set(OrganizationMembership.objects.filter(
                organization=org, pk__in=membership_ids,
            ).values_list('pk', flat=True))
            visible_membership_ids.update(
                access.membership_id for access in scoped_queryset(actor, AcessoMunicipal.objects.all())
            )
            self.fields['membership'].queryset = self.fields['membership'].queryset.filter(pk__in=visible_membership_ids)
            self.fields['secretaria'].queryset = scoped_queryset(actor, self.fields['secretaria'].queryset)
            self.fields['departamento'].queryset = scoped_queryset(actor, self.fields['departamento'].queryset)
            self.fields['setor'].queryset = scoped_queryset(actor, self.fields['setor'].queryset)
            self.fields['unidade'].queryset = scoped_queryset(actor, self.fields['unidade'].queryset)
            self.fields['funcao'].queryset = self.fields['funcao'].queryset.none()
        self.fields['secretaria'].label = 'Secretaria (escopo)'
        self.fields['departamento'].label = 'Departamento (escopo)'
        self.fields['setor'].label = 'Setor (escopo)'
        self.fields['unidade'].label = 'Unidade (escopo)'

    def clean(self):
        data = super().clean()
        _validate_scope(data)
        return data


class ConviteMunicipalForm(forms.Form):
    email = forms.EmailField(label='E-mail do profissional')
    papel = forms.ChoiceField(choices=AcessoMunicipal.Papel.choices, label='Papel municipal')
    escopo = forms.ChoiceField(choices=AcessoMunicipal.Escopo.choices, label='Escopo')
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)
    funcao = forms.ModelChoiceField(queryset=FuncaoMunicipal.objects.none(), required=False, label='Função municipal')
    permissoes = forms.MultipleChoiceField(choices=sorted(PUBLIC_PERMISSION_LABELS.items()), required=False,
        widget=forms.CheckboxSelectMultiple, label='Permissões pretendidas')

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['secretaria'].queryset = Secretaria.objects.filter(organization=org, ativo=True)
        self.fields['departamento'].queryset = DepartamentoMunicipal.objects.filter(organization=org, ativo=True).select_related('secretaria')
        self.fields['setor'].queryset = SetorMunicipal.objects.filter(organization=org, ativo=True).select_related('departamento')
        self.fields['unidade'].queryset = UnidadeMunicipal.objects.filter(organization=org, ativo=True).select_related('setor')
        self.fields['funcao'].queryset = FuncaoMunicipal.objects.filter(organization=org, ativo=True)
        if actor is not None:
            for name in ('secretaria', 'departamento', 'setor', 'unidade'):
                self.fields[name].queryset = scoped_queryset(actor, self.fields[name].queryset)
        self.fields['secretaria'].label = 'Secretaria (escopo)'
        self.fields['departamento'].label = 'Departamento (escopo)'
        self.fields['setor'].label = 'Setor (escopo)'
        self.fields['unidade'].label = 'Unidade (escopo)'

    def clean(self):
        data = super().clean()
        _validate_scope(data)
        if data.get('email'):
            data['email'] = data['email'].strip().lower()
        return data


def _validate_scope(data):
    scope = data.get('escopo')
    role = data.get('papel')
    required_field = {
        AcessoMunicipal.Escopo.PREFEITURA: None,
        AcessoMunicipal.Escopo.SECRETARIA: 'secretaria',
        AcessoMunicipal.Escopo.DEPARTAMENTO: 'departamento',
        AcessoMunicipal.Escopo.SETOR: 'setor',
        AcessoMunicipal.Escopo.UNIDADE: 'unidade',
    }.get(scope)
    if required_field is None:
        if scope != AcessoMunicipal.Escopo.PREFEITURA:
            return
        if any(data.get(field) for field in ('secretaria', 'departamento', 'setor', 'unidade')):
            raise ValidationError('Escopo Prefeitura não pode apontar para uma unidade inferior.')
    elif not data.get(required_field):
        raise ValidationError(f'Selecione {required_field} para o escopo escolhido.')
    expected = {
        AcessoMunicipal.Papel.ADMIN_PREFEITURA: AcessoMunicipal.Escopo.PREFEITURA,
        AcessoMunicipal.Papel.ADMIN_SECRETARIA: AcessoMunicipal.Escopo.SECRETARIA,
        AcessoMunicipal.Papel.GESTOR_DEPARTAMENTO: AcessoMunicipal.Escopo.DEPARTAMENTO,
    }.get(role)
    if expected and scope != expected:
        raise ValidationError('O papel selecionado exige seu escopo hierárquico correspondente.')
    if role == AcessoMunicipal.Papel.PROFISSIONAL and scope not in {AcessoMunicipal.Escopo.SETOR, AcessoMunicipal.Escopo.UNIDADE}:
        raise ValidationError('Profissional/Servidor precisa de escopo de Setor ou Unidade.')
    secretary, department, sector, unit = (data.get(x) for x in ('secretaria', 'departamento', 'setor', 'unidade'))
    if department and secretary and department.secretaria_id != secretary.pk:
        raise ValidationError('O Departamento não pertence à Secretaria selecionada.')
    if sector and department and sector.departamento_id != department.pk:
        raise ValidationError('O Setor não pertence ao Departamento selecionado.')
    if unit and sector and unit.setor_id != sector.pk:
        raise ValidationError('A Unidade não pertence ao Setor selecionado.')


class ConviteAceiteForm(forms.Form):
    email = forms.EmailField(disabled=True, label='E-mail convidado')
    username = forms.CharField(max_length=150, label='Usuário', widget=forms.TextInput(attrs={'autocomplete': 'username'}))
    first_name = forms.CharField(max_length=150, label='Nome')
    last_name = forms.CharField(max_length=150, required=False, label='Sobrenome')
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), label='Criar senha')
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), label='Confirmar senha')

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('Este nome de usuário já está em uso.')
        return username

    def clean(self):
        data = super().clean()
        if data.get('password1') and data.get('password2') and data['password1'] != data['password2']:
            self.add_error('password2', 'As senhas não coincidem.')
        if data.get('password1'):
            try:
                validate_password(data['password1'])
            except ValidationError as exc:
                self.add_error('password1', exc)
        return data
