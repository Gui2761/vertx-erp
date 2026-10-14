"""Synthetic fiscal boundaries; labels do not provision real legal entities."""
import copy
import uuid
from dataclasses import replace
from unittest.mock import patch
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.test import TestCase
from contas.models import Usuario
from platform_core.context import tenant_context
from platform_core.models import Organization, OrganizationERP, OrganizationMembership, PermissaoMembership, FilialEmpresa
from platform_core.modules import has_capability
from fiscal import foundation as s
from fiscal.nfce import services as nfce
from . import models as m
from .test_fiscal_foundation import FiscalData
from .test_nfce_homologacao import NFCeData


class FiscalThreeTenantsTests(FiscalData, TestCase):
    def setUp(self):
        self.fiscal_setup()
        # Never use real company identifiers in unit fixtures.
        self.a.nome_fantasia='VERTYX — organização sintética'; self.a.save()
        self.b.nome_fantasia='TECNOLMED — organização sintética'; self.b.save()
        self.other=Organization.objects.create(slug='cliente-b-fiscal-qa',razao_social='Cliente B — sintético')
        OrganizationERP.objects.create(organization=self.other,erp=self.erp)
        self.other_admin=self.user('admin-cliente-b-fiscal-qa',self.other,'ADMIN')
        self.other_customer=self.data(self.other,self.other_admin)['customer']
        with tenant_context(self.other):
            branch=FilialEmpresa.objects.create(codigo='SIM',nome='Estabelecimento sintético Cliente B')
            s.cadastrar(self.other_admin,m.PerfilFiscalEstabelecimento,estabelecimento=branch,municipio_ibge='3550308',uf='SP')
            self.other_config=s.cadastrar(self.other_admin,m.ConfiguracaoFiscal,estabelecimento=branch,tipo='NFSE',habilitada=True)
            self.other_series=s.cadastrar(self.other_admin,m.SerieFiscal,estabelecimento=branch,tipo='NFSE',serie='SIM')
        self.contexts=[(self.a,self.admin,self.da['customer'],self.configs[self.a.pk,'NFSE'],self.series[self.a.pk,'NFSE']),
                       (self.b,self.admin_b,self.db['customer'],self.configs[self.b.pk,'NFSE'],self.series[self.b.pk,'NFSE']),
                       (self.other,self.other_admin,self.other_customer,self.other_config,self.other_series)]

    def authorized_documents(self):
        docs=[]
        for org,user,customer,config,series in self.contexts:
            with tenant_context(org):
                doc=s.preparar_documento(user,config.pk,series.pk,cliente_id=customer.pk,valor='149.00')
                req=s.solicitar(user,doc.pk,uuid.uuid4());s.processar(user,req.pk);doc.refresh_from_db()
                docs.append((org,user,doc,m.Documento.objects.get(fiscal=doc)))
        return docs

    def test_three_issuers_keep_own_documents_numbers_and_private_xml(self):
        docs=self.authorized_documents()
        for org,user,doc,file in docs:
            with self.subTest(organization=org.slug),tenant_context(org):
                self.assertEqual(doc.numero,'1')
                self.assertEqual(doc.organization_id,org.pk)
                self.assertEqual(doc.snapshot_fiscal['emitente']['organization'],str(org.public_id))
                self.assertEqual(set(m.DocumentoFiscal.objects.values_list('pk',flat=True)),{doc.pk})
                self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)
                self.assertIn(str(org.public_id),file.arquivo.name)
                self.assertFalse(file.disponivel_portal)
                with file.arquivo.open('rb') as stream:
                    content=stream.read().decode()
                self.assertIn(str(org.public_id),content)
                for foreign_org,_,_,_ in docs:
                    if foreign_org.pk!=org.pk:self.assertNotIn(str(foreign_org.public_id),content)
        self.assertFalse(m.DocumentoFiscal.objects.exists())

    def test_all_three_tenant_pairs_reject_foreign_document_and_xml_urls(self):
        docs=self.authorized_documents()
        for org,user,own_doc,own_file in docs:
            self.client.force_login(user)
            session=self.client.session;session['organization_id']=org.pk;session.save()
            self.assertEqual(self.client.get(f'/fiscal/simulacao/documentos/{own_doc.pk}/').status_code,200)
            own=self.client.get(f'/documentos/{own_file.pk}/arquivo/')
            self.assertEqual(own.status_code,200)
            self.assertIn(str(org.public_id).encode(),b''.join(own.streaming_content))
            for foreign_org,_,doc,file in docs:
                if org.pk==foreign_org.pk:continue
                with self.subTest(source=org.slug,target=foreign_org.slug):
                    self.assertEqual(self.client.get(f'/fiscal/simulacao/documentos/{doc.pk}/').status_code,404)
                    self.assertEqual(self.client.get(f'/documentos/{file.pk}/arquivo/').status_code,404)

    def test_all_three_tenant_pairs_reject_foreign_config_series_credentials_establishments(self):
        creds={}
        for org,user,_,_,_ in self.contexts:
            with tenant_context(org):
                creds[org.pk]=s.cadastrar(user,m.CredencialFiscal,referencia='simulacao://'+str(uuid.uuid4()),mecanismo='SIMULACAO')
        for org,user,customer,config,series in self.contexts:
            with tenant_context(org):
                for foreign_org,_,_,foreign_config,foreign_series in self.contexts:
                    if org.pk==foreign_org.pk:continue
                    with self.subTest(source=org.slug,target=foreign_org.slug):
                        for cfg,ser,cred in [(foreign_config,series,None),(config,foreign_series,None),(config,series,creds[foreign_org.pk].pk)]:
                            with self.assertRaises(ObjectDoesNotExist):
                                s.preparar_documento(user,cfg.pk,ser.pk,cliente_id=customer.pk,valor=10,credencial_id=cred)
                        with self.assertRaises(ValidationError):
                            s.cadastrar(user,m.VinculoCredencialFiscal,configuracao=config,credencial=creds[foreign_org.pk])
                        with self.assertRaises(ValidationError):
                            s.cadastrar(user,m.ConfiguracaoFiscal,estabelecimento=foreign_config.estabelecimento,tipo='NFSE',versao=2)
                self.assertFalse(m.DocumentoFiscal.objects.exists())

    def test_platform_superuser_without_tenant_membership_has_no_fiscal_capabilities(self):
        platform_admin=Usuario.objects.create_superuser('saas-fiscal-qa','saas-qa@example.invalid','synthetic-test-only')
        for org,_,_,_,_ in self.contexts:
            with tenant_context(org):
                for cap in ('fiscal_consultar','fiscal_emitir','fiscal_cancelar','fiscal_configurar','fiscal_gerenciar_credenciais'):
                    self.assertFalse(has_capability(platform_admin,cap))
                with self.assertRaises(PermissionDenied):s.permissao(platform_admin,'fiscal_gerenciar_credenciais')

    def test_proprietor_membership_and_staff_status_do_not_grant_customer_fiscal(self):
        self.admin.is_superuser=True;self.admin.is_staff=True;self.admin.save()
        with tenant_context(self.a):self.assertTrue(has_capability(self.admin,'fiscal_gerenciar_credenciais'))
        for org in (self.b,self.other):
            with tenant_context(org):
                self.assertFalse(has_capability(self.admin,'fiscal_emitir'))
                with self.assertRaises(PermissionDenied):s.permissao(self.admin,'fiscal_gerenciar_credenciais')

    def test_explicit_tenant_denial_still_blocks_platform_superuser(self):
        self.admin.is_superuser=True;self.admin.is_staff=True;self.admin.save()
        with tenant_context(self.a):
            membership=OrganizationMembership.objects.get(user=self.admin,organization=self.a)
            PermissaoMembership.objects.create(membership=membership,capacidade='fiscal_gerenciar_credenciais',permitido=False)
            self.assertFalse(has_capability(self.admin,'fiscal_gerenciar_credenciais'))
            with self.assertRaises(PermissionDenied):s.revogar_credencial(self.admin,1)

    def test_proprietor_nfse_never_reuses_customer_tenant_customer_record(self):
        with tenant_context(self.a):
            with self.assertRaises(ObjectDoesNotExist):
                s.preparar_documento(self.admin,self.configs[self.a.pk,'NFSE'].pk,self.series[self.a.pk,'NFSE'].pk,cliente_id=self.db['customer'].pk,valor='149.00')
            self.assertFalse(m.DocumentoFiscal.objects.exists())


class FiscalVaultBoundaryTests(NFCeData,TestCase):
    def setUp(self):self.nfce_setup()

    def test_certificate_wrong_establishment_even_same_cnpj_is_rejected(self):
        with tenant_context(self.a):
            doc=self.homdoc()
            self.vault.identity=replace(self.vault.identity,estabelecimento_id=self.configs[self.a.pk,'NFSE'].estabelecimento_id)
            with patch.object(self.vault,'assinar',wraps=self.vault.assinar) as sign:
                with self.assertRaises(ValidationError):self.motor.preparar_assinado(doc,self.generated(doc),'EMITIR')
                sign.assert_not_called()

    def test_vault_receives_full_context_for_identity_signature_and_transport(self):
        with tenant_context(self.a):
            req=self.homreq();doc=req.documento;context=self.motor.contexto(doc)
            with patch.object(self.vault,'identidade',wraps=self.vault.identidade) as identity,patch.object(self.vault,'assinar',wraps=self.vault.assinar) as sign,patch.object(self.vault,'transmitir',wraps=self.vault.transmitir) as send:
                self.assertEqual(self.runreq(req).estado,'CONCLUIDA')
                for call in identity.call_args_list:self.assertEqual(call.kwargs,context)
                self.assertEqual(sign.call_args.kwargs,context);self.assertEqual(send.call_args.kwargs,context)

    def test_cached_document_in_foreign_tenant_rejected_before_vault_access(self):
        with tenant_context(self.a):doc=self.homdoc()
        with tenant_context(self.b),patch.object(self.vault,'identidade',wraps=self.vault.identidade) as identity:
            with self.assertRaises(ValidationError):self.motor.validar(doc)
            identity.assert_not_called()

    def test_missing_context_rejected_before_vault_access(self):
        with tenant_context(self.a):doc=self.homdoc()
        with patch.object(self.vault,'identidade',wraps=self.vault.identidade) as identity:
            with self.assertRaises(PermissionDenied):self.motor.validar(doc)
            identity.assert_not_called()

    def test_unlinked_same_tenant_credential_rejected_before_vault_access(self):
        with tenant_context(self.a):
            doc=self.homdoc()
            doc.credencial_fiscal=m.CredencialFiscal.objects.create(referencia='cofre://'+str(uuid.uuid4()),mecanismo='REFERENCIA',ambiente='HOMOLOGACAO')
            with patch.object(self.vault,'identidade',wraps=self.vault.identidade) as identity:
                with self.assertRaises(ValidationError):self.motor.validar(doc)
                identity.assert_not_called()

    def test_snapshot_foreign_issuer_rejected_before_vault_access(self):
        with tenant_context(self.a):
            doc=self.homdoc();doc.snapshot_fiscal=copy.deepcopy(doc.snapshot_fiscal)
            doc.snapshot_fiscal['emitente']['cnpj']='00000000000000'
            with patch.object(self.vault,'identidade',wraps=self.vault.identidade) as identity:
                with self.assertRaises(ValidationError):self.motor.validar(doc)
                identity.assert_not_called()

    def test_unsigned_foreign_xml_or_environment_rejected_before_signature(self):
        with tenant_context(self.a):
            doc=self.homreq().documento;original=self.generated(doc)
            for data in (original.replace(self.branch.cnpj.encode(),b'00000000000000'),original.replace(b'<tpAmb>2</tpAmb>',b'<tpAmb>1</tpAmb>'),original.replace(('NFe'+doc.chave).encode(),b'NFe'+b'0'*44)):
                with self.subTest(payload=data[:10]),patch.object(self.vault,'assinar',wraps=self.vault.assinar) as sign:
                    with self.assertRaises(ValidationError):self.motor.preparar_assinado(doc,data,'EMITIR')
                    sign.assert_not_called()

    def test_query_for_foreign_document_rejected_before_transport(self):
        from fiscal.nfce.schema import NFE
        with tenant_context(self.a):
            doc=self.homreq().documento
            payload=(f'<consSitNFe xmlns="{NFE}" versao="4.00"><tpAmb>2</tpAmb><xServ>CONSULTAR</xServ><chNFe>'+('0'*44)+'</chNFe></consSitNFe>').encode()
            with patch.object(self.vault,'transmitir',wraps=self.vault.transmitir) as send:
                with self.assertRaises(ValidationError):self.motor.enviar(doc,payload,'CONSULTAR')
                send.assert_not_called()

    def test_customer_nfce_does_not_use_proprietor_nfse_config(self):
        with tenant_context(self.a):sale=self.confirmed()
        with tenant_context(self.b):
            config=self.configs[self.b.pk,'NFSE'];series=self.series[self.b.pk,'NFSE']
        with tenant_context(self.a):
            with self.assertRaises(ObjectDoesNotExist):nfce.preparar(self.admin,sale.pk,config.pk,series.pk,self.cred.pk,self.rule.pk)
            self.assertFalse(m.DocumentoFiscal.objects.filter(venda=sale).exists())
