from django import forms
from django.forms import inlineformset_factory

from .models import Cliente, ContatoCliente, Unidade
from platform_core.forms import TenantModelForm


class ClienteForm(TenantModelForm):
    class Meta:
        model = Cliente
        fields = [
            "tipo_pessoa",
            "nome_razao_social",
            "nome_fantasia",
            "cpf_cnpj",
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
            "telefone",
            "ativo",
        ]
