"""Concorrência real: conexões independentes, transações e lock PostgreSQL."""
import base64
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase
from contas.models import Usuario, Tecnico
from clientes.models import Cliente
from equipamentos.models import CategoriaEquipamento, Equipamento
from platform_core.models import Organization, OrganizationERP, OrganizationMembership, MembershipERP, ERPCatalog
from platform_core.context import tenant_context
from .models import OrdemServico, Localizacao, Assinatura, Auditoria
from . import services
from .tests import png
from .forms import AssinaturaForm


@skipUnless(connection.vendor == 'postgresql', 'Locks concorrentes exigem PostgreSQL real.')
class PostgreSQLConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(slug='concurrency', razao_social='Teste de concorrência')
        erp, _ = ERPCatalog.objects.get_or_create(code='assistencia', defaults={'name': 'ERP Assistência'})
        OrganizationERP.objects.create(organization=self.org, erp=erp)
        self.user = Usuario.objects.create_user('concurrent-tech')
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.user, role='TECNICO')
        MembershipERP.objects.create(membership=membership, erp=erp)
        with tenant_context(self.org):
            customer = Cliente.objects.create(nome_razao_social='Cliente concorrência', cpf_cnpj='CONCURRENCY')
            category = CategoriaEquipamento.objects.create(nome='Teste')
            equipment = Equipamento.objects.create(nome='Equipamento', cliente=customer, categoria=category)
            tech = Tecnico.objects.create(nome='Técnico', usuario=self.user)
            self.order = OrdemServico.objects.create(cliente=customer, equipamento=equipment, tecnico=tech, defeito='Falha')

    def race(self, action):
        barrier = threading.Barrier(2)
        def work():
            connections.close_all()
            try:
                with tenant_context(self.org):
                    user = Usuario.objects.get(pk=self.user.pk)
                    barrier.wait(timeout=10)
                    try:
                        action(user)
                        return 'ok'
                    except ValidationError:
                        return 'blocked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: work(), range(2)))
        self.assertCountEqual(results, ['ok', 'blocked'])

    def test_inicio_simultaneo_registra_apenas_um_inicio_e_auditoria(self):
        self.race(lambda user: services.iniciar(user, self.order.pk, {'resultado': 'NEGADA'}))
        with tenant_context(self.org):
            self.assertEqual(Localizacao.objects.filter(ordem=self.order, evento='INICIO').count(), 1)
            self.assertEqual(Auditoria.objects.filter(ordem=self.order, acao='INICIO').count(), 1)

    def test_finalizacao_simultanea_uma_assinatura_hash_e_snapshot_preservados(self):
        with tenant_context(self.org):
            services.iniciar(self.user, self.order.pk, {'resultado': 'NEGADA'})
            self.order.refresh_from_db()
            self.order.diagnostico, self.order.servico_executado = 'Falha', 'Reparo'
            self.order.save()
            conference = services.preparar(self.user, self.order.pk, {'resultado': 'NEGADA'})
            form = AssinaturaForm({'token': 'unused', 'nome': 'Responsável', 'cargo': 'Gerente', 'imagem': 'data:image/png;base64,' + base64.b64encode(png()).decode(), 'confirmacao': True})
            self.assertTrue(form.is_valid(), form.errors)
            signed_data = form.cleaned_data
            digest = conference.digest
        self.race(lambda user: services.finalizar(user, self.order.pk, conference.pk, signed_data))
        with tenant_context(self.org):
            self.assertEqual(Assinatura.objects.filter(ordem=self.order).count(), 1)
            self.assertEqual(Auditoria.objects.filter(ordem=self.order, acao='FINALIZACAO').count(), 1)
            conference.refresh_from_db()
            self.assertEqual(conference.digest, digest)
            self.assertEqual(services.digest(conference.dados), digest)
