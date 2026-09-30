from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError
from platform_core.tenancy import OrganizationOwned
from platform_core.access import effective_role


class Perfil(models.TextChoices):
    ADMINISTRADOR = "ADMIN", "Administrador"
    GESTOR = "GESTOR", "Gestor"
    TECNICO = "TECNICO", "Técnico"
    ESTOQUISTA = "ESTOQUE", "Estoquista"
    FINANCEIRO = "FINANCEIRO", "Financeiro"


class Usuario(AbstractUser):
    """
    Usuário do sistema. O cadastro de dados profissionais do técnico
    (especialidades, custo/hora, etc.) fica em Tecnico, vinculado
    opcionalmente a este usuário — uma pessoa pode existir como técnico
    sem ter login, e um login pode existir sem registro de técnico
    (ex.: financeiro, gestor).
    """

    perfil = models.CharField(
        max_length=20,
        choices=Perfil.choices,
        default=Perfil.TECNICO,
        verbose_name="Perfil de acesso",
    )
    telefone = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_administrador(self):
        return effective_role(self) == Perfil.ADMINISTRADOR

    @property
    def is_gestor(self):
        return effective_role(self) == Perfil.GESTOR

    @property
    def is_tecnico(self):
        return effective_role(self) == Perfil.TECNICO

    @property
    def is_estoquista(self):
        return effective_role(self) == Perfil.ESTOQUISTA

    @property
    def is_financeiro(self):
        return effective_role(self) == Perfil.FINANCEIRO


class Tecnico(OrganizationOwned):
    """
    Ficha profissional do técnico. Separada da conta de acesso (Usuario)
    conforme pedido: um técnico pode existir sem login, e pode ser
    vinculado a um usuário depois.
    """

    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fichas_tecnico",
        verbose_name="Conta de acesso vinculada",
    )
    nome = models.CharField(max_length=150)
    telefone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    especialidades = models.CharField(
        max_length=255,
        blank=True,
        help_text="Ex.: equipamentos odontológicos, ventiladores, autoclaves...",
    )
    registro_profissional = models.CharField(
        max_length=100, blank=True, help_text="Ex.: CREA, CRT, etc., quando aplicável."
    )
    jornada = models.CharField(
        max_length=100,
        blank=True,
        help_text="Ex.: Seg a sex, 08h-18h",
    )
    custo_hora = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Visível apenas para administradores e gestores.",
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Técnico"
        verbose_name_plural = "Técnicos"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=['organization', 'usuario'], condition=models.Q(usuario__isnull=False), name='tecnico_usuario_por_org')]

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        from platform_core.models import OrganizationMembership
        if self.usuario_id and not OrganizationMembership.objects.filter(organization_id=self.organization_id, user_id=self.usuario_id).exists():
            raise ValidationError({'usuario': 'Usuário deve possuir vínculo com esta organização.'})

    def save(self, *args, **kwargs):
        self.validate_tenant()
        self.clean()
        return super().save(*args, **kwargs)
