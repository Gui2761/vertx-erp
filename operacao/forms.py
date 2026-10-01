import uuid
from decimal import Decimal
from pathlib import PurePosixPath
from django import forms
from django.utils import timezone
from platform_core.context import current_organization
from gestao.forms import Estilizado
from contas.models import Usuario
from equipamentos.models import Equipamento
from . import models as m

def model_form(model, fields):
    return type(model.__name__ + 'Form', (Estilizado,), {'__module__': __name__, 'Meta': type('Meta', (), {'model': model, 'fields': fields})})

DepositoForm = model_form(m.Deposito, ['nome', 'endereco', 'ativo'])
CategoriaPecaForm = model_form(m.CategoriaPeca, ['nome', 'ativo'])
ChamadoForm = model_form(m.Chamado, ['cliente', 'unidade', 'equipamento', 'contrato', 'titulo', 'descricao', 'prioridade'])
CompraForm = model_form(m.Compra, ['fornecedor', 'deposito', 'necessidade', 'vencimento', 'observacoes'])
ItemCompraForm = model_form(m.ItemCompra, ['peca', 'quantidade', 'custo_unitario', 'lote', 'fabricacao', 'validade', 'documento_entrada'])
CotacaoCompraForm = model_form(m.CotacaoCompra, ['fornecedor', 'valor', 'validade', 'prazo', 'observacoes'])
ItemVendaForm = model_form(m.ItemVenda, ['peca', 'quantidade', 'valor_unitario', 'desconto'])
ContaBancariaForm = model_form(m.ContaBancaria, ['nome', 'banco', 'agencia', 'numero', 'tipo', 'saldo_inicial', 'permite_saldo_negativo', 'ativo'])
ExtratoForm = model_form(m.ExtratoBancario, ['conta', 'identificador', 'data', 'valor', 'descricao'])
FiscalForm = model_form(m.DocumentoFiscal, ['tipo', 'cliente', 'lancamento', 'ordem', 'venda', 'serie', 'ambiente', 'municipio', 'codigo_servico', 'impostos', 'retencoes', 'descricao', 'valor'])

class VendaForm(Estilizado):
    class Meta:
        model = m.Venda
        fields = ['cliente', 'vendedor', 'deposito', 'vencimento', 'observacoes']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vendedor'].queryset = Usuario.objects.filter(memberships__organization=current_organization(), memberships__status='ATIVO', is_active=True).distinct()

class ChecklistForm(Estilizado):
    itens = forms.CharField(label='Itens do checklist', widget=forms.Textarea(attrs={'rows': 8}), help_text='Um item por linha. Inicie com * os itens obrigatórios.')
    class Meta:
        model = m.ModeloChecklist
        fields = ['nome', 'ativo', 'itens']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['itens'] = '\n'.join(('* ' if row.get('obrigatorio') else '') + row['item'] for row in self.instance.itens)
    def clean_itens(self):
        rows = [{'item': line.strip().lstrip('*').strip(), 'obrigatorio': line.strip().startswith('*')} for line in self.cleaned_data['itens'].splitlines() if line.strip()]
        m.checklist_valido(rows)
        return rows

class PlanoForm(Estilizado):
    equipamentos = forms.ModelMultipleChoiceField(queryset=Equipamento.objects.none())
    class Meta:
        model = m.PlanoPreventivo
        fields = ['nome', 'cliente', 'contrato', 'equipamentos', 'checklist', 'tecnico', 'periodicidade', 'intervalo_dias', 'inicio', 'fim', 'observacoes', 'ativo']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['equipamentos'] = self.instance.equipamentos.all()
    def clean(self):
        data = super().clean()
        if data.get('cliente') and any(eq.cliente_id != data['cliente'].pk for eq in data.get('equipamentos', [])):
            self.add_error('equipamentos', 'Use equipamentos do cliente selecionado.')
        if data.get('contrato') and any(not data['contrato'].equipamentos.filter(pk=eq.pk).exists() for eq in data.get('equipamentos', [])):
            self.add_error('equipamentos', 'Use equipamentos cobertos pelo contrato.')
        return data

class DocumentoForm(Estilizado):
    class Meta:
        model = m.Documento
        fields = ['titulo', 'tipo', 'arquivo', 'cliente', 'equipamento', 'ordem', 'contrato', 'orcamento', 'fiscal', 'disponivel_portal']
    def clean_arquivo(self):
        upload = self.cleaned_data['arquivo']
        if upload.size > 25 * 1024 * 1024:
            raise forms.ValidationError('Arquivo limitado a 25 MB.')
        suffix = PurePosixPath(upload.name).suffix.lower()
        head = upload.read(4096)
        upload.seek(0)
        if suffix not in ['.pdf', '.jpg', '.jpeg', '.png', '.webp', '.xml', '.mp4', '.webm']:
            raise forms.ValidationError('Use PDF, imagem, XML, MP4 ou WebM.')
        if suffix == '.pdf' and not head.startswith(b'%PDF-'):
            raise forms.ValidationError('PDF inválido.')
        if suffix in ['.jpg', '.jpeg', '.png', '.webp']:
            from PIL import Image
            try:
                with Image.open(upload) as img:
                    if img.width * img.height > 25000000:
                        raise ValueError()
                    img.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise forms.ValidationError('Imagem inválida ou grande demais.')
            upload.seek(0)
        if suffix == '.xml':
            import xml.etree.ElementTree as xml
            content = upload.read()
            upload.seek(0)
            try:
                if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                    raise ValueError()
                xml.fromstring(content)
            except (ValueError, xml.ParseError):
                raise forms.ValidationError('XML inválido ou com entidades externas.')
        if suffix == '.mp4' and head[4:8] != b'ftyp' or suffix == '.webm' and not head.startswith(b'\x1aE\xdf\xa3'):
            raise forms.ValidationError('Vídeo inválido.')
        return upload

class PortalForm(Estilizado):
    class Meta:
        model = m.PortalCliente
        fields = ['usuario', 'cliente', 'ativo']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['usuario'].queryset = Usuario.objects.filter(memberships__organization=current_organization(), memberships__role='CLIENTE', memberships__status='ATIVO', is_active=True).distinct()

class PagamentoForm(forms.Form):
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('.01'))
    data = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    conta = forms.ModelChoiceField(queryset=m.ContaBancaria.objects.none(), required=False)
    observacao = forms.CharField(required=False, widget=forms.Textarea)
    request_id = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['conta'].queryset = m.ContaBancaria.objects.filter(ativo=True)

class CaixaForm(PagamentoForm):
    tipo = forms.ChoiceField(choices=[('ENTRADA', 'Entrada'), ('SAIDA', 'Saída')])
    descricao = forms.CharField(max_length=255)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['conta'].required = True

class TransferenciaForm(PagamentoForm):
    destino = forms.ModelChoiceField(queryset=m.ContaBancaria.objects.none())
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['conta'].required = True
        self.fields['destino'].queryset = m.ContaBancaria.objects.filter(ativo=True)

class ParcelasForm(forms.Form):
    quantidade = forms.IntegerField(min_value=2, max_value=60)
    primeiro_vencimento = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))

class ConciliacaoForm(forms.Form):
    movimento = forms.ModelChoiceField(queryset=m.MovimentoCaixa.objects.none())
    def __init__(self, *args, conta, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['movimento'].queryset = m.MovimentoCaixa.objects.filter(conta=conta, extratobancario__isnull=True)

ConfiguracaoForm = model_form(m.Configuracao, ['endereco', 'prefixo_os', 'prefixo_orcamento', 'prefixo_contrato', 'digitos_numero', 'prazo_financeiro_dias', 'juros_mensal_percentual', 'multa_percentual', 'municipio_fiscal', 'codigo_servico', 'ambiente_fiscal', 'provedor_fiscal'])
