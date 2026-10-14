"""Synthetic LOCAL model-65 tests. No certificate, issuer or SEFAZ request real.

Identity/series here are isolated unit-test vectors, never TECNOLMED setup.
Schema/signature/transport success paths use declared doubles; official XSD
and real A1 remain external homologation requirements, not validated by doubles.
"""
import copy
import hashlib
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import connection,close_old_connections
from django.test import TestCase,TransactionTestCase,SimpleTestCase,override_settings
from django.utils import timezone
from lxml import etree
from platform_core.context import tenant_context
from platform_core.models import FilialEmpresa,ConfiguracaoEmpresa
from gestao import models as g,services as gs
from fiscal import foundation
from fiscal.motors import resolver
from fiscal.motors.nfce_homologacao import MotorNFCeHomologacao
from fiscal.nfce import services as s,xml,transport,signature
from fiscal.nfce.contracts import IdentidadeCertificado,DependenciaFiscal
from fiscal.nfce.schema import parse,SchemaOficial,NFE,local_schema_path
from . import models as m,commerce as c
from .test_fiscal_foundation import FiscalData


class SchemaDuploLocal:
    """Not an official XSD; only records orchestration of the gate."""
    def __init__(self):self.calls=[]
    def validar(self,data,nome):parse(data);self.calls.append(nome)


class CofreDuploLocal:
    """No certificate/signature/mTLS or HTTP; in-memory authority test double."""
    def __init__(self,org,cnpj,estabelecimento):
        self.identity=IdentidadeCertificado(org,'HOMOLOGACAO',cnpj,True,True,estabelecimento)
        self.code='100';self.timeout=False;self.fail_before=False;self.records={};self.calls=[]
    def identidade(self,reference,**kwargs):return self.identity
    def assinar(self,reference,data,**kwargs):return data
    def transmitir(self,reference,endpoint,method,body,**kwargs):
        root=parse(body);ns={'n':NFE};self.calls.append(endpoint)
        if 'NfeConsulta' in endpoint:
            key=root.findtext('.//n:chNFe',namespaces=ns)
            return self.records.get(key,self.response(key,'217',consult=True))
        if 'recepcaoevento' in endpoint:
            key=root.findtext('.//n:chNFe',namespaces=ns)
            return self.cancel_response(key)
        key=root.find('.//n:infNFe',ns).get('Id')[3:]
        if self.fail_before:raise TimeoutError('synthetic-before-receipt')
        result=self.response(key,self.code)
        self.records[key]=result
        if self.timeout:raise TimeoutError('synthetic-lost-response')
        return result
    def response(self,key,code,consult=False):
        root=etree.Element('{'+NFE+'}'+('retConsSitNFe' if consult else 'retEnviNFe'),versao='4.00',nsmap={None:NFE})
        status=code if consult else '104'
        for k,v in [('tpAmb','2'),('verAplic','TEST-DOUBLE'),('cStat',status),('xMotivo','Resposta sintética sem emissão'),('cUF','28'),('dhRecbto',timezone.localtime().isoformat(timespec='seconds'))]:xml.tag(root,k,v)
        if consult:xml.tag(root,'chNFe',key)
        if not consult or code in ('100','150'):
            prot=etree.SubElement(root,'{'+NFE+'}protNFe',versao='4.00');info=etree.SubElement(prot,'{'+NFE+'}infProt')
            fields=[('tpAmb','2'),('verAplic','TEST-DOUBLE'),('chNFe',key),('dhRecbto',timezone.localtime().isoformat(timespec='seconds'))]
            if code in ('100','150'):fields.extend([('nProt','128260000000001'),('digVal','SYNTHETIC')])
            fields.extend([('cStat',code),('xMotivo','AUTORIZACAO APENAS DO DUPLO LOCAL')])
            for k,v in fields:xml.tag(info,k,v)
        return etree.tostring(root)
    def cancel_response(self,key):
        root=etree.Element('{'+NFE+'}retEnvEvento',versao='1.00',nsmap={None:NFE});xml.tag(root,'cStat','128')
        event=etree.SubElement(root,'{'+NFE+'}retEvento',versao='1.00');info=etree.SubElement(event,'{'+NFE+'}infEvento')
        for k,v in [('tpAmb','2'),('chNFe',key),('tpEvento','110111'),('nSeqEvento','1'),('cStat','135'),('nProt','128260000000002'),('dhRegEvento',timezone.localtime().isoformat(timespec='seconds')),('xMotivo','CANCELAMENTO DO DUPLO LOCAL')]:xml.tag(info,k,v)
        return etree.tostring(root)


class TransporteDuploLocal:
    """Explicit test-only transport; never loads credentials or opens sockets."""
    habilitado=False
    def __init__(self, authority):
        self.authority=authority
    def enviar(self, operation, payload, **context):
        endpoint,_,method=transport.SERVICOS[operation]
        envelope,_action=transport.envelope(operation,payload)
        return self.authority.transmitir('test-only-transport-reference',endpoint,method,envelope,**context)


class NFCeData(FiscalData):
    def nfce_setup(self):
        self.fiscal_setup()
        self.nfce_override=override_settings(FISCAL_NFCE_LOCAL_ENABLED=True,FISCAL_NFCE_SEFAZ_APPROVED=True)
        self.nfce_override.enable();self.addCleanup(self.nfce_override.disable)
        with tenant_context(self.a):
            # Test vector only, never written into the TECNOLMED/local source DB.
            self.a.cnpj='11222333000181';self.a.save()
            self.branch=FilialEmpresa.objects.create(codigo='QA-NFCE',nome='Emitente unitário sintético',cnpj='11222333000181',inscricao_estadual='271234567')
            m.PerfilFiscalEstabelecimento.objects.create(estabelecimento=self.branch,municipio_ibge='2800308',uf='SE',atividade='Ensaio unitário',endereco_estruturado={'logradouro':'Endereço de teste','numero':'1','bairro':'Teste','cep':'49000000'})
            ConfiguracaoEmpresa.objects.create(crt='1',regime_tributario='Fixture SN')
            self.config=m.ConfiguracaoFiscal.objects.create(estabelecimento=self.branch,tipo='NFCE',ambiente='HOMOLOGACAO',motor='NFCE_SVRS_HOM',habilitada=True)
            self.options=m.ConfiguracaoNFCe.objects.create(configuracao=self.config,municipio_nome='Aracaju',natureza_operacao='Ensaio unitário',qr_versao='3',qr_url='https://example.invalid/qr',consulta_url='https://example.invalid/consulta',fonte_urls='https://example.invalid/fonte',urls_confirmadas=True,schema_release='TEST-DOUBLE-NOT-OFFICIAL',schema_aplicabilidade_confirmada=True)
            self.serie=m.SerieFiscal.objects.create(estabelecimento=self.branch,tipo='NFCE',ambiente='HOMOLOGACAO',serie='1')
            self.cred=m.CredencialFiscal.objects.create(referencia='cofre://'+str(uuid.uuid4()),mecanismo='REFERENCIA',ambiente='HOMOLOGACAO')
            m.VinculoCredencialFiscal.objects.create(configuracao=self.config,credencial=self.cred)
            self.rule=m.RegraTributariaFiscal.objects.create(configuracao=self.config,inicio=timezone.localdate())
            self.part.ncm='90189099';self.part.cfop='5102';self.part.origem_fiscal='0';self.part.csosn='102';self.part.save()
            self.tax={'icms_codigo':'102','pis_codigo':'07','cofins_codigo':'07','base_tributaria':'LIQUIDO','rtc_aplicavel':False,'rtc_fundamento':'Fixture explícita para teste SN em 2026, não regra TECNOLMED','gtin_ausente':True,'cest_aplicavel':False}
            self.taxrow=m.TributacaoProdutoNFCe.objects.create(configuracao=self.options,peca=self.part,regra=self.rule,parametros=self.tax)
            self.payment=m.PagamentoFiscalNFCe.objects.create(configuracao=self.options,forma=self.cash_method,codigo='01')
        self.vault=CofreDuploLocal(self.a.pk,self.branch.cnpj,self.branch.pk);self.schema=SchemaDuploLocal()
        self.motor=MotorNFCeHomologacao(cofre=self.vault,schema=self.schema,verificador=lambda *args:None,
                                        transporte=TransporteDuploLocal(self.vault))
    def confirmed(self,quantity=1):
        self.incoming(quantity);sale,item=self.sale(quantity);return self.paid(sale)
    def homdoc(self,sale=None):
        return s.preparar(self.admin,(sale or self.confirmed()).pk,self.config.pk,self.serie.pk,self.cred.pk,self.rule.pk)
    def homreq(self,doc=None,**kwargs):return s.solicitar(self.admin,(doc or self.homdoc()).pk,uuid.uuid4(),**kwargs)
    def runreq(self,req=None):return s.processar(self.admin,(req or self.homreq()).pk,motor=self.motor)
    def generated(self,doc):return xml.gerar(doc.snapshot_fiscal,int(doc.numero or 1),datetime.fromisoformat(doc.snapshot_fiscal['emissao']),doc.snapshot_fiscal['cnf'])[0]


class NFCeHomologacaoTests(NFCeData,TestCase):
    def setUp(self):self.nfce_setup()
    def test_motor_selection_preserves_simulation_and_disallows_production(self):
        self.assertEqual(type(resolver('NFCE')).__name__,'MotorNFCeSimulado')
        self.assertIsInstance(resolver('NFCE','HOMOLOGACAO'),MotorNFCeHomologacao)
        for kind,env in [('NFSE','HOMOLOGACAO'),('NFE','HOMOLOGACAO'),('NFCE','PRODUCAO')]:
            with self.assertRaises(ValidationError):resolver(kind,env)
    def test_sale_stays_finalized_fiscal_pending_and_idempotent_preparation(self):
        with tenant_context(self.a):
            sale=self.confirmed();before=copy.deepcopy(sale.snapshot);doc=self.homdoc(sale)
            self.assertEqual(self.homdoc(sale).pk,doc.pk);sale.refresh_from_db()
            self.assertEqual((sale.status,doc.status),('FINALIZADA','PENDENTE'));self.assertEqual(before,sale.snapshot)
    def test_official_namespace_identification_key_payments_and_no_offline(self):
        with tenant_context(self.a):
            req=self.homreq();root=parse(self.generated(req.documento));ns={'n':NFE}
            self.assertEqual(root.findtext('.//n:mod',namespaces=ns),'65');self.assertEqual(root.findtext('.//n:tpAmb',namespaces=ns),'2')
            self.assertEqual(root.findtext('.//n:tpEmis',namespaces=ns),'1');self.assertEqual(root.findtext('.//n:cUF',namespaces=ns),'28')
            self.assertEqual(root.findtext('.//n:tPag',namespaces=ns),'01');self.assertEqual(root.findtext('.//n:vNF',namespaces=ns),'10.00')
            self.assertEqual(req.documento.chave[-1],xml.digito(req.documento.chave[:43]));self.assertIn(xml.HOM,self.generated(req.documento).decode())
    def test_missing_tax_blocks_before_document_or_number_created(self):
        with tenant_context(self.a):
            self.taxrow.parametros={};gs.write(self.taxrow)
            with self.assertRaisesMessage(ValidationError,'faltam'):self.homdoc()
            self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),0);self.assertFalse(m.DocumentoFiscal.objects.exists())
    def test_missing_ncm_and_gtin_are_named(self):
        with tenant_context(self.a):
            self.part.ncm='';self.part.save()
            with self.assertRaisesMessage(ValidationError,'ncm'):self.homdoc()
            self.part.ncm='90189099';self.part.save();self.taxrow.parametros={**self.tax,'gtin_ausente':False};gs.write(self.taxrow)
            with self.assertRaisesMessage(ValidationError,'GTIN'):self.homdoc()
    def test_unsupported_rtc_or_icms_never_inferred(self):
        with tenant_context(self.a):
            self.taxrow.parametros={**self.tax,'rtc_aplicavel':True};gs.write(self.taxrow)
            with self.assertRaisesMessage(ValidationError,'IBS/CBS'):self.homdoc()
    def test_rule_product_mismatch_blocked(self):
        with tenant_context(self.a):
            self.part.csosn='500';self.part.save()
            with self.assertRaisesMessage(ValidationError,'CST/CSOSN'):self.homdoc()
    def test_payment_mapping_required(self):
        with tenant_context(self.a):
            sale=self.confirmed();self.payment.codigo='20';gs.write(self.payment)
            with self.assertRaisesMessage(ValidationError,'meio de pagamento'):self.homdoc(sale)
    def test_mixed_cash_pix_and_change_exact_xml(self):
        with tenant_context(self.a):
            m.PagamentoFiscalNFCe.objects.create(configuracao=self.options,forma=self.pix,codigo='20',integracao='2')
            self.incoming(2);sale,item=self.sale(2)
            sale=c.finalize(self.operator,sale.public_id,[{'forma':self.cash_method.pk,'valor':'8','recebido':'10'},{'forma':self.pix.pk,'valor':'12'}],uuid.uuid4())
            root=parse(self.generated(self.homdoc(sale)));ns={'n':NFE}
            self.assertEqual(root.findall('.//n:tPag',ns)[1].text,'20');self.assertEqual(root.findtext('.//n:vTroco',namespaces=ns),'2.00')
            self.assertEqual(sum(Decimal(n.text) for n in root.findall('.//n:vPag',ns))-Decimal(root.findtext('.//n:vTroco',namespaces=ns)),Decimal('20.00'))
    def test_credit_debit_and_dynamic_pix_require_explicit_mapping(self):
        with tenant_context(self.a):
            for commercial,code in [('CREDITO','03'),('DEBITO','04'),('PIX','17')]:
                method=g.FormaPagamento.objects.create(nome='Fixture '+commercial,tipo_pdv=commercial,conta_pdv=self.bank)
                m.PagamentoFiscalNFCe.objects.create(configuracao=self.options,forma=method,codigo=code,integracao='2')
                self.incoming(1);sale,item=self.sale();sale=c.finalize(self.operator,sale.public_id,[{'forma':method.pk,'valor':'10'}],uuid.uuid4())
                root=parse(self.generated(self.homdoc(sale)));self.assertEqual(root.findtext('.//{'+NFE+'}tPag'),code)
    def test_discount_cent_totals_match_sale_snapshot(self):
        with tenant_context(self.a):
            self.incoming(3);sale,item=self.sale(3);c.pricing(self.admin,sale.public_id,'1.33','.04','Fixture desconto');sale.refresh_from_db();sale=self.paid(sale,sale.total)
            root=parse(self.generated(self.homdoc(sale)));ns={'n':NFE}
            gross=Decimal(root.findtext('.//n:ICMSTot/n:vProd',namespaces=ns));desc=Decimal(root.findtext('.//n:ICMSTot/n:vDesc',namespaces=ns))
            self.assertEqual(gross-desc,Decimal(root.findtext('.//n:vNF',namespaces=ns)))
    def test_authorization_double_persists_xml_protocol_without_commercial_mutation(self):
        with tenant_context(self.a):
            doc=self.homdoc();sale=doc.venda;before=copy.deepcopy(sale.snapshot);req=self.homreq(doc);result=self.runreq(req);doc.refresh_from_db();sale.refresh_from_db()
            self.assertEqual((result.estado,doc.status),('CONCLUIDA','AUTORIZADA'));self.assertEqual(doc.protocolo,'128260000000001');self.assertEqual(sale.snapshot,before)
            self.assertEqual(req.artefatos_nfce.filter(tipo='PROCESSADO').count(),1);self.assertIn('nfe_v4.00.xsd',self.schema.calls)
            for artifact in req.artefatos_nfce.all():
                with artifact.arquivo.arquivo.open('rb') as stream:data=stream.read()
                self.assertEqual(artifact.arquivo.sha256,hashlib.sha256(data).hexdigest());self.assertFalse(artifact.arquivo.disponivel_portal)
    def test_rejection_preserves_attempt_code_and_xml_without_authorization(self):
        with tenant_context(self.a):
            self.vault.code='225';req=self.homreq();self.runreq(req);doc=req.documento;doc.refresh_from_db()
            self.assertEqual(doc.status,'REJEITADA');self.assertFalse(doc.protocolo);self.assertTrue(req.artefatos_nfce.filter(codigo='225').exists())
            self.assertEqual(req.artefatos_nfce.filter(tipo='ENVIADO').count(),1);self.assertFalse(req.artefatos_nfce.filter(tipo='PROCESSADO').exists())
    def test_four_digit_rejection_code_preserved(self):
        with tenant_context(self.a):
            self.vault.code='1001';req=self.homreq();self.runreq(req);doc=req.documento;doc.refresh_from_db()
            self.assertEqual(doc.status,'REJEITADA');self.assertTrue(req.artefatos_nfce.filter(codigo='1001').exists())
    def test_timeout_after_receipt_reconciles_without_second_emission(self):
        with tenant_context(self.a):
            self.vault.timeout=True;req=self.homreq();self.assertEqual(self.runreq(req).estado,'RESULTADO_DESCONHECIDO')
            self.assertEqual(self.runreq(req).estado,'CONCLUIDA');req.documento.refresh_from_db();self.assertEqual(req.documento.status,'AUTORIZADA')
            self.assertEqual(sum('NfeAutorizacao' in url for url in self.vault.calls),1);self.assertEqual(len(self.vault.calls),2)
    def test_timeout_before_receipt_not_found_never_reemits(self):
        with tenant_context(self.a):
            self.vault.fail_before=True;req=self.homreq();self.runreq(req);self.runreq(req)
            self.assertEqual(self.runreq(req).estado,'RESULTADO_DESCONHECIDO');self.assertEqual(sum('NfeAutorizacao' in u for u in self.vault.calls),1)
            req.documento.refresh_from_db();self.assertNotEqual(req.documento.status,'AUTORIZADA')
    def test_repeated_operation_creates_one_request_number_and_authorization(self):
        with tenant_context(self.a):
            doc=self.homdoc();rid=uuid.uuid4();one=s.solicitar(self.admin,doc.pk,rid);two=s.solicitar(self.admin,doc.pk,uuid.uuid4())
            self.assertEqual(one.pk,two.pk);self.runreq(one);self.runreq(two)
            self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1);self.assertEqual(len(self.vault.calls),1)
    def test_cancel_preserves_original_key_protocol_xml_and_user_event(self):
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);doc=req.documento;doc.refresh_from_db();original=(doc.chave,doc.protocolo,doc.numero)
            cancel=self.homreq(doc,operacao='CANCELAR',motivo='Cancelamento sintético justificado');self.runreq(cancel);doc.refresh_from_db()
            self.assertEqual(doc.status,'CANCELADA');self.assertEqual((doc.chave,doc.protocolo,doc.numero),original)
            self.assertTrue(req.artefatos_nfce.filter(tipo='PROCESSADO').exists());self.assertTrue(cancel.artefatos_nfce.filter(protocolo='128260000000002').exists())
            self.assertEqual(doc.eventos_fiscais.last().usuario_id,self.admin.pk)
    def test_cancel_requires_authorization_and_justification(self):
        with tenant_context(self.a):
            doc=self.homdoc()
            with self.assertRaises(ValidationError):self.homreq(doc,operacao='CANCELAR',motivo='curto')
    def test_default_vault_and_schema_block_emission(self):
        with tenant_context(self.a):
            req=self.homreq();self.assertEqual(s.processar(self.admin,req.pk).estado,'BLOQUEADA')
            self.assertFalse(req.artefatos_nfce.exists());req.documento.refresh_from_db();self.assertEqual(req.documento.status,'PENDENTE')
        with self.assertRaisesMessage(DependenciaFiscal,'XSD'):SchemaOficial().validar(b'<NFe/>')
    def test_cert_other_tenant_cnpj_environment_expired_are_blocked(self):
        with tenant_context(self.a):
            doc=self.homdoc()
            for identity in [IdentidadeCertificado(self.b.pk,'HOMOLOGACAO',self.branch.cnpj,True,True,self.branch.pk),IdentidadeCertificado(self.a.pk,'PRODUCAO',self.branch.cnpj,True,True,self.branch.pk),IdentidadeCertificado(self.a.pk,'HOMOLOGACAO','00000000000000',True,True,self.branch.pk),IdentidadeCertificado(self.a.pk,'HOMOLOGACAO',self.branch.cnpj,False,True,self.branch.pk)]:
                self.vault.identity=identity
                with self.assertRaises(ValidationError):self.motor.validar(doc)
    def test_credential_from_other_organization_not_queryable(self):
        with tenant_context(self.a):sale=self.confirmed()
        with tenant_context(self.b):
            with self.assertRaises(m.Venda.DoesNotExist):s.preparar(self.admin_b,sale.pk,self.config.pk,self.serie.pk,self.cred.pk,self.rule.pk)
    def test_pdv_technician_seller_cannot_prepare_or_administer_fiscal(self):
        with tenant_context(self.a):
            sale=self.confirmed()
            for user in [self.operator,self.user('nfce-tech',self.a,'TECNICO'),self.user('nfce-seller',self.a,'VENDEDOR')]:
                with self.assertRaises(PermissionDenied):s.preparar(user,sale.pk,self.config.pk,self.serie.pk,self.cred.pk,self.rule.pk)
    def test_wrong_environment_config_not_saved(self):
        with tenant_context(self.a):
            for kind,env in [('NFE','HOMOLOGACAO'),('NFCE','PRODUCAO')]:
                with self.assertRaises(ValidationError):m.ConfiguracaoFiscal.objects.create(estabelecimento=self.branch,tipo=kind,ambiente=env,motor='NFCE_SVRS_HOM',versao=2)
    def test_main_db_flag_is_not_enough_to_enable_production(self):
        with tenant_context(self.a),override_settings(FISCAL_NFCE_LOCAL_ENABLED=False):
            with self.assertRaisesMessage(ValidationError,'sintético'):s.local()
    def test_profile_missing_address_report_and_no_guessed_identity(self):
        with tenant_context(self.a):
            profile=self.branch.perfil_fiscal;profile.endereco_estruturado={};gs.write(profile)
            with self.assertRaisesMessage(ValidationError,'endereço/logradouro'):self.homdoc()
    def test_official_urls_and_release_require_confirmation(self):
        with tenant_context(self.a):
            self.options.urls_confirmadas=False;gs.write(self.options)
            with self.assertRaisesMessage(ValidationError,'URLs oficiais'):self.homdoc()
    def test_no_foreign_tax_rule_or_piece_links(self):
        with tenant_context(self.b):other=self.db['part']
        with tenant_context(self.a):
            with self.assertRaises(ValidationError):m.TributacaoProdutoNFCe.objects.create(configuracao=self.options,peca=other,regra=self.rule,parametros=self.tax)
    def test_immutable_artifacts_and_credentials_have_no_secret_columns(self):
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);artifact=req.artefatos_nfce.first()
            with self.assertRaises(ValidationError):artifact.codigo='999';artifact.save()
            with self.assertRaises(ValidationError):artifact.delete()
            for model in [m.CredencialFiscal,m.ConfiguracaoNFCe,m.TributacaoProdutoNFCe,m.PagamentoFiscalNFCe]:
                self.assertFalse({'password','senha','token','csc','pfx','chave_privada'} & {f.name for f in model._meta.fields})
    def test_invalid_response_never_authorizes_and_remains_preserved(self):
        with tenant_context(self.a):
            req=self.homreq();real=self.vault.response
            self.vault.response=lambda key,code,consult=False:real(key,code,consult).replace(b'<tpAmb>2</tpAmb>',b'<tpAmb>1</tpAmb>')
            self.assertEqual(self.runreq(req).estado,'RESULTADO_DESCONHECIDO');self.assertTrue(req.artefatos_nfce.filter(tipo='RESPOSTA').exists())
            req.documento.refresh_from_db();self.assertNotEqual(req.documento.status,'AUTORIZADA')
    def test_signed_xml_schema_gate_precedes_transport(self):
        with tenant_context(self.a):
            req=self.homreq()
            def invalid(*args):raise DependenciaFiscal('Synthetic schema gate rejection')
            self.schema.validar=invalid
            self.assertEqual(self.runreq(req).estado,'BLOQUEADA');self.assertEqual(self.vault.calls,[])
            self.assertFalse(req.artefatos_nfce.exists())
    def test_sefaz_flag_not_enabled_blocks_even_in_test_lab(self):
        with tenant_context(self.a),override_settings(FISCAL_NFCE_SEFAZ_APPROVED=False):
            req=self.homreq();self.assertEqual(self.runreq(req).estado,'RESULTADO_DESCONHECIDO');self.assertEqual(self.vault.calls,[])

    def test_signing_vault_cannot_be_used_as_implicit_transport(self):
        with tenant_context(self.a):
            req=self.homreq()
            motor=MotorNFCeHomologacao(cofre=self.vault,schema=self.schema)
            with self.assertRaisesMessage(DependenciaFiscal,'Transporte HTTPS/mTLS segregado'):
                motor.emitir(req.documento,self.generated(req.documento))
            self.assertEqual(self.vault.calls,[])
    def test_local_danfe_is_private_idempotent_and_not_authorization(self):
        from fiscal.nfce.danfe import gerar
        with tenant_context(self.a):
            doc=self.homdoc()
            with self.assertRaises(ValidationError):gerar(self.admin,doc.pk)
            req=self.homreq(doc);self.runreq(req);file=gerar(self.admin,doc.pk)
            self.assertEqual(gerar(self.admin,doc.pk).pk,file.pk)
            with file.arquivo.open('rb') as stream:self.assertTrue(stream.read().startswith(b'%PDF-'))
            self.assertFalse(file.disponivel_portal);self.assertEqual(req.artefatos_nfce.filter(tipo='DANFE').count(),1)
    def test_home_and_forms_explicit_local_notice_no_certificate_field(self):
        response=self.client.get('/fiscal/nfce/homologacao/')
        self.assertContains(response,'LABORATÓRIO LOCAL');self.assertContains(response,'não representa produção')
        for kind in ['configuracao','parametros','serie','regra','produto','pagamento','referencia','vinculo']:
            response=self.client.get('/fiscal/nfce/homologacao/cadastros/'+kind+'/');self.assertEqual(response.status_code,200)
            self.assertNotIn('type="file"',response.content.decode())
    def test_backend_blocks_seller_technician_pdv_on_local_ui(self):
        for user in [self.operator,self.user('nfce-ui-tech',self.a,'TECNICO'),self.user('nfce-ui-seller',self.a,'VENDEDOR')]:
            self.client.force_login(user)
            for url in ['/fiscal/nfce/homologacao/','/fiscal/nfce/homologacao/cadastros/configuracao/','/fiscal/nfce/homologacao/preparar/']:
                self.assertEqual(self.client.get(url).status_code,403)
    def test_foreign_html_document_and_form_ids_denied(self):
        with tenant_context(self.a):doc=self.homdoc();sale=doc.venda
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(f'/fiscal/nfce/homologacao/documentos/{doc.pk}/').status_code,404)
        response=self.client.post('/fiscal/nfce/homologacao/preparar/',{'venda':sale.pk,'configuracao':self.config.pk,'serie':self.serie.pk,'credencial':self.cred.pk,'regra':self.rule.pk})
        self.assertEqual(response.status_code,200)
        for field in ('venda','configuracao','serie','credencial','regra'):
            self.assertEqual(response.context['form'].errors.as_data()[field][0].code,'invalid_choice')
    def test_frontend_organization_spoof_and_secret_fields_not_accepted(self):
        url='/fiscal/nfce/homologacao/cadastros/serie/'
        for key in ['organization_id','organization','senha','certificado','CSC','token']:
            response=self.client.post(url,{'estabelecimento':self.branch.pk,'serie':'2','proximo_numero':'40',key:'forbidden'})
            self.assertEqual(response.status_code,200);self.assertContains(response,'Campos não permitidos')
        with tenant_context(self.a):self.assertFalse(m.SerieFiscal.objects.filter(serie='2').exists())
    def test_series_number_creation_explicit_and_audited(self):
        response=self.client.post('/fiscal/nfce/homologacao/cadastros/serie/',{'estabelecimento':self.branch.pk,'serie':'2','proximo_numero':'40'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):self.assertEqual(m.SerieFiscal.objects.get(serie='2').proximo_numero,40)
    def test_signed_xml_is_backend_only_and_danfe_download_remains_private(self):
        from django.urls import reverse
        from fiscal.nfce.danfe import gerar
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);artifact=req.artefatos_nfce.filter(tipo='ENVIADO').get();pdf=gerar(self.admin,req.documento_id)
        self.assertEqual(self.client.get(reverse('operacao:documento_arquivo',args=[artifact.arquivo_id])).status_code,403)
        response=self.client.get(reverse('operacao:documento_arquivo',args=[pdf.pk]));self.assertEqual(response.status_code,200);self.assertIn('no-store',response['Cache-Control'])
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
    def test_issuer_must_belong_to_organization(self):
        with tenant_context(self.a):
            self.a.cnpj='11444777000161';self.a.save()
            with self.assertRaisesMessage(ValidationError,'identidade jurídica'):self.homdoc()
    def test_duplicate_branch_cannot_split_numbering_for_same_issuer(self):
        with tenant_context(self.a):
            branch=FilialEmpresa.objects.create(codigo='DUP',nome='Fixture filial duplicada',cnpj=self.branch.cnpj)
            m.SerieFiscal.objects.create(estabelecimento=branch,tipo='NFCE',ambiente='HOMOLOGACAO',serie=self.serie.serie)
            with self.assertRaisesMessage(ValidationError,'numeração deve ser única'):self.homdoc()


class NFCePureTests(SimpleTestCase):
    def test_schema_file_uri_preserves_spaces_and_local_path(self):
        with tempfile.TemporaryDirectory(prefix='vertyx schema ') as directory:
            path=Path(directory,'schema oficial.xsd').resolve()
            self.assertEqual(local_schema_path(path.as_uri()),path)
            self.assertEqual(local_schema_path(str(path)),path)
    def test_schema_file_uri_remote_host_rejected(self):
        with self.assertRaises(ValueError):
            local_schema_path('file://external.invalid/schema.xsd')
    def test_cnpj_series_number_check_digit_vector(self):
        date=datetime.fromisoformat('2026-10-08T10:00:00-03:00');key=xml.chave('11222333000181','1',1,date,'12345678')
        self.assertEqual(len(key),44);self.assertEqual(key[:6],'282610');self.assertEqual(key[20:22],'65')
        self.assertEqual(key[-1],xml.digito(key[:43]))
        self.assertEqual(xml.chave('11222333000181','0',1,date,'12345678')[22:25],'000')
        for series,number in [('SIM',1),('890',1),('1000',1),('1',0),('1',1000000000)]:
            with self.assertRaises(ValidationError):xml.chave('11222333000181',series,number,date,'12345678')
    def test_qr3_online_has_no_csc_and_no_contingency(self):
        key=xml.chave('11222333000181','1',1,datetime.fromisoformat('2026-10-08T10:00:00-03:00'),'12345678')
        self.assertEqual(xml.qr_online(key,'https://example.invalid/qr'),'https://example.invalid/qr?p='+key+'|3|2')
        with self.assertRaises(ValidationError):xml.qr_online(key,'https://user:password@example.invalid/qr')
    def test_xml_parser_disallows_entities_and_large_payload(self):
        for data in [b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><x>&a;</x>',b'X'*2_000_001,b'<invalid>']:
            with self.assertRaises(ValidationError):parse(data)
    def test_signature_tampered_unsigned_or_missing_signature_blocked(self):
        identity=IdentidadeCertificado(1,'HOMOLOGACAO','11222333000181',True,True,1)
        for signed in [b'<NFe/>',b'<NFe><Signature>fake</Signature></NFe>']:
            with self.assertRaisesMessage(ValidationError,'Assinatura'):signature.verificar(b'<NFe/>',signed,identity)
    def test_production_endpoint_absent_and_soap_namespace_is_12(self):
        self.assertTrue(all('nfce-homologacao.svrs.rs.gov.br' in data[0] for data in transport.SERVICOS.values()))
        data,method=transport.envelope('CONSULTAR',b'<consSitNFe xmlns="http://www.portalfiscal.inf.br/nfe"/>')
        self.assertIn(b'http://www.w3.org/2003/05/soap-envelope',data);self.assertTrue(method.endswith('/nfeConsultaNF'))
    def test_schema_manifest_tamper_and_unverified_package_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'manifest.json').write_text('{"release":"TEST","aplicabilidade_confirmada":true,"fonte":"https://example.invalid/official","sha256":{"../bad.xsd":"bad"}}')
            with self.assertRaises(DependenciaFiscal):SchemaOficial(directory,'TEST').validar(b'<NFe/>')


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class NFCeConcurrencyTests(NFCeData,TransactionTestCase):
    def setUp(self):self.nfce_setup()
    def worker(self,doc):
        close_old_connections()
        try:
            with tenant_context(self.a):return s.solicitar(self.admin,doc.pk,uuid.uuid4()).pk
        finally:close_old_connections()
    def test_same_doc_one_operation_one_number_concurrently(self):
        with tenant_context(self.a):doc=self.homdoc()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.worker(doc),range(2)))
        self.assertEqual(results[0],results[1])
        with tenant_context(self.a):self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)
    def test_different_docs_distinct_numbers_concurrently(self):
        with tenant_context(self.a):docs=[self.homdoc(),self.homdoc()]
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(self.worker,docs))
        self.assertEqual(len(set(results)),2)
        with tenant_context(self.a):self.assertEqual(set(m.ReservaNumeracaoFiscal.objects.values_list('numero',flat=True)),{1,2})
    def test_same_operation_concurrent_processing_one_send(self):
        with tenant_context(self.a):req=self.homreq()
        def run(_):
            close_old_connections()
            try:
                with tenant_context(self.a):return s.processar(self.admin,req.pk,self.motor).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.vault.calls),1)
        with tenant_context(self.a):self.assertEqual(req.artefatos_nfce.filter(tipo='PROCESSADO').count(),1)


class NFCeMigrationPreservationTests(FiscalData,TransactionTestCase):
    def test_0020_preserves_all_old_columns_rows_and_phase1_document(self):
        from django.db.migrations.executor import MigrationExecutor
        self.assertEqual(connection.settings_dict['HOST'],'127.0.0.1')
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        # Build the authorized Phase-1 fixture on the current schema. Do not
        # query current models after entering a historical schema: subsequent
        # additive fields (e.g. documentary proposal) do not exist there yet.
        self.fiscal_setup()
        with tenant_context(self.a):
            doc=self.doc();req=self.request(doc);foundation.processar(self.admin,req.pk)
        executor=MigrationExecutor(connection)
        try:
            executor.migrate([('operacao','0019_fiscal_foundation')])
            columns={}
            with connection.cursor() as cursor:
                for table in connection.introspection.table_names():
                    if table!='django_migrations':columns[table]=[x.name for x in connection.introspection.get_table_description(cursor,table)]
            def snapshot():
                rows={}
                with connection.cursor() as cursor:
                    for table,fields in sorted(columns.items()):
                        cursor.execute('SELECT '+','.join(connection.ops.quote_name(x) for x in fields)+' FROM '+connection.ops.quote_name(table))
                        rows[table]=sorted(repr(x) for x in cursor.fetchall())
                return rows
            before=snapshot();MigrationExecutor(connection).migrate([('operacao','0021_nfce_response_code')])
            self.assertEqual(snapshot(),before)
            with tenant_context(self.a):
                doc.refresh_from_db();self.assertEqual(doc.status,'AUTORIZADA');self.assertTrue(doc.chave.startswith('SIM-'))
                self.assertEqual(m.ConfiguracaoNFCe.objects.count(),0);self.assertEqual(m.PagamentoFiscalNFCe.objects.count(),0)
        finally:
            executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
