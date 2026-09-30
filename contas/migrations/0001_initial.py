import django.contrib.auth.models
import django.contrib.auth.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="Usuario",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                (
                    "is_superuser",
                    models.BooleanField(
                        default=False,
                        help_text="Designates that this user has all permissions without explicitly assigning them.",
                        verbose_name="superuser status",
                    ),
                ),
                (
                    "username",
                    models.CharField(
                        error_messages={"unique": "A user with that username already exists."},
                        help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.",
                        max_length=150,
                        unique=True,
                        validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                        verbose_name="username",
                    ),
                ),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="email address")),
                (
                    "is_staff",
                    models.BooleanField(
                        default=False,
                        help_text="Designates whether the user can log into this admin site.",
                        verbose_name="staff status",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.",
                        verbose_name="active",
                    ),
                ),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date joined")),
                (
                    "perfil",
                    models.CharField(
                        choices=[
                            ("ADMIN", "Administrador"),
                            ("GESTOR", "Gestor"),
                            ("TECNICO", "Técnico"),
                            ("ESTOQUE", "Estoquista"),
                            ("FINANCEIRO", "Financeiro"),
                        ],
                        default="TECNICO",
                        max_length=20,
                        verbose_name="Perfil de acesso",
                    ),
                ),
                ("telefone", models.CharField(blank=True, max_length=20)),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.group",
                        verbose_name="groups",
                    ),
                ),
                (
                    "user_permissions",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Specific permissions for this user.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.permission",
                        verbose_name="user permissions",
                    ),
                ),
            ],
            options={
                "verbose_name": "Usuário",
                "verbose_name_plural": "Usuários",
            },
            managers=[
                ("objects", django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name="Tecnico",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=150)),
                ("telefone", models.CharField(blank=True, max_length=20)),
                ("whatsapp", models.CharField(blank=True, max_length=20)),
                ("email", models.EmailField(blank=True, max_length=254)),
                (
                    "especialidades",
                    models.CharField(
                        blank=True,
                        help_text="Ex.: equipamentos odontológicos, ventiladores, autoclaves...",
                        max_length=255,
                    ),
                ),
                (
                    "registro_profissional",
                    models.CharField(
                        blank=True, help_text="Ex.: CREA, CRT, etc., quando aplicável.", max_length=100
                    ),
                ),
                (
                    "jornada",
                    models.CharField(blank=True, help_text="Ex.: Seg a sex, 08h-18h", max_length=100),
                ),
                (
                    "custo_hora",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Visível apenas para administradores e gestores.",
                        max_digits=10,
                        null=True,
                    ),
                ),
                ("ativo", models.BooleanField(default=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "usuario",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ficha_tecnico",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Conta de acesso vinculada",
                    ),
                ),
            ],
            options={
                "verbose_name": "Técnico",
                "verbose_name_plural": "Técnicos",
                "ordering": ["nome"],
            },
        ),
    ]
