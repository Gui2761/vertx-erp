"""Bateria Exaustiva de Testes de Falha, Resiliência e Caos (VERTYX ERP).

Cobre:
1. Resiliência matemática em pricing (divisão por zero, markup > 100%, custo zero, valores extremos).
2. Degradação graciosa de rede na API PNCP (timeout, 400, 500, HTML/JSON quebrado).
3. Blindagem de multi-inquilino (Org A vs Org B) e prevenção de vazamento de dados.
4. Resiliência de comprovantes e telas do PDV frente a payloads nulos ou corrompidos.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch, MagicMock
import urllib.error
import socket
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, RequestFactory
from django.utils import timezone

from operacao import licita_services as ls
from operacao import pricing_services as ps
from operacao.licita_models import RadarFiltroPNCP, OportunidadeLicitacao
from operacao.pricing_models import CalculadoraPrecoProduto, CalculadoraHoraTecnica
from operacao.pdv import sale, _company_receipt_context
from operacao import models as m
from platform_core.context import tenant_context
from .test_block3_commerce import CommerceData


class SystemFailureAndResilienceTests(CommerceData, TestCase):
    def setUp(self):
        self.setup_commerce()
        self.org_a = self.a
        self.org_b = self.b
        self.admin_a = self.admin
        self.user_b = self.other_admin

    # =========================================================================
    # 1. RESILIÊNCIA MATEMÁTICA E VALIDAÇÃO DE ENTRADAS (PRICING)
    # =========================================================================
    def test_pricing_produto_divisao_por_zero_rejeitada(self):
        """Soma de despesas + margem >= 100% causaria divisão por zero ou negativa."""
        with tenant_context(self.org_a):
            # Soma = 50 + 30 + 20 = 100% -> Denominador = 0
            with self.assertRaises(ValidationError) as ctx:
                ps.salvar_calculo_produto(
                    self.admin_a,
                    {
                        'nome_produto': 'Produto Risco Zero',
                        'custo_aquisicao': '100.00',
                        'percentual_despesas_fixas': '50.00',
                        'percentual_tributos': '30.00',
                        'percentual_outras_variaveis': '0.00',
                        'percentual_margem_desejada': '20.00',
                    },
                )
            self.assertIn('inferior a 100%', str(ctx.exception))

    def test_pricing_produto_soma_superior_a_100_rejeitada(self):
        """Soma > 100% gera preço negativo se desprotegido."""
        with tenant_context(self.org_a):
            with self.assertRaises(ValidationError):
                ps.salvar_calculo_produto(
                    self.admin_a,
                    {
                        'nome_produto': 'Produto Margem Impossível',
                        'custo_aquisicao': '500.00',
                        'percentual_despesas_fixas': '40.00',
                        'percentual_tributos': '40.00',
                        'percentual_margem_desejada': '30.00', # Total = 110%
                    },
                )

    def test_pricing_produto_custo_zero_ou_negativo(self):
        """Custo zero ou negativo deve ser validado com segurança."""
        with tenant_context(self.org_a):
            with self.assertRaises(ValidationError):
                ps.salvar_calculo_produto(
                    self.admin_a,
                    {
                        'nome_produto': 'Custo Negativo',
                        'custo_aquisicao': '-50.00',
                    },
                )

    def test_pricing_hora_tecnica_zero_tecnicos_ou_dias(self):
        """Evita divisão por zero se quantidade de técnicos ou dias for zero."""
        with tenant_context(self.org_a):
            with self.assertRaises(ValidationError):
                ps.salvar_calculo_hora_tecnica(
                    self.admin_a,
                    {
                        'especialidade': 'Técnico Fantasma',
                        'numero_tecnicos': '0',
                        'dias_trabalhados_mes': '22',
                        'horas_dia': '8.00',
                        'percentual_ocupacao': '70.00',
                        'custo_total_equipe': '5000.00',
                    },
                )

    # =========================================================================
    # 2. RESILIÊNCIA DA API PNCP CONTRA FALHAS DE REDE E PAYLOADS CORROMPIDOS
    # =========================================================================
    @patch('urllib.request.urlopen')
    def test_pncp_timeout_degrada_graciosamente(self, mock_urlopen):
        """Simula Timeout do servidor federal PNCP: não deve lançar 500, deve retornar lista vazia."""
        mock_urlopen.side_effect = socket.timeout("Connection timed out after 20s")
        resultado = ls.consultar_api_pncp_publicacoes(uf='AL', pagina=1, tamanho_pagina=10)
        self.assertEqual(resultado, [])

    @patch('urllib.request.urlopen')
    def test_pncp_erro_400_bad_request(self, mock_urlopen):
        """Simula erro 400 da API (ex: tamanhoPagina inválido): captura sem crash."""
        mock_urlopen.side_effect = urllib.error.HTTPError('https://pncp.gov.br', 400, 'Bad Request', {}, None)
        resultado = ls.consultar_api_pncp_publicacoes(uf='SE', pagina=1, tamanho_pagina=5)
        self.assertEqual(resultado, [])

    @patch('urllib.request.urlopen')
    def test_pncp_erro_500_ou_502_gateway(self, mock_urlopen):
        """Simula instabilidade no gateway PNCP (retorno HTML 502 Bad Gateway)."""
        mock_urlopen.side_effect = urllib.error.HTTPError('https://pncp.gov.br', 502, 'Bad Gateway', {}, None)
        resultado = ls.consultar_api_pncp_publicacoes(pagina=1, tamanho_pagina=10)
        self.assertEqual(resultado, [])

    @patch('urllib.request.urlopen')
    def test_pncp_json_invalido_ou_corrompido(self, mock_urlopen):
        """Resposta com status 200 mas corpo não-JSON ou corrompido."""
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'<html>corrupted non-json body</html>'
        mock_urlopen.return_value.__enter__.return_value = resp
        resultado = ls.consultar_api_pncp_publicacoes(pagina=1, tamanho_pagina=10)
        self.assertEqual(resultado, [])

    # =========================================================================
    # 3. ISOLAMENTO MULTI-TENANT E PREVENÇÃO DE VAZAMENTO DE DADOS
    # =========================================================================
    def test_radar_pncp_isolamento_estrito_entre_organizacoes(self):
        """Radar criado na Org A jamais pode ser acessado pela Org B."""
        with tenant_context(self.org_a):
            radar_a = RadarFiltroPNCP.objects.create(
                organization=self.org_a,
                nome='Radar Secreto Org A',
                palavras_chave='Autoclave, Desfibrilador',
                ufs='AL',
                criado_por=self.admin_a,
            )

        with tenant_context(self.org_b):
            # Consulta filtrada não deve ver o radar da Org A
            radars_b = RadarFiltroPNCP.objects.filter(pk=radar_a.pk)
            self.assertFalse(radars_b.exists())
            # Edição por usuário da Org B deve ser rejeitada
            with self.assertRaises(PermissionDenied):
                ls.salvar_radar_pncp(
                    self.user_b,
                    {'nome': 'Tentativa Invasao', 'palavras_chave': 'Hacker'},
                    radar_id=radar_a.pk,
                )

    def test_calculo_preco_isolamento_estrito_entre_organizacoes(self):
        """Cálculo de preço industrial da Org A invisível para Org B."""
        with tenant_context(self.org_a):
            calc_a = ps.salvar_calculo_produto(
                self.admin_a,
                {
                    'nome_produto': 'Raio-X Digital Estratégico',
                    'custo_aquisicao': '50000.00',
                    'percentual_despesas_fixas': '10.00',
                    'percentual_tributos': '12.00',
                    'percentual_margem_desejada': '20.00',
                },
            )

        with tenant_context(self.org_b):
            calcs_b = CalculadoraPrecoProduto.objects.filter(pk=calc_a.pk)
            self.assertFalse(calcs_b.exists())

    # =========================================================================
    # 4. RESILIÊNCIA DE COMPROVANTES DO PDV E TRATAMENTO DE PAYLOADS NULOS
    # =========================================================================
    def test_company_receipt_context_fallback_seguro_sem_organizacao(self):
        """Garante que _company_receipt_context não quebra mesmo se org for None."""
        ctx = _company_receipt_context(None)
        self.assertIn('company_razao_social', ctx)
        self.assertIn('company_cnpj', ctx)
        self.assertTrue(len(ctx['company_razao_social']) > 0)
        self.assertTrue(len(ctx['company_cnpj']) > 0)

    def test_comprovante_venda_com_snapshot_vazio_ou_sem_itens(self):
        """Garante que a rota de comprovante renderiza com fallback se snapshot estiver incompleto."""
        with tenant_context(self.org_a):
            # Cria sessão e venda finalizada com snapshot parcial
            depot = self.depot
            conta = m.ContaBancaria.objects.create(nome='Caixa Teste Falha', tipo='CAIXA', deposito_padrao=depot)
            sessao = m.SessaoCaixa.objects.create(
                conta=conta,
                operador=self.admin_a,
                saldo_abertura=Decimal('100.00'),
            )
            venda = m.Venda.objects.create(
                status='FINALIZADA',
                sessao_caixa=sessao,
                deposito=depot,
                vencimento=timezone.localdate(),
                vendedor=self.admin_a,
                total=Decimal('50.00'),
                snapshot={
                    'numero': 'VENDA-TESTE-RESILIENTE',
                    'total': '50.00',
                    'tipo_emissao': 'CUPOM',
                    'itens': [],
                    'pagamentos': [],
                },
            )

            rf = RequestFactory()
            req = rf.get(f'/pdv/vendas/{venda.public_id}/comprovante/')
            req.user = self.admin_a

            resp = sale(req, venda.public_id, receipt=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b'COMPROVANTE', resp.content)
