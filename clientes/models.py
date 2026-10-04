from django.db import models
from platform_core.tenancy import OrganizationOwned, TenantOwned


class TipoPessoa(models.TextChoices):
    FISICA = "PF", "Pessoa física"
    JURIDICA = "PJ", "Pessoa jurídica / Empresa"


class Cliente(OrganizationOwned):
    """
    Cliente da assistência técnica: pode ser pessoa física, empresa,
    clínica, hospital ou órgão público. Um cliente pode ter várias
    unidades, e cada unidade pode ter vários equipamentos.
    """

    tipo_pessoa = models.CharField(max_length=2, choices=TipoPessoa.choices, default=TipoPessoa.JURIDICA)
    nome_razao_social = models.CharField("Nome / Razão social", max_length=255)
    nome_fantasia = models.CharField("Nome fantasia", max_length=255, blank=True)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=20)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    inscricao_municipal = models.CharField(max_length=30, blank=True)
    responsavel = models.CharField(max_length=150, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    endereco = models.CharField(max_length=255, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    cep = models.CharField(max_length=10, blank=True)

    observacoes = models.TextField(blank=True)
    limite_credito = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["nome_razao_social"]
        constraints = [models.UniqueConstraint(fields=['organization', 'cpf_cnpj'], name='cliente_documento_por_org')]

    def __str__(self):
        return self.nome_razao_social


class ContatoCliente(TenantOwned):
    tenant_lookup = 'cliente__organization_id'
    """Pessoa responsável do lado do cliente (ex.: gerente de manutenção)."""

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contatos")
    nome = models.CharField(max_length=150)
    cargo = models.CharField(max_length=100, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    principal = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Contato do cliente"
        verbose_name_plural = "Contatos do cliente"

    def __str__(self):
        return f"{self.nome} ({self.cliente.nome_razao_social})"


class Unidade(TenantOwned):
    tenant_lookup = 'cliente__organization_id'
    """Unidade/filial/setor físico do cliente onde os equipamentos ficam."""

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="unidades")
    nome = models.CharField(max_length=150, help_text="Ex.: Matriz, Filial Centro, Bloco Cirúrgico")
    setor = models.CharField(max_length=100, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    cep = models.CharField(max_length=10, blank=True)
    responsavel_local = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    observacoes = models.TextField(blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Unidade"
        verbose_name_plural = "Unidades"
        ordering = ["cliente__nome_razao_social", "nome"]

    def __str__(self):
        return f"{self.nome} - {self.cliente.nome_razao_social}"
