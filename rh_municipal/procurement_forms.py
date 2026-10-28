"""Tenant-filtered model forms for municipal procurement screens."""
from decimal import Decimal

from django import forms

from platform_core.context import current_organization

from .phase_b_models import (
    AtaRegistroPrecosMunicipal, CotacaoFornecedorMunicipal,
    AditivoContratoPublico,
    ContratoPublicoMunicipal, DocumentoContratacaoMunicipal,
    FornecedorProcessoMunicipal, ItemAtaRegistroPrecosMunicipal,
    ItemContratoPublicoMunicipal, ItemContratacaoMunicipal,
    ItemPesquisaPrecoMunicipal, ItemPropostaMunicipal,
    ItemSolicitacaoCompra, LicitacaoMunicipal,
    LoteContratacaoMunicipal, ModalidadeContratacaoMunicipal,
    PesquisaPrecoMunicipal, ProcessoContratacaoMunicipal, PropostaMunicipal, SolicitacaoCompra,
)
from .public_services import scoped_queryset


MODEL_ACTIONS = {
    'solicitacao': ('Solicitação de compra', SolicitacaoCompra, (
        'numero', 'exercicio', 'secretaria', 'departamento', 'setor', 'unidade',
        'justificativa', 'prioridade', 'fonte_recurso', 'unidade_orcamentaria', 'dotacao',
    )),
    'item_solicitacao': ('Item da solicitação', ItemSolicitacaoCompra, (
        'solicitacao', 'descricao', 'especificacao', 'quantidade', 'unidade_medida', 'estimativa_unitaria',
    )),
    'modalidade': ('Modalidade / fundamento parametrizável', ModalidadeContratacaoMunicipal, (
        'codigo', 'nome', 'fundamento_referencia', 'descricao', 'ativo',
    )),
    'pesquisa': ('Pesquisa de preços', PesquisaPrecoMunicipal, ('solicitacao', 'processo', 'data_referencia', 'observacoes')),
    'cotacao': ('Cotação de fornecedor', CotacaoFornecedorMunicipal, (
        'pesquisa', 'fornecedor', 'data', 'fonte', 'documento_referencia', 'observacao',
    )),
    'cotacao_item': ('Preço cotado por item', ItemPesquisaPrecoMunicipal, (
        'cotacao', 'descricao', 'quantidade', 'unidade_medida', 'preco_unitario', 'observacao',
    )),
    'processo': ('Processo de contratação', None, ()),
    'lote': ('Lote do processo', LoteContratacaoMunicipal, ('processo', 'numero', 'descricao')),
    'item_processo': ('Item do processo', ItemContratacaoMunicipal, (
        'processo', 'solicitacao_item', 'lote', 'numero', 'descricao', 'especificacao',
        'quantidade', 'unidade_medida', 'valor_estimado_unitario',
    )),
    'licitacao': ('Edital / publicação', LicitacaoMunicipal, (
        'processo', 'numero_edital', 'data_publicacao', 'meio_publicacao', 'prazo_propostas', 'resultado_resumo',
    )),
    'participante': ('Fornecedor participante', FornecedorProcessoMunicipal, ('processo', 'fornecedor', 'status', 'observacoes')),
    'proposta': ('Proposta do fornecedor', PropostaMunicipal, ('fornecedor_processo', 'numero', 'data_envio', 'observacoes')),
    'proposta_item': ('Proposta para item', ItemPropostaMunicipal, (
        'proposta', 'item_processo', 'valor_unitario', 'quantidade', 'classificacao', 'vencedor', 'observacao',
    )),
    'ata': ('Ata de Registro de Preços', AtaRegistroPrecosMunicipal, (
        'numero', 'exercicio', 'processo', 'fornecedor', 'inicio_vigencia', 'fim_vigencia', 'status', 'documento_referencia',
    )),
    'ata_item': ('Item registrado na Ata', ItemAtaRegistroPrecosMunicipal, (
        'ata', 'item_processo', 'quantidade_registrada', 'valor_unitario',
    )),
    'contrato': ('Contrato público', ContratoPublicoMunicipal, (
        'numero', 'exercicio', 'processo', 'ata', 'fornecedor', 'secretaria', 'unidade',
        'objeto', 'valor', 'assinado_em', 'inicio_vigencia', 'fim_vigencia', 'fiscal', 'status', 'observacoes',
    )),
    'contrato_item': ('Item do contrato', ItemContratoPublicoMunicipal, (
        'contrato', 'item_processo', 'descricao', 'quantidade_contratada', 'valor_unitario',
    )),
    'aditivo': ('Aditivo / apostilamento / prorrogação', AditivoContratoPublico, (
        'contrato', 'tipo', 'numero', 'valor_anterior', 'valor_novo',
        'fim_vigencia_anterior', 'fim_vigencia_novo', 'fundamento', 'observacoes',
    )),
    'documento_solicitacao': ('Referência de documento da solicitação', DocumentoContratacaoMunicipal, (
        'solicitacao', 'documento', 'categoria',
    )),
    'documento_processo': ('Referência de documento do processo', DocumentoContratacaoMunicipal, (
        'processo', 'documento', 'categoria',
    )),
    'documento_contrato': ('Referência de documento do contrato', DocumentoContratacaoMunicipal, (
        'contrato', 'documento', 'categoria',
    )),
}


class ProcessoFromRequestForm(forms.Form):
    solicitacao = forms.ModelChoiceField(queryset=SolicitacaoCompra.objects.none(), label='Solicitação aprovada')
    numero = forms.CharField(max_length=40, label='Número do processo')
    exercicio = forms.IntegerField(min_value=1900, max_value=2200, label='Exercício')
    modalidade = forms.ModelChoiceField(queryset=ModalidadeContratacaoMunicipal.objects.none(), label='Modalidade parametrizada')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['solicitacao'].queryset = scoped_queryset(actor, SolicitacaoCompra.objects.filter(
            organization=org, status=SolicitacaoCompra.Status.APROVADA,
        ))
        self.fields['modalidade'].queryset = scoped_queryset(actor, ModalidadeContratacaoMunicipal.objects.filter(
            organization=org, ativo=True,
        ))
        for field in self.fields.values():
            field.widget.attrs['class'] = 'gp-input'


class AtaUsoForm(forms.Form):
    item_ata = forms.ModelChoiceField(queryset=ItemAtaRegistroPrecosMunicipal.objects.none(), label='Item da Ata')
    quantidade = forms.DecimalField(max_digits=16, decimal_places=4, min_value=Decimal('0.0001'))
    unidade = forms.ModelChoiceField(queryset=None, required=False, label='Unidade destinatária')
    referencia = forms.CharField(max_length=120, required=False, help_text='Chave única de operação para evitar duplicidade.')

    def __init__(self, *args, actor, **kwargs):
        from .models import UnidadeMunicipal
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['item_ata'].queryset = scoped_queryset(actor, ItemAtaRegistroPrecosMunicipal.objects.filter(organization=org))
        self.fields['unidade'].queryset = scoped_queryset(actor, UnidadeMunicipal.objects.filter(organization=org))
        for field in self.fields.values():
            field.widget.attrs['class'] = 'gp-input'


class ContractExecutionForm(forms.Form):
    contrato = forms.ModelChoiceField(queryset=ContratoPublicoMunicipal.objects.none(), label='Contrato')
    item_contrato = forms.ModelChoiceField(queryset=ItemContratoPublicoMunicipal.objects.none(), required=False, label='Item contratual')
    tipo = forms.ChoiceField(choices=[('', 'Selecione'), ('ENTREGA', 'Entrega'), ('MEDICAO', 'Medição'), ('OCORRENCIA', 'Ocorrência'), ('FISCALIZACAO', 'Fiscalização')])
    referencia = forms.CharField(max_length=80, required=False)
    quantidade = forms.DecimalField(max_digits=16, decimal_places=4, min_value=Decimal('0'), required=False)
    valor = forms.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal('0'), required=False)
    descricao = forms.CharField(widget=forms.Textarea, label='Registro / observação')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['contrato'].queryset = scoped_queryset(actor, ContratoPublicoMunicipal.objects.filter(organization=org))
        self.fields['item_contrato'].queryset = scoped_queryset(actor, ItemContratoPublicoMunicipal.objects.filter(organization=org))
        for field in self.fields.values():
            field.widget.attrs['class'] = 'gp-input'


class ProcurementDocumentForm(forms.Form):
    titulo = forms.CharField(max_length=180, label='Título do arquivo')
    categoria = forms.ChoiceField(choices=DocumentoContratacaoMunicipal.Categoria.choices)
    arquivo = forms.FileField(label='Arquivo privado')

    def __init__(self, *args, actor, action, **kwargs):
        super().__init__(*args, **kwargs)
        self.action = action
        target_model = {
            'documento_solicitacao': SolicitacaoCompra,
            'documento_processo': ProcessoContratacaoMunicipal,
            'documento_contrato': ContratoPublicoMunicipal,
        }[action]
        label = {'documento_solicitacao': 'Solicitação', 'documento_processo': 'Processo', 'documento_contrato': 'Contrato'}[action]
        self.fields['alvo'] = forms.ModelChoiceField(
            queryset=scoped_queryset(actor, target_model.objects.filter(organization=current_organization())),
            label=label,
        )
        for field in self.fields.values():
            field.widget.attrs['class'] = 'gp-input'

    def clean_arquivo(self):
        import os
        upload = self.cleaned_data['arquivo']
        if upload.size > 25 * 1024 * 1024:
            raise forms.ValidationError('O arquivo deve ter até 25 MB.')
        suffix = os.path.splitext(upload.name)[1].lower()
        if suffix not in {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.xml'}:
            raise forms.ValidationError('Formato aceito: PDF, PNG, JPG, WEBP ou XML.')
        if suffix == '.pdf':
            head = upload.read(5)
            upload.seek(0)
            if head != b'%PDF-':
                raise forms.ValidationError('O arquivo não parece ser um PDF válido.')
        return upload


def procurement_model_form(action, *, actor, data=None, files=None):
    title, model, field_names = MODEL_ACTIONS[action]
    if action == 'processo':
        return title, ProcessoFromRequestForm(data=data, actor=actor)
    if action.startswith('documento_'):
        return title, ProcurementDocumentForm(data=data, files=files, actor=actor, action=action)
    meta = type('Meta', (), {'model': model, 'fields': field_names})

    def __init__(self, *args, **kwargs):
        super(form_class, self).__init__(*args, **kwargs)
        org = current_organization()
        for field in self.fields.values():
            css = 'gp-select' if isinstance(field.widget, (forms.Select, forms.SelectMultiple)) else 'gp-input'
            field.widget.attrs.update({'class': css})
            if isinstance(field, forms.ModelChoiceField):
                related = field.queryset.model
                if any(item.name == 'organization' for item in related._meta.fields):
                    field.queryset = scoped_queryset(actor, related.objects.filter(organization=org))
            if isinstance(field, forms.DecimalField):
                field.widget.attrs['inputmode'] = 'decimal'
            if isinstance(field, forms.DateField):
                field.widget.attrs['type'] = 'date'
            if isinstance(field, forms.DateTimeField):
                field.widget.attrs['type'] = 'datetime-local'

    form_class = type(f'{model.__name__}ProcurementForm', (forms.ModelForm,), {'Meta': meta, '__init__': __init__})
    return title, form_class(data=data)

