import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from gestao import models as g
from gestao.forms import FormaPagamentoForm
from gestao.payment_methods import DEFAULT_PDV_METHODS, ensure_default_pdv_methods
from platform_core.context import tenant_context
from platform_core.models import Organization
from . import models as m, commerce as c
from .test_block3_commerce import CommerceData


class PDVPaymentMethodTests(CommerceData, TestCase):
    def setUp(self):
        self.setup_commerce()
        with tenant_context(self.a):
            self.incoming(30)

    def _bank(self, name='Banco de recebimento'):
        with tenant_context(self.a):
            return m.ContaBancaria.objects.create(nome=name, tipo='BANCO')

    def _sale_with_payment(self, method, *, installments=1):
        with tenant_context(self.a):
            sale, _ = self.sale()
            c.add_item(self.operator, sale.public_id, self.part.sku, 1)
            expected_total = sale.total
            payment = {'forma': method.pk, 'valor': str(expected_total)}
            if installments > 1:
                payment['parcelas'] = installments
            result = c.finalize(self.operator, sale.public_id, [payment], uuid.uuid4())
            return result, result.pagamentos_pdv.get(), expected_total

    def test_new_tenant_gets_required_catalog_with_cash_active_only(self):
        organization = Organization.objects.create(slug='pdv-payments-new', razao_social='Tenant synthetic')
        created = ensure_default_pdv_methods(organization)
        self.assertEqual(len(created), len(DEFAULT_PDV_METHODS))
        with tenant_context(organization):
            methods = list(g.FormaPagamento.objects.order_by('tipo_pdv'))
            self.assertEqual(len(methods), 7)
            self.assertEqual({row.nome for row in methods}, {row[0] for row in DEFAULT_PDV_METHODS})
            self.assertEqual({row.tipo_pdv for row in methods}, {row[1] for row in DEFAULT_PDV_METHODS})
            self.assertEqual([row.tipo_pdv for row in methods if row.ativo], ['DINHEIRO'])
        self.assertEqual(ensure_default_pdv_methods(organization), [])

    def test_payment_method_catalog_is_tenant_scoped(self):
        bank = self._bank()
        with tenant_context(self.a):
            method_a = g.FormaPagamento.objects.create(nome='PIX tenant A', tipo_pdv='PIX', conta_pdv=bank)
        with tenant_context(self.b):
            bank_b = m.ContaBancaria.objects.create(nome='Banco tenant B', tipo='BANCO')
            method_b = g.FormaPagamento.objects.create(nome='PIX tenant B', tipo_pdv='PIX', conta_pdv=bank_b)
            self.assertEqual(list(g.FormaPagamento.objects.values_list('pk', flat=True)), [method_b.pk])
        with tenant_context(self.a):
            self.assertEqual(set(g.FormaPagamento.objects.values_list('pk', flat=True)), {method_a.pk, self.cash_method.pk, self.pix.pk, self.credit.pk})

    def test_admin_can_create_activate_and_deactivate_method_but_operator_cannot_configure(self):
        bank = self._bank()
        self.client.force_login(self.admin)
        create_url = reverse('gestao:forma_pagamento_novo')
        response = self.client.post(create_url, {'nome': 'Débito loja', 'tipo_pdv': 'DEBITO', 'conta_pdv': bank.pk})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.a):
            method = g.FormaPagamento.objects.get(nome='Débito loja')
            self.assertFalse(method.ativo)
        edit_url = reverse('gestao:forma_pagamento_editar', args=[method.pk])
        response = self.client.post(edit_url, {'nome': method.nome, 'tipo_pdv': 'DEBITO', 'conta_pdv': bank.pk, 'ativo': 'on'})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.a):
            method.refresh_from_db(); self.assertTrue(method.ativo)
        response = self.client.post(edit_url, {'nome': method.nome, 'tipo_pdv': 'DEBITO', 'conta_pdv': bank.pk})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.a):
            method.refresh_from_db(); self.assertFalse(method.ativo)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('gestao:forma_pagamento_lista')).status_code, 403)
        self.assertEqual(self.client.post(edit_url, {'nome': method.nome, 'tipo_pdv': 'DEBITO', 'conta_pdv': bank.pk, 'ativo': 'on'}).status_code, 403)

    def test_form_rejects_bank_method_without_active_account_and_foreign_account(self):
        with tenant_context(self.a):
            form = FormaPagamentoForm(
                {'nome': 'PIX sem banco', 'tipo_pdv': 'PIX', 'ativo': 'on'}
            )
            self.assertFalse(form.is_valid())
            self.assertIn('conta_pdv', form.errors)
        with tenant_context(self.b):
            foreign_bank = m.ContaBancaria.objects.create(nome='Conta B', tipo='BANCO')
        with tenant_context(self.a):
            form = FormaPagamentoForm(
                {'nome': 'PIX adulterado', 'tipo_pdv': 'PIX', 'conta_pdv': foreign_bank.pk, 'ativo': 'on'}
            )
            self.assertFalse(form.is_valid())
            self.assertIn('conta_pdv', form.errors)

    def test_cash_pix_debit_credit_and_installments_keep_finance_and_history(self):
        bank = self._bank()
        with tenant_context(self.a):
            debit = g.FormaPagamento.objects.create(nome='Débito', tipo_pdv='DEBITO', conta_pdv=bank)
            credit = g.FormaPagamento.objects.create(nome='Crédito', tipo_pdv='CREDITO', conta_pdv=bank)
        scenarios = [
            (self.cash_method, 1, self.cash.pk),
            (self.pix, 1, self.bank.pk),
            (debit, 1, bank.pk),
            (credit, 1, bank.pk),
            (credit, 6, bank.pk),
        ]
        for method, installments, expected_account in scenarios:
            with self.subTest(method=method.tipo_pdv, installments=installments):
                sale, row, expected_total = self._sale_with_payment(method, installments=installments)
                self.assertEqual(row.forma_id, method.pk)
                self.assertEqual(row.parcelas, installments)
                self.assertEqual((row.valor, row.recebido, row.troco), (expected_total, expected_total, Decimal('0.00')))
                self.assertEqual(row.pagamento.conta_id, expected_account)
                with tenant_context(self.a):
                    sale.refresh_from_db()
                    self.assertEqual(sale.conta.status, 'LIQUIDADO')
                    self.assertEqual(sale.snapshot['pagamentos'][0]['forma'], method.pk)
                    if installments > 1:
                        self.assertEqual(sale.snapshot['pagamentos'][0]['parcelas'], installments)
                    self.assertEqual(sale.pagamentos_pdv.count(), 1)
                    if method.tipo_pdv == 'DINHEIRO':
                        self.assertEqual(m.EventoCaixa.objects.filter(sessao=self.session, movimento__referencia=row.pagamento.request_id).count(), 1)

    def test_disabled_and_cross_tenant_payment_methods_are_rejected(self):
        bank = self._bank()
        with tenant_context(self.a):
            disabled = g.FormaPagamento.objects.create(nome='PIX desativado', tipo_pdv='PIX', conta_pdv=bank, ativo=False)
        with self.assertRaisesMessage(ValidationError, 'não está ativa nesta organização'):
            with tenant_context(self.a):
                c.normalize_payments([{'forma': disabled.pk, 'valor': '10.00'}])
        with tenant_context(self.b):
            bank_b = m.ContaBancaria.objects.create(nome='Banco B', tipo='BANCO')
            foreign = g.FormaPagamento.objects.create(nome='Débito B', tipo_pdv='DEBITO', conta_pdv=bank_b)
        with tenant_context(self.a):
            with self.assertRaisesMessage(ValidationError, 'não está ativa nesta organização'):
                c.normalize_payments([{'forma': foreign.pk, 'valor': '10.00'}])

    def test_payment_method_cannot_route_finance_to_another_tenants_account(self):
        with tenant_context(self.b):
            foreign_bank = m.ContaBancaria.objects.create(nome='Banco isolado', tipo='BANCO')
        with tenant_context(self.a):
            method = g.FormaPagamento.objects.create(nome='PIX sem conta', tipo_pdv='PIX')
            with self.assertRaisesMessage(ValidationError, 'desta organização'):
                c.normalize_payments([{'forma': method.pk, 'valor': '10.00'}])
            with self.assertRaisesMessage(ValidationError, 'Vínculo com outra organização'):
                g.FormaPagamento.objects.create(
                    nome='PIX com conta estrangeira', tipo_pdv='PIX', conta_pdv=foreign_bank
                )

    def test_credit_installment_range_and_other_methods_cannot_install(self):
        bank = self._bank()
        with tenant_context(self.a):
            credit = g.FormaPagamento.objects.create(nome='Crédito parcelas', tipo_pdv='CREDITO', conta_pdv=bank)
        for count in [0, 13, '1.5']:
            with self.subTest(count=count), tenant_context(self.a), self.assertRaises(ValidationError):
                c.normalize_payments([{'forma': credit.pk, 'valor': '10.00', 'parcelas': count}])
        with tenant_context(self.a):
            with self.assertRaisesMessage(ValidationError, 'somente para cartão de crédito'):
                c.normalize_payments([{'forma': self.cash_method.pk, 'valor': '10.00', 'parcelas': 3}])

