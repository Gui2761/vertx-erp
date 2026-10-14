import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from platform_core.models import ERPCatalog, MembershipERP, OrganizationERP, OrganizationMembership
from platform_core.tenancy import OrganizationOwned, TenantManager, TenantOwned, TenantQuerySet


PRODUCT_CODE = 'gestao-publica'


def product_enabled(organization_id):
    return bool(organization_id and OrganizationERP.objects.filter(
        organization_id=organization_id, erp__code=PRODUCT_CODE,
        erp__active=True, enabled=True,
    ).exists())


class MunicipalRecord(OrganizationOwned):
    """Tenant-owned record that can only exist under the Public Management ERP."""

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if not product_enabled(self.organization_id):
            raise ValidationError('O registro exige ERP Gestão Pública habilitado nesta organização.')

    def save(self, *args, **kwargs):
        self.validate_tenant()
        self.full_clean()
        return super().save(*args, **kwargs)


class CatalogoMunicipal(MunicipalRecord):
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=150)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Secretaria(CatalogoMunicipal):
    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_secretaria_codigo')]


class DepartamentoMunicipal(CatalogoMunicipal):
    secretaria = models.ForeignKey(Secretaria, on_delete=models.PROTECT, related_name='departamentos')

    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_depto_codigo')]


class SetorMunicipal(CatalogoMunicipal):
    departamento = models.ForeignKey(DepartamentoMunicipal, on_delete=models.PROTECT, related_name='setores')

    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_setor_codigo')]


class UnidadeMunicipal(CatalogoMunicipal):
    setor = models.ForeignKey(SetorMunicipal, on_delete=models.PROTECT, related_name='unidades')

    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_unidade_codigo')]


class CargoMunicipal(CatalogoMunicipal):
    carga_horaria_semanal = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_cargo_codigo')]


class FuncaoMunicipal(CatalogoMunicipal):
    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_funcao_codigo')]


class VinculoFuncional(CatalogoMunicipal):
    class Meta(CatalogoMunicipal.Meta):
        abstract = False
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_vinculo_codigo')]


class JornadaMunicipal(MunicipalRecord):
    nome = models.CharField(max_length=100)
    semana = models.JSONField(default=dict, help_text='Parâmetros informativos; regras locais devem ser homologadas antes do cálculo de folha/ponto.')
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='rhmun_jornada_nome')]

    def __str__(self):
        return self.nome


class Servidor(MunicipalRecord):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='servidores_municipais')
    matricula = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    nome_social = models.CharField(max_length=180, blank=True)
    cpf = models.CharField(max_length=14, blank=True)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    secretaria = models.ForeignKey(Secretaria, on_delete=models.PROTECT, related_name='servidores')
    departamento = models.ForeignKey(DepartamentoMunicipal, on_delete=models.PROTECT, related_name='servidores')
    setor = models.ForeignKey(SetorMunicipal, on_delete=models.PROTECT, related_name='servidores')
    unidade = models.ForeignKey(UnidadeMunicipal, on_delete=models.PROTECT, related_name='servidores')
    cargo = models.ForeignKey(CargoMunicipal, on_delete=models.PROTECT, related_name='servidores')
    funcao = models.ForeignKey(FuncaoMunicipal, on_delete=models.PROTECT, null=True, blank=True, related_name='servidores')
    vinculo = models.ForeignKey(VinculoFuncional, on_delete=models.PROTECT, related_name='servidores')
    jornada = models.ForeignKey(JornadaMunicipal, on_delete=models.PROTECT, null=True, blank=True, related_name='servidores')
    data_admissao = models.DateField(null=True, blank=True)
    data_desligamento = models.DateField(null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'matricula'], name='rhmun_matricula_org'),
            models.UniqueConstraint(fields=['organization', 'usuario'], condition=models.Q(usuario__isnull=False), name='rhmun_usuario_org'),
        ]

    def clean(self):
        super().clean()
        if not self.secretaria_id or not self.departamento_id or not self.setor_id or not self.unidade_id:
            return
        if self.departamento.secretaria_id != self.secretaria_id:
            raise ValidationError({'departamento': 'O departamento não pertence à secretaria informada.'})
        if self.setor.departamento_id != self.departamento_id:
            raise ValidationError({'setor': 'O setor não pertence ao departamento informado.'})
        if self.unidade.setor_id != self.setor_id:
            raise ValidationError({'unidade': 'A unidade não pertence ao setor informado.'})
        if self.data_admissao and self.data_desligamento and self.data_desligamento < self.data_admissao:
            raise ValidationError({'data_desligamento': 'A data de desligamento não pode anteceder a admissão.'})
        if self.usuario_id and not MembershipERP.objects.filter(
            membership__user_id=self.usuario_id, membership__organization_id=self.organization_id,
            membership__status='ATIVO', erp__code=PRODUCT_CODE, enabled=True, erp__active=True,
        ).exists():
            raise ValidationError({'usuario': 'A conta precisa ter membership ativo e acesso ao ERP Gestão Pública nesta organização.'})

    def __str__(self):
        return f'{self.matricula} · {self.nome}'


class AcessoRH(TenantOwned):
    tenant_lookup = 'membership__organization_id'
    class Papel(models.TextChoices):
        ADMIN_MUNICIPAL = 'ADMIN_MUNICIPAL', 'Administrador municipal'
        GESTOR_RH = 'GESTOR_RH', 'Gestor de RH'
        RH_OPERADOR = 'RH_OPERADOR', 'Operador de RH'
        CHEFIA = 'CHEFIA', 'Chefia'
        SERVIDOR = 'SERVIDOR', 'Servidor'

    membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT, related_name='acessos_rh_municipal')
    papel = models.CharField(max_length=24, choices=Papel.choices)
    ativo = models.BooleanField(default=True)
    atribuido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='acessos_rh_municipal_atribuidos')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['membership', 'papel'], name='rhmun_acesso_membership_papel')]

    def clean(self):
        super().clean()
        if self.membership_id and (self.membership.status != 'ATIVO' or not MembershipERP.objects.filter(
            membership=self.membership, erp__code=PRODUCT_CODE, erp__active=True, enabled=True,
        ).exists()):
            raise ValidationError('Acesso exige membership ativo no ERP Gestão Pública.')
        if self.atribuido_por_id and not self.atribuido_por.memberships.filter(
            organization_id=self.membership.organization_id, status='ATIVO',
        ).exists():
            raise ValidationError({'atribuido_por': 'Quem atribui o acesso deve pertencer à mesma organização.'})

    def save(self, *args, **kwargs):
        self.validate_tenant()
        self.full_clean()
        return super().save(*args, **kwargs)


class MunicipalHistoryQuerySet(TenantQuerySet):
    def delete(self):
        raise ValidationError('Histórico funcional municipal não pode ser excluído.')


class RegistroMunicipalImutavel(MunicipalRecord):
    objects = TenantManager.from_queryset(MunicipalHistoryQuerySet)()
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('Use o serviço municipal auditado; o registro é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Histórico municipal não pode ser excluído.')


class HistoricoServidor(RegistroMunicipalImutavel):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='historico')
    acao = models.CharField(max_length=60)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)


class SolicitacaoServidor(RegistroMunicipalImutavel):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='solicitacoes')
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request_id = models.UUIDField(default=uuid.uuid4, editable=False)
    tipo = models.CharField(max_length=32, choices=[
        ('FERIAS', 'Férias'), ('AFASTAMENTO', 'Afastamento'),
        ('CORRECAO_PONTO', 'Correção de ponto'), ('DOCUMENTO', 'Documento'),
        ('ATUALIZACAO_CADASTRAL', 'Atualização cadastral'),
    ])
    descricao = models.TextField()
    dados = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'request_id'], name='rhmun_solic_request')]

    @property
    def status(self):
        try:
            return 'APROVADA' if self.decisao.aprovada else 'RECUSADA'
        except DecisaoSolicitacaoServidor.DoesNotExist:
            return 'PENDENTE'


class DecisaoSolicitacaoServidor(RegistroMunicipalImutavel):
    solicitacao = models.OneToOneField(SolicitacaoServidor, on_delete=models.PROTECT, related_name='decisao')
    aprovada = models.BooleanField()
    motivo = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        super().clean()
        if self.usuario_id and not self.usuario.memberships.filter(organization_id=self.organization_id, status='ATIVO').exists():
            raise ValidationError({'usuario': 'Quem decide deve pertencer à mesma organização.'})


class PontoServidor(RegistroMunicipalImutavel):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='marcacoes_ponto')
    request_id = models.UUIDField(default=uuid.uuid4, editable=False)
    tipo = models.CharField(max_length=24, choices=[('ENTRADA','Entrada'),('SAIDA_INTERVALO','Saída para intervalo'),('RETORNO_INTERVALO','Retorno do intervalo'),('SAIDA','Saída')])
    data_hora = models.DateTimeField(default=timezone.now, editable=False)
    origem = models.CharField(max_length=12, choices=[('WEB','Web'),('MOBILE','Mobile')], default='WEB')
    dispositivo = models.CharField(max_length=160, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'request_id'], name='rhmun_ponto_request')]


class FeriasServidor(MunicipalRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='ferias')
    inicio = models.DateField()
    fim = models.DateField()
    status = models.CharField(max_length=16, choices=[('SOLICITADA','Solicitada'),('APROVADA','Aprovada'),('RECUSADA','Recusada'),('CANCELADA','Cancelada')], default='SOLICITADA')
    observacao = models.TextField(blank=True)

    def clean(self):
        super().clean()
        if self.inicio and self.fim and self.fim < self.inicio:
            raise ValidationError({'fim': 'O fim das férias deve ser igual ou posterior ao início.'})


class AfastamentoServidor(MunicipalRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='afastamentos')
    tipo = models.CharField(max_length=40)
    inicio = models.DateField()
    fim = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=[('SOLICITADO','Solicitado'),('REGISTRADO','Registrado'),('ENCERRADO','Encerrado'),('RECUSADO','Recusado')], default='SOLICITADO')
    observacao = models.TextField(blank=True)

    def clean(self):
        super().clean()
        if self.inicio and self.fim and self.fim < self.inicio:
            raise ValidationError({'fim': 'O fim do afastamento deve ser igual ou posterior ao início.'})


class DocumentoServidor(MunicipalRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='documentos')
    titulo = models.CharField(max_length=160)
    categoria = models.CharField(max_length=40)
    storage_key = models.CharField(max_length=500)
    sha256 = models.CharField(max_length=64, blank=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        prefix = f'organizations/{self.organization.public_id}/gestao-publica/servidores/{self.servidor.public_id}/'
        if not self.storage_key.startswith(prefix) or '..' in self.storage_key.split('/') or '\\' in self.storage_key:
            raise ValidationError({'storage_key': 'O documento deve usar chave privada deste servidor e organização.'})
