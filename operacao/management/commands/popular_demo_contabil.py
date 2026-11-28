"""Comando Django para popular dados da Carteira Contábil (VERTYX Contábil) para demonstração aos contadores e clientes."""
from __future__ import annotations

import decimal
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from contas.models import Usuario
from fiscal import carteira_services as cs
from operacao.contabil_models import (
    CertidaoFiscalCarteira,
    ComunicacaoClienteContabil,
    DepartamentoContabil,
    EmpresaCarteiraContabil,
    EventoHistoricoContabil,
    ObrigacaoFiscalCarteira,
    PendenciaFiscalCarteira,
    PreAnaliseComercialCNPJ,
    RegimeTributarioCarteira,
    validar_cnpj_digitos,
)
from platform_core.context import tenant_context
from platform_core.models import Organization


def make_valid_cnpj(base12: str) -> str:
    digits = [int(x) for x in base12]
    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    s1 = sum(digits[i] * pesos_1[i] for i in range(12))
    r1 = s1 % 11
    dv1 = 0 if r1 < 2 else 11 - r1
    digits.append(dv1)
    pesos_2 = [6] + pesos_1
    s2 = sum(digits[i] * pesos_2[i] for i in range(13))
    r2 = s2 % 11
    dv2 = 0 if r2 < 2 else 11 - r2
    digits.append(dv2)
    cnpj = ''.join(str(x) for x in digits)
    return validar_cnpj_digitos(cnpj)


class Command(BaseCommand):
    help = "Popula carteira de clientes, certidões, obrigações e pendências operacionais para o VERTYX Contábil"

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
            self.stderr.write(self.style.ERROR("Nenhuma organização encontrada no sistema."))
            return

        self.stdout.write(self.style.SUCCESS(f"Populando carteira contábil na organização: {org.razao_social}"))

        with tenant_context(org):
            with transaction.atomic():
                self._popular_contabil(org)

        self.stdout.write(self.style.SUCCESS("Dados do VERTYX Contábil populados com sucesso!"))

    def _popular_contabil(self, org: Organization):
        hoje = timezone.localdate()
        from platform_core.models import OrganizationMembership
        admin_user = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        if admin_user:
            OrganizationMembership.objects.get_or_create(
                organization=org,
                user=admin_user,
                defaults={'role': 'ADMIN', 'status': 'ATIVO'}
            )

        # 1. Cadastro de Empresas da Carteira (Clientes Contábeis)
        empresas_dados = [
            {
                'razao_social': "Clínica Médica e Diagnóstico Vilela Ltda",
                'nome_fantasia': "Clínica Vilela Saúde",
                'base_cnpj': "142859120001",
                'regime': RegimeTributarioCarteira.SIMPLES_NACIONAL,
                'situacao_fiscal': EmpresaCarteiraContabil.SituacaoFiscal.REGULAR,
                'honorario': Decimal("1850.00"),
                'cidade': "Teotônio Vilela",
                'uf': "AL",
                'email': "financeiro@clinicavilela.med.br",
                'whatsapp': "(82) 99120-1122",
                'certificado_tipo': EmpresaCarteiraContabil.TipoCertificado.A1,
                'certificado_validade': hoje + timedelta(days=210),
                'procuracao_ecac': True,
                'procuracao_validade': hoje + timedelta(days=365),
            },
            {
                'razao_social': "Distribuidora de Medicamentos e Material Hospitalar Alagoas Ltda",
                'nome_fantasia': "MedAlagoas Distribuidora",
                'base_cnpj': "284105930001",
                'regime': RegimeTributarioCarteira.LUCRO_PRESUMIDO,
                'situacao_fiscal': EmpresaCarteiraContabil.SituacaoFiscal.ALERTA,
                'honorario': Decimal("3200.00"),
                'cidade': "Maceió",
                'uf': "AL",
                'email': "fiscal@medalagoas.com.br",
                'whatsapp': "(82) 98841-3344",
                'certificado_tipo': EmpresaCarteiraContabil.TipoCertificado.A1,
                'certificado_validade': hoje + timedelta(days=45),
                'procuracao_ecac': True,
                'procuracao_validade': hoje + timedelta(days=180),
            },
            {
                'razao_social': "Laboratório de Análises Clínicas Campo Alegre Ltda",
                'nome_fantasia': "BioAnálises Campo Alegre",
                'base_cnpj': "359128440001",
                'regime': RegimeTributarioCarteira.SIMPLES_NACIONAL,
                'situacao_fiscal': EmpresaCarteiraContabil.SituacaoFiscal.IRREGULAR,
                'honorario': Decimal("1600.00"),
                'cidade': "Campo Alegre",
                'uf': "AL",
                'email': "adm@bioanalisesca.com.br",
                'whatsapp': "(82) 99650-8899",
                'certificado_tipo': EmpresaCarteiraContabil.TipoCertificado.A3,
                'certificado_validade': hoje - timedelta(days=10),  # Vencido
                'procuracao_ecac': False,
            },
            {
                'razao_social': "Centro de Imagem & Radiologia São Jorge Eireli",
                'nome_fantasia': "Radiologia São Jorge",
                'base_cnpj': "410293840001",
                'regime': RegimeTributarioCarteira.LUCRO_REAL,
                'situacao_fiscal': EmpresaCarteiraContabil.SituacaoFiscal.REGULAR,
                'honorario': Decimal("4800.00"),
                'cidade': "Arapiraca",
                'uf': "AL",
                'email': "contabil@radiologiasaojorge.com.br",
                'whatsapp': "(82) 99312-5566",
                'certificado_tipo': EmpresaCarteiraContabil.TipoCertificado.A1,
                'certificado_validade': hoje + timedelta(days=140),
                'procuracao_ecac': True,
                'procuracao_validade': hoje + timedelta(days=290),
            },
            {
                'razao_social': "Distribuidora de Oxigênio & Gases Medicinais do Agreste Ltda",
                'nome_fantasia': "Oxigênio Agreste",
                'base_cnpj': "529183400001",
                'regime': RegimeTributarioCarteira.LUCRO_PRESUMIDO,
                'situacao_fiscal': EmpresaCarteiraContabil.SituacaoFiscal.REGULAR,
                'honorario': Decimal("2500.00"),
                'cidade': "Teotônio Vilela",
                'uf': "AL",
                'email': "gerencia@oxigenioagreste.com.br",
                'whatsapp': "(82) 98711-2233",
                'certificado_tipo': EmpresaCarteiraContabil.TipoCertificado.A1,
                'certificado_validade': hoje + timedelta(days=90),
                'procuracao_ecac': True,
                'procuracao_validade': hoje + timedelta(days=220),
            },
            {
                'razao_social': "Policlínica Odontológica Integrada Ltda",
                'nome_fantasia': "OdontoIntegrada",
                'base_cnpj': "618294030001",
                'regime': RegimeTributarioCarteira.SIMPLES_NACIONAL,
                'situacao_fiscal': EmpresaCarteiraContabil.SituacaoFiscal.CRITICA,
                'honorario': Decimal("1400.00"),
                'cidade': "São Miguel dos Campos",
                'uf': "AL",
                'email': "contato@odontointegrada.com.br",
                'whatsapp': "(82) 99420-7788",
                'certificado_tipo': EmpresaCarteiraContabil.TipoCertificado.NENHUM,
                'procuracao_ecac': False,
            },
        ]

        empresas_criadas = []
        for d in empresas_dados:
            cnpj_valido = make_valid_cnpj(d['base_cnpj'])
            emp, _ = EmpresaCarteiraContabil.objects.get_or_create(
                organization=org,
                cnpj=cnpj_valido,
                defaults={
                    'razao_social': d['razao_social'],
                    'nome_fantasia': d['nome_fantasia'],
                    'regime_tributario': d['regime'],
                    'situacao_fiscal': d['situacao_fiscal'],
                    'responsavel_interno': admin_user,
                    'departamento_padrao': DepartamentoContabil.FISCAL,
                    'honorario_mensal': d['honorario'],
                    'cidade': d['cidade'],
                    'uf': d['uf'],
                    'email_contato': d['email'],
                    'whatsapp_contato': d['whatsapp'],
                    'certificado_tipo': d['certificado_tipo'],
                    'certificado_validade': d.get('certificado_validade'),
                    'procuracao_ecac_ativa': d.get('procuracao_ecac', False),
                    'procuracao_validade': d.get('procuracao_validade'),
                    'ativo': True,
                },
            )
            empresas_criadas.append(emp)

        # 2. Certidões Fiscais (Federais, Estaduais, Municipais e FGTS)
        for emp in empresas_criadas:
            # Federal
            CertidaoFiscalCarteira.objects.get_or_create(
                organization=org,
                empresa=emp,
                esfera=CertidaoFiscalCarteira.Esfera.FEDERAL,
                defaults={
                    'situacao': CertidaoFiscalCarteira.Situacao.REGULAR if emp.situacao_fiscal != EmpresaCarteiraContabil.SituacaoFiscal.CRITICA else CertidaoFiscalCarteira.Situacao.IRREGULAR,
                    'emitida_em': hoje - timedelta(days=60),
                    'validade': hoje + timedelta(days=120) if emp.situacao_fiscal != EmpresaCarteiraContabil.SituacaoFiscal.CRITICA else hoje - timedelta(days=15),
                    'codigo_controle': f"FED-{emp.cnpj[:6]}-{hoje.year}",
                    'dias_alerta_antecedencia': 20,
                    'observacoes': "Certidão Conjunta Negativa de Débitos Relativos a Tributos Federais e à Dívida Ativa da União.",
                },
            )
            # Estadual SEFAZ-AL
            val_est = hoje + timedelta(days=90)
            sit_est = CertidaoFiscalCarteira.Situacao.REGULAR
            if emp.razao_social.startswith("Laboratório"):
                val_est = hoje + timedelta(days=12)  # Próxima ao vencimento (alerta)
            elif emp.situacao_fiscal == EmpresaCarteiraContabil.SituacaoFiscal.CRITICA:
                val_est = hoje - timedelta(days=5)
                sit_est = CertidaoFiscalCarteira.Situacao.VENCIDA

            CertidaoFiscalCarteira.objects.get_or_create(
                organization=org,
                empresa=emp,
                esfera=CertidaoFiscalCarteira.Esfera.ESTADUAL,
                defaults={
                    'situacao': sit_est,
                    'emitida_em': hoje - timedelta(days=70),
                    'validade': val_est,
                    'codigo_controle': f"SEFAZ-AL-{emp.cnpj[:6]}-{hoje.year}",
                    'dias_alerta_antecedencia': 15,
                    'observacoes': "Certidão Negativa de Débitos Estaduais da Secretaria de Estado da Fazenda de Alagoas.",
                },
            )
            # FGTS
            CertidaoFiscalCarteira.objects.get_or_create(
                organization=org,
                empresa=emp,
                esfera=CertidaoFiscalCarteira.Esfera.FGTS,
                defaults={
                    'situacao': CertidaoFiscalCarteira.Situacao.REGULAR if emp.situacao_fiscal != EmpresaCarteiraContabil.SituacaoFiscal.CRITICA else CertidaoFiscalCarteira.Situacao.IRREGULAR,
                    'emitida_em': hoje - timedelta(days=10),
                    'validade': hoje + timedelta(days=20),
                    'codigo_controle': f"CRF-CEF-{emp.cnpj[:8]}",
                    'dias_alerta_antecedencia': 10,
                    'observacoes': "Certificado de Regularidade do FGTS - CRF da Caixa Econômica Federal.",
                },
            )

        # 3. Obrigações e Guias Fiscais Mensais
        comp_atual = hoje.strftime("%m/%Y")
        comp_anterior = (hoje - timedelta(days=30)).strftime("%m/%Y")

        for emp in empresas_criadas:
            # DCTFWeb
            status_dctf = ObrigacaoFiscalCarteira.Status.TRANSMITIDA
            if emp.razao_social.startswith("Distribuidora de Medicamentos"):
                status_dctf = ObrigacaoFiscalCarteira.Status.PENDENTE
            elif emp.situacao_fiscal == EmpresaCarteiraContabil.SituacaoFiscal.CRITICA:
                status_dctf = ObrigacaoFiscalCarteira.Status.ATRASADA

            ObrigacaoFiscalCarteira.objects.get_or_create(
                organization=org,
                empresa=emp,
                tipo=ObrigacaoFiscalCarteira.Tipo.DCTFWEB,
                competencia=comp_anterior,
                defaults={
                    'natureza': ObrigacaoFiscalCarteira.Natureza.DECLARACAO,
                    'vencimento': hoje + timedelta(days=5),
                    'valor_guia': Decimal("0.00"),
                    'status': status_dctf,
                    'responsavel': admin_user,
                    'observacoes': "Declaração de Débitos e Créditos Tributários Federais Previdenciários.",
                },
            )

            # Guia de Tributo (DAS para Simples ou DARF para Presumido/Real)
            if emp.regime_tributario == RegimeTributarioCarteira.SIMPLES_NACIONAL:
                tipo_g = ObrigacaoFiscalCarteira.Tipo.DAS
                val_g = Decimal("1450.80")
            else:
                tipo_g = ObrigacaoFiscalCarteira.Tipo.DARF
                val_g = Decimal("3890.45")

            status_guia = ObrigacaoFiscalCarteira.Status.EM_APURACAO
            if emp.situacao_fiscal == EmpresaCarteiraContabil.SituacaoFiscal.REGULAR:
                status_guia = ObrigacaoFiscalCarteira.Status.PAGA
            elif emp.situacao_fiscal == EmpresaCarteiraContabil.SituacaoFiscal.CRITICA:
                status_guia = ObrigacaoFiscalCarteira.Status.ATRASADA

            ObrigacaoFiscalCarteira.objects.get_or_create(
                organization=org,
                empresa=emp,
                tipo=tipo_g,
                competencia=comp_anterior,
                defaults={
                    'natureza': ObrigacaoFiscalCarteira.Natureza.GUIA,
                    'vencimento': hoje + timedelta(days=10),
                    'valor_guia': val_g,
                    'status': status_guia,
                    'responsavel': admin_user,
                    'observacoes': "Guia de apuração mensal de tributos sobre o faturamento.",
                },
            )

        # 4. Central de Pendências Operacional (Fluxo Diferencial: Pendência -> Resp -> Tarefa -> Comunicação -> Resolução)
        emp_med = empresas_criadas[1]  # MedAlagoas
        emp_lab = empresas_criadas[2]  # BioAnálises
        emp_odonto = empresas_criadas[5]  # OdontoIntegrada

        # Pendência 1: Regularização DCTFWeb em Atraso (Resolvida com histórico)
        pend1, created1 = PendenciaFiscalCarteira.objects.get_or_create(
            organization=org,
            codigo="PEND-2026-001",
            defaults={
                'empresa': emp_med,
                'titulo': f"Regularização de DCTFWeb em Aberto ({comp_anterior})",
                'descricao': "Transmissão da DCTFWeb da competência anterior para liberação da guia unificada e emissão de CND Federal.",
                'departamento': DepartamentoContabil.FISCAL,
                'prioridade': PendenciaFiscalCarteira.Prioridade.ALTA,
                'status': PendenciaFiscalCarteira.Status.RESOLVIDO,
                'etapa_fluxo': PendenciaFiscalCarteira.EtapaFluxo.AUDITAR,
                'responsavel': admin_user,
                'criado_por': admin_user,
                'prazo': hoje - timedelta(days=1),
                'resolvido_em': timezone.now() - timedelta(hours=6),
            },
        )
        if created1:
            # Registra comunicação de WhatsApp com cliente
            ComunicacaoClienteContabil.objects.create(
                organization=org,
                pendencia=pend1,
                empresa=emp_med,
                canal=ComunicacaoClienteContabil.Canal.WHATSAPP,
                tipo=ComunicacaoClienteContabil.Tipo.SOLICITACAO_DOC,
                destinatario=emp_med.whatsapp_contato,
                assunto="Solicitação de Fechamento de Folha para DCTFWeb",
                documento_solicitado="Relatório de Pró-Labore e Folha de Pagamento",
                mensagem=(
                    f"Olá equipe da {emp_med.nome_fantasia}, precisamos do relatório de pró-labore e eventos para fechar a DCTFWeb "
                    f"competência {comp_anterior} e evitar multas da Receita Federal."
                ),
                enviado_por=admin_user,
                confirmado_recebimento=True,
                confirmado_em=timezone.now() - timedelta(days=2),
            )
            # Registra auditoria
            EventoHistoricoContabil.objects.create(
                organization=org,
                pendencia=pend1,
                empresa=emp_med,
                autor=admin_user,
                tipo_evento=EventoHistoricoContabil.TipoEvento.PENDENCIA_RESOLVIDA,
                descricao="DCTFWeb transmitida com recibo nº 2026.11.890412. Situação fiscal regularizada no e-CAC.",
            )

        # Pendência 2: Renovação CND Estadual SEFAZ-AL (Em Andamento)
        PendenciaFiscalCarteira.objects.get_or_create(
            organization=org,
            codigo="PEND-2026-002",
            defaults={
                'empresa': emp_lab,
                'titulo': "Renovação Preventiva da CND Estadual SEFAZ/AL (Vence em 12 dias)",
                'descricao': "Certidão Negativa de Débitos Estaduais está próxima do vencimento. Necessário auditar pendências no Domicílio Tributário Eletrônico da SEFAZ.",
                'departamento': DepartamentoContabil.FISCAL,
                'prioridade': PendenciaFiscalCarteira.Prioridade.ALTA,
                'status': PendenciaFiscalCarteira.Status.EM_ANDAMENTO,
                'etapa_fluxo': PendenciaFiscalCarteira.EtapaFluxo.EXECUTAR,
                'responsavel': admin_user,
                'criado_por': admin_user,
                'prazo': hoje + timedelta(days=5),
            },
        )

        # Pendência 3: Ausência de Certificado Digital A1 (Aberto)
        PendenciaFiscalCarteira.objects.get_or_create(
            organization=org,
            codigo="PEND-2026-003",
            defaults={
                'empresa': emp_odonto,
                'titulo': "Emissão Urgente de Certificado Digital e-CNPJ A1 e Procuração e-CAC",
                'descricao': "Empresa sem procuração e sem certificado digital ativo, impossibilitando consulta automatizada de certidões e entrega do PGDAS.",
                'departamento': DepartamentoContabil.LEGALIZACAO,
                'prioridade': PendenciaFiscalCarteira.Prioridade.CRITICA,
                'status': PendenciaFiscalCarteira.Status.ABERTO,
                'etapa_fluxo': PendenciaFiscalCarteira.EtapaFluxo.COMUNICAR,
                'responsavel': admin_user,
                'criado_por': admin_user,
                'prazo': hoje + timedelta(days=3),
            },
        )

        # 5. Pré-Análise Comercial (Diagnóstico de Prospecção para Novos Clientes Contábeis)
        PreAnaliseComercialCNPJ.objects.get_or_create(
            organization=org,
            cnpj="08249102000185",
            defaults={
                'razao_social_identificada': "Hospital dos Olhos e Oftalmologia do Nordeste Ltda",
                'regime_estimado': RegimeTributarioCarteira.LUCRO_PRESUMIDO,
                'uf': "AL",
                'cidade': "Maceió",
                'pendencias_conhecidas': "2 pendências conhecidas em dívida ativa e ausência de entrega da EFD Contribuições nos últimos 2 meses.",
                'diagnostico_inicial': (
                    "Empresa com faturamento estimado > R$ 120k/mês. Forte oportunidade comercial para "
                    "oferecer serviço de regularização e migração de contabilidade com honorário de R$ 3.500,00."
                ),
                'nivel_oportunidade': PreAnaliseComercialCNPJ.Oportunidade.ALTA,
                'consultado_por': admin_user,
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f"  - 6 Empresas da Carteira Contábil cadastradas (Simples, Presumido, Real)\n"
            f"  - {len(empresas_criadas) * 3} Certidões Fiscais (Federal, Estadual AL e FGTS)\n"
            f"  - Obrigações e Guias Mensais geradas (DCTFWeb, PGDAS, DAS, DARF)\n"
            f"  - 3 Pendências Operacionais no fluxo 'Pendência -> Tarefa -> Comunicação -> Resolução'\n"
            f"  - 1 Pré-Análise Comercial de Prospecção registrada"
        ))
