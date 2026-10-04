import io
import uuid
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.db import models
from django.core.exceptions import ValidationError
from platform_core.tenancy import OrganizationOwned


def equipment_file(instance, filename, kind):
    suffix = PurePosixPath(filename).suffix.lower()
    if len(suffix) > 12:
        suffix = '.bin'
    return f'organizations/{instance.organization.public_id}/assistencia/equipamentos/{instance.codigo_publico}/{kind}/{uuid.uuid4().hex}{suffix}'


def equipment_photo(instance, filename):
    return equipment_file(instance, filename, 'fotos')


def equipment_manual(instance, filename):
    return equipment_file(instance, filename, 'manuais')


def equipment_qr(instance, filename):
    return equipment_file(instance, filename, 'qr')


class CategoriaEquipamento(OrganizationOwned):
    nome = models.CharField(max_length=100)
    descricao = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Categoria de equipamento"
        verbose_name_plural = "Categorias de equipamento"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='categoria_nome_por_org')]

    def __str__(self):
        return self.nome


class SituacaoOperacional(models.TextChoices):
    FUNCIONANDO = "OK", "Funcionando"
    RESTRICAO = "RESTRICAO", "Funcionando com restrição"
    INOPERANTE = "INOPERANTE", "Inoperante"
    DESATIVADO = "DESATIVADO", "Desativado"


class Equipamento(OrganizationOwned):
    """
    Equipamento hospitalar/odontológico/laboratorial de um cliente.
    A situação operacional é independente da situação de qualquer OS:
    reflete o estado físico do equipamento, não o andamento de um
    atendimento (isso é tratado no app de ordens de serviço, na Etapa 2).
    """

    # identificador público usado no QR Code (não é a chave primária,
    # para não expor sequência interna do banco)
    codigo_publico = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    codigo_interno = models.CharField(
        "Código interno / patrimônio", max_length=50, blank=True, db_index=True
    )
    numero_serie = models.CharField("Número de série", max_length=100, blank=True)
    nome = models.CharField(max_length=150)
    categoria = models.ForeignKey(
        CategoriaEquipamento, on_delete=models.PROTECT, related_name="equipamentos"
    )
    fabricante = models.CharField(max_length=150, blank=True)
    marca = models.CharField(max_length=150, blank=True)
    tipo = models.CharField('Tipo de equipamento', max_length=100, blank=True)
    registro_anvisa = models.CharField('Registro ANVISA (quando aplicável)', max_length=100, blank=True)
    tensao = models.CharField('Tensão', max_length=60, blank=True)
    potencia = models.CharField('Potência', max_length=60, blank=True)
    situacao_cadastro = models.CharField('Situação do cadastro', max_length=20, blank=True, choices=[('ATIVO', 'Ativo'), ('INATIVO', 'Inativo'), ('MANUTENCAO', 'Em manutenção'), ('AG_PECA', 'Aguardando peça'), ('FORA_USO', 'Fora de uso'), ('BAIXADO', 'Baixado')], help_text='Independente da condição física. Vazio: histórico sem classificação.')
    modelo = models.CharField(max_length=150, blank=True)

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="equipamentos"
    )
    unidade = models.ForeignKey(
        "clientes.Unidade",
        on_delete=models.PROTECT,
        related_name="equipamentos",
        null=True,
        blank=True,
    )
    setor = models.CharField(max_length=100, blank=True)
    localizacao = models.CharField('Localização', max_length=255, blank=True)
    patrimonio = models.CharField('Patrimônio', max_length=80, blank=True)
    data_aquisicao = models.DateField(null=True, blank=True)
    criticidade = models.CharField(max_length=10, choices=[('BAIXA', 'Baixa'), ('MEDIA', 'Média'), ('ALTA', 'Alta'), ('CRITICA', 'Crítica')], default='MEDIA', blank=True)

    data_instalacao = models.DateField(null=True, blank=True)
    data_fim_garantia = models.DateField(null=True, blank=True)

    periodicidade_preventiva_meses = models.PositiveIntegerField(
        null=True, blank=True, help_text="Intervalo entre manutenções preventivas, em meses."
    )
    periodicidade_calibracao_meses = models.PositiveIntegerField(
        null=True, blank=True, help_text="Intervalo entre calibrações, em meses (quando aplicável)."
    )
    data_ultima_preventiva = models.DateField(null=True, blank=True)
    data_ultima_calibracao = models.DateField(null=True, blank=True)

    situacao_operacional = models.CharField(
        max_length=20,
        choices=SituacaoOperacional.choices,
        default=SituacaoOperacional.FUNCIONANDO,
    )

    foto = models.ImageField(upload_to=equipment_photo, max_length=500, null=True, blank=True)
    manual = models.FileField(upload_to=equipment_manual, max_length=500, null=True, blank=True)
    observacoes = models.TextField(blank=True)

    qr_code = models.ImageField(upload_to=equipment_qr, max_length=500, null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Equipamento"
        verbose_name_plural = "Equipamentos"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.cliente.nome_razao_social})"

    def clean(self):
        super().clean()
        if self.unidade_id and self.unidade.cliente_id != self.cliente_id:
            raise ValidationError({'unidade': 'Unidade deve pertencer ao cliente do equipamento.'})

    def save(self, *args, **kwargs):
        self.validate_tenant()
        self.clean()
        return super().save(*args, **kwargs)

    @property
    def proxima_preventiva(self):
        from operacao.models import PreventivaProgramada, ENCERRADAS
        from gestao.models import AgendaPreventiva
        dates = list(PreventivaProgramada.objects.filter(equipamento=self, plano__ativo=True, cancelada=False).exclude(ordem__status__in=ENCERRADAS).values_list('data', flat=True))
        dates += list(AgendaPreventiva.objects.filter(equipamento=self, cancelada=False).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO']).exclude(ordem__status__in=ENCERRADAS).values_list('data_prevista', flat=True))
        if dates:
            return min(dates)
        if self.data_ultima_preventiva and self.periodicidade_preventiva_meses:
            from dateutil.relativedelta import relativedelta

            return self.data_ultima_preventiva + relativedelta(
                months=self.periodicidade_preventiva_meses
            )
        return None

    @property
    def proxima_calibracao(self):
        if self.data_ultima_calibracao and self.periodicidade_calibracao_meses:
            from dateutil.relativedelta import relativedelta

            return self.data_ultima_calibracao + relativedelta(
                months=self.periodicidade_calibracao_meses
            )
        return None

    def gerar_qr_code(self, base_url=""):
        """
        Gera a imagem de QR Code apontando para a ficha pública do
        equipamento (a view por trás da URL exige login, então o QR
        Code por si só não expõe dados a quem não tem permissão).
        """
        import qrcode

        url = f"{base_url}/equipamentos/qr/{self.codigo_publico}/"
        img = qrcode.make(url)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        nome_arquivo = f"qrcode_{self.codigo_publico}.png"
        self.qr_code.save(nome_arquivo, ContentFile(buffer.getvalue()), save=False)
