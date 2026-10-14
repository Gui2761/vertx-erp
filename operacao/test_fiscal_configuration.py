"""Public fiscal preparation: synthetic tenants only, no real fiscal secrets."""
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, override_settings
from platform_core.context import tenant_context
from platform_core.models import FilialEmpresa, ConfiguracaoEmpresa, PlatformAudit
from gestao.tests import Dados
from gestao.services import write
from fiscal.nfce import configuration as c, services as s
from .test_fiscal_documental import proposal
from . import models as m


@override_settings(FISCAL_NFCE_LOCAL_ENABLED=True, PRIVATE_STORAGE=None, UPLOAD_STORAGE='local')
class FiscalConfigurationTests(Dados, TestCase):
    def setUp(self):
        self.prepare_data()
        with tenant_context(self.a):
            self.config = s.registrar_proposta_documental(self.admin, proposal())
        self.client.force_login(self.admin)
        self.url = '/fiscal/configuracao/' + str(self.config.pk) + '/'

    def payload(self, **changes):
        data = {'revisao': 0, 'dados_confirmados': True, 'logradouro': 'Rua teste', 'numero': '15',
            'complemento': '', 'bairro': 'Bairro confirmado', 'cep': '49200000', 'endereco_confirmado': True,
            'municipio': 'Município sintético', 'uf': 'SE', 'municipio_ibge': '2802106',
            'municipio_confirmado': True, 'cnae': '4645101', 'divergencias_confirmadas': True,
            'tipo_estabelecimento': 'MATRIZ', 'regime': '', 'crt': '', 'enquadramento': '',
            'regime_confirmado': False, 'credenciamento_confirmado': False, 'serie': '', 'proximo_numero': '',
            'natureza_operacao': '', 'qr_url': '', 'consulta_url': '', 'fonte_urls': '', 'schema_release': '', 'produto': ''}
        data.update(changes); return data

    def save(self, confirm=False, **changes):
        return c.save_preparation(self.admin, self.config.pk, self.payload(**changes), confirm=confirm)

    def test_admin_screen_has_document_source_and_pending_crt(self):
        response = self.client.get(self.url)
        for text in ('Fonte: documentação cadastral', 'Pendente de confirmação', 'EMISSÃO BLOQUEADA', 'Não provisionado', 'Confirmar estabelecimento fiscal', 'Simples Nacional: Sim', 'Bairro antigo', '3312103'):
            self.assertContains(response, text)
        self.assertContains(response, 'value="" selected>Pendente de confirmação')

    def test_no_secret_input_upload_or_emission_post_form(self):
        response = self.client.get(self.url)
        for field in ('pfx', 'senha', 'password', 'csc', 'certificado', 'organization_id', 'ambiente', 'cnpj', 'habilitada'):
            self.assertNotContains(response, 'name="' + field + '"')
        self.assertNotContains(response, 'type="file"')
        self.assertContains(response, 'disabled aria-disabled="true">Emitir NFC-e')

    def test_draft_can_save_without_crt_ibge_or_series(self):
        with tenant_context(self.a):
            cfg = c.save_preparation(self.admin, self.config.pk, {'revisao': 0})
            self.assertEqual(cfg.preparacao_fiscal['crt'], '')
            self.assertIsNone(cfg.preparacao_fiscal['serie'])
            self.assertFalse(cfg.habilitada)
            self.assertFalse(m.PerfilFiscalEstabelecimento.objects.exists())

    def test_required_establishment_fields_rejected_atomically(self):
        with tenant_context(self.a):
            for field in ('municipio_ibge', 'bairro', 'numero', 'municipio', 'cnae', 'tipo_estabelecimento'):
                with self.subTest(field=field), self.assertRaises(ValidationError): self.save(confirm=True, **{field: ''})
            self.assertEqual(FilialEmpresa.objects.count(), 1)
            self.config.refresh_from_db(); self.assertEqual(self.config.preparacao_fiscal, {})

    def test_explicit_confirmations_required(self):
        with tenant_context(self.a):
            for field in ('dados_confirmados', 'endereco_confirmado', 'municipio_confirmado', 'divergencias_confirmadas'):
                with self.subTest(field=field), self.assertRaises(ValidationError): self.save(confirm=True, **{field: False})

    def test_confirmation_preserves_provisional_and_original_proposal(self):
        with tenant_context(self.a):
            old = self.config.proposta_documental.copy(); branch = self.config.estabelecimento
            cfg = self.save(confirm=True); branch.refresh_from_db()
            self.assertFalse(branch.ativo)
            self.assertNotEqual(cfg.configuracao_confirmada.estabelecimento_id, branch.pk)
            self.assertTrue(cfg.configuracao_confirmada.estabelecimento.ativo)
            self.assertEqual(cfg.proposta_documental, old)
            self.assertFalse(cfg.configuracao_confirmada.habilitada)
            self.assertTrue(PlatformAudit.objects.filter(action='FISCAL_ESTABELECIMENTO_CONFIRMADO_LOCAL').exists())

    def test_confirmation_does_not_create_series_credentials_or_document(self):
        with tenant_context(self.a), patch('fiscal.nfce.contracts.CofreIndisponivel.transmitir') as transmit:
            self.save(confirm=True); transmit.assert_not_called()
            for model in (m.SerieFiscal, m.CredencialFiscal, m.VinculoCredencialFiscal, m.DocumentoFiscal, m.SolicitacaoFiscal, m.ReservaNumeracaoFiscal, m.ArtefatoNFCe):
                self.assertFalse(model.objects.exists())

    def test_series_zero_is_explicit_and_number_has_no_default(self):
        with tenant_context(self.a):
            cfg = self.save(serie=0)
            rows = dict(c.readiness(cfg)[0])
            self.assertTrue(rows['Série definida']); self.assertFalse(rows['Próximo número definido'])
            self.assertFalse(m.SerieFiscal.objects.exists())

    def test_series_and_next_number_bounds(self):
        with tenant_context(self.a):
            for changes in ({'serie': 890}, {'serie': -1}, {'proximo_numero': 0}, {'proximo_numero': 1000000000}):
                with self.subTest(changes=changes), self.assertRaises(ValidationError): self.save(**changes)

    def test_crt_not_inferred_from_simples(self):
        with tenant_context(self.a):
            cfg = self.save(); rows = dict(c.readiness(cfg)[0])
            self.assertFalse(rows['CRT confirmado']); self.assertFalse(rows['Regime confirmado'])
            company = ConfiguracaoEmpresa.objects.get(); self.assertEqual(company.crt, '')

    def test_regime_confirmation_requires_all_explicit_values(self):
        with tenant_context(self.a), self.assertRaises(ValidationError): self.save(regime_confirmado=True)

    def test_pending_accreditation_establishment_certificate(self):
        with tenant_context(self.a):
            cfg = self.save(); rows = dict(c.readiness(cfg)[0])
            for name in ('Estabelecimento confirmado', 'Credenciamento NFC-e confirmado', 'Certificado provisionado'):
                self.assertFalse(rows[name])

    def test_select_product_without_creating_taxation(self):
        with tenant_context(self.a):
            cfg = self.save(produto=self.da['part'].pk)
            rows, product = c.readiness(cfg)
            self.assertEqual(product.pk, self.da['part'].pk)
            self.assertTrue(dict(rows)['Produto definido']); self.assertFalse(dict(rows)['Tributação definida'])
            self.assertFalse(m.TributacaoProdutoNFCe.objects.exists())
        response = self.client.get(self.url)
        self.assertContains(response, 'Tributação pendente de definição pelo responsável fiscal')

    def test_other_tenant_product_rejected(self):
        with tenant_context(self.a), self.assertRaises(ValidationError): self.save(produto=self.db['part'].pk)

    def test_preparation_cannot_enable_even_if_public_checklist_filled(self):
        with tenant_context(self.a):
            cfg = self.save(confirm=True, crt='1', regime='Regime confirmado', enquadramento='EPP', regime_confirmado=True, credenciamento_confirmado=True, serie=1, proximo_numero=1, produto=self.da['part'].pk)
            final = cfg.configuracao_confirmada; final.habilitada = True
            with self.assertRaises(ValidationError): write(final)
            self.assertFalse(dict(c.readiness(cfg)[0])['Certificado provisionado'])

    def test_direct_legacy_configuration_cannot_bypass_preparation(self):
        with tenant_context(self.a):
            cfg = self.save(confirm=True)
            with self.assertRaises(ValidationError): s.cadastrar_local(self.admin, m.ConfiguracaoFiscal, estabelecimento=cfg.configuracao_confirmada.estabelecimento, versao=2, habilitada=True)

    def test_direct_backend_emission_validation_rejected(self):
        with tenant_context(self.a):
            cfg = self.save(confirm=True).configuracao_confirmada
            with self.assertRaises(ValidationError): s.validar_config(cfg, cfg, cfg, cfg)
            self.assertFalse(m.DocumentoFiscal.objects.exists())

    def test_actual_emission_endpoint_rejects_document_in_preparation(self):
        import uuid
        with tenant_context(self.a):
            cfg = self.save(confirm=True).configuracao_confirmada
            doc = m.DocumentoFiscal.objects.create(tipo='NFCE', modelo='65', ambiente='HOMOLOGACAO',
                configuracao_fiscal=cfg, estabelecimento=cfg.estabelecimento, criado_por=self.admin, valor=10, descricao='Documento sintético bloqueado')
        with patch('fiscal.nfce.contracts.CofreIndisponivel.transmitir') as send:
            response = self.client.post('/fiscal/nfce/homologacao/documentos/' + str(doc.pk) + '/EMITIR/', {'request_id': str(uuid.uuid4())})
            self.assertEqual(response.status_code, 400); send.assert_not_called()
        with tenant_context(self.a):
            self.assertFalse(m.SolicitacaoFiscal.objects.exists()); self.assertFalse(m.ReservaNumeracaoFiscal.objects.exists())

    def test_direct_model_habilitation_on_confirmed_branch_rejected(self):
        with tenant_context(self.a):
            cfg = self.save(confirm=True).configuracao_confirmada
            with self.assertRaises(ValidationError):
                m.ConfiguracaoFiscal.objects.create(estabelecimento=cfg.estabelecimento, tipo='NFCE', ambiente='HOMOLOGACAO', motor='NFCE_SVRS_HOM', versao=2, habilitada=True)

    def test_nonlocal_page_returns_access_denied_without_debug_error(self):
        with override_settings(FISCAL_NFCE_LOCAL_ENABLED=False):
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_direct_url_enable_or_emit_rejected(self):
        for payload in ({'acao': 'emitir', 'revisao': 0}, {'acao': 'salvar', 'revisao': 0, 'habilitada': 'on'}):
            response = self.client.post(self.url, payload)
            self.assertContains(response, 'Preparação não salva')
        with tenant_context(self.a):
            self.config.refresh_from_db(); self.assertFalse(self.config.habilitada)

    def test_production_and_issuer_tampering_rejected(self):
        for key, value in [('ambiente', 'PRODUCAO'), ('cnpj', '11444777000161'), ('organization_id', self.b.pk)]:
            response = self.client.post(self.url, {'revisao': 0, 'acao': 'salvar', key: value})
            self.assertContains(response, 'Preparação não salva')

    def test_foreign_credential_and_secret_payload_rejected(self):
        with tenant_context(self.b):
            cred = m.CredencialFiscal.objects.create(referencia='cofre://11111111-1111-1111-1111-111111111111', mecanismo='REFERENCIA', ambiente='HOMOLOGACAO')
        with tenant_context(self.a):
            for key, value in [('credencial', cred.pk), ('csc', 'forbidden'), ('certificado', 'forbidden')]:
                with self.assertRaises(ValidationError): self.save(**{key: value})
            self.assertFalse(m.VinculoCredencialFiscal.objects.exists())

    def test_sensitive_text_cannot_enter_audit_or_db(self):
        with tenant_context(self.a), self.assertRaises(ValidationError): self.save(enquadramento='BEGIN CERTIFICATE')
        with tenant_context(self.a):
            self.config.refresh_from_db(); self.assertEqual(self.config.preparacao_fiscal, {})

    def test_other_tenant_admin_cannot_view_or_change_config(self):
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {'acao': 'salvar', 'revisao': 0}).status_code, 404)
        response = self.client.get('/fiscal/configuracao/')
        self.assertNotContains(response, proposal()['dados']['cnpj'])
        with tenant_context(self.b), self.assertRaises(m.ConfiguracaoFiscal.DoesNotExist): c.save_preparation(self.admin_b, self.config.pk, {'revisao': 0})

    def test_customer_admin_has_no_authority_in_platform_tenant(self):
        with tenant_context(self.b), self.assertRaises(PermissionDenied): c.authorize(self.admin)

    def test_non_admin_roles_cannot_view_or_save(self):
        for role in ('GESTOR', 'FINANCEIRO', 'CONTABILIDADE', 'VENDEDOR', 'TECNICO', 'PDV'):
            user = self.user('prep-' + role, self.a, role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {'acao': 'salvar', 'revisao': 0}).status_code, 403)

    def test_stale_revision_rejected_without_losing_previous_data(self):
        with tenant_context(self.a):
            self.save(serie=3)
            with self.assertRaises(ValidationError): self.save(serie=4)
            self.config.refresh_from_db(); self.assertEqual(self.config.preparacao_fiscal['serie'], 3)

    def test_confirmed_establishment_not_silently_edited(self):
        with tenant_context(self.a):
            self.save(confirm=True)
            with self.assertRaises(ValidationError): self.save(revisao=1, bairro='Outro bairro')
            self.assertEqual(FilialEmpresa.objects.count(), 2)

    def test_subsequent_parameters_versioned_without_replacing_establishment(self):
        with tenant_context(self.a):
            first = self.save(confirm=True).configuracao_confirmada
            cfg = self.save(revisao=1, serie=8, proximo_numero=9)
            first.refresh_from_db()
            self.assertEqual(first.preparacao_fiscal['serie'], None)
            self.assertEqual(cfg.configuracao_confirmada.versao, 2)
            self.assertEqual(cfg.configuracao_confirmada.estabelecimento_id, first.estabelecimento_id)
            self.assertFalse(first.habilitada)

    def test_urls_and_xsd_presence_do_not_mean_validated(self):
        with tenant_context(self.a):
            cfg = self.save(qr_url='https://example.invalid/qr', consulta_url='https://example.invalid/consulta', fonte_urls='https://example.invalid/fonte', schema_release='Proposta não validada')
            rows = dict(c.readiness(cfg)[0]); self.assertFalse(rows['XSD validado']); self.assertFalse(rows['QR Code/consulta confirmados'])

    def test_local_guard_blocks_regular_environment(self):
        with tenant_context(self.a), override_settings(FISCAL_NFCE_LOCAL_ENABLED=False), self.assertRaises(ValidationError): self.save()

    def test_preserves_stock_membership_documents_and_company_tax_data(self):
        from platform_core.models import OrganizationMembership
        with tenant_context(self.a):
            company = ConfiguracaoEmpresa.objects.get(); company.crt = '3'; company.regime_tributario = 'Anterior'; company.save()
            balance = self.da['part'].quantidade_atual
            memberships = list(OrganizationMembership.objects.filter(organization=self.a).values())
            legacy = m.DocumentoFiscal.objects.create(tipo='NFSE', numero='LEGADO-CFG', valor=10, criado_por=self.admin, cliente=self.da['customer'], descricao='Legado sintético preservado')
            before = m.DocumentoFiscal.objects.filter(pk=legacy.pk).values().get()
            self.save(confirm=True)
            self.assertEqual(m.DocumentoFiscal.objects.filter(pk=legacy.pk).values().get(), before)
            self.assertEqual(list(OrganizationMembership.objects.filter(organization=self.a).values()), memberships)
            self.da['part'].refresh_from_db(); self.assertEqual(self.da['part'].quantidade_atual, balance)
            company.refresh_from_db(); self.assertEqual((company.crt, company.regime_tributario), ('3', 'Anterior'))
