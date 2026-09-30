import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Cliente",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "tipo_pessoa",
                    models.CharField(
                        choices=[("PF", "Pessoa física"), ("PJ", "Pessoa jurídica / Empresa")],
                        default="PJ",
                        max_length=2,
                    ),
                ),
                ("nome_razao_social", models.CharField(max_length=255, verbose_name="Nome / Razão social")),
                ("nome_fantasia", models.CharField(blank=True, max_length=255, verbose_name="Nome fantasia")),
                ("cpf_cnpj", models.CharField(max_length=20, unique=True, verbose_name="CPF/CNPJ")),
                ("telefone", models.CharField(blank=True, max_length=20)),
                ("whatsapp", models.CharField(blank=True, max_length=20)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("endereco", models.CharField(blank=True, max_length=255)),
                ("numero", models.CharField(blank=True, max_length=20)),
                ("complemento", models.CharField(blank=True, max_length=100)),
                ("bairro", models.CharField(blank=True, max_length=100)),
                ("cidade", models.CharField(blank=True, max_length=100)),
                ("uf", models.CharField(blank=True, max_length=2)),
                ("cep", models.CharField(blank=True, max_length=10)),
                ("observacoes", models.TextField(blank=True)),
                ("ativo", models.BooleanField(default=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Cliente",
                "verbose_name_plural": "Clientes",
                "ordering": ["nome_razao_social"],
            },
        ),
        migrations.CreateModel(
            name="Unidade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "nome",
                    models.CharField(
                        help_text="Ex.: Matriz, Filial Centro, Bloco Cirúrgico", max_length=150
                    ),
                ),
                ("setor", models.CharField(blank=True, max_length=100)),
                ("endereco", models.CharField(blank=True, max_length=255)),
                ("numero", models.CharField(blank=True, max_length=20)),
                ("bairro", models.CharField(blank=True, max_length=100)),
                ("cidade", models.CharField(blank=True, max_length=100)),
                ("uf", models.CharField(blank=True, max_length=2)),
                ("cep", models.CharField(blank=True, max_length=10)),
                ("responsavel_local", models.CharField(blank=True, max_length=150)),
                ("telefone", models.CharField(blank=True, max_length=20)),
                ("ativo", models.BooleanField(default=True)),
                (
                    "cliente",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="unidades",
                        to="clientes.cliente",
                    ),
                ),
            ],
            options={
                "verbose_name": "Unidade",
                "verbose_name_plural": "Unidades",
                "ordering": ["cliente__nome_razao_social", "nome"],
            },
        ),
        migrations.CreateModel(
            name="ContatoCliente",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=150)),
                ("cargo", models.CharField(blank=True, max_length=100)),
                ("telefone", models.CharField(blank=True, max_length=20)),
                ("whatsapp", models.CharField(blank=True, max_length=20)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("principal", models.BooleanField(default=False)),
                (
                    "cliente",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contatos",
                        to="clientes.cliente",
                    ),
                ),
            ],
            options={
                "verbose_name": "Contato do cliente",
                "verbose_name_plural": "Contatos do cliente",
            },
        ),
    ]
