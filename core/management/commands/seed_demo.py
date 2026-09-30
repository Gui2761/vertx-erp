import datetime

from django.core.management.base import BaseCommand

from clientes.models import Cliente, ContatoCliente, TipoPessoa, Unidade
from contas.models import Perfil, Tecnico, Usuario
from equipamentos.models import CategoriaEquipamento, Equipamento, SituacaoOperacional
from platform_core.models import Organization
from platform_core.context import tenant_context
from django.core.management.base import CommandError


class Command(BaseCommand):
    help = (
        "Carrega dados de demonstração (opcional). Cria clientes, unidades, "
        "categorias, equipamentos e um técnico de exemplo, claramente "
        "identificados como demonstrativos. Não afeta dados reais já cadastrados."
    )

    def add_arguments(self, parser):
        parser.add_argument('--organization', default='tecnolmed', help='Slug da organização que receberá os dados demo.')

    def handle(self, *args, **options):
        try:
            organization = Organization.objects.get(slug=options['organization'], status='ATIVA')
        except Organization.DoesNotExist:
            raise CommandError('Organização ativa não encontrada.')
        with tenant_context(organization):
            return self.seed(*args, **options)

    def seed(self, *args, **options):
        categoria_odonto, _ = CategoriaEquipamento.objects.get_or_create(
            nome="Odontológico", defaults={"descricao": "Equipamentos odontológicos"}
        )
        categoria_hospitalar, _ = CategoriaEquipamento.objects.get_or_create(
            nome="Hospitalar", defaults={"descricao": "Equipamentos hospitalares"}
        )

        cliente, criado = Cliente.objects.get_or_create(
            cpf_cnpj="00.000.000/0001-00",
            defaults=dict(
                tipo_pessoa=TipoPessoa.JURIDICA,
                nome_razao_social="[DEMO] Clínica Modelo Ltda",
                telefone="(82) 90000-0000",
                email="contato@clinicamodelo.exemplo",
                cidade="Maceió",
                uf="AL",
            ),
        )
        if criado:
            ContatoCliente.objects.create(
                cliente=cliente, nome="[DEMO] Maria Responsável", cargo="Gerente", principal=True
            )

        unidade, _ = Unidade.objects.get_or_create(
            cliente=cliente, nome="[DEMO] Unidade Matriz", defaults={"cidade": "Maceió", "uf": "AL"}
        )

        Equipamento.objects.get_or_create(
            nome="[DEMO] Autoclave 21L",
            cliente=cliente,
            defaults=dict(
                unidade=unidade,
                categoria=categoria_odonto,
                fabricante="Fabricante Exemplo",
                modelo="AX-21",
                periodicidade_preventiva_meses=6,
                data_ultima_preventiva=datetime.date.today() - datetime.timedelta(days=150),
                situacao_operacional=SituacaoOperacional.FUNCIONANDO,
            ),
        )
        Equipamento.objects.get_or_create(
            nome="[DEMO] Monitor Multiparâmetro",
            cliente=cliente,
            defaults=dict(
                unidade=unidade,
                categoria=categoria_hospitalar,
                fabricante="Fabricante Exemplo",
                modelo="MM-500",
                periodicidade_calibracao_meses=12,
                situacao_operacional=SituacaoOperacional.RESTRICAO,
            ),
        )

        if not Tecnico.objects.filter(nome="[DEMO] Técnico Exemplo").exists():
            Tecnico.objects.create(
                nome="[DEMO] Técnico Exemplo",
                especialidades="Equipamentos odontológicos e hospitalares",
                telefone="(82) 90000-1111",
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Dados de demonstração carregados (todos com prefixo [DEMO])."
            )
        )
