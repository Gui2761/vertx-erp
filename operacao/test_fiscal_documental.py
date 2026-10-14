"""Public registration proposals in an isolated local DB. Synthetic identities."""
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, override_settings
from platform_core.context import tenant_context
from platform_core.models import ConfiguracaoEmpresa, FilialEmpresa, PlatformAudit
from gestao.tests import Dados
from gestao.services import write
from fiscal.nfce import services as s
from . import models as m


def proposal():
    return {'dados': {'cnpj': '11222333000181', 'razao_social': 'Cliente documental de teste',
        'nome_fantasia': 'Cliente teste', 'ie': '271234567', 'im': '100001',
        'logradouro': 'Rua sintética', 'numero': '715', 'complemento': 'Sala 01',
        'bairro': 'Bairro proposto', 'cep': '49200000', 'municipio': 'Município documental',
        'uf': 'SE', 'cnae_principal': '4645101', 'natureza_juridica': 'Sociedade Empresária Limitada',
        'porte': 'EPP', 'simples_nacional': True},
        'fontes': ['Documento sintético 2026'],
        'divergencias': [{'campo': 'bairro', 'anterior': 'Bairro antigo', 'proposta': 'Bairro proposto'},
            {'campo': 'cnae_principal', 'anterior': '3312103', 'proposta': '4645101'}],
        'cadastro_anterior': {}}


@override_settings(FISCAL_NFCE_LOCAL_ENABLED=True, PRIVATE_STORAGE=None, UPLOAD_STORAGE='local')
class FiscalDocumentalTests(Dados, TestCase):
    def setUp(self):
        self.prepare_data()

    def register(self):
        return s.registrar_proposta_documental(self.admin, proposal())

    def test_confirmed_registration_and_provisional_establishment(self):
        with tenant_context(self.a):
            cfg = self.register(); self.a.refresh_from_db()
            self.assertEqual(self.a.cnpj, proposal()['dados']['cnpj'])
            self.assertEqual(self.a.razao_social, proposal()['dados']['razao_social'])
            self.assertEqual(cfg.estabelecimento.inscricao_municipal, '100001')
            self.assertFalse(cfg.estabelecimento.ativo)
            self.assertEqual((cfg.tipo, cfg.ambiente, cfg.habilitada), ('NFCE', 'HOMOLOGACAO', False))

    def test_no_inferred_tax_profile_series_or_credentials(self):
        with tenant_context(self.a):
            self.register(); company = ConfiguracaoEmpresa.objects.get()
            self.assertEqual((company.crt, company.regime_tributario), ('', ''))
            for model in (m.PerfilFiscalEstabelecimento, m.SerieFiscal, m.CredencialFiscal,
                          m.VinculoCredencialFiscal, m.RegraTributariaFiscal, m.ConfiguracaoNFCe):
                self.assertFalse(model.objects.exists())

    def test_no_document_request_number_xml_or_transmission(self):
        with tenant_context(self.a), patch('fiscal.nfce.contracts.CofreIndisponivel.identidade') as identity, patch('fiscal.nfce.contracts.CofreIndisponivel.assinar') as sign, patch('fiscal.nfce.contracts.CofreIndisponivel.transmitir') as send:
            self.register(); identity.assert_not_called(); sign.assert_not_called(); send.assert_not_called()
            for model in (m.DocumentoFiscal, m.SolicitacaoFiscal, m.ReservaNumeracaoFiscal, m.ArtefatoNFCe):
                self.assertFalse(model.objects.exists())

    def test_repeat_is_idempotent_and_preserves_audit(self):
        with tenant_context(self.a):
            cfg = self.register(); count = PlatformAudit.objects.filter(organization=self.a).count()
            self.assertEqual(self.register().pk, cfg.pk)
            self.assertEqual(PlatformAudit.objects.filter(organization=self.a).count(), count)
            self.assertEqual(FilialEmpresa.objects.count(), 1)

    def test_changed_proposal_requires_explicit_revision(self):
        with tenant_context(self.a):
            cfg = self.register(); changed = proposal(); changed['dados']['numero'] = '716'
            with self.assertRaises(ValidationError): s.registrar_proposta_documental(self.admin, changed)
            cfg.refresh_from_db(); self.assertEqual(cfg.proposta_documental['dados']['numero'], '715')

    def test_conflicting_ie_im_are_preserved_and_recorded(self):
        with tenant_context(self.a):
            company = ConfiguracaoEmpresa.objects.create(inscricao_estadual='IE-antiga', inscricao_municipal='IM-antiga')
            cfg = self.register(); company.refresh_from_db()
            self.assertEqual((company.inscricao_estadual, company.inscricao_municipal), ('IE-antiga', 'IM-antiga'))
            self.assertEqual(len(cfg.proposta_documental['divergencias']), 4)
            self.assertEqual(self.register().pk, cfg.pk)

    def test_existing_definitive_tax_fields_are_not_overwritten(self):
        with tenant_context(self.a):
            company = ConfiguracaoEmpresa.objects.create(crt='3', regime_tributario='Regime anterior')
            self.register(); company.refresh_from_db()
            self.assertEqual((company.crt, company.regime_tributario), ('3', 'Regime anterior'))

    def test_conflicting_organization_cnpj_rejected_atomically(self):
        with tenant_context(self.a):
            self.a.cnpj = '11444777000161'; self.a.save()
            with self.assertRaises(ValidationError): self.register()
            self.assertFalse(FilialEmpresa.objects.exists()); self.assertFalse(ConfiguracaoEmpresa.objects.exists())

    def test_prior_name_recorded_in_audit_and_proposal(self):
        with tenant_context(self.a):
            old = self.a.razao_social; cfg = self.register()
            self.assertEqual(cfg.proposta_documental['cadastro_anterior']['razao_social'], old)
            self.assertTrue(PlatformAudit.objects.filter(organization=self.a, action='FISCAL_CADASTRO_DOCUMENTAL').exists())

    def test_draft_cannot_be_enabled_even_through_audited_service(self):
        with tenant_context(self.a):
            cfg = self.register(); cfg.habilitada = True
            with self.assertRaises(ValidationError): write(cfg)
            cfg.refresh_from_db(); self.assertFalse(cfg.habilitada)

    def test_draft_cannot_change_environment(self):
        with tenant_context(self.a):
            cfg = self.register()
            for env in ('SIMULACAO', 'PRODUCAO'):
                cfg.ambiente = env
                with self.assertRaises(ValidationError): cfg.full_clean()

    def test_disabled_configuration_blocks_preparation_before_vault(self):
        with tenant_context(self.a):
            cfg = self.register()
            with self.assertRaises(ValidationError): s.validar_config(cfg, cfg, cfg, cfg)
            self.assertFalse(m.DocumentoFiscal.objects.exists())

    def test_tenant_id_and_secrets_not_accepted(self):
        with tenant_context(self.a):
            for key in ('organization_id', 'certificado', 'CSC', 'token', 'crt', 'serie'):
                data = proposal(); data['dados'][key] = 'forbidden'
                with self.assertRaises(ValidationError): s.registrar_proposta_documental(self.admin, data)
            self.assertFalse(m.ConfiguracaoFiscal.objects.exists())

    def test_secret_material_and_inconsistent_divergence_rejected(self):
        with tenant_context(self.a):
            data = proposal(); data['fontes'] = ['BEGIN CERTIFICATE']
            with self.assertRaises(ValidationError): s.registrar_proposta_documental(self.admin, data)
            data = proposal(); data['divergencias'][0]['proposta'] = 'Diferente'
            with self.assertRaises(ValidationError): s.registrar_proposta_documental(self.admin, data)

    def test_local_guard_blocks_without_modifying_organization(self):
        with tenant_context(self.a), override_settings(FISCAL_NFCE_LOCAL_ENABLED=False):
            old = self.a.cnpj
            with self.assertRaises(ValidationError): self.register()
            self.a.refresh_from_db(); self.assertEqual(self.a.cnpj, old)

    def test_technician_seller_pdv_cannot_register_or_access(self):
        for role in ('TECNICO', 'VENDEDOR', 'PDV'):
            user = self.user('documental-' + role, self.a, role)
            with tenant_context(self.a), self.assertRaises(PermissionDenied):
                s.registrar_proposta_documental(user, proposal())
            self.client.force_login(user)
            self.assertEqual(self.client.get('/fiscal/nfce/homologacao/').status_code, 403)

    def test_membership_of_other_tenant_cannot_register(self):
        with tenant_context(self.b), self.assertRaises(PermissionDenied): self.register()

    def test_proprietor_does_not_see_or_use_customer_proposal(self):
        before = (self.b.cnpj, self.b.razao_social)
        with tenant_context(self.a): cfg = self.register()
        with tenant_context(self.b):
            self.assertFalse(m.ConfiguracaoFiscal.objects.filter(pk=cfg.pk).exists())
            self.assertFalse(FilialEmpresa.objects.exists())
        self.b.refresh_from_db(); self.assertEqual((self.b.cnpj, self.b.razao_social), before)
        self.client.force_login(self.admin_b)
        response = self.client.get('/fiscal/nfce/homologacao/')
        self.assertNotContains(response, proposal()['dados']['cnpj'])

    def test_documental_screen_shows_confirmed_data_pending_and_divergences(self):
        with tenant_context(self.a): self.register()
        self.client.force_login(self.admin)
        response = self.client.get('/fiscal/nfce/homologacao/')
        for text in ('Cliente teste', '11222333000181', '271234567', '100001',
                     'Bairro antigo', 'Bairro proposto', '3312103', '4645101',
                     'Pendente de confirmação', 'Não configurados', 'cofre://UUID', 'Emissão bloqueada'):
            self.assertContains(response, text)
        self.assertNotContains(response, '>Preparar venda finalizada</a>')

    def test_existing_document_and_stock_are_preserved(self):
        with tenant_context(self.a):
            old = m.DocumentoFiscal.objects.create(tipo='NFSE', numero='LEGADO-1', valor=10,
                cliente=self.da['customer'], criado_por=self.admin, descricao='Documento legado sintético')
            balance = self.da['part'].quantidade_atual
            self.register(); old.refresh_from_db(); self.da['part'].refresh_from_db()
            self.assertEqual((old.numero, old.valor), ('LEGADO-1', 10))
            self.assertEqual(self.da['part'].quantidade_atual, balance)
