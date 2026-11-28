"""Testes automatizados do VERTYX Market & Pricing e VERTYX Licita (Fórmulas, Multi-Tenant, Auditoria e Telas)."""
from __future__ import annotations

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from operacao import licita_services as ls
from operacao import pricing_services as ps
from operacao.licita_models import (
    AnaliseEditalRequisito,
    HistoricoLicitacaoEvento,
    OportunidadeLicitacao,
    RadarFiltroPNCP,
)
from operacao.pricing_models import (
    CalculadoraHoraTecnica,
    CalculadoraPrecoProduto,
    CentroCustoRateio,
    HistoricoCalculoPreco,
    PesquisaPrecoConcorrente,
    SimulacaoLanceEdital,
)
from platform_core.context import tenant_context
from .test_block3_commerce import CommerceData


class VertyxPricingAndLicitaTests(CommerceData, TestCase):
    def setUp(self):
        self.setup_commerce()
        self.org_a = self.a
        self.org_b = self.b
        self.admin_a = self.admin
        self.gestor_a = self.users['GESTOR']
        self.tecnico_a = self.users['TECNICO']

    def _login_org(self, user, org):
        self.client.force_login(user)
        session = self.client.session
        session['organization_id'] = org.pk
        session.save()

    def test_formulas_precificacao_produto_break_even_e_margem(self):
        with tenant_context(self.org_a):
            # Exemplo exato do PDF: Custo 2.100, Fixos 15%, Tributos 8%, Margem 15%
            calc = ps.salvar_calculo_produto(
                self.admin_a,
                {
                    'nome_produto': 'Cama Hospitalar Fowler Elétrica',
                    'custo_aquisicao': '2100.00',
                    'custo_frete_seguro': '0.00',
                    'percentual_despesas_fixas': '15.00',
                    'percentual_tributos': '8.00',
                    'percentual_outras_variaveis': '0.00',
                    'percentual_margem_desejada': '15.00',
                },
            )
            # Preço de Equilíbrio (Break-Even): 2.100 / (1 - 0.23) = 2.100 / 0.77 = R$ 2.727,27
            self.assertEqual(calc.preco_equilibrio, Decimal('2727.27'))
            # Preço Alvo: 2.100 / (1 - 0.38) = 2.100 / 0.62 = R$ 3.387,10
            self.assertEqual(calc.preco_alvo, Decimal('3387.10'))
            # Margem estimada vendendo no concorrente a R$ 2.850,00 -> ~ 3.32%
            margem_cenario = calc.calcular_margem_cenario(Decimal('2850.00'))
            self.assertAlmostEqual(float(margem_cenario), 3.32, places=1)

    def test_formula_hora_tecnica_capacidade_produtiva(self):
        with tenant_context(self.org_a):
            # Exemplo do PDF: 2 técnicos, 22 dias, 8h, 65% ocupação, R$ 13.000 custo mensal, 12% trib, 25% margem
            hora = ps.salvar_calculo_hora_tecnica(
                self.admin_a,
                {
                    'especialidade': 'Engenharia Clínica Biomédica',
                    'num_tecnicos': 2,
                    'dias_uteis_mes': 22,
                    'horas_dia': '8.00',
                    'percentual_ocupacao_faturavel': '65.00',
                    'custo_mensal_centro': '13000.00',
                    'percentual_tributos': '12.00',
                    'percentual_margem': '25.00',
                },
            )
            # Horas faturáveis: 2 * 22 * 8 * 0.65 = 228.80h
            self.assertEqual(hora.horas_faturaveis_mes, Decimal('228.80'))
            # Custo/hora: 13.000 / 228.8 = R$ 56.82
            self.assertEqual(hora.custo_por_hora, Decimal('56.82'))
            # Hora sugerida: 56.82 / (1 - 0.37) = R$ 90.19
            self.assertEqual(hora.hora_sugerida, Decimal('90.19'))

    def test_simulador_lance_trava_piso_sustentavel(self):
        with tenant_context(self.org_a):
            sim = ps.salvar_simulacao_lance(
                self.admin_a,
                {
                    'titulo_edital': 'Pregão 015/2026 - SMS Campo Alegre',
                    'orgao_comprador': 'Prefeitura de Campo Alegre / AL',
                    'objeto_resumo': 'Manutenção preventiva e corretiva de equipamentos hospitalares',
                    'custos_pecas_equipamentos': '30000.00',
                    'horas_tecnicas_estimadas': '200.00',
                    'custo_hora_aplicado': '100.00',  # 20.000 em horas
                    'custos_deslocamento_logistica': '10000.00',
                    'outras_despesas_diretas': '5000.00',  # Subtotal = 65.000
                    'percentual_taxa_risco': '0.00',  # Risco zero para bater com exemplo do PDF
                    'percentual_tributos': '8.00',
                    'percentual_margem_minima': '15.00',
                    'lance_simulado_disputa': '70000.00',  # Abaixo do piso!
                },
            )
            # Custo Composto: R$ 65.000,00
            self.assertEqual(sim.custo_total_composto, Decimal('65000.00'))
            # Piso Sem Lucro (Break-even): 65.000 / 0.92 = R$ 70.652,17
            self.assertEqual(sim.piso_sem_lucro, Decimal('70652.17'))
            # Preço com margem: 65.000 / (1 - 0.23) = 65.000 / 0.77 = R$ 84.415,58
            self.assertEqual(sim.lance_com_margem, Decimal('84415.58'))
            # Lance de R$ 70.000 está ABAIXO do piso de R$ 70.652,17 -> Guardrail ativado
            self.assertTrue(sim.lance_abaixo_do_piso)
            self.assertLess(sim.calcular_lucro_lance(Decimal('70000.00')), Decimal('0.00'))
            # Lance a R$ 90.000 -> Lucro de 90.000 * 0.92 - 65.000 = R$ 17.800,00
            self.assertEqual(sim.calcular_lucro_lance(Decimal('90000.00')), Decimal('17800.00'))

    def test_licita_checklist_edital_com_citacao_e_funil(self):
        with tenant_context(self.org_a):
            radar = RadarFiltroPNCP.objects.create(
                organization=self.org_a,
                nome='Hospitalar Alagoas',
                palavras_chave='hospitalar, engenharia',
                ufs='AL',
                modalidades_pncp='6, 8',
            )
            op = OportunidadeLicitacao.objects.create(
                organization=self.org_a,
                numero_controle_pncp='00394494000136-1-000001/2026',
                orgao_nome='Fundo Municipal de Saúde de Teotônio Vilela',
                uf='AL',
                municipio='Teotônio Vilela',
                modalidade_nome='Pregão Eletrônico',
                numero_edital='PE 001/2026',
                objeto='Contratação de empresa especializada em engenharia clínica hospitalar',
                valor_total_estimado=Decimal('180000.00'),
                radar_origem=radar,
                responsavel=self.admin_a,
            )
            # Gera checklist padrão de requisitos com citação de página
            reqs = ls.gerar_checklist_padrao_edital(self.admin_a, op)
            self.assertGreaterEqual(len(reqs), 5)
            primeiro_req = reqs[0]
            self.assertGreater(primeiro_req.pagina_edital, 0)
            self.assertTrue(len(primeiro_req.trecho_citado) > 10)

            # Avança etapa no funil comercial
            op_atualizada = ls.atualizar_etapa_funil(self.admin_a, op, OportunidadeLicitacao.EtapaFunil.DOCUMENTACAO)
            self.assertEqual(op_atualizada.etapa, 'DOCUMENTACAO')
            self.assertEqual(HistoricoLicitacaoEvento.objects.filter(oportunidade=op).count(), 1)

    def test_isolamento_multitenant_pricing_e_licita(self):
        with tenant_context(self.org_a):
            prod_a = ps.salvar_calculo_produto(
                self.admin_a,
                {'nome_produto': 'Produto Exclusivo Org A', 'custo_aquisicao': '100.00'},
            )
            self.assertEqual(CalculadoraPrecoProduto.objects.count(), 1)

        with tenant_context(self.org_b):
            self.assertEqual(CalculadoraPrecoProduto.objects.count(), 0)

    def test_rotas_http_e_telas_operacionais_autenticadas(self):
        self._login_org(self.admin_a, self.org_a)
        # 1. Dashboard de Pricing
        resp_pricing = self.client.get('/comercial/pricing/')
        self.assertEqual(resp_pricing.status_code, 200)
        self.assertContains(resp_pricing, 'VERTYX MARKET &amp; PRICING')

        # 2. Produtos
        resp_prods = self.client.get('/comercial/pricing/produtos/')
        self.assertEqual(resp_prods.status_code, 200)
        self.assertContains(resp_prods, 'Planilha Dinâmica de Formação de Preço')

        # 3. Hora Técnica
        resp_hora = self.client.get('/comercial/pricing/hora-tecnica/')
        self.assertEqual(resp_hora.status_code, 200)
        self.assertContains(resp_hora, 'Formação da Hora Técnica da Assistência')

        # 4. Central de Licitações (PNCP)
        resp_licita = self.client.get('/comercial/licita/')
        self.assertEqual(resp_licita.status_code, 200)
        self.assertContains(resp_licita, 'VERTYX LICITA')

        # 5. Funil Comercial
        resp_funil = self.client.get('/comercial/licita/funil/')
        self.assertEqual(resp_funil.status_code, 200)
        self.assertContains(resp_funil, 'Funil de Gestão Comercial das Licitações')

    def test_inicializacao_padrao_radares_e_especialidades(self):
        with tenant_context(self.org_a):
            radares = ls.inicializar_radares_padrao(self.admin_a)
            self.assertEqual(len(radares), 3)
            self.assertTrue(any('Alagoas' in r.nome for r in radares))

            especialidades = ps.inicializar_especialidades_padrao(self.admin_a)
            self.assertEqual(len(especialidades), 3)
            self.assertTrue(any('Biomédico' in e.especialidade for e in especialidades))
