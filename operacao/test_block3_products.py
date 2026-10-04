from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from platform_core.context import tenant_context
from gestao import models as g, services as gs, products
from .test_block2 import Block2Fixtures

class ProductTests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()

    def test_decimal_box_and_fraction_conversion(self):
        with tenant_context(self.a):
            self.part.fator_compra=Decimal('100'); self.part.unidade_compra='CX'; self.part.save()
            result=products.convert(self.part,'1.25','compra','250.00')
            self.assertEqual((result['quantidade_base'],result['valor_base']),(Decimal('125'),Decimal('2.50')))
            self.assertEqual(products.convert(self.part,'.001','base')['quantidade_base'],Decimal('.001'))

    def test_no_silent_rounding_nonfinite_and_nonfractional(self):
        with tenant_context(self.a):
            self.part.fator_compra=Decimal('3')
            for value, price in [('1','10.00'),('NaN',None),('1.0001',None)]:
                with self.assertRaises(ValidationError): products.convert(self.part,value,'compra',price)
            self.part.fracionavel=False
            with self.assertRaises(ValidationError): products.convert(self.part,'.5','base')

    def test_scan_codes_and_ambiguity_scoped_to_organization(self):
        with tenant_context(self.a):
            code=g.CodigoProduto.objects.create(peca=self.part,codigo='LEITOR-1')
            self.assertEqual(products.lookup(code.codigo),self.part)
            self.part.codigo_barras='LEITOR-1';self.part.save()
            self.assertEqual(products.lookup('LEITOR-1'),self.part)
        with tenant_context(self.b):
            with self.assertRaises(ValidationError): products.lookup('LEITOR-1')

    def test_supplier_relation_cannot_cross_organization(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError): g.FornecedorProduto.objects.create(peca=self.db['part'],fornecedor=self.supplier)

    def test_required_lot_rolls_back_official_stock(self):
        with tenant_context(self.a):
            self.part.exige_lote=True;self.part.save()
            with self.assertRaises(ValidationError): gs.movimentar(self.admin,self.part.pk,'ENTRADA',1)
            self.part.refresh_from_db();self.assertEqual(self.part.quantidade_atual,0)
            self.incoming(1)
            self.part.refresh_from_db();self.assertEqual(self.part.quantidade_atual,1)
