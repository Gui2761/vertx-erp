from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError

from .models import Cliente, ContatoCliente, Unidade
from platform_core.forms import TenantModelForm


class ClienteForm(TenantModelForm):
    def __init__(self,*args,user=None,**kwargs):
        super().__init__(*args,**kwargs)
        from platform_core.modules import has_capability
        if not user or not has_capability(user,'credito_cliente'):
            self.fields.pop('limite_credito',None)
        else:
            self.fields['limite_credito'].min_value=0
    def clean_limite_credito(self):
        value=self.cleaned_data.get('limite_credito')
        if value is not None and value<0: raise ValidationError('Limite não pode ser negativo.')
        return value
    class Meta:
        model = Cliente
        fields = [
            "tipo_pessoa",
            "nome_razao_social",
            "nome_fantasia",
            "cpf_cnpj",
            "inscricao_estadual", "inscricao_municipal", "responsavel",
            "telefone",
            "whatsapp",
            "email",
            "endereco",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "cep",
            "observacoes",
            "limite_credito",
            "ativo",
        ]


ContatoFormSet = inlineformset_factory(
    Cliente,
    ContatoCliente,
    fields=["nome", "cargo", "telefone", "whatsapp", "email", "principal"],
    extra=1,
    can_delete=True,
)


class UnidadeForm(TenantModelForm):
    class Meta:
        model = Unidade
        fields = [
            "cliente",
            "nome",
            "setor",
            "endereco",
            "numero",
            "bairro",
            "cidade",
            "uf",
            "cep",
            "responsavel_local",
            "email", "observacoes",
            "telefone",
            "ativo",
        ]
