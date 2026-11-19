from django.test import TestCase
from django.urls import reverse
from platform_core.context import tenant_context
from gestao import models as g, services as gs
from operacao.barcode_generator import generate_code128_svg
from .test_block2 import Block2Fixtures

class ThermalAndLabelsTests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()

    def test_code128_svg_generation(self):
        svg = generate_code128_svg('7898652370342', height=40, module_width=1.5)
        self.assertIn('<svg', svg)
        self.assertIn('7898652370342', svg)
        self.assertIn('<rect', svg)

    def test_barcode_labels_get(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            response = self.client.get(reverse('operacao:barcode_labels'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Gerador de Etiquetas')
            self.assertContains(response, self.part.sku)

    def test_barcode_labels_post_print_view(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            response = self.client.post(reverse('operacao:barcode_labels'), {
                'selected_pks': [self.part.pk],
                f'copies_{self.part.pk}': 2,
                'layout': 'termica_50x30',
                'show_price': '1',
                'show_org': '1',
                'show_sku': '1',
            })
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Impressão de Etiquetas')
            self.assertContains(response, self.part.descricao)
            self.assertContains(response, '<svg')

    def test_backup_dashboard_requires_permission(self):
        with tenant_context(self.a):
            self.client.force_login(self.admin)
            response = self.client.get(reverse('operacao:backup_dashboard'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Backups do Banco de Dados')
