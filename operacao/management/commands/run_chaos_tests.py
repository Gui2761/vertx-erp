"""Comando de Auditoria e Testes de Resiliência, Caos e Falhas do VERTYX ERP.

Executa a bateria completa de 13 testes de resiliência, isolamento e tolerância a falhas.
Todas as mutações de banco são executadas com rollback atômico ou isoladas.
"""
from __future__ import annotations

import sys
import time
from decimal import Decimal
from unittest.mock import patch, MagicMock
import urllib.error
import socket

from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import RequestFactory
from django.utils import timezone
from django.db import transaction

from platform_core.models import Organization
from platform_core.context import tenant_context
from operacao import licita_services as ls
from operacao import pricing_services as ps
from operacao.licita_models import RadarFiltroPNCP
from operacao.pricing_models import CalculadoraPrecoProduto
from operacao.pdv import sale, _company_receipt_context
from operacao import models as m


class Command(BaseCommand):
    help = 'Executa bateria exaustiva de testes de falha, resiliência e caos em todos os sistemas.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))
        self.stdout.write(self.style.MIGRATE_HEADING(' VERTYX ERP - AUDITORIA DE RESILIÊNCIA, CAOS E TESTE DE FALHAS'))
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))

        tests = [
            ('Pricing: Divisão por Zero Rejeitada (Soma = 100%)', self.test_pricing_div_zero),
            ('Pricing: Soma Percentuais > 100% Rejeitada', self.test_pricing_sum_gt_100),
            ('Pricing: Custo Zero ou Negativo Rejeitado', self.test_pricing_custo_negativo),
            ('Pricing: Hora Técnica Sem Técnicos / Dias Rejeitado', self.test_pricing_hora_zero),
            ('PNCP API: Timeout de Rede Degrada Graciosamente', self.test_pncp_timeout),
            ('PNCP API: Erro HTTP 400 Bad Request Tratado', self.test_pncp_400),
            ('PNCP API: Erro HTTP 502 Bad Gateway Tratado', self.test_pncp_502),
            ('PNCP API: Payload Corrompido / Não-JSON Tratado', self.test_pncp_corrupt_json),
            ('Multi-Tenant: Isolamento Estrito de Radar PNCP (Org A vs Org B)', self.test_tenant_radar),
            ('Multi-Tenant: Isolamento Estrito de Pricing Industrial', self.test_tenant_pricing),
            ('PDV Comprovante: Fallback Seguro Sem Organização (None)', self.test_receipt_org_none),
            ('PDV Comprovante: Venda Com Snapshot Vazio / Sem Itens', self.test_receipt_empty_snapshot),
            ('PDV Produção: Comprovante da Venda Real (VENDA-000074)', self.test_real_sale_receipt),
        ]

        passed = 0
        failed = 0
        start_total = time.time()

        for name, test_func in tests:
            t0 = time.time()
            try:
                test_func()
                elapsed = (time.time() - t0) * 1000
                self.stdout.write(self.style.SUCCESS(f'  [PASS] {name} ({elapsed:.1f}ms)'))
                passed += 1
            except Exception as e:
                elapsed = (time.time() - t0) * 1000
                self.stdout.write(self.style.ERROR(f'  [FAIL] {name} ({elapsed:.1f}ms) -> {e}'))
                failed += 1

        total_elapsed = time.time() - start_total
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))
        self.stdout.write(f'Resultado: {passed} APROVADOS | {failed} FALHAS | Tempo Total: {total_elapsed:.2f}s')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))

        if failed > 0:
            sys.exit(1)

    # 1. PRICING
    def test_pricing_div_zero(self):
        org = Organization.objects.first()
        user = org.memberships.first().user if org and org.memberships.exists() else None
        if not user:
            return
        with tenant_context(org):
            try:
                ps.salvar_calculo_produto(
                    user,
                    {
                        'nome_produto': 'Produto Risco Zero',
                        'custo_aquisicao': '100.00',
                        'percentual_despesas_fixas': '50.00',
                        'percentual_tributos': '30.00',
                        'percentual_outras_variaveis': '0.00',
                        'percentual_margem_desejada': '20.00',
                    },
                )
                raise AssertionError('Deveria ter lançado ValidationError para soma=100%')
            except ValidationError as e:
                assert 'inferior a 100%' in str(e)

    def test_pricing_sum_gt_100(self):
        org = Organization.objects.first()
        user = org.memberships.first().user if org and org.memberships.exists() else None
        if not user:
            return
        with tenant_context(org):
            try:
                ps.salvar_calculo_produto(
                    user,
                    {
                        'nome_produto': 'Produto Margem Impossível',
                        'custo_aquisicao': '500.00',
                        'percentual_despesas_fixas': '40.00',
                        'percentual_tributos': '40.00',
                        'percentual_margem_desejada': '30.00',
                    },
                )
                raise AssertionError('Deveria ter lançado ValidationError para soma > 100%')
            except ValidationError:
                pass

    def test_pricing_custo_negativo(self):
        org = Organization.objects.first()
        user = org.memberships.first().user if org and org.memberships.exists() else None
        if not user:
            return
        with tenant_context(org):
            try:
                ps.salvar_calculo_produto(
                    user,
                    {
                        'nome_produto': 'Custo Negativo',
                        'custo_aquisicao': '-50.00',
                    },
                )
                raise AssertionError('Deveria ter lançado ValidationError para custo negativo')
            except ValidationError:
                pass

    def test_pricing_hora_zero(self):
        org = Organization.objects.first()
        user = org.memberships.first().user if org and org.memberships.exists() else None
        if not user:
            return
        with tenant_context(org):
            try:
                ps.salvar_calculo_hora_tecnica(
                    user,
                    {
                        'especialidade': 'Técnico Fantasma',
                        'num_tecnicos': '0',
                        'dias_uteis_mes': '22',
                        'horas_dia': '8.00',
                        'percentual_ocupacao_faturavel': '70.00',
                        'custo_mensal_centro': '5000.00',
                    },
                )
                raise AssertionError('Deveria ter lançado ValidationError para 0 técnicos')
            except ValidationError:
                pass

    # 2. PNCP API
    @patch('urllib.request.urlopen')
    def test_pncp_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = socket.timeout('Connection timed out')
        res = ls.consultar_api_pncp_publicacoes(uf='AL', pagina=1, tamanho_pagina=10)
        assert res == [], f'Esperado [], obtido {res}'

    @patch('urllib.request.urlopen')
    def test_pncp_400(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError('https://pncp.gov.br', 400, 'Bad Request', {}, None)
        res = ls.consultar_api_pncp_publicacoes(uf='SE', pagina=1, tamanho_pagina=5)
        assert res == [], f'Esperado [], obtido {res}'

    @patch('urllib.request.urlopen')
    def test_pncp_502(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError('https://pncp.gov.br', 502, 'Bad Gateway', {}, None)
        res = ls.consultar_api_pncp_publicacoes(pagina=1, tamanho_pagina=10)
        assert res == [], f'Esperado [], obtido {res}'

    @patch('urllib.request.urlopen')
    def test_pncp_corrupt_json(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'<html>Gateway Timeout Non-JSON</html>'
        mock_urlopen.return_value.__enter__.return_value = resp
        res = ls.consultar_api_pncp_publicacoes(pagina=1, tamanho_pagina=10)
        assert res == [], f'Esperado [], obtido {res}'

    # 3. MULTI-TENANT ISOLATION
    def test_tenant_radar(self):
        orgs = list(Organization.objects.all()[:2])
        if len(orgs) < 2:
            return
        org_a, org_b = orgs[0], orgs[1]

        with transaction.atomic():
            with tenant_context(org_a):
                radar = RadarFiltroPNCP.objects.create(
                    organization=org_a,
                    nome='__RADAR_AUDIT_CHAOS__',
                    palavras_chave='Autoclave, Desfibrilador',
                    ufs='AL',
                )

            with tenant_context(org_b):
                radars_b = RadarFiltroPNCP.objects.filter(pk=radar.pk)
                assert not radars_b.exists(), 'Vazamento: Org B conseguiu ver o radar da Org A!'

            transaction.set_rollback(True)

    def test_tenant_pricing(self):
        orgs = list(Organization.objects.all()[:2])
        if len(orgs) < 2:
            return
        org_a, org_b = orgs[0], orgs[1]
        user_a = org_a.memberships.first().user

        with transaction.atomic():
            with tenant_context(org_a):
                calc_a = ps.salvar_calculo_produto(
                    user_a,
                    {
                        'nome_produto': '__PRICING_AUDIT_CHAOS__',
                        'custo_aquisicao': '50000.00',
                        'percentual_despesas_fixas': '10.00',
                        'percentual_tributos': '12.00',
                        'percentual_margem_desejada': '20.00',
                    },
                )

            with tenant_context(org_b):
                calcs_b = CalculadoraPrecoProduto.objects.filter(pk=calc_a.pk)
                assert not calcs_b.exists(), 'Vazamento: Org B conseguiu ver o cálculo de pricing da Org A!'

            transaction.set_rollback(True)

    # 4. PDV RECEIPT
    def test_receipt_org_none(self):
        ctx = _company_receipt_context(None)
        assert 'company_razao_social' in ctx
        assert 'company_cnpj' in ctx
        assert len(ctx['company_razao_social']) > 0
        assert len(ctx['company_cnpj']) > 0

    def test_receipt_empty_snapshot(self):
        org = Organization.objects.filter(slug='tecnolmed-gestao-clinica-ltda-000186').first()
        if not org:
            org = Organization.objects.first()
        user = org.memberships.first().user if org and org.memberships.exists() else None
        if not user:
            return

        with transaction.atomic():
            with tenant_context(org):
                sessao = m.SessaoCaixa.objects.filter(organization=org).first()
                depot = m.Deposito.objects.filter(organization=org).first()
                if not sessao or not depot:
                    return

                venda = m.Venda(
                    organization=org,
                    status='FINALIZADA',
                    sessao_caixa=sessao,
                    deposito=depot,
                    vencimento=timezone.localdate(),
                    vendedor=user,
                    snapshot={
                        'numero': 'VENDA-CHAOS-EMPTY',
                        'total': '50.00',
                        'tipo_emissao': 'CUPOM',
                        'itens': [],
                        'pagamentos': [],
                    },
                )
                venda._service_write = True
                venda.save()

                rf = RequestFactory()
                req = rf.get(f'/pdv/vendas/{venda.public_id}/comprovante/')
                req.user = user

                resp = sale(req, venda.public_id, receipt=True)
                assert resp.status_code == 200, f'Status esperado 200, obtido {resp.status_code}'
                assert b'COMPROVANTE' in resp.content or b'CUPOM' in resp.content or b'NFC-e' in resp.content

            transaction.set_rollback(True)

    def test_real_sale_receipt(self):
        org = Organization.objects.filter(slug='tecnolmed-gestao-clinica-ltda-000186').first()
        if not org:
            org = Organization.objects.first()
        user = org.memberships.first().user

        with tenant_context(org):
            venda = m.Venda.objects.filter(public_id='fb78be66-cd63-4f5c-99bc-4d32b6fa774c').first()
            if not venda:
                venda = m.Venda.objects.filter(status='FINALIZADA').order_by('-id').first()
            if not venda:
                return

            rf = RequestFactory()
            req = rf.get(f'/pdv/vendas/{venda.public_id}/comprovante/')
            req.user = user

            resp = sale(req, venda.public_id, receipt=True)
            assert resp.status_code == 200, f'Status esperado 200, obtido {resp.status_code}'
            assert len(resp.content) > 5000, f'Conteúdo muito pequeno: {len(resp.content)} bytes'
            assert b'NFC-e' in resp.content or b'DANFE' in resp.content or b'COMPROVANTE' in resp.content
