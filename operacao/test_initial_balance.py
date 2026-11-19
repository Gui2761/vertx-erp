from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from platform_core.context import tenant_context
from gestao import models as g, services as gs
from . import models as m
from .test_block2 import Block2Fixtures

class InitialBalanceTests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()

    def test_initial_balance_get_lists_products(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            response = self.client.get(reverse('operacao:stock_initial_balance'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Levantamento Inicial de Estoque')
            self.assertContains(response, 'Balanço Físico')

    def test_initial_balance_individual_post_adjusts_stock(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            self.assertEqual(self.part.quantidade_atual, Decimal('0.000'))
            
            response = self.client.post(reverse('operacao:stock_initial_balance'), {
                'action': 'salvar_individual',
                'peca_id': self.part.pk,
                'quantidade': '15.500',
                'lote': 'INICIAL-01',
            })
            self.assertEqual(response.status_code, 302)
            self.part.refresh_from_db()
            self.assertEqual(self.part.quantidade_atual, Decimal('15.500'))
            
            # Verificar se gerou movimentação do tipo AJUSTE
            mov = g.Movimentacao.objects.filter(peca=self.part, tipo='AJUSTE').last()
            self.assertIsNotNone(mov)
            self.assertEqual(mov.quantidade, Decimal('15.500'))

    def test_initial_balance_batch_post_adjusts_multiple(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            part2 = gs.write(g.Peca(organization=self.a, sku='SKU-BAL-02', descricao='Produto Balanço 2'))
            
            response = self.client.post(reverse('operacao:stock_initial_balance'), {
                'action': 'salvar_lote',
                'peca_pks': [self.part.pk, part2.pk],
                f'qty_{self.part.pk}': '20.000',
                f'lote_{self.part.pk}': 'LOTE-A',
                f'qty_{part2.pk}': '35.000',
                f'lote_{part2.pk}': 'LOTE-B',
            })
            self.assertEqual(response.status_code, 302)
            self.part.refresh_from_db()
            part2.refresh_from_db()
            self.assertEqual(self.part.quantidade_atual, Decimal('20.000'))
            self.assertEqual(part2.quantidade_atual, Decimal('35.000'))

    def test_initial_balance_template_download(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            response = self.client.get(reverse('operacao:stock_initial_balance_template'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
            content = response.content.decode('utf-8-sig')
            self.assertIn('CODIGO_SKU;DESCRICAO', content)
            self.assertIn(self.part.sku, content)

    def test_initial_balance_import_csv(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            csv_content = f"CODIGO_SKU;QUANTIDADE;NUMERO_LOTE\n{self.part.sku};42.000;LOTE-IMPORT\n"
            uploaded = SimpleUploadedFile(
                "balanco.csv",
                csv_content.encode('utf-8'),
                content_type="text/csv"
            )
            response = self.client.post(
                reverse('operacao:stock_initial_balance_import'),
                {'arquivo': uploaded}
            )
            self.assertEqual(response.status_code, 302)
            self.part.refresh_from_db()
            self.assertEqual(self.part.quantidade_atual, Decimal('42.000'))
