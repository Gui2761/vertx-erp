import base64
import binascii
import io
import math
from decimal import Decimal, InvalidOperation
from PIL import Image, ImageOps, UnidentifiedImageError
from django import forms
from .models import OrdemServico
from platform_core.forms import TenantModelForm


class OrdemForm(TenantModelForm):
    revisao = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = OrdemServico
        fields = ['cliente', 'unidade', 'equipamento', 'contrato', 'tecnico', 'auxiliares', 'modelo_checklist', 'tipo_atendimento', 'prioridade', 'agendada_para', 'agendada_ate', 'prazo', 'defeito', 'diagnostico', 'condicao_final', 'pendencias_tecnicas', 'causa_provavel', 'solucao', 'servico_executado', 'recomendacoes', 'materiais', 'pecas', 'horas', 'deslocamento_km', 'observacoes', 'valor_cobranca', 'vencimento_cobranca']
        widgets = {name: forms.Textarea(attrs={'rows': 3}) for name in ['defeito', 'diagnostico', 'servico_executado', 'pecas', 'observacoes']}

    def __init__(self, *args, operacional=False, **kwargs):
        super().__init__(*args, **kwargs)
        # Campos aditivos de resultado técnico, independentes do cadastro físico.
        if operacional:
            for name in ['cliente', 'unidade', 'equipamento', 'contrato', 'tecnico', 'auxiliares', 'modelo_checklist', 'tipo_atendimento', 'prioridade', 'agendada_para', 'agendada_ate', 'prazo', 'defeito', 'valor_cobranca', 'vencimento_cobranca']:
                self.fields.pop(name)
        self.fields['revisao'].initial = self.instance.revisao
        for name in ['agendada_para', 'agendada_ate', 'prazo']:
            if name in self.fields:
                self.fields[name].widget = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def _save_m2m(self):
        # Tenant-validated explicit through rows are written by ordens.services.
        pass

    def clean_valor_cobranca(self):
        return self.cleaned_data.get('valor_cobranca') or Decimal('0')

    def clean_horas(self):
        return self.cleaned_data.get('horas') or Decimal('0')

    def clean_deslocamento_km(self):
        return self.cleaned_data.get('deslocamento_km') or Decimal('0')


class GeoForm(forms.Form):
    resultado = forms.ChoiceField(choices=[(s, s) for s in ['OBTIDA', 'NEGADA', 'INDISPONIVEL', 'TIMEOUT', 'NAO_SUPORTADA']])
    latitude = forms.CharField(required=False)
    longitude = forms.CharField(required=False)
    precisao = forms.CharField(required=False)

    def clean(self):
        data = super().clean()
        if data.get('resultado') == 'OBTIDA':
            for name, limite in [('latitude', 90), ('longitude', 180)]:
                try:
                    value = Decimal(data.get(name, ''))
                    if not value.is_finite() or abs(value) > limite:
                        raise ValueError()
                    data[name] = value.quantize(Decimal('0.0000001'))
                except (InvalidOperation, ValueError):
                    self.add_error(name, 'Coordenada inválida.')
            try:
                value = float(data['precisao']) if data.get('precisao') else None
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError()
                data['precisao'] = value
            except ValueError:
                self.add_error('precisao', 'Precisão inválida.')
        else:
            if any(data.get(k) for k in ['latitude', 'longitude', 'precisao']):
                raise forms.ValidationError('Uma tentativa sem sucesso não pode conter coordenadas.')
            data.update(latitude=None, longitude=None, precisao=None)
        return data


class FotoForm(forms.Form):
    from .models import Foto
    categoria = forms.ChoiceField(label='Categoria', choices=[('', 'Sem classificação')] + list(Foto._meta.get_field('categoria').choices), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    arquivo = forms.ImageField(widget=forms.FileInput(attrs={'accept': 'image/*', 'capture': 'environment', 'class': 'form-control'}))
    descricao = forms.CharField(label='Descrição (opcional)', max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def clean_arquivo(self):
        arquivo = self.cleaned_data['arquivo']
        if arquivo.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Foto deve ter no máximo 10 MB.')
        try:
            with Image.open(arquivo) as img:
                if img.width * img.height > 25_000_000:
                    raise ValueError()
                img = ImageOps.exif_transpose(img).convert('RGB')
                img.thumbnail((2000, 2000))
                buffer = io.BytesIO()
                img.save(buffer, 'JPEG', quality=88)
        except (ValueError, OSError, Image.DecompressionBombError):
            raise forms.ValidationError('Imagem inválida ou grande demais.')
        from django.core.files.base import ContentFile
        return ContentFile(buffer.getvalue(), name='foto.jpg')


class AssinaturaForm(forms.Form):
    imagem_tecnico = forms.CharField(widget=forms.HiddenInput, max_length=400000, required=False)
    token = forms.CharField(widget=forms.HiddenInput)
    nome = forms.CharField(label='Nome completo', max_length=150)
    cargo = forms.CharField(label='Cargo / função', max_length=100)
    imagem = forms.CharField(widget=forms.HiddenInput, max_length=400000)
    confirmacao = forms.BooleanField(label='Conferi os dados acima e confirmo o recebimento do serviço.')

    def clean_imagem(self):
        value = self.cleaned_data['imagem']
        try:
            if not value.startswith('data:image/png;base64,'):
                raise ValueError()
            raw = base64.b64decode(value.split(',', 1)[1], validate=True)
            if len(raw) > 300000:
                raise ValueError()
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != 'PNG' or not (100 <= img.width <= 1600 and 50 <= img.height <= 800):
                    raise ValueError()
                rgba = img.convert('RGBA')
                white = Image.new('RGBA', rgba.size, 'white')
                white.alpha_composite(rgba)
                gray = white.convert('L')
                if sum(n for i, n in enumerate(gray.histogram()) if i < 220) < 30:
                    raise ValueError()
                output = io.BytesIO()
                white.convert('RGB').save(output, 'PNG')
                raw = output.getvalue()
        except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            raise forms.ValidationError('Desenhe uma assinatura válida antes de confirmar.')
        return base64.b64encode(raw).decode('ascii')

    def clean_imagem_tecnico(self):
        value=self.cleaned_data.get('imagem_tecnico')
        if not value:
            return ''
        # A mesma validação/normalização de imagem da assinatura do responsável.
        original=self.cleaned_data.get('imagem')
        try:
            self.cleaned_data['imagem']=value
            return self.clean_imagem()
        finally:
            if original is None: self.cleaned_data.pop('imagem',None)
            else: self.cleaned_data['imagem']=original


class ReabrirForm(forms.Form):
    justificativa = forms.CharField(min_length=10, max_length=2000, widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}))
