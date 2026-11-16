import uuid
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from platform_core.context import tenant_context
from platform_core.models import (
    ERPCatalog, ERPProductModule, Organization, OrganizationERP,
    OrganizationMembership, MembershipERP, PermissaoMembership,
)
from contas.models import Usuario
from operacao import models as m


class CaixasPDVUnificadoTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(slug='empresa-caixa-test', razao_social='Empresa Teste Caixas')
        self.user = Usuario.objects.create_user('admin-caixas', password='Password123!')
        self.membership = OrganizationMembership.objects.create(
            organization=self.org, user=self.user, role='ADMIN', status='ATIVO'
        )
        self.erp_servicos = ERPCatalog.objects.get_or_create(code='assistencia', defaults={'name': 'VERTYX Serviços', 'active': True})[0]
        self.erp_lojas = ERPCatalog.objects.get_or_create(code='comercio-pdv', defaults={'name': 'VERTYX Lojas', 'active': True})[0]
        OrganizationERP.objects.create(organization=self.org, erp=self.erp_servicos)
        MembershipERP.objects.create(membership=self.membership, erp=self.erp_servicos)

        with tenant_context(self.org):
            self.depot = m.Deposito.objects.create(nome='deposito 01', ativo=True)
            self.bank_account = m.ContaBancaria.objects.create(
                nome='caixa01', tipo='BANCO', saldo_inicial=Decimal('0.00'), ativo=True
            )

        self.client.force_login(self.user)
        session = self.client.session
        session['organization_id'] = self.org.pk
        session.save()

    def test_pdv_displays_warning_and_available_banks_when_no_caixa_configured(self):
        with tenant_context(self.org):
            self.assertEqual(m.ContaBancaria.objects.filter(tipo='CAIXA').count(), 0)

        response = self.client.get('/pdv/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nenhum Caixa Físico disponível para abertura')
        self.assertContains(response, 'caixa01')
        self.assertContains(response, 'Tornar Caixa PDV')
        self.assertContains(response, '/bancos/novo/?tipo=CAIXA')

    def test_banco_acao_tornar_caixa_auto_assigns_depot_and_enables_pdv(self):
        with tenant_context(self.org):
            self.assertEqual(self.bank_account.tipo, 'BANCO')
            self.assertIsNone(self.bank_account.deposito_padrao)

        # Trigger conversion action
        url = reverse('operacao:banco_acao', args=[self.bank_account.pk, 'tornar_caixa'])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        with tenant_context(self.org):
            self.bank_account.refresh_from_db()
            self.assertEqual(self.bank_account.tipo, 'CAIXA')
            self.assertEqual(self.bank_account.deposito_padrao, self.depot)

        # Now PDV should have the account available for opening
        response = self.client.get('/pdv/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'caixa01 · deposito 01')
        self.assertNotContains(response, 'Nenhum Caixa Físico disponível para abertura')

    def test_banco_acao_tornar_banco_reverts_to_banco(self):
        with tenant_context(self.org):
            self.bank_account.tipo = 'CAIXA'
            self.bank_account.deposito_padrao = self.depot
            self.bank_account.save()

        url = reverse('operacao:banco_acao', args=[self.bank_account.pk, 'tornar_banco'])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        with tenant_context(self.org):
            self.bank_account.refresh_from_db()
            self.assertEqual(self.bank_account.tipo, 'BANCO')

    def test_bancos_list_filter_caixa_and_actions(self):
        with tenant_context(self.org):
            caixa = m.ContaBancaria.objects.create(nome='Caixa Balcao', tipo='CAIXA', deposito_padrao=self.depot, ativo=True)

        # List all
        response = self.client.get('/bancos/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'caixa01')
        self.assertContains(response, 'Caixa Balcao')
        self.assertContains(response, 'Tornar Caixa')
        self.assertContains(response, 'Tornar Banco')

        # Filter only CAIXA
        response = self.client.get('/bancos/?tipo=CAIXA')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Caixa Balcao')
        self.assertNotContains(response, 'caixa01')
        self.assertContains(response, 'href="/bancos/novo/?tipo=CAIXA"')

    def test_banco_novo_with_tipo_caixa_preselects_tipo_and_depot(self):
        response = self.client.get('/bancos/novo/?tipo=CAIXA')
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(form.initial.get('tipo'), 'CAIXA')
        self.assertEqual(form.initial.get('deposito_padrao'), self.depot)

        # Post new cash account without explicit depot -> clean() auto-selects the only active depot
        post_url = reverse('operacao:banco_novo')
        post_response = self.client.post(post_url, {
            'nome': 'Caixa Loja 2',
            'tipo': 'CAIXA',
            'saldo_inicial': '0.00',
            'ativo': 'on',
        })
        self.assertEqual(post_response.status_code, 302)
        with tenant_context(self.org):
            novo = m.ContaBancaria.objects.get(nome='Caixa Loja 2')
            self.assertEqual(novo.tipo, 'CAIXA')
            self.assertEqual(novo.deposito_padrao, self.depot)
