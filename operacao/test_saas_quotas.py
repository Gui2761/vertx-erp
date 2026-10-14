from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from gestao import models as g
from gestao.tests import Dados
from ordens import services as os_services
from platform_core.context import tenant_context
from platform_core.saas_models import AssinaturaSaaS, PlanoSaaS
from platform_core.saas_services import uso_quota, verificar_limite

from . import models as m, services


class SaaSQuotaOperationalTests(Dados, TestCase):
    def setUp(self):
        self.prepare_data()

    def plan_for(self, organization, limits):
        plan = PlanoSaaS.objects.create(
            slug=f'quota-{organization.slug}', nome='Plano de quota',
            modulos=['assistencia', 'estoque', 'pdv'], limites=limits,
        )
        AssinaturaSaaS.objects.create(organization=organization, plano=plan)
        return plan

    def test_medicao_os_e_vendas_usa_registros_oficiais_do_tenant_e_do_mes(self):
        self.plan_for(self.a, {'vendas_mes': 1, 'ordens_mes': 1})
        with tenant_context(self.a):
            self.assertEqual(uso_quota(self.a, 'ordens_mes'), 1)
            depot = m.Deposito.objects.create(nome='Quota PDV')
            confirmed = m.Venda.objects.create(cliente=self.da['customer'], deposito=depot,
                                               vencimento=timezone.localdate(), criado_por=self.admin)
            confirmed.status = 'FINALIZADA'
            confirmed.finalizada_em = timezone.now()
            confirmed._service_write = True
            confirmed.save()
            draft = m.Venda.objects.create(cliente=self.da['customer'], deposito=depot,
                                           vencimento=timezone.localdate(), criado_por=self.admin)
            m.ItemVenda.objects.create(venda=draft, peca=self.da['part'], quantidade=1, valor_unitario=20)
            cancelled = m.Venda.objects.create(cliente=self.da['customer'], deposito=depot,
                                               vencimento=timezone.localdate(), criado_por=self.admin)
            cancelled.status = 'CANCELADA'
            cancelled._service_write = True
            cancelled.save()
            self.assertEqual(uso_quota(self.a, 'vendas_mes'), 1)
            with self.assertRaisesMessage(ValidationError, 'Limite de vendas do plano atingido.'):
                services.venda_confirmar(self.admin, draft.pk)
            with self.assertRaisesMessage(ValidationError, 'Limite de ordens de serviço do plano atingido.'):
                os_services.criar(self.admin, object())
            self.assertEqual(draft.status, 'RASCUNHO')
        with tenant_context(self.b):
            self.assertEqual(uso_quota(self.b, 'vendas_mes'), 0)
            self.assertEqual(uso_quota(self.b, 'ordens_mes'), 1)

    def test_os_de_outro_mes_nao_consumem_quota_atual(self):
        self.plan_for(self.a, {'ordens_mes': 2})
        order = self.da['order']
        # The official opening is immutable through model save; timestamp override
        # is isolated to this synthetic validation fixture.
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('UPDATE ordens_ordemservico SET abertura = %s WHERE id = %s', [timezone.now() - timedelta(days=40), order.pk])
        with tenant_context(self.a):
            self.assertEqual(uso_quota(self.a, 'ordens_mes'), 0)

    def test_upload_de_foto_da_os_e_bloqueado_ao_estourar_storage_sem_gravar_arquivo(self):
        from unittest.mock import patch
        self.plan_for(self.a, {'armazenamento_mb': 1})
        order = self.da['order']
        with tenant_context(self.a):
            os_services.iniciar(self.admin, order.pk, {
                'resultado': 'NEGADA', 'latitude': None, 'longitude': None, 'precisao': None,
            })
            before = order.fotos.count()
            with patch('platform_core.saas_services._storage_usage_bytes', return_value=1024 * 1024):
                with self.assertRaisesMessage(ValidationError, 'Limite de armazenamento do plano atingido.'):
                    os_services.adicionar_foto(self.admin, order.pk, {
                        'arquivo': ContentFile(b'new-tenant-photo', name='foto.jpg'),
                        'descricao': 'Não deve gravar', 'categoria': 'ANTES',
                    })
            self.assertEqual(order.fotos.count(), before)
