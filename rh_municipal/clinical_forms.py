import uuid
from decimal import Decimal

from django import forms
from platform_core.context import current_organization
from . import phase_g_models as health
from .public_services import scoped_queryset


PURPOSES = (('assistencia', 'Assistência ao cidadão'), ('continuidade', 'Continuidade do cuidado'),
            ('auditoria', 'Auditoria clínica autorizada'))
KINDS = (('acolhimento', 'Acolhimento'), ('medico', 'Atendimento médico'),
         ('enfermagem', 'Atendimento de enfermagem'), ('evolucao', 'Evolução clínica'),
         ('exame', 'Solicitação de exame'), ('encaminhamento', 'Encaminhamento'))


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'gp-input', 'autocomplete': 'off'})


class RecordSearchForm(StyledForm):
    documento = forms.CharField(max_length=20, label='CPF ou CNS completo')

    def clean_documento(self):
        value = self.cleaned_data['documento'].replace('.', '').replace('-', '').replace(' ', '')
        if not value.isascii() or not value.isdigit() or len(value) not in (11, 15):
            raise forms.ValidationError('Informe CPF com 11 dígitos ou CNS com 15 dígitos.')
        return value


class EncounterForm(StyledForm):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    unidade = forms.ModelChoiceField(queryset=health.UnidadeSaudeMunicipal.objects.none(), label='Unidade responsável')
    profissional = forms.ModelChoiceField(queryset=health.ProfissionalSaudeMunicipal.objects.none(), label='Profissional responsável')

    def __init__(self, *args, actor, patient, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['request_id'].initial = uuid.uuid4()
        org = current_organization()
        self.fields['unidade'].queryset = scoped_queryset(actor, health.UnidadeSaudeMunicipal.objects.filter(
            organization=org, ativo=True, unidade_id=patient.unidade_id, unidade__ativo=True,
        ), capability='saude.records.create').select_related('unidade')
        self.fields['unidade'].label_from_instance = lambda row: row.unidade.nome
        self.fields['profissional'].queryset = scoped_queryset(actor, health.ProfissionalSaudeMunicipal.objects.filter(
            organization=org, ativo=True, servidor__ativo=True, servidor__situacao_funcional='ATIVO',
            unidade_saude__in=self.fields['unidade'].queryset,
        ), capability='saude.records.create').select_related('servidor', 'unidade_saude__unidade')
        self.fields['profissional'].label_from_instance = lambda row: f'{row.servidor.nome} · {row.unidade_saude.unidade.nome}'


class ClinicalEventForm(StyledForm):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    tipo = forms.ChoiceField(choices=KINDS)
    queixa = forms.CharField(max_length=4000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    avaliacao = forms.CharField(max_length=8000, required=False, label='Avaliação', widget=forms.Textarea(attrs={'rows': 3}))
    diagnostico = forms.CharField(max_length=2000, required=False, label='Diagnóstico informado pelo profissional')
    cid = forms.CharField(max_length=16, required=False, label='CID informado (opcional, sem validação oficial)')
    procedimentos = forms.CharField(max_length=4000, required=False, label='Procedimentos realizados e códigos informados', widget=forms.Textarea(attrs={'rows': 2}))
    texto = forms.CharField(max_length=12000, required=False, label='Evolução / conduta', widget=forms.Textarea(attrs={'rows': 4}))
    solicitacao = forms.CharField(max_length=4000, required=False, label='Exame ou encaminhamento solicitado')
    destino = forms.CharField(max_length=240, required=False, label='Destino / especialidade')
    pressao_sistolica = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False, label='Pressão sistólica (mmHg)')
    pressao_diastolica = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False, label='Pressão diastólica (mmHg)')
    frequencia_cardiaca = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False, label='Frequência cardíaca (bpm)')
    frequencia_respiratoria = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False, label='Frequência respiratória (irpm)')
    temperatura = forms.DecimalField(min_value=0, max_digits=5, decimal_places=2, required=False, label='Temperatura (°C)')
    saturacao = forms.DecimalField(min_value=0, max_value=100, max_digits=5, decimal_places=2, required=False, label='Saturação (%)')
    peso = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False, label='Peso (kg)')
    altura = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False, label='Altura (cm)')
    corrige = forms.UUIDField(required=False, widget=forms.HiddenInput)
    motivo = forms.CharField(max_length=2000, required=False, label='Motivo da retificação (protegido)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['request_id'].initial = uuid.uuid4()

    def clean(self):
        data = super().clean()
        if data.get('tipo') in {'exame', 'encaminhamento'} and not data.get('solicitacao'):
            self.add_error('solicitacao', 'Informe a solicitação.')
        if data.get('tipo') == 'encaminhamento' and not data.get('destino'):
            self.add_error('destino', 'Informe o destino do encaminhamento.')
        if not any(data.get(key) for key in ('queixa', 'avaliacao', 'diagnostico', 'texto', 'solicitacao', 'procedimentos')):
            raise forms.ValidationError('Informe o conteúdo clínico do registro.')
        if data.get('corrige') and not data.get('motivo'):
            self.add_error('motivo', 'Justifique a retificação.')
        return data


class PrescriptionForm(StyledForm):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    medicamento = forms.CharField(max_length=140, label='Medicamento informado pelo profissional')
    quantidade = forms.DecimalField(min_value=Decimal('0.01'), max_digits=10, decimal_places=2)
    posologia = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={'rows': 3}), label='Posologia / via / duração')
    orientacao = forms.CharField(max_length=4000, required=False, label='Orientações', widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['request_id'].initial = uuid.uuid4()


class ClinicalDocumentForm(StyledForm):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    titulo = forms.CharField(max_length=160, label='Título do documento')
    arquivo = forms.FileField(label='Documento PDF (até 2 MB)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['request_id'].initial = uuid.uuid4()
