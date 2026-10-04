from django import forms

from clientes.models import Unidade
from .models import Equipamento, CategoriaEquipamento
from platform_core.forms import TenantModelForm


class EquipamentoForm(TenantModelForm):
    class Meta:
        model = Equipamento
        fields = [
            "codigo_interno",
            "numero_serie",
            "nome",
            "categoria",
            "fabricante",
            "marca", "tipo", "registro_anvisa", "tensao", "potencia", "situacao_cadastro",
            "modelo",
            "cliente",
            "unidade",
            "setor",
            "localizacao", "patrimonio", "data_aquisicao", "criticidade",
            "data_instalacao",
            "data_fim_garantia",
            "periodicidade_preventiva_meses",
            "periodicidade_calibracao_meses",
            "data_ultima_preventiva",
            "data_ultima_calibracao",
            "situacao_operacional",
            "foto",
            "manual",
            "observacoes",
        ]
        widgets = {
            "data_aquisicao": forms.DateInput(attrs={"type": "date"}, format='%Y-%m-%d'),
            "data_instalacao": forms.DateInput(attrs={"type": "date"}),
            "data_fim_garantia": forms.DateInput(attrs={"type": "date"}),
            "data_ultima_preventiva": forms.DateInput(attrs={"type": "date"}),
            "data_ultima_calibracao": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cliente_id = None
        if self.data.get("cliente"):
            cliente_id = self.data.get("cliente")
        elif self.instance and self.instance.pk:
            cliente_id = self.instance.cliente_id
        if cliente_id and str(cliente_id).isdigit():
            self.fields["unidade"].queryset = Unidade.objects.filter(cliente_id=cliente_id)
        else:
            self.fields["unidade"].queryset = Unidade.objects.none()


class CategoriaForm(TenantModelForm):
    class Meta:
        model = CategoriaEquipamento
        fields = ['nome', 'descricao']
