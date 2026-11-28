"""Comando Django para popular dados REAIS e completos de Engenharia Clínica para demonstração nas Prefeituras de Teotônio Vilela (AL) e Campo Alegre (AL)."""
from __future__ import annotations

import decimal
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clientes.models import Cliente, TipoPessoa, Unidade
from contas.models import Tecnico, Usuario
from equipamentos.models import CategoriaEquipamento, Equipamento, SituacaoOperacional
from ordens.models import OrdemServico, Status
from platform_core.context import tenant_context
from platform_core.models import Organization, OrganizationMembership


class Command(BaseCommand):
    help = "Popula dados de demonstração de Engenharia Clínica Hospitalar para Teotônio Vilela e Campo Alegre (AL)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-slug',
            type=str,
            default='',
            help='Slug da organização destino. Se vazio, usa a primeira organização ativa do sistema.',
        )

    def handle(self, *args, **options):
        slug = options.get('org_slug')
        if slug:
            org = Organization.objects.filter(slug=slug).first()
        else:
            org = Organization.objects.first()

        if not org:
            self.stderr.write(self.style.ERROR("Nenhuma organização encontrada no sistema. Crie ao menos uma organização."))
            return

        self.stdout.write(self.style.SUCCESS(f"Iniciando população da Demo Alagoas na organização: {org.razao_social} ({org.slug})"))

        with tenant_context(org):
            with transaction.atomic():
                self._popular_demo(org)

        self.stdout.write(self.style.SUCCESS("Dados da Demo Alagoas populados com sucesso!"))

    def _popular_demo(self, org: Organization):
        hoje = timezone.localdate()

        # 1. Usuário e Técnico Responsável
        from platform_core.models import OrganizationMembership
        admin_user = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        if admin_user:
            OrganizationMembership.objects.get_or_create(
                organization=org,
                user=admin_user,
                defaults={'role': 'ADMIN', 'status': 'ATIVO'}
            )
        tecnico, _ = Tecnico.objects.get_or_create(
            organization=org,
            nome="Eng. Rafael Tenório (RT Biomédico)",
            defaults={
                'registro_profissional': 'CREA-AL 021489/D',
                'especialidades': 'Engenharia Clínica, Calibração Biomédica, Eletromedicina e CME',
                'email': 'rafael.tenorio@vertyx.com.br',
                'telefone': '(82) 99124-8890',
                'whatsapp': '(82) 99124-8890',
                'ativo': True,
                'usuario': admin_user,
            },
        )

        # 2. Categorias de Equipamentos Hospitalares
        categorias_dados = [
            ("Cardiologia & Suporte de Vida", "Desfibriladores, cardioversores, marcapassos e eletrocardiógrafos."),
            ("Central de Material & Esterilização (CME)", "Autoclaves hospitalares, termodesinfectoras e seladoras."),
            ("Monitorização & UTI", "Monitores multiparamétricos, oxímetros de pulso e capnógrafos."),
            ("Terapia Intensiva & Infusão", "Bombas de infusão peristálticas e de seringa, ventiladores pulmonares."),
            ("Diagnóstico por Imagem & Odontologia", "Aparelhos de raio-X coluna/pantográfico, ultrassons e fotopolimerizadores."),
            ("Centro Cirúrgico & Anestesia", "Focos cirúrgicos de LED, mesas cirúrgicas e bisturis eletrônicos de alta frequência."),
        ]
        cats = {}
        for nome, desc in categorias_dados:
            cat, _ = CategoriaEquipamento.objects.get_or_create(
                organization=org,
                nome=nome,
                defaults={'descricao': desc},
            )
            cats[nome] = cat

        # 3. Cliente 1: Prefeitura / FMS de Teotônio Vilela (AL)
        cliente_tv, _ = Cliente.objects.get_or_create(
            organization=org,
            cpf_cnpj="12842829000110",
            defaults={
                'nome_razao_social': "FUNDO MUNICIPAL DE SAUDE DE TEOTONIO VILELA",
                'nome_fantasia': "Secretaria Municipal de Saúde de Teotônio Vilela",
                'tipo_pessoa': TipoPessoa.JURIDICA,
                'responsavel': "Secretário Municipal de Saúde / Coord. Engenharia Clínica",
                'telefone': "(82) 3543-1250",
                'whatsapp': "(82) 98822-4411",
                'email': "saude@teotoniovilela.al.gov.br",
                'endereco': "Rua Pedro Cavalcante",
                'numero': "150",
                'bairro': "Centro",
                'cidade': "Teotônio Vilela",
                'uf': "AL",
                'cep': "57265-000",
                'observacoes': "Piloto oficial de Gestão e Engenharia Clínica Hospitalar (4 meses de homologação).",
                'ativo': True,
            },
        )

        # Unidades de Teotônio Vilela
        unid_tv_hosp, _ = Unidade.objects.get_or_create(
            cliente=cliente_tv,
            nome="Hospital Municipal Nossa Senhora das Graças",
            defaults={
                'setor': "Emergência, Centro Cirúrgico, CME e Internação",
                'endereco': "Av. Jorge Duarte",
                'numero': "400",
                'bairro': "Centro",
                'cidade': "Teotônio Vilela",
                'uf': "AL",
                'responsavel_local': "Dra. Fabiana Albuquerque (Diretora Médica)",
                'ativo': True,
            },
        )
        unid_tv_ubs1, _ = Unidade.objects.get_or_create(
            cliente=cliente_tv,
            nome="UBS PSF 01 - Dr. José Maria",
            defaults={
                'setor': "Atenção Básica, Sala de Vacinas e Curativos",
                'endereco': "Rua Manoel Pereira",
                'numero': "85",
                'bairro': "Centro",
                'cidade': "Teotônio Vilela",
                'uf': "AL",
                'responsavel_local': "Enf. Carla Rezende",
                'ativo': True,
            },
        )
        unid_tv_ceo, _ = Unidade.objects.get_or_create(
            cliente=cliente_tv,
            nome="Centro de Especialidades Odontológicas (CEO Municipal)",
            defaults={
                'setor': "Clínica Odontológica Especializada e Radiologia Oral",
                'endereco': "Rua São Jorge",
                'numero': "210",
                'bairro': "São Jorge",
                'cidade': "Teotônio Vilela",
                'uf': "AL",
                'responsavel_local': "Dr. Marcos Vinícius (Coord. Saúde Bucal)",
                'ativo': True,
            },
        )

        # 4. Cliente 2: Prefeitura / FMS de Campo Alegre (AL)
        cliente_ca, _ = Cliente.objects.get_or_create(
            organization=org,
            cpf_cnpj="12207445000126",
            defaults={
                'nome_razao_social': "FUNDO MUNICIPAL DE SAUDE DE CAMPO ALEGRE",
                'nome_fantasia': "Secretaria Municipal de Saúde de Campo Alegre",
                'tipo_pessoa': TipoPessoa.JURIDICA,
                'responsavel': "Gerente Geral de Saúde / Coord. de Infraestrutura",
                'telefone': "(82) 3275-1600",
                'whatsapp': "(82) 99933-7722",
                'email': "saude@campoalegre.al.gov.br",
                'endereco': "Av. Monsenhor Hildebrando",
                'numero': "200",
                'bairro': "Centro",
                'cidade': "Campo Alegre",
                'uf': "AL",
                'cep': "57250-000",
                'observacoes': "Pré-acordo para teste de engenharia clínica e manutenção preventiva da frota de equipamentos.",
                'ativo': True,
            },
        )

        unid_ca_mista, _ = Unidade.objects.get_or_create(
            cliente=cliente_ca,
            nome="Unidade Mista Senador Arnon de Mello",
            defaults={
                'setor': "Pronto Atendimento 24h e Maternidade Local",
                'endereco': "Rua Bom Jesus",
                'numero': "315",
                'bairro': "Centro",
                'cidade': "Campo Alegre",
                'uf': "AL",
                'responsavel_local': "Enf. Luciana Moura (Coord. Geral)",
                'ativo': True,
            },
        )
        unid_ca_ubs2, _ = Unidade.objects.get_or_create(
            cliente=cliente_ca,
            nome="UBS PSF 02 - Povoado Chã da Imbira",
            defaults={
                'setor': "Atenção Primária Rural",
                'endereco': "Praça Central",
                'numero': "s/n",
                'bairro': "Chã da Imbira",
                'cidade': "Campo Alegre",
                'uf': "AL",
                'responsavel_local': "Enf. Thiago Santana",
                'ativo': True,
            },
        )

        # 5. Equipamentos Médicos de Teotônio Vilela (Parque Hospitalar Real)
        equipamentos_tv_dados = [
            {
                'nome': "Desfibrilador Bifásico Cardioversor Mindray BeneHeart D3",
                'patrimonio': "FMS-TV-0142",
                'codigo_interno': "EQ-MED-0142",
                'numero_serie': "MD894120",
                'fabricante': "Mindray Medical",
                'modelo': "BeneHeart D3 c/ Pacing Externo e ECG",
                'registro_anvisa': "80070210022",
                'categoria': cats["Cardiologia & Suporte de Vida"],
                'unidade': unid_tv_hosp,
                'setor': "Sala de Emergência / Vermelha",
                'criticidade': "CRITICA",
                'tensao': "Bivolt Automático 110/220V + Bateria Lítio",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=20),
                'data_ultima_preventiva': hoje - timedelta(days=20),
                'observacoes': "Equipamento prioritário de suporte à vida. Aprovado em calibração normatizada NBR IEC 60601-2-4.",
            },
            {
                'nome': "Monitor Multiparamétrico Philips Efficia CM10",
                'patrimonio': "FMS-TV-0089",
                'codigo_interno': "EQ-MED-0089",
                'numero_serie': "PH202491",
                'fabricante': "Philips Medical Systems",
                'modelo': "Efficia CM10 (ECG, SpO2, PNI, Temp, Resp)",
                'registro_anvisa': "10216710214",
                'categoria': cats["Monitorização & UTI"],
                'unidade': unid_tv_hosp,
                'setor': "Leito 02 - Estabilização",
                'criticidade': "ALTA",
                'tensao': "Bivolt 100-240V",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=45),
                'data_ultima_preventiva': hoje - timedelta(days=45),
                'observacoes': "Sensores de SpO2 adulto e manguitos de PNI revisados.",
            },
            {
                'nome': "Autoclave Hospitalar Horizontal Baumer 150L",
                'patrimonio': "FMS-TV-0012",
                'codigo_interno': "EQ-MED-0012",
                'numero_serie': "BM55018",
                'fabricante': "Baumer S.A.",
                'modelo': "Hi-Vac Plus 150 Litros",
                'registro_anvisa': "10167820015",
                'categoria': cats["Central de Material & Esterilização (CME)"],
                'unidade': unid_tv_hosp,
                'setor': "CME Central",
                'criticidade': "CRITICA",
                'tensao': "220V Trifásico",
                'situacao_operacional': SituacaoOperacional.RESTRICAO,
                'periodicidade_calibracao_meses': 6,
                'periodicidade_preventiva_meses': 3,
                'data_ultima_calibracao': hoje - timedelta(days=95),
                'data_ultima_preventiva': hoje - timedelta(days=95),
                'observacoes': "Em atendimento corretivo para troca de guarnição da porta e aferição do manômetro de pressão.",
            },
            {
                'nome': "Ventilador Pulmonar Microtakaoka Carmel",
                'patrimonio': "FMS-TV-0034",
                'codigo_interno': "EQ-MED-0034",
                'numero_serie': "MTK77102",
                'fabricante': "Microtakaoka",
                'modelo': "Carmel Touch UTI Adulto/Pediátrico",
                'registro_anvisa': "10237610118",
                'categoria': cats["Terapia Intensiva & Infusão"],
                'unidade': unid_tv_hosp,
                'setor': "Sala Vermelha / Leito de Suporte Respiratório",
                'criticidade': "CRITICA",
                'tensao': "Bivolt + Bateria",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 6,
                'periodicidade_preventiva_meses': 3,
                'data_ultima_calibracao': hoje - timedelta(days=60),
                'data_ultima_preventiva': hoje - timedelta(days=60),
                'observacoes': "Válvula expiratória esterilizável e sensor de fluxo calibrados.",
            },
            {
                'nome': "Bisturi Eletrônico WEM SS-501SX",
                'patrimonio': "FMS-TV-0021",
                'codigo_interno': "EQ-MED-0021",
                'numero_serie': "WEM41098",
                'fabricante': "WEM Equipamentos Eletrônicos",
                'modelo': "SS-501SX Monopolar e Bipolar 300W",
                'registro_anvisa': "10247670038",
                'categoria': cats["Centro Cirúrgico & Anestesia"],
                'unidade': unid_tv_hosp,
                'setor': "Centro Cirúrgico - Sala 01",
                'criticidade': "ALTA",
                'tensao': "220V",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=120),
                'data_ultima_preventiva': hoje - timedelta(days=120),
                'observacoes': "Placa de retorno capacitiva testada com corrente de fuga em conformidade com IEC 60601-2-2.",
            },
            {
                'nome': "Eletrocardiógrafo Digital Nihon Kohden ECG-2150",
                'patrimonio': "FMS-TV-0077",
                'codigo_interno': "EQ-MED-0077",
                'numero_serie': "NK88410",
                'fabricante': "Nihon Kohden",
                'modelo': "Cardiofax C ECG-2150 12 Derivações",
                'registro_anvisa': "10216710189",
                'categoria': cats["Cardiologia & Suporte de Vida"],
                'unidade': unid_tv_ubs1,
                'setor': "Consultório Médico 02",
                'criticidade': "MEDIA",
                'tensao': "Bivolt",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 12,
                'data_ultima_calibracao': hoje - timedelta(days=180),
                'data_ultima_preventiva': hoje - timedelta(days=180),
                'observacoes': "Cabo de paciente de 10 vias e rolete térmico revisados.",
            },
            {
                'nome': "Aparelho de Raio-X Odontológico Dabi Atlante Spectro 70X",
                'patrimonio': "FMS-TV-0305",
                'codigo_interno': "EQ-MED-0305",
                'numero_serie': "DA70014",
                'fabricante': "Dabi Atlante / Alliage",
                'modelo': "Spectro 70X Coluna Móvel",
                'registro_anvisa': "10069210080",
                'categoria': cats["Diagnóstico por Imagem & Odontologia"],
                'unidade': unid_tv_ceo,
                'setor': "Sala de Radiologia Oral",
                'criticidade': "ALTA",
                'tensao': "220V",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=15),
                'data_ultima_preventiva': hoje - timedelta(days=15),
                'observacoes': "Laudo de radioproteção e exatidão de kVp e tempo de exposição aprovados conforme RDC 611/2022 ANVISA.",
            },
            {
                'nome': "Bomba de Infusão Peristáltica Samtronic ST550T2",
                'patrimonio': "FMS-TV-0210",
                'codigo_interno': "EQ-MED-0210",
                'numero_serie': "ST55209",
                'fabricante': "Samtronic Indústria",
                'modelo': "ST550T2 Volumétrica c/ Sensor de Gotas",
                'registro_anvisa': "10266690014",
                'categoria': cats["Terapia Intensiva & Infusão"],
                'unidade': unid_tv_hosp,
                'setor': "Sala de Medicação Rápida",
                'criticidade': "MEDIA",
                'tensao': "Bivolt + Bateria",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=80),
                'data_ultima_preventiva': hoje - timedelta(days=80),
                'observacoes': "Teste de vazão com balança analítica aferida com erro < 2.5%.",
            },
        ]

        eqs_criados = {}
        for d in equipamentos_tv_dados:
            eq, _ = Equipamento.objects.get_or_create(
                organization=org,
                cliente=cliente_tv,
                patrimonio=d['patrimonio'],
                defaults={
                    'nome': d['nome'],
                    'codigo_interno': d['codigo_interno'],
                    'numero_serie': d['numero_serie'],
                    'fabricante': d['fabricante'],
                    'modelo': d['modelo'],
                    'registro_anvisa': d['registro_anvisa'],
                    'categoria': d['categoria'],
                    'unidade': d['unidade'],
                    'setor': d['setor'],
                    'criticidade': d['criticidade'],
                    'tensao': d['tensao'],
                    'situacao_operacional': d['situacao_operacional'],
                    'periodicidade_calibracao_meses': d['periodicidade_calibracao_meses'],
                    'periodicidade_preventiva_meses': d['periodicidade_preventiva_meses'],
                    'data_ultima_calibracao': d['data_ultima_calibracao'],
                    'data_ultima_preventiva': d['data_ultima_preventiva'],
                    'observacoes': d['observacoes'],
                },
            )
            eqs_criados[d['patrimonio']] = eq

        # 6. Equipamentos Médicos de Campo Alegre (AL)
        equipamentos_ca_dados = [
            {
                'nome': "Desfibrilador Cardioversor Instramed CardioMax",
                'patrimonio': "FMS-CA-0015",
                'codigo_interno': "EQ-CA-0015",
                'numero_serie': "IM44201",
                'fabricante': "Instramed",
                'modelo': "CardioMax Bifásico c/ DEA e SpO2",
                'registro_anvisa': "10242220028",
                'categoria': cats["Cardiologia & Suporte de Vida"],
                'unidade': unid_ca_mista,
                'setor': "Emergência 24h",
                'criticidade': "CRITICA",
                'tensao': "Bivolt Automático",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=30),
                'data_ultima_preventiva': hoje - timedelta(days=30),
                'observacoes': "Equipamento regulado e calibrado. Autonomia da bateria em carga máxima.",
            },
            {
                'nome': "Incubadora Neonatal Fanem 1186",
                'patrimonio': "FMS-CA-0044",
                'codigo_interno': "EQ-CA-0044",
                'numero_serie': "FN11865",
                'fabricante': "Fanem Ltda",
                'modelo': "Vision 1186 c/ Servocontrole de Oxigênio",
                'registro_anvisa': "10222460021",
                'categoria': cats["Terapia Intensiva & Infusão"],
                'unidade': unid_ca_mista,
                'setor': "Maternidade / Berçário Local",
                'criticidade': "CRITICA",
                'tensao': "220V",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 6,
                'periodicidade_preventiva_meses': 3,
                'data_ultima_calibracao': hoje - timedelta(days=40),
                'data_ultima_preventiva': hoje - timedelta(days=40),
                'observacoes': "Sensores de temperatura de pele calibrados em banho térmico padrão rastreável RBC.",
            },
            {
                'nome': "Autoclave Odontológica Cristófoli Vitale 21L",
                'patrimonio': "FMS-CA-0089",
                'codigo_interno': "EQ-CA-0089",
                'numero_serie': "CR21094",
                'fabricante': "Cristófoli Biossegurança",
                'modelo': "Vitale Class 21 Litros Digital",
                'registro_anvisa': "10363350005",
                'categoria': cats["Central de Material & Esterilização (CME)"],
                'unidade': unid_ca_ubs2,
                'setor': "Consultório Odontológico PSF",
                'criticidade': "MEDIA",
                'tensao': "220V",
                'situacao_operacional': SituacaoOperacional.FUNCIONANDO,
                'periodicidade_calibracao_meses': 12,
                'periodicidade_preventiva_meses': 6,
                'data_ultima_calibracao': hoje - timedelta(days=70),
                'data_ultima_preventiva': hoje - timedelta(days=70),
                'observacoes': "Válvula solenóide e ciclo de despressurização verificados.",
            },
        ]
        for d in equipamentos_ca_dados:
            eq, _ = Equipamento.objects.get_or_create(
                organization=org,
                cliente=cliente_ca,
                patrimonio=d['patrimonio'],
                defaults={
                    'nome': d['nome'],
                    'codigo_interno': d['codigo_interno'],
                    'numero_serie': d['numero_serie'],
                    'fabricante': d['fabricante'],
                    'modelo': d['modelo'],
                    'registro_anvisa': d['registro_anvisa'],
                    'categoria': d['categoria'],
                    'unidade': d['unidade'],
                    'setor': d['setor'],
                    'criticidade': d['criticidade'],
                    'tensao': d['tensao'],
                    'situacao_operacional': d['situacao_operacional'],
                    'periodicidade_calibracao_meses': d['periodicidade_calibracao_meses'],
                    'periodicidade_preventiva_meses': d['periodicidade_preventiva_meses'],
                    'data_ultima_calibracao': d['data_ultima_calibracao'],
                    'data_ultima_preventiva': d['data_ultima_preventiva'],
                    'observacoes': d['observacoes'],
                },
            )
            eqs_criados[d['patrimonio']] = eq

        # 7. Ordens de Serviço Reais de Demonstração (Laudos Técnicos e Preventivas)
        eq_desfib = eqs_criados.get("FMS-TV-0142")
        if eq_desfib:
            os_calib, _ = OrdemServico.objects.get_or_create(
                organization=org,
                equipamento=eq_desfib,
                tipo_atendimento='CALIBRACAO',
                status=Status.FINALIZADA,
                defaults={
                    'cliente': cliente_tv,
                    'unidade': unid_tv_hosp,
                    'tecnico': tecnico,
                    'prioridade': 'URGENTE',
                    'defeito': "Calibração periódica anual obrigatória de desfibrilador/cardioversor e teste de segurança elétrica.",
                    'diagnostico': "Avaliação metrológica de energia de choque entregue em carga simulada de 50 ohms conforme NBR IEC 60601-2-4.",
                    'servico_executado': (
                        "1. Inspeção visual de pás adultas/pediátricas e conectores.\n"
                        "2. Ensaio de energia entregue com Analisador Fluke Biomedical Impulse 7000DP nas escalas: 5J, 10J, 50J, 100J, 200J e 360J.\n"
                        "3. Medição de tempo de carga máxima (360 Joules): 4.12 segundos (máx normativo 15s).\n"
                        "4. Teste de segurança elétrica (NBR IEC 60601-1): resistência de aterramento 0.08 ohms, corrente de fuga no chassi 42 uA (dentro dos limites).\n"
                        "5. Afixada etiqueta metalizada de calibração VERTYX nº TV-2026-0142 com QR Code de rastreabilidade."
                    ),
                    'solucao': "Equipamento APROVADO sem ressalvas para uso em suporte avançado de vida e reanimação cardiopulmonar.",
                    'condicao_final': 'OK',
                    'recomendacoes': "Manter conectado à rede elétrica quando fora de transporte para preservação da carga da bateria de backup.",
                    'inicio': timezone.now() - timedelta(days=20, hours=4),
                    'conclusao': timezone.now() - timedelta(days=20, hours=1),
                    'horas': Decimal('3.00'),
                },
            )

        eq_autoclave = eqs_criados.get("FMS-TV-0012")
        if eq_autoclave:
            os_corr, _ = OrdemServico.objects.get_or_create(
                organization=org,
                equipamento=eq_autoclave,
                tipo_atendimento='CORRETIVA',
                status=Status.EXECUCAO,
                defaults={
                    'cliente': cliente_tv,
                    'unidade': unid_tv_hosp,
                    'tecnico': tecnico,
                    'prioridade': 'ALTA',
                    'defeito': "Válvula de segurança escapando vapor antes do final do ciclo de 134°C; código de erro de vácuo insuficiente.",
                    'diagnostico': "Ressecamento da guarnição de vedação da porta da câmara de esterilização e acúmulo de biofilme na tubulação de purga.",
                    'servico_executado': (
                        "Desmontagem do anel de vedação frontal, limpeza química das canaletas com desincrustante hospitalar. "
                        "Substituição da guarnição perfil de silicone farmacêutico 150L Baumer e teste hidrostático da válvula."
                    ),
                    'solucao': "Em andamento: executando ciclo de validação com teste Bowie & Dick para liberação da CME.",
                    'condicao_final': 'RESTRICAO',
                    'horas': Decimal('2.50'),
                    'inicio': timezone.now() - timedelta(hours=3),
                },
            )

        eq_vent = eqs_criados.get("FMS-TV-0034")
        if eq_vent:
            os_prev, _ = OrdemServico.objects.get_or_create(
                organization=org,
                equipamento=eq_vent,
                tipo_atendimento='PREVENTIVA',
                status=Status.AGENDADA,
                defaults={
                    'cliente': cliente_tv,
                    'unidade': unid_tv_hosp,
                    'tecnico': tecnico,
                    'prioridade': 'NORMAL',
                    'defeito': "Manutenção preventiva trimestral programada do ventilador de UTI.",
                    'diagnostico': "Troca de diafragmas de silicone, filtros de entrada de ar/oxigênio e conferência de calibração baroplégica.",
                    'agendada_para': timezone.now() + timedelta(days=3, hours=9),
                    'agendada_ate': timezone.now() + timedelta(days=3, hours=12),
                    'observacoes': "Agendado para terça-feira pela manhã durante a ronda técnica no hospital.",
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"  - 2 Clientes Criados: Teotônio Vilela (AL) e Campo Alegre (AL)\n"
            f"  - 5 Unidades de Saúde (Hospitais, UBS e CEO Odontológico)\n"
            f"  - {len(eqs_criados)} Equipamentos Hospitalares com dados patrimoniais e ANVISA\n"
            f"  - 3 Ordens de Serviço (Calibração Aprovada c/ laudo, Corretiva CME e Preventiva Agendada)\n"
            f"  - Técnico Responsável: Eng. Rafael Tenório (CREA-AL)"
        ))
