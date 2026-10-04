import uuid
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError, PermissionDenied
from platform_core.context import tenant_context
from gestao import models as g, services as gs
from . import models as m, inventory as inv, stock
from .test_block2 import Block2Fixtures

class InventoryTests(Block2Fixtures,TestCase):
    def setUp(self): self.setup_operations()
    def test_lot_count_approval_adjusts_official_stock_and_cost(self):
        with tenant_context(self.a):
            lot=self.incoming(5,7,'7.33');inventory=inv.open_inventory(self.admin,self.depot.pk,'Conferência física');item=inventory.itens.get()
            counted=inv.count(self.admin,inventory.public_id,item.pk,'3.250',uuid.uuid4())
            inv.approve_inventory(self.admin,inventory.public_id);inv.approve_inventory(self.admin,inventory.public_id)
            lot.refresh_from_db();self.part.refresh_from_db()
            self.assertEqual((lot.quantidade,self.part.quantidade_atual),(Decimal('3.250'),Decimal('3.250')))
            adjustment=m.AjusteInventario.objects.get(item=item)
            self.assertEqual(adjustment.movimento.valor_custo,Decimal('12.82750'))
            self.assertEqual(adjustment.movimento.lotes_movimentados.get().lote_id,lot.pk)
    def test_movement_requires_recount_and_preserves_count_history(self):
        with tenant_context(self.a):
            lot=self.incoming(5);inventory=inv.open_inventory(self.admin,self.depot.pk,'Inventário');item=inventory.itens.get()
            inv.count(self.admin,inventory.public_id,item.pk,5,uuid.uuid4())
            gs.movimentar(self.admin,self.part.pk,'SAIDA',1,origem_id=self.depot.pk)
            with self.assertRaises(ValidationError): inv.approve_inventory(self.admin,inventory.public_id)
            inv.count(self.admin,inventory.public_id,item.pk,4,uuid.uuid4());inv.approve_inventory(self.admin,inventory.public_id)
            self.assertEqual(item.contagens.count(),2)
    def test_expired_lot_can_be_counted_but_adjust_requires_approval(self):
        with tenant_context(self.a):
            lot=self.incoming(1);inventory=inv.open_inventory(self.admin,self.depot.pk,'Baixa física');item=inventory.itens.get()
            with self.assertRaises(PermissionDenied): gs.movimentar(self.admin,self.part.pk,'INVENTARIO',0,lote_id=lot.pk,origem_id=self.depot.pk)
            inv.count(self.admin,inventory.public_id,item.pk,0,uuid.uuid4());inv.approve_inventory(self.admin,inventory.public_id)
            self.part.refresh_from_db();self.assertEqual(self.part.quantidade_atual,0)
    def test_staged_transfer_preserves_groups_cost_and_protects_transit(self):
        with tenant_context(self.a):
            lot=self.incoming(2,7,'7.33');transit=m.Deposito.objects.create(nome='Trânsito');destination=m.Deposito.objects.create(nome='Filial destino')
            row=inv.create_transfer(self.admin,self.part.pk,self.depot.pk,destination.pk,2,'Mudança de localização',uuid.uuid4(),transit.pk)
            inv.send_transfer(self.admin,row.public_id);inv.send_transfer(self.admin,row.public_id)
            self.assertEqual(stock.metrics(self.part)['disponivel'],0)
            with self.assertRaises(ValidationError): gs.movimentar(self.admin,self.part.pk,'SAIDA',1,origem_id=transit.pk)
            inv.receive_transfer(self.admin,row.public_id);inv.receive_transfer(self.admin,row.public_id)
            received=m.LoteEstoque.objects.get(grupo=lot.grupo,deposito=destination)
            self.assertEqual((received.quantidade,received.custo_unitario),(2,Decimal('7.33')))
            self.assertEqual(row.etapas.count(),2)
            self.part.refresh_from_db();self.assertEqual(self.part.quantidade_atual,2)
    def test_inventory_and_transfer_foreign_tenant_are_hidden(self):
        with tenant_context(self.a):
            self.incoming(1);inventory=inv.open_inventory(self.admin,self.depot.pk,'Inventário')
        with tenant_context(self.b):
            with self.assertRaises(m.Inventario.DoesNotExist): inv.approve_inventory(self.admin_b,inventory.public_id)
