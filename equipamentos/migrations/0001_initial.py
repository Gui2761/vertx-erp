import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("clientes", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoriaEquipamento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100, unique=True)),
                ("descricao", models.CharField(blank=True, max_length=255)),
            ],
            options={
                "verbose_name": "Categoria de equipamento",
                "verbose_name_plural": "Categorias de equipamento",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Equipamento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo_publico", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                (
                    "codigo_interno",
                    models.CharField(
                        blank=True, db_index=True, max_length=50, verbose_name="Código interno / patrimônio"
                    ),
                ),
                ("numero_serie", models.CharField(blank=True, max_length=100, verbose_name="Número de série")),
                ("nome", models.CharField(max_length=150)),
                ("fabricante", models.CharField(blank=True, max_length=150)),
                ("modelo", models.CharField(blank=True, max_length=150)),
                ("setor", models.CharField(blank=True, max_length=100)),
                ("data_instalacao", models.DateField(blank=True, null=True)),
                ("data_fim_garantia", models.DateField(blank=True, null=True)),
                (
                    "periodicidade_preventiva_meses",
                    models.PositiveIntegerField(
                        blank=True, help_text="Intervalo entre manutenções preventivas, em meses.", null=True
                    ),
                ),
                (
                    "periodicidade_calibracao_meses",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Intervalo entre calibrações, em meses (quando aplicável).",
                        null=True,
                    ),
                ),
                ("data_ultima_preventiva", models.DateField(blank=True, null=True)),
                ("data_ultima_calibracao", models.DateField(blank=True, null=True)),
                (
                    "situacao_operacional",
                    models.CharField(
                        choices=[
                            ("OK", "Funcionando"),
                            ("RESTRICAO", "Funcionando com restrição"),
                            ("INOPERANTE", "Inoperante"),
                            ("DESATIVADO", "Desativado"),
                        ],
                        default="OK",
                        max_length=20,
                    ),
                ),
                ("foto", models.ImageField(blank=True, null=True, upload_to="equipamentos/fotos/")),
                ("manual", models.FileField(blank=True, null=True, upload_to="equipamentos/manuais/")),
                ("observacoes", models.TextField(blank=True)),
                ("qr_code", models.ImageField(blank=True, null=True, upload_to="equipamentos/qrcodes/")),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "categoria",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipamentos",
                        to="equipamentos.categoriaequipamento",
                    ),
                ),
                (
                    "cliente",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipamentos",
                        to="clientes.cliente",
                    ),
                ),
                (
                    "unidade",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipamentos",
                        to="clientes.unidade",
                    ),
                ),
            ],
            options={
                "verbose_name": "Equipamento",
                "verbose_name_plural": "Equipamentos",
                "ordering": ["nome"],
            },
        ),
    ]
