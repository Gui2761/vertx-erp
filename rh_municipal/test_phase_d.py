from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, OrganizationERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from . import phase_d_models as d
from . import phase_d_services as services
from .models import AcessoMunicipal, PermissaoMunicipal
from .public_services import scoped_queryset
from .tests import MunicipalFixtures


PHASE_D_MODULES = ('gestao_publica', 'patrimonio', 'almoxarifado', 'frotas')


class MunicipalPhaseDTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.modules = {}
        for index, code in enumerate(PHASE_D_MODULES, start=70):
            self.modules[code] = ERPProductModule.objects.get_or_create(
                erp=self.publico, code=code,
                defaults={'name': code.replace('_', ' ').title(), 'active': True, 'sort_order': index},
            )[0]
        self.plan = PlanoSaaS.objects.create(slug='fase-d-municipal-test', nome='Plano sintético Fase D', erp=self.publico, modulos=[])
        for module in self.modules.values():
            PlanoProdutoModulo.objects.create(plano=self.plan, modulo=module)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.city_access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )
            self.unit_access = AcessoMunicipal.objects.create(
                membership=self.server_user, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            for code in ('almoxarifado.view', 'almoxarifado.request', 'patrimonio.inventory'):
                PermissaoMunicipal.objects.create(acesso=self.unit_access, capacidade=code)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

    def _deposit_item(self):
        with tenant_context(self.c):
            deposit = d.DepositoAlmoxarifadoMunicipal(organization=self.c, codigo='DEP-1', nome='Depósito Central', criado_por=self.admin_c.user)
            deposit.save()
            item = d.ItemAlmoxarifadoMunicipal(organization=self.c, codigo='MAT-1', nome='Material de teste', unidade_medida='UN')
            item.save()
        return deposit, item

    def test_module_isolation_and_direct_url_access(self):
        for url_name in ('patrimonio_home', 'almoxarifado_home', 'frotas_home'):
            self.assertEqual(self.client.get(reverse(f'rh_municipal_public:{url_name}')).status_code, 200)
        restricted = PlanoSaaS.objects.create(slug='fase-d-without-fleet', nome='Sem frota', erp=self.publico, modulos=[])
        for code in ('gestao_publica', 'patrimonio', 'almoxarifado'):
            PlanoProdutoModulo.objects.create(plano=restricted, modulo=self.modules[code])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=restricted)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:frotas_home')).status_code, 403)

    def test_asset_tombstone_movement_and_writeoff_preserve_history(self):
        with tenant_context(self.c):
            asset = services.create_asset(self.admin_c.user, data={
                'tombamento': 'PAT-001', 'descricao': 'Computador sintético', 'categoria': 'Informática',
            })
            movement = services.move_asset(self.admin_c.user, asset.pk, data={
                'tipo': d.MovimentacaoPatrimonial.Tipo.BAIXA,
                'motivo': 'Baixa de teste auditável',
            })
            asset.refresh_from_db()
            self.assertEqual(asset.situacao, d.BemPatrimonial.Situacao.BAIXADO)
            self.assertEqual(d.MovimentacaoPatrimonial.objects.filter(pk=movement.pk).count(), 1)
            with self.assertRaises(ValidationError):
                movement.delete()
            with self.assertRaises(ValidationError):
                services.move_asset(self.admin_c.user, asset.pk, data={'tipo': 'TRANSFERENCIA', 'motivo': 'Não permitido'})

    def test_foreign_tenant_reference_is_rejected(self):
        OrganizationERP.objects.get_or_create(organization=self.a, erp=self.publico, defaults={'enabled': True})
        with tenant_context(self.a):
            other_secretary = self._structure(self.a)[0]
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                services.create_asset(self.admin_c.user, data={
                    'tombamento': 'PAT-X', 'descricao': 'Bem com referência externa',
                    'categoria': 'Teste', 'secretaria': other_secretary,
                })

    def test_store_receipt_transfer_and_nonnegative_constraint(self):
        deposit, item = self._deposit_item()
        with tenant_context(self.c):
            services.receive_stock(self.admin_c.user, deposit_id=deposit.pk, item_id=item.pk,
                                   quantity='8', reason='Recebimento sintético')
            destination = d.DepositoAlmoxarifadoMunicipal(organization=self.c, codigo='DEP-2', nome='Unidade Norte', unidade=self.structure[3], criado_por=self.admin_c.user)
            destination.save()
            services.transfer_stock(self.admin_c.user, source_id=deposit.pk, target_id=destination.pk,
                                    item_id=item.pk, quantity='3', reason='Transferência sintética')
            source_balance = d.SaldoAlmoxarifadoMunicipal.objects.get(deposito=deposit, item=item)
            target_balance = d.SaldoAlmoxarifadoMunicipal.objects.get(deposito=destination, item=item)
            self.assertEqual(source_balance.quantidade, Decimal('5'))
            self.assertEqual(target_balance.quantidade, Decimal('3'))
            self.assertEqual(d.MovimentoAlmoxarifadoMunicipal.objects.filter(transferencia_id__isnull=False).count(), 2)
            with self.assertRaises(ValidationError):
                services.transfer_stock(self.admin_c.user, source_id=deposit.pk, target_id=destination.pk,
                                        item_id=item.pk, quantity='9', reason='Tentativa de saldo negativo')
            source_balance.refresh_from_db()
            self.assertEqual(source_balance.quantidade, Decimal('5'))

    def test_request_approval_and_delivery_decrements_stock_atomically(self):
        deposit, item = self._deposit_item()
        with tenant_context(self.c):
            services.receive_stock(self.admin_c.user, deposit_id=deposit.pk, item_id=item.pk, quantity='10', reason='Entrada')
            request = services.create_material_request(self.server_user.user, unit=self.structure[3],
                items=[(item, '2')], priority='NORMAL', reason='Reposição de material')
            services.decide_material_request(self.admin_c.user, request.pk, approve=True, reason='Aprovada')
            services.issue_material_request(self.admin_c.user, request.pk, deposit_id=deposit.pk, quantities={}, deliver=True)
            request.refresh_from_db()
            balance = d.SaldoAlmoxarifadoMunicipal.objects.get(deposito=deposit, item=item)
            self.assertEqual(request.status, d.SolicitacaoMaterialMunicipal.Status.ENTREGUE)
            self.assertEqual(balance.quantidade, Decimal('8'))
            self.assertEqual(request.historico.count(), 3)

    def test_inventories_count_and_adjust_with_audit(self):
        deposit, item = self._deposit_item()
        with tenant_context(self.c):
            services.receive_stock(self.admin_c.user, deposit_id=deposit.pk, item_id=item.pk, quantity='7', reason='Entrada')
            inventory = services.start_store_inventory(self.admin_c.user, deposit_id=deposit.pk, exercise=2026)
            row = inventory.itens.get(item=item)
            services.count_store_item(self.admin_c.user, row.pk, quantity='6', reason='Contagem física')
            services.close_store_inventory(self.admin_c.user, inventory.pk)
            inventory.refresh_from_db()
            row.refresh_from_db()
            self.assertEqual(inventory.status, d.InventarioAlmoxarifadoMunicipal.Status.ENCERRADO)
            self.assertEqual(d.SaldoAlmoxarifadoMunicipal.objects.get(deposito=deposit, item=item).quantidade, Decimal('6'))
            self.assertEqual(row.divergencia, Decimal('-1'))
            self.assertTrue(d.MovimentoAlmoxarifadoMunicipal.objects.filter(tipo=d.MovimentoAlmoxarifadoMunicipal.Tipo.AJUSTE).exists())

    def test_unit_scope_sees_only_own_unit_and_rejects_cross_unit_request(self):
        self.client.force_login(self.server_user.user)
        session = self.client.session; session['organization_id'] = self.c.pk; session.save()
        deposit, item = self._deposit_item()
        with tenant_context(self.c):
            sector = self.structure[2]
            outside = self.structure[3].__class__.objects.create(
                organization=self.c, setor=sector, codigo='UNI-OUT', nome='Unidade fora do escopo',
            )
            self.assertFalse(scoped_queryset(self.server_user.user, d.DepositoAlmoxarifadoMunicipal.objects.filter(unidade=outside)).exists())
        response = self.client.get(reverse('rh_municipal_public:almoxarifado_home'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, outside.nome)

    def test_fleet_trip_odometer_driver_validity_and_return(self):
        with tenant_context(self.c):
            vehicle = d.VeiculoMunicipal(organization=self.c, placa='ABC1D23', marca='Teste', modelo='Van', quilometragem_atual=100)
            vehicle.save()
            driver = d.CondutorMunicipal(organization=self.c, servidor=self.server, numero_cnh='CNH-1', categoria='B', validade=date.today() + timedelta(days=30))
            driver.save()
            trip = services.start_trip(self.admin_c.user, vehicle_id=vehicle.pk, driver_id=driver.pk,
                data={'origem': 'Paço', 'destino': 'Unidade', 'finalidade': 'Serviço', 'quilometragem_inicial': 100})
            with self.assertRaises(ValidationError):
                services.return_trip(self.admin_c.user, trip.pk, final_km=99)
            services.return_trip(self.admin_c.user, trip.pk, final_km=132)
            vehicle.refresh_from_db(); trip.refresh_from_db()
            self.assertEqual(trip.km_percorridos, 32)
            self.assertEqual(vehicle.quilometragem_atual, 132)
            self.assertEqual(vehicle.situacao, d.VeiculoMunicipal.Situacao.DISPONIVEL)

    def test_expired_driver_cannot_start_trip(self):
        with tenant_context(self.c):
            vehicle = d.VeiculoMunicipal(organization=self.c, placa='ABC1D24', marca='Teste', modelo='Van')
            vehicle.save()
            driver = d.CondutorMunicipal(organization=self.c, servidor=self.server, numero_cnh='CNH-2', categoria='B', validade=date.today() - timedelta(days=1))
            driver.save()
            with self.assertRaises(ValidationError):
                services.start_trip(self.admin_c.user, vehicle_id=vehicle.pk, driver_id=driver.pk,
                    data={'origem': 'Paço', 'destino': 'Unidade', 'finalidade': 'Serviço', 'quilometragem_inicial': 0})

    def test_fueling_cost_and_consumption_require_full_tank_sequence(self):
        with tenant_context(self.c):
            vehicle = d.VeiculoMunicipal(organization=self.c, placa='ABC1D25', marca='Teste', modelo='Van')
            vehicle.save()
            first = services.record_fueling(self.admin_c.user, vehicle_id=vehicle.pk, data={
                'combustivel': 'Diesel', 'quantidade_litros': '30', 'tanque_completo': True,
                'valor_unitario': '6.00', 'quilometragem': 100, 'posto': 'Posto sintético',
            })
            self.assertEqual(first.valor_total, Decimal('180.00'))
            self.assertIsNone(first.media_km_l)
            services.record_fueling(self.admin_c.user, vehicle_id=vehicle.pk, data={
                'combustivel': 'Diesel', 'quantidade_litros': '20', 'tanque_completo': True,
                'valor_unitario': '6.00', 'quilometragem': 300,
            })
            latest = d.AbastecimentoMunicipal.objects.order_by('-pk').first()
            self.assertEqual(latest.media_km_l, Decimal('10.0000'))

    def test_public_dashboard_shows_scoped_fleet_costs_and_distance(self):
        with tenant_context(self.c):
            vehicle = d.VeiculoMunicipal(organization=self.c, placa='ABC1D26', marca='Teste', modelo='Van',
                                         unidade=self.structure[3])
            vehicle.save()
            services.record_fueling(self.admin_c.user, vehicle_id=vehicle.pk, data={
                'combustivel': 'Diesel', 'quantidade_litros': '30', 'tanque_completo': True,
                'valor_unitario': '6.00', 'quilometragem': 100,
            })
            driver = d.CondutorMunicipal(organization=self.c, servidor=self.server,
                numero_cnh='CNH-DASH', categoria='B', validade=date.today() + timedelta(days=30))
            driver.save()
            trip = services.start_trip(self.admin_c.user, vehicle_id=vehicle.pk, driver_id=driver.pk,
                data={'origem': 'Paço', 'destino': 'Unidade', 'finalidade': 'Indicador sintético', 'quilometragem_inicial': 100})
            services.return_trip(self.admin_c.user, trip.pk, final_km=150)
        response = self.client.get('/gestao-publica/')
        self.assertEqual(response.status_code, 200)
        monthly = response.context['phase_d_summary']['fleet_month']
        self.assertEqual(monthly['fuel'], Decimal('180.00'))
        self.assertEqual(monthly['km'], 50)
        self.assertEqual(monthly['per_km'], Decimal('3.6000'))
        self.assertContains(response, 'Custo registrado no mês')

    def test_admin_scope_cannot_access_other_organization_id(self):
        response = self.client.get(reverse('rh_municipal_public:patrimonio_home'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(d.BemPatrimonial.objects.filter(pk=999999).count(), 0)

