"""Bounded input forms for Phase E municipal and public-facing workflows."""
from django import forms
from django.contrib.auth import get_user_model

from platform_core.context import current_organization
from platform_core.models import OrganizationMembership
from . import phase_e_models as m
from .models import DepartamentoMunicipal, Secretaria, SetorMunicipal, UnidadeMunicipal
from .public_services import scoped_queryset


class PublicStyledForm(forms.Form):
    """Common renderer hook; templates provide the visual layout and feedback."""


class ProtocolForm(forms.ModelForm):
    class Meta:
        model = m.ProtocoloMunicipal
        fields = ('origem', 'interessado_nome', 'interessado_documento', 'interessado_email', 'interessado_telefone',
                  'assunto', 'resumo', 'prioridade', 'prazo_em', 'secretaria', 'departamento', 'setor', 'unidade', 'responsavel')
        widgets = {'resumo': forms.Textarea(attrs={'rows': 3}), 'prazo_em': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['secretaria'].queryset = scoped_queryset(actor, Secretaria.objects.filter(ativo=True))
        self.fields['departamento'].queryset = scoped_queryset(actor, DepartamentoMunicipal.objects.filter(ativo=True))
        self.fields['setor'].queryset = scoped_queryset(actor, SetorMunicipal.objects.filter(ativo=True))
        self.fields['unidade'].queryset = scoped_queryset(actor, UnidadeMunicipal.objects.filter(ativo=True))
        self.fields['responsavel'].queryset = get_user_model().objects.filter(
            memberships__organization=current_organization(), memberships__status=OrganizationMembership.Status.ACTIVE,
            is_active=True,
        ).distinct()


class ProcessForm(forms.ModelForm):
    class Meta:
        model = m.ProcessoDigitalMunicipal
        fields = ('titulo', 'assunto', 'descricao', 'prioridade', 'sigilo', 'prazo_em', 'protocolo',
                  'secretaria', 'departamento', 'setor', 'unidade', 'responsavel')
        widgets = {'descricao': forms.Textarea(attrs={'rows': 4}), 'prazo_em': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['protocolo'].queryset = scoped_queryset(actor, m.ProtocoloMunicipal.objects.filter(organization=org)).filter(processo_digital__isnull=True)
        self.fields['secretaria'].queryset = scoped_queryset(actor, Secretaria.objects.filter(ativo=True))
        self.fields['departamento'].queryset = scoped_queryset(actor, DepartamentoMunicipal.objects.filter(ativo=True))
        self.fields['setor'].queryset = scoped_queryset(actor, SetorMunicipal.objects.filter(ativo=True))
        self.fields['unidade'].queryset = scoped_queryset(actor, UnidadeMunicipal.objects.filter(ativo=True))
        self.fields['responsavel'].queryset = get_user_model().objects.filter(
            memberships__organization=org, memberships__status=OrganizationMembership.Status.ACTIVE,
            is_active=True,
        ).distinct()


class ProcessTransitionForm(forms.Form):
    status = forms.ChoiceField(choices=m.ProcessoDigitalMunicipal.Status.choices)
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)
    responsavel = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False)
    descricao = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['secretaria'].queryset = scoped_queryset(actor, Secretaria.objects.filter(ativo=True))
        self.fields['departamento'].queryset = scoped_queryset(actor, DepartamentoMunicipal.objects.filter(ativo=True))
        self.fields['setor'].queryset = scoped_queryset(actor, SetorMunicipal.objects.filter(ativo=True))
        self.fields['unidade'].queryset = scoped_queryset(actor, UnidadeMunicipal.objects.filter(ativo=True))
        self.fields['responsavel'].queryset = get_user_model().objects.filter(
            memberships__organization=org, memberships__status=OrganizationMembership.Status.ACTIVE,
            is_active=True,
        ).distinct()


class ProcessNoteForm(PublicStyledForm):
    tipo = forms.ChoiceField(choices=(('DESPACHO', 'Despacho'), ('PARECER', 'Parecer')))
    texto = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows': 5}))
    resultado = forms.ChoiceField(choices=m.ParecerProcessoMunicipal.Resultado.choices, required=False)
    referencia = forms.CharField(max_length=180, required=False)


class ProcessTaskForm(forms.ModelForm):
    class Meta:
        model = m.TarefaProcessoMunicipal
        fields = ('titulo', 'descricao', 'atribuida_a', 'prazo_em')
        widgets = {'descricao': forms.Textarea(attrs={'rows': 2}), 'prazo_em': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['atribuida_a'].queryset = get_user_model().objects.filter(
            memberships__organization=current_organization(), memberships__status=OrganizationMembership.Status.ACTIVE,
            is_active=True,
        ).distinct()


class ProcessDocumentForm(PublicStyledForm):
    titulo = forms.CharField(max_length=180)
    categoria = forms.ChoiceField(choices=m.DocumentoProcessoMunicipal.Categoria.choices)
    arquivo = forms.FileField()


class SignatureRequestForm(PublicStyledForm):
    versao = forms.ModelChoiceField(queryset=m.VersaoDocumentoProcessoMunicipal.objects.none())
    signatarios = forms.ModelMultipleChoiceField(queryset=OrganizationMembership.objects.none())

    def __init__(self, *args, actor, process, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['versao'].queryset = scoped_queryset(
            actor, m.VersaoDocumentoProcessoMunicipal.objects.filter(documento__processo=process),
        )
        self.fields['signatarios'].queryset = OrganizationMembership.objects.filter(
            organization=current_organization(), status=OrganizationMembership.Status.ACTIVE,
            user__is_active=True,
        ).select_related('user')


class TransparencyForm(forms.ModelForm):
    class Meta:
        model = m.PublicacaoTransparenciaMunicipal
        fields = ('categoria', 'titulo', 'resumo', 'conteudo_publico', 'fonte_referencia', 'data_referencia',
                  'secretaria', 'departamento', 'setor', 'unidade')
        widgets = {'resumo': forms.Textarea(attrs={'rows': 2}), 'conteudo_publico': forms.Textarea(attrs={'rows': 8}),
                   'data_referencia': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['secretaria'].queryset = scoped_queryset(actor, Secretaria.objects.filter(ativo=True))
        self.fields['departamento'].queryset = scoped_queryset(actor, DepartamentoMunicipal.objects.filter(ativo=True))
        self.fields['setor'].queryset = scoped_queryset(actor, SetorMunicipal.objects.filter(ativo=True))
        self.fields['unidade'].queryset = scoped_queryset(actor, UnidadeMunicipal.objects.filter(ativo=True))


class PublicManifestationForm(PublicStyledForm):
    tipo = forms.ChoiceField(choices=m.ManifestacaoOuvidoriaMunicipal.Tipo.choices)
    assunto = forms.CharField(max_length=180)
    relato = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows': 6}))
    anonima = forms.BooleanField(required=False)
    sigilosa = forms.BooleanField(required=False)
    nome = forms.CharField(max_length=180, required=False)
    documento = forms.CharField(max_length=20, required=False)
    email = forms.EmailField(required=False)
    telefone = forms.CharField(max_length=30, required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('anonima'):
            cleaned.update(nome='', documento='', email='', telefone='')
        elif not cleaned.get('nome') or not cleaned.get('email'):
            raise forms.ValidationError('Informe nome e e-mail ou marque o envio anônimo.')
        return cleaned


class PublicEsicForm(PublicStyledForm):
    assunto = forms.CharField(max_length=180)
    pedido = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows': 6}))
    nome = forms.CharField(max_length=180)
    documento = forms.CharField(max_length=20, required=False)
    email = forms.EmailField()
    telefone = forms.CharField(max_length=30, required=False)


class OmbudsmanResponseForm(PublicStyledForm):
    resposta = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows': 5}))
    publicar_no_acompanhamento = forms.BooleanField(required=False)


class EsicResponseForm(PublicStyledForm):
    resposta = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows': 5}))
    documento_key = forms.CharField(max_length=500, required=False)


class EsicAppealForm(PublicStyledForm):
    fundamento = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows': 5}))


class TrackingForm(PublicStyledForm):
    protocolo = forms.CharField(max_length=32)
    chave = forms.CharField(max_length=100, widget=forms.PasswordInput(render_value=False))
