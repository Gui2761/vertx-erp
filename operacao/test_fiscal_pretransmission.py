"""Real cryptographic/XSD checks on synthetic issuers. NO transmission or real A1."""
import copy
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, SimpleTestCase, override_settings
from platform_core.context import tenant_context
from platform_core.models import Organization, FilialEmpresa, PlatformAudit
from gestao.tests import Dados
from fiscal.nfce import signature, pretransmission as p, services as s
from fiscal.nfce.certificates import cnpj_certificado, verificar_cadeia
from fiscal.nfce.schema import parse, NFE, SchemaOficial
from fiscal.nfce.vault import AdaptadorCofre
from fiscal.nfce.contracts import DependenciaFiscal
from .fiscal_test_support import SyntheticCertificate
from .test_nfce_homologacao import NFCeData
from .test_fiscal_documental import proposal
from . import models as m


@override_settings(FISCAL_NFCE_LOCAL_ENABLED=True, PRIVATE_STORAGE=None, UPLOAD_STORAGE='local')
class SignatureCryptographicTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cert = SyntheticCertificate()
        cls.unsigned = ('<NFe xmlns="'+NFE+'"><infNFe Id="NFe'+'1'*44+'" versao="4.00"><x>synthetic</x></infNFe></NFe>').encode()
        cls.signed = cls.cert.sign(cls.unsigned)

    def verify(self, signed=None, identity=None, **kwargs):
        return signature.verificar(self.unsigned, signed or self.signed, identity or self.cert.identity(),
            cadeia=self.cert.chain, ancoras_sha256=self.cert.anchors, ensaio_sintetico=True, **kwargs)

    def mutate(self, path, value=None, attr=None):
        root = parse(self.signed); row = root.find(path)
        if attr: row.set(attr, value)
        else: row.text = value
        return __import__('lxml.etree', fromlist=['etree']).tostring(root)

    def test_real_xmldsig_crypto_digest_certificate_and_chain(self):
        result = self.verify()
        self.assertEqual((result['xmldsig'], result['algoritmo'], result['digest'], result['cadeia']), ('VALIDADA','RSA-SHA1','SHA1','VALIDADA'))
        self.assertTrue(result['ensaio_sintetico'])

    def test_synthetic_certificate_never_accepted_as_real_icp(self):
        with self.assertRaises(ValidationError): signature.verificar(self.unsigned, self.signed, self.cert.identity())

    @override_settings(FISCAL_NFCE_LOCAL_ENABLED=False)
    def test_synthetic_flag_cannot_bypass_local_gate(self):
        with self.assertRaises(ValidationError): self.verify()

    def test_cnpj_taken_from_signed_public_certificate(self):
        self.assertEqual(cnpj_certificado(self.cert.cert), self.cert.cnpj)

    def test_missing_cnpj_othername_rejected(self):
        cert = SyntheticCertificate(missing_cnpj=True)
        with self.assertRaises(ValidationError): cnpj_certificado(cert.cert)

    def test_cnpj_identity_mismatch_rejected(self):
        with self.assertRaises(ValidationError): self.verify(identity=replace(self.cert.identity(), cnpj='11444777000161'))

    def test_fingerprint_mismatch_rejected(self):
        with self.assertRaises(ValidationError): self.verify(identity=replace(self.cert.identity(), sha256_certificado='0'*64))

    def test_reference_external_or_wrong_rejected(self):
        for uri in ('https://example.invalid/xml', '#wrong', ''):
            with self.subTest(uri=uri), self.assertRaises(ValidationError):
                self.verify(self.mutate('.//{'+signature.DS+'}Reference', uri, 'URI'))

    def test_digest_tamper_rejected(self):
        with self.assertRaises(ValidationError): self.verify(self.mutate('.//{'+signature.DS+'}DigestValue','AAAA'))

    def test_signature_tamper_rejected(self):
        with self.assertRaises(ValidationError): self.verify(self.mutate('.//{'+signature.DS+'}SignatureValue','AAAA'))

    def test_algorithm_canonicalization_and_transforms_rejected(self):
        for tag in ('SignatureMethod','CanonicalizationMethod','DigestMethod','Transform'):
            with self.subTest(tag=tag), self.assertRaises(ValidationError):
                self.verify(self.mutate('.//{'+signature.DS+'}'+tag, 'https://example.invalid/algorithm', 'Algorithm'))

    def test_duplicate_signature_rejected(self):
        root = parse(self.signed);root.append(copy.deepcopy(root.find('{'+signature.DS+'}Signature')))
        from lxml import etree
        with self.assertRaises(ValidationError): self.verify(etree.tostring(root))

    def test_wrapping_duplicate_identifier_rejected(self):
        root = parse(self.signed);root.append(copy.deepcopy(root.find('{'+NFE+'}infNFe')))
        from lxml import etree
        with self.assertRaises(ValidationError): self.verify(etree.tostring(root))

    def test_changed_business_xml_rejected(self):
        with self.assertRaises(ValidationError): self.verify(self.mutate('.//{'+NFE+'}x', 'altered'))

    def test_changed_supplement_rejected(self):
        from lxml import etree
        root = parse(self.signed);etree.SubElement(root,'{'+NFE+'}infNFeSupl')
        with self.assertRaises(ValidationError): self.verify(etree.tostring(root))

    def test_expired_leaf_rejected(self):
        cert = SyntheticCertificate(expired=True)
        with self.assertRaises(ValidationError): signature.verificar(self.unsigned,cert.sign(self.unsigned),cert.identity(),ensaio_sintetico=True)

    def test_untrusted_chain_root_rejected(self):
        with self.assertRaises(ValidationError): verificar_cadeia(self.cert.der,self.cert.chain,('0'*64,))

    def test_wrong_chain_rejected(self):
        other = SyntheticCertificate()
        with self.assertRaises(ValidationError): verificar_cadeia(self.cert.der,other.chain,other.anchors)

    def test_absent_or_duplicate_chain_rejected(self):
        for chain in ((), (self.cert.der,*self.cert.chain)):
            with self.subTest(chain_length=len(chain)), self.assertRaises(ValidationError):
                verificar_cadeia(self.cert.der,chain,self.cert.anchors)

    def test_chain_result_does_not_claim_icp_or_revocation(self):
        proof = verificar_cadeia(self.cert.der,self.cert.chain,self.cert.anchors)
        self.assertEqual(proof['icp_brasil'],'NÃO INFERIDA');self.assertEqual(proof['revogacao'],'PENDENTE NO PROVEDOR')


class VaultContextTests(NFCeData, TestCase):
    def setUp(self):
        self.nfce_setup()
        self.provider = Mock()
        cert = SyntheticCertificate(self.branch.cnpj)
        self.provider.identidade.return_value = replace(cert.identity(self.a.pk,self.branch.pk), icp_brasil=True, cadeia_validada=True, revogacao_verificada=True)
        self.adapter = AdaptadorCofre(self.provider,ancoras_icp_brasil=cert.anchors)
        self.context = {'organization_id':self.a.pk,'estabelecimento_id':self.branch.pk,'ambiente':'HOMOLOGACAO','emitente_cnpj':self.branch.cnpj}

    def identity(self, **changes):
        return self.adapter.identidade(self.cred.referencia,**{**self.context,**changes})

    def test_valid_scoped_backend_identity(self):
        with tenant_context(self.a): self.assertEqual(self.identity().cnpj,self.branch.cnpj)
        self.provider.identidade.assert_called_once_with(self.cred.referencia,**self.context)

    def test_unprovisioned_state_is_explicit_and_no_provider_called(self):
        with tenant_context(self.a), self.assertRaisesMessage(DependenciaFiscal,'COFRE NÃO PROVISIONADO'):
            AdaptadorCofre().identidade(self.cred.referencia,**self.context)
        self.provider.identidade.assert_not_called()

    def test_client_b_cannot_access_tecnolmed_context(self):
        with tenant_context(self.b), self.assertRaises(ValidationError): self.identity()
        self.provider.identidade.assert_not_called()

    def test_vertyx_owner_has_no_automatic_client_certificate_access(self):
        owner=Organization.objects.create(slug='vertyx-vault-test',razao_social='VERTYX — synthetic owner')
        with tenant_context(owner), self.assertRaises(ValidationError): self.identity()
        self.provider.identidade.assert_not_called()

    def test_adulterated_organization_rejected_before_provider(self):
        with tenant_context(self.a), self.assertRaises(ValidationError): self.identity(organization_id=self.b.pk)
        self.provider.identidade.assert_not_called()

    def test_other_branch_same_cnpj_rejected_before_provider(self):
        with tenant_context(self.a):
            branch=FilialEmpresa.objects.create(codigo='OTHER',nome='Other branch',cnpj=self.branch.cnpj)
            with self.assertRaises(ValidationError): self.identity(estabelecimento_id=branch.pk)
        self.provider.identidade.assert_not_called()

    def test_production_environment_rejected_before_provider(self):
        with tenant_context(self.a), self.assertRaises(ValidationError): self.identity(ambiente='PRODUCAO')
        self.provider.identidade.assert_not_called()

    def test_other_cnpj_rejected_before_provider(self):
        with tenant_context(self.a), self.assertRaises(ValidationError): self.identity(emitente_cnpj='11444777000161')
        self.provider.identidade.assert_not_called()

    def test_provider_wrong_scope_rejected(self):
        good=self.provider.identidade.return_value
        for field,value in [('organization_id',self.b.pk),('estabelecimento_id',self.branch.pk+99),('ambiente','PRODUCAO'),('cnpj','11444777000161')]:
            self.provider.identidade.return_value=replace(good,**{field:value})
            with tenant_context(self.a),self.subTest(field=field),self.assertRaises(ValidationError): self.identity()

    def test_missing_chain_revocation_metadata_rejected(self):
        good=self.provider.identidade.return_value
        for field,value in [('cadeia_validada',False),('revogacao_verificada',False),('valido_ate',None),('titular',''),('sha256_certificado','')]:
            self.provider.identidade.return_value=replace(good,**{field:value})
            with tenant_context(self.a),self.subTest(field=field),self.assertRaises(ValidationError): self.identity()

    def test_provider_exception_is_sanitized(self):
        self.provider.identidade.side_effect=RuntimeError('sensitive-provider-value')
        with tenant_context(self.a),self.assertRaises(ValidationError) as caught:self.identity()
        self.assertNotIn('sensitive-provider-value',str(caught.exception))

    def test_transmission_always_blocked(self):
        with self.assertRaises(ValidationError):self.adapter.transmitir(self.cred.referencia,b'payload',**self.context)
        self.provider.transmitir.assert_not_called()

    def test_reference_link_from_client_b_not_visible_to_tecnolmed(self):
        with tenant_context(self.b):
            import uuid
            foreign=m.CredencialFiscal.objects.create(referencia='cofre://'+str(uuid.uuid4()),mecanismo='REFERENCIA',ambiente='HOMOLOGACAO')
        with tenant_context(self.a),self.assertRaises(ValidationError):self.adapter.identidade(foreign.referencia,**self.context)
        self.provider.identidade.assert_not_called()


class PretransmissionOfficialSchemaTests(NFCeData, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.cert=SyntheticCertificate()

    def setUp(self):self.nfce_setup()

    def flow(self):
        with tenant_context(self.a):
            sale=self.confirmed();doc=self.homdoc(sale);request=self.homreq(doc)
            doc.refresh_from_db();unsigned=self.generated(doc);signed=self.cert.sign(unsigned)
            return sale,doc,request,unsigned,signed

    def validate(self,doc,unsigned,signed,**kwargs):
        with override_settings(FISCAL_NFCE_SEFAZ_APPROVED=False):
            return p.validar_ensaio(self.admin,doc.pk,unsigned,signed,self.cert.identity(self.a.pk,self.branch.pk),
                cadeia=self.cert.chain,ancoras_sha256=self.cert.anchors,**kwargs)

    def test_complete_paid_pdv_to_official_xsd_and_signature_without_transmission(self):
        sale,doc,request,unsigned,signed=self.flow()
        with tenant_context(self.a),patch('fiscal.nfce.transport.envelope',side_effect=AssertionError('network forbidden')):
            before=copy.deepcopy(sale.snapshot);result=self.validate(doc,unsigned,signed)
            sale.refresh_from_db();doc.refresh_from_db();request.refresh_from_db()
            self.assertEqual(result['estado'],'PRONTO PARA TRANSMISSÃO');self.assertEqual(result['conclusao'],'PRONTO PARA HOMOLOGAÇÃO OFICIAL')
            self.assertEqual(result['xsd']['resultado'],'APROVADO');self.assertEqual(result['xsd']['arquivo'],'nfe_v4.00.xsd')
            self.assertEqual(result['xsd']['namespace'],NFE);self.assertEqual(result['xsd']['release'],p.SCHEMA_RELEASE)
            self.assertFalse(result['autorizado_sefaz']);self.assertFalse(result['certificado_real']);self.assertFalse(result['transmissao'])
            self.assertFalse(result['xsd']['aplicabilidade_sefaz_confirmada']);self.assertEqual(doc.status,'PENDENTE');self.assertFalse(doc.protocolo)
            self.assertEqual(sale.snapshot,before);self.assertEqual(sale.status,'FINALIZADA');self.assertEqual(request.estado,'PENDENTE')
            self.assertFalse(m.TentativaFiscal.objects.exists());self.assertFalse(m.ArtefatoNFCe.objects.exists())
            audit=PlatformAudit.objects.filter(action='FISCAL_PRETRANSMISSAO_ENSAIO').last()
            self.assertNotIn('X509Certificate',json.dumps(audit.changes));self.assertNotIn('PRIVATE KEY',json.dumps(result))

    def test_official_xsd_rejects_missing_signature(self):
        _,_,_,unsigned,_=self.flow()
        with tenant_context(self.a),self.assertRaisesMessage(DependenciaFiscal,'não atende'):
            SchemaOficial(p.SCHEMA_DIRECTORY,p.SCHEMA_RELEASE).validar(unsigned,ensaio_local=True)

    def test_official_xsd_rejects_missing_issuer_wrong_namespace_or_version(self):
        from lxml import etree
        _,_,_,_,signed=self.flow()
        for variant in ('issuer','namespace','version'):
            root=parse(signed)
            if variant=='issuer':
                emit=root.find('.//{'+NFE+'}emit');emit.getparent().remove(emit)
            elif variant=='namespace':root.tag='{https://example.invalid}NFe'
            else:root.find('{'+NFE+'}infNFe').set('versao','3.10')
            with tenant_context(self.a),self.subTest(variant=variant),self.assertRaises(DependenciaFiscal):
                SchemaOficial(p.SCHEMA_DIRECTORY,p.SCHEMA_RELEASE).validar(etree.tostring(root),ensaio_local=True)

    def test_lab_package_cannot_be_activated_for_normal_emission(self):
        _,_,_,_,signed=self.flow()
        with self.assertRaises(DependenciaFiscal):SchemaOficial(p.SCHEMA_DIRECTORY,p.SCHEMA_RELEASE).validar(signed)

    def test_official_package_hashes_all_match(self):
        manifest=json.loads((p.SCHEMA_DIRECTORY/'manifest.json').read_text())
        self.assertEqual(len(manifest['sha256']),5)
        for name,digest in manifest['sha256'].items():self.assertEqual(hashlib.sha256((p.SCHEMA_DIRECTORY/name).read_bytes()).hexdigest(),digest)

    def test_modified_official_xsd_blocked(self):
        import shutil
        _,_,_,_,signed=self.flow()
        with tempfile.TemporaryDirectory() as temp:
            for file in p.SCHEMA_DIRECTORY.iterdir():shutil.copyfile(file,Path(temp)/file.name)
            with (Path(temp)/'nfe_v4.00.xsd').open('ab') as out:out.write(b'<!--modified-->')
            with tenant_context(self.a),self.assertRaises(DependenciaFiscal):SchemaOficial(temp,p.SCHEMA_RELEASE).validar(signed,ensaio_local=True)

    def test_pretransmission_other_tenant_cannot_read_document(self):
        _,doc,_,unsigned,signed=self.flow()
        with tenant_context(self.b),self.assertRaises((PermissionDenied,m.DocumentoFiscal.DoesNotExist)):self.validate(doc,unsigned,signed)

    def test_pretransmission_wrong_cert_context_rejected(self):
        _,doc,_,unsigned,signed=self.flow()
        good=self.cert.identity(self.a.pk,self.branch.pk)
        for field,value in [('organization_id',self.b.pk),('estabelecimento_id',self.branch.pk+99),('ambiente','PRODUCAO'),('cnpj','11444777000161')]:
            with tenant_context(self.a),override_settings(FISCAL_NFCE_SEFAZ_APPROVED=False),self.subTest(field=field),self.assertRaises(ValidationError):
                p.validar_ensaio(self.admin,doc.pk,unsigned,signed,replace(good,**{field:value}),cadeia=self.cert.chain,ancoras_sha256=self.cert.anchors)

    def test_transmission_flag_blocks_technical_lab(self):
        _,doc,_,unsigned,signed=self.flow()
        with tenant_context(self.a),self.assertRaisesMessage(ValidationError,'desabilitada'):
            p.validar_ensaio(self.admin,doc.pk,unsigned,signed,self.cert.identity(),cadeia=self.cert.chain,ancoras_sha256=self.cert.anchors)

    def test_revalidation_does_not_duplicate_sale_or_fiscal_reservation(self):
        _,doc,_,unsigned,signed=self.flow()
        with tenant_context(self.a):
            before=(m.Venda.objects.count(),m.DocumentoFiscal.objects.count(),m.ReservaNumeracaoFiscal.objects.count())
            self.validate(doc,unsigned,signed);self.validate(doc,unsigned,signed)
            self.assertEqual(before,(m.Venda.objects.count(),m.DocumentoFiscal.objects.count(),m.ReservaNumeracaoFiscal.objects.count()))

    def test_operator_permission_does_not_grant_fiscal_lab(self):
        _,doc,_,unsigned,signed=self.flow()
        with tenant_context(self.a),override_settings(FISCAL_NFCE_SEFAZ_APPROVED=False),self.assertRaises(PermissionDenied):
            p.validar_ensaio(self.operator,doc.pk,unsigned,signed,self.cert.identity(),cadeia=self.cert.chain,ancoras_sha256=self.cert.anchors)


@override_settings(FISCAL_NFCE_LOCAL_ENABLED=True,PRIVATE_STORAGE=None,UPLOAD_STORAGE='local')
class FinalFiscalChecklistTests(Dados,TestCase):
    def setUp(self):
        self.prepare_data()
        with tenant_context(self.a):self.cfg=s.registrar_proposta_documental(self.admin,proposal())
        self.url=f'/fiscal/configuracao/{self.cfg.pk}/'

    def test_documental_and_accountant_and_technical_sections_separate(self):
        response=self.client.get(self.url)
        for text in ('Confirmado documentalmente','Confirmação do responsável fiscal / contador','Código IBGE','NCM','CEST / aplicabilidade','PIS / COFINS','COFRE NÃO PROVISIONADO','Não provisionado','Validação técnica · laboratório separado','HOMOLOGAÇÃO SE','PRODUÇÃO SE','EMISSÃO BLOQUEADA'):
            self.assertContains(response,text)
        self.assertContains(response,'disabled aria-disabled="true">Emitir NFC-e')

    def test_get_does_not_confirm_data_or_load_certificate(self):
        before=copy.deepcopy(self.cfg.proposta_documental)
        with patch.object(AdaptadorCofre,'identidade',side_effect=AssertionError('no vault on GET')):
            self.assertEqual(self.client.get(self.url).status_code,200)
        with tenant_context(self.a):
            self.cfg.refresh_from_db();self.assertEqual(self.cfg.proposta_documental,before);self.assertEqual(self.cfg.preparacao_fiscal,{})
            self.assertFalse(m.CredencialFiscal.objects.exists());self.assertFalse(m.SerieFiscal.objects.exists());self.assertFalse(m.SolicitacaoFiscal.objects.exists())

    def test_no_certificate_upload_or_secret_fields_on_final_checklist(self):
        response=self.client.get(self.url)
        for name in ('senha','certificado','csc','token','organization_id'):
            self.assertNotContains(response,f'name="{name}"')
        self.assertNotContains(response,'type="file"')

    def test_documental_emission_stays_blocked_even_with_fake_metadata(self):
        with tenant_context(self.a),self.assertRaisesMessage(ValidationError,'EMISSÃO BLOQUEADA'):
            s.validar_config(self.cfg,None,None,None)
