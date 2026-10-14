"""No network, real A1 or emission. Official XSD + cryptographic local doubles."""
import base64
import copy
import hashlib
import tempfile
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import TestCase,SimpleTestCase,override_settings
from django.utils import timezone
from lxml import etree
from platform_core.context import tenant_context
from fiscal.nfce import services as s,xml,transport,signature,readiness,workflow
from fiscal.nfce.signing import assinar_xml
from fiscal.nfce.schema import parse,NFE
from fiscal.nfce.schema_flow import SchemaFluxo
from fiscal.nfce.svrs import (TransporteSVRSHomologacao,RequisicaoSOAP,RespostaHTTPS,validar_wsdl,SOAP,WSDL,SOAP_BINDING)
from fiscal.nfce.vault import AdaptadorCofre
from fiscal.motors.nfce_homologacao import MotorNFCeHomologacao
from .test_nfce_homologacao import NFCeData,CofreDuploLocal,TransporteDuploLocal
from .fiscal_test_support import SyntheticCertificate
from . import models as m


def synthetic_wsdl(operation='AUTORIZAR'):
    """Contract fixture, NEVER distributed as an official SVRS WSDL."""
    endpoint,service,method=transport.SERVICOS[operation];ns='http://www.portalfiscal.inf.br/nfe/wsdl/'+service
    root=etree.Element('{'+WSDL+'}definitions',targetNamespace=ns,nsmap={'w':WSDL,'s':SOAP_BINDING,'n':ns})
    binding=etree.SubElement(root,'{'+WSDL+'}binding',name='QA12')
    etree.SubElement(binding,'{'+SOAP_BINDING+'}binding',transport='http://schemas.xmlsoap.org/soap/http')
    op=etree.SubElement(binding,'{'+WSDL+'}operation',name=method)
    etree.SubElement(op,'{'+SOAP_BINDING+'}operation',soapAction=ns+'/'+method)
    etree.SubElement(etree.SubElement(op,'{'+WSDL+'}input'),'{'+SOAP_BINDING+'}body',use='literal')
    port=etree.SubElement(etree.SubElement(root,'{'+WSDL+'}service',name=service),'{'+WSDL+'}port',binding='n:QA12')
    etree.SubElement(port,'{'+SOAP_BINDING+'}address',location=endpoint)
    return etree.tostring(root)


class SOAPContractTests(SimpleTestCase):
    def test_authorization_endpoint_exact_and_hom_only(self):
        self.assertEqual(transport.SERVICOS['AUTORIZAR'][0],'https://nfce-homologacao.svrs.rs.gov.br/ws/NfeAutorizacao/NFeAutorizacao4.asmx')
        self.assertTrue(all(url.startswith(transport.BASE) for url,_,_ in transport.SERVICOS.values()))

    def test_soap12_body_and_content_type_action(self):
        payload=b'<enviNFe xmlns="http://www.portalfiscal.inf.br/nfe"/>'
        data,action=transport.envelope('AUTORIZAR',payload);root=parse(data)
        self.assertEqual(root.tag,'{'+SOAP+'}Envelope');self.assertEqual(len(root.find('{'+SOAP+'}Body')),1)
        req=RequisicaoSOAP(transport.SERVICOS['AUTORIZAR'][0],action,data)
        self.assertIn('application/soap+xml',req.headers['Content-Type']);self.assertIn(action,req.headers['Content-Type'])
        self.assertFalse(req.permitir_redirect);self.assertEqual(req.retries_automaticos,0);self.assertTrue(req.verificar_tls and req.verificar_hostname)

    def test_unknown_operation_and_xml_entities_blocked(self):
        for op,payload in [('PRODUCAO',b'<x/>'),('AUTORIZAR',b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><x>&a;</x>')]:
            with self.assertRaises(ValidationError):transport.envelope(op,payload)

    def test_all_pinned_wsdl_contracts_synthetic(self):
        for operation in ('AUTORIZAR','CONSULTAR','RECIBO','CANCELAR'):
            data=synthetic_wsdl(operation)
            self.assertEqual(validar_wsdl(data,operation,hashlib.sha256(data).hexdigest())['soap'],'1.2')

    def test_wsdl_modified_hash_blocked(self):
        with self.assertRaises(ValidationError):validar_wsdl(synthetic_wsdl(),'AUTORIZAR','0'*64)

    def test_wsdl_production_endpoint_blocked(self):
        data=synthetic_wsdl().replace(b'nfce-homologacao.',b'nfce.')
        with self.assertRaises(ValidationError):validar_wsdl(data,'AUTORIZAR',hashlib.sha256(data).hexdigest())

    def test_wsdl_other_action_blocked(self):
        data=synthetic_wsdl().replace(b'/nfeAutorizacaoLote',b'/wrongAction')
        with self.assertRaises(ValidationError):validar_wsdl(data,'AUTORIZAR',hashlib.sha256(data).hexdigest())

    def test_wsdl_external_import_blocked(self):
        root=parse(synthetic_wsdl());etree.SubElement(root,'{'+WSDL+'}import',location='https://example.invalid/import')
        data=etree.tostring(root)
        with self.assertRaises(ValidationError):validar_wsdl(data,'AUTORIZAR',hashlib.sha256(data).hexdigest())


class CryptographicSOAPDouble(CofreDuploLocal):
    """Complete fake authority; signs in memory with a NON ICP-BRASIL key."""
    def __init__(self,org,cnpj,branch):
        super().__init__(org,cnpj,branch);self.cert=SyntheticCertificate(cnpj)
        self.identity=replace(self.cert.identity(org,branch),icp_brasil=True)
        self.digest='';self.events={};self.signed_events={}

    def assinar(self,reference,data,**context):
        return assinar_xml(data,self.identity,lambda si:self.cert.key.sign(si,padding.PKCS1v15(),hashes.SHA1()))

    def response(self,key,code,consult=False):
        root=parse(super().response(key,code,consult));ns={'n':NFE}
        digest=root.find('.//n:digVal',ns)
        if digest is not None:digest.text=self.digest
        if consult:
            if key in self.events:
                root.find('{'+NFE+'}cStat').text='101'
                proc=etree.SubElement(root,'{'+NFE+'}procEventoNFe',versao='1.00')
                proc.append(copy.deepcopy(parse(self.signed_events[key]).find('{'+NFE+'}evento')))
                proc.append(copy.deepcopy(parse(self.events[key]).find('{'+NFE+'}retEvento')))
        return etree.tostring(root)

    def cancel_response(self,key):
        root=etree.Element('{'+NFE+'}retEnvEvento',versao='1.00',nsmap={None:NFE})
        for k,v in [('idLote','1'),('tpAmb','2'),('verAplic','QA-ONLY'),('cOrgao','28'),('cStat','128'),('xMotivo','Resposta sintetica de evento')]:xml.tag(root,k,v)
        info=etree.SubElement(etree.SubElement(root,'{'+NFE+'}retEvento',versao='1.00'),'{'+NFE+'}infEvento')
        for k,v in [('tpAmb','2'),('verAplic','QA-ONLY'),('cOrgao','28'),('cStat','135'),('xMotivo','Cancelamento exclusivamente sintetico'),('chNFe',key),('tpEvento','110111'),('xEvento','Cancelamento'),('nSeqEvento','1'),('dhRegEvento',timezone.localtime().isoformat(timespec='seconds')),('nProt','128260000000002')]:xml.tag(info,k,v)
        return etree.tostring(root)

    def transmitir(self,reference,endpoint,method,body,**context):
        root=parse(body)
        if 'NfeAutorizacao/' in endpoint:self.digest=root.findtext('.//{'+signature.DS+'}DigestValue')
        if 'NfeConsulta/' in endpoint:
            self.calls.append(endpoint);key=root.findtext('.//{'+NFE+'}chNFe')
            return self.response(key,'100',consult=True) if key in self.records else self.response(key,'217',consult=True)
        if 'recepcaoevento' in endpoint:
            self.calls.append(endpoint);event=root.find('.//{'+NFE+'}envEvento');key=event.findtext('.//{'+NFE+'}chNFe')
            self.signed_events[key]=etree.tostring(event);self.events[key]=self.cancel_response(key)
            if self.timeout:raise TimeoutError('Only synthetic lost event response')
            return self.events[key]
        return super().transmitir(reference,endpoint,method,body,**context)


class InfrastructureFlowTests(NFCeData,TestCase):
    def setUp(self):
        self.nfce_setup();self.vault=CryptographicSOAPDouble(self.a.pk,self.branch.cnpj,self.branch.pk)
        self.schema=SchemaFluxo(ensaio_local=True)
        self.motor=MotorNFCeHomologacao(cofre=self.vault,schema=self.schema,verificador=lambda u,signed,i:signature.verificar(u,signed,i,cadeia=self.vault.cert.chain,ancoras_sha256=self.vault.cert.anchors,ensaio_sintetico=True),transporte=TransporteDuploLocal(self.vault))

    def test_full_pdv_crypto_official_xsd_authorization(self):
        with tenant_context(self.a):
            doc=self.homdoc();sale=doc.venda;before=copy.deepcopy(sale.snapshot);req=self.homreq(doc)
            result=self.runreq(req);doc.refresh_from_db();sale.refresh_from_db()
            self.assertEqual((result.estado,doc.status),('CONCLUIDA','AUTORIZADA'))
            self.assertEqual(sale.snapshot,before);self.assertEqual(sale.status,'FINALIZADA')
            self.assertEqual(req.artefatos_nfce.filter(tipo='PROCESSADO').count(),1)
            file=req.artefatos_nfce.get(tipo='PROCESSADO').arquivo
            with file.arquivo.open('rb') as f:self.schema.validar(f.read(),'procNFe_v4.00.xsd')
            self.assertFalse(file.disponivel_portal)

    def test_unsigned_official_fields_before_signature_and_signed_after(self):
        with tenant_context(self.a):
            req=self.homreq();unsigned=self.generated(req.documento)
            proof=self.schema.validar_sem_assinatura(unsigned)
            self.assertEqual(proof['etapa'],'ANTES_DA_ASSINATURA')
            signed=self.vault.assinar('',unsigned)
            self.assertEqual(self.schema.validar(signed)['etapa'],'INTEGRAL')
            with self.assertRaises(ValidationError):self.schema.validar(unsigned)
            with self.assertRaises(ValidationError):self.schema.validar_sem_assinatura(signed)

    def test_invalid_field_blocks_before_vault_signing(self):
        with tenant_context(self.a):
            req=self.homreq();root=parse(self.generated(req.documento));root.find('.//{'+NFE+'}CRT').text='INVALID'
            self.vault.assinar=Mock()
            with self.assertRaises(ValidationError):self.motor.preparar_assinado(req.documento,etree.tostring(root),'EMITIR')
            self.vault.assinar.assert_not_called()

    def test_real_defaults_cannot_activate_lab_package(self):
        with tenant_context(self.a):
            req=self.homreq();signed=self.vault.assinar('',self.generated(req.documento))
            with self.assertRaises(ValidationError):SchemaFluxo().validar(signed)

    def test_official_rejection_preserved_no_sale_rollback(self):
        with tenant_context(self.a):
            self.vault.code='225';req=self.homreq();result=self.runreq(req);doc=req.documento;doc.refresh_from_db()
            self.assertEqual((result.estado,doc.status),('CONCLUIDA','REJEITADA'));self.assertEqual(doc.venda.status,'FINALIZADA')
            self.assertTrue(req.artefatos_nfce.filter(codigo='225').exists());self.assertFalse(doc.protocolo)

    def test_lost_authorization_reconciles_official_query_no_second_sale_number(self):
        with tenant_context(self.a):
            self.vault.timeout=True;req=self.homreq();number=req.documento.numero
            self.assertEqual(self.runreq(req).estado,'RESULTADO_DESCONHECIDO')
            self.assertEqual(workflow.estado(req.documento,self.runreq(req)),'CONSULTA_PENDENTE')
            self.vault.timeout=False;result=self.runreq(req);doc=req.documento;doc.refresh_from_db()
            self.assertEqual((result.estado,doc.status),('CONCLUIDA','AUTORIZADA'))
            self.assertEqual(doc.numero,number);self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)
            self.assertEqual(sum('NfeAutorizacao/' in x for x in self.vault.calls),1)

    def test_timeout_state_visible_then_query_pending(self):
        with tenant_context(self.a):
            self.vault.fail_before=True;req=self.homreq();result=self.runreq(req)
            self.assertEqual(workflow.estado(req.documento,result),'TIMEOUT')
            self.vault.fail_before=False;result=self.runreq(req)
            self.assertEqual(workflow.estado(req.documento,result),'CONSULTA_PENDENTE')
            self.assertEqual(sum('NfeAutorizacao/' in x for x in self.vault.calls),1)

    def test_official_cancellation_xsd_crypto_and_status(self):
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);doc=req.documento;doc.refresh_from_db();protocol=doc.protocolo
            cancel=self.homreq(doc,operacao='CANCELAR',motivo='Justificativa sintetica para cancelamento')
            self.assertEqual(self.runreq(cancel).estado,'CONCLUIDA');doc.refresh_from_db()
            self.assertEqual(doc.status,'CANCELADA');self.assertEqual(doc.protocolo,protocol);self.assertEqual(doc.venda.status,'FINALIZADA')

    def test_lost_cancellation_query_recovers_event_without_resend(self):
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);doc=req.documento;doc.refresh_from_db()
            cancel=self.homreq(doc,operacao='CANCELAR',motivo='Justificativa sintetica para cancelamento')
            self.vault.timeout=True;self.assertEqual(self.runreq(cancel).estado,'RESULTADO_DESCONHECIDO')
            self.vault.timeout=False;self.assertEqual(self.runreq(cancel).estado,'CONCLUIDA');doc.refresh_from_db()
            self.assertEqual(doc.status,'CANCELADA');self.assertEqual(sum('recepcaoevento' in x for x in self.vault.calls),1)

    def test_duplicate_retry_does_not_duplicate_artifacts_sales_or_reservations(self):
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);before=(m.Venda.objects.count(),m.ReservaNumeracaoFiscal.objects.count(),req.artefatos_nfce.count(),len(self.vault.calls))
            self.runreq(req);self.assertEqual(before,(m.Venda.objects.count(),m.ReservaNumeracaoFiscal.objects.count(),req.artefatos_nfce.count(),len(self.vault.calls)))

    def test_final_readiness_blocked_despite_synthetic_authorization_configuration(self):
        with tenant_context(self.a):
            req=self.homreq();proof=readiness.verificar(self.admin,req.documento_id,motor=self.motor)
            self.assertEqual(proof['estado'],'EMISSÃO BLOQUEADA');self.assertFalse(proof['transmissao_executada'])
            self.assertIn('WSDL oficial pinado',proof['pendencias']);self.assertIn('Credenciamento explicitamente confirmado',proof['pendencias'])

    def test_readiness_wrong_tenant_and_operar_pdv_rejected(self):
        with tenant_context(self.a):
            req=self.homreq()
            with self.assertRaises(PermissionDenied):readiness.verificar(self.operator,req.documento_id)
        with tenant_context(self.b),self.assertRaises(m.DocumentoFiscal.DoesNotExist):readiness.verificar(self.admin_b,req.documento_id)

    def test_wrong_certificate_xml_and_environment_blocked_before_transport(self):
        with tenant_context(self.a):
            req=self.homreq();root=parse(self.generated(req.documento))
            for node,value in [('.//{'+NFE+'}CNPJ','11444777000161'),('.//{'+NFE+'}tpAmb','1')]:
                changed=copy.deepcopy(root);changed.find(node).text=value
                with self.assertRaises(ValidationError):self.motor.preparar_assinado(req.documento,etree.tostring(changed),'EMITIR')
            self.assertEqual(self.vault.calls,[])

    def test_cancel_deadline_scoped_explicit_and_not_inferred(self):
        with tenant_context(self.a):
            req=self.homreq();self.runreq(req);doc=req.documento;doc.refresh_from_db()
            rule=workflow.RegraCancelamento(self.a.pk,self.branch.pk,10,'https://www.sefaz.se.gov.br/',True)
            # Ten minutes is a synthetic test vector, NOT an SE legal deadline.
            rule.validar(doc)
            for bad in (replace(rule,confirmada=False),replace(rule,organization_id=self.b.pk),replace(rule,estabelecimento_id=99999),replace(rule,fonte='https://example.invalid')):
                with self.assertRaises(ValidationError):bad.validar(doc)
            doc.autorizado_em=timezone.now()-timedelta(minutes=11)
            with self.assertRaises(ValidationError):rule.validar(doc)

    def test_receipt_validation_and_no_automatic_resend(self):
        with tenant_context(self.a):
            req=self.homreq()
            with self.assertRaises(ValidationError):self.motor.consultar_recibo(req.documento,'invalid')
            payload=b'<consReciNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><tpAmb>2</tpAmb><nRec>128260000000001</nRec></consReciNFe>'
            self.schema.validar(payload,'consReciNFe_v4.00.xsd')


class SecureVaultAndMTLSTests(NFCeData,TestCase):
    def setUp(self):
        self.nfce_setup();self.cert=SyntheticCertificate(self.branch.cnpj)
        self.provider=Mock();self.provider.identidade.return_value=replace(self.cert.identity(self.a.pk,self.branch.pk),icp_brasil=True,cadeia_validada=True,revogacao_verificada=True)
        self.provider.assinar_canonicalizado.side_effect=lambda ref,data,**kw:self.cert.key.sign(data,padding.PKCS1v15(),hashes.SHA1())
        self.adapter=AdaptadorCofre(self.provider,ancoras_icp_brasil=self.cert.anchors)
        with tenant_context(self.a):
            self.transport_credential=m.CredencialFiscal.objects.create(
                referencia='cofre://'+str(uuid.uuid4()),mecanismo='REFERENCIA',ambiente='HOMOLOGACAO')
            m.VinculoCredencialFiscal.objects.create(configuracao=self.config,credencial=self.transport_credential)
        self.transport_vault=AdaptadorCofre(self.provider,ancoras_icp_brasil=self.cert.anchors)
        self.context={'organization_id':self.a.pk,'estabelecimento_id':self.branch.pk,'ambiente':'HOMOLOGACAO','emitente_cnpj':self.branch.cnpj}
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        path=Path(self.directory.name)/'aut.wsdl';data=synthetic_wsdl();path.write_bytes(data)
        self.secure=TransporteSVRSHomologacao(self.provider,cofre_transporte=self.transport_vault,referencia_transporte=self.transport_credential.referencia,wsdl_pins={'AUTORIZAR':(path,hashlib.sha256(data).hexdigest())},habilitado=True)
        root=etree.Element('{'+SOAP+'}Envelope');body=etree.SubElement(root,'{'+SOAP+'}Body')
        etree.SubElement(body,'{http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4}nfeResultMsg')
        self.good=RespostaHTTPS(200,'application/soap+xml',etree.tostring(root),transport.SERVICOS['AUTORIZAR'][0],True,True,self.cert.fingerprint)
        self.provider.executar_mtls.return_value=self.good

    def send(self,**context):return self.secure.enviar('AUTORIZAR',b'<enviNFe xmlns="http://www.portalfiscal.inf.br/nfe"/>',**{**self.context,**context})

    def test_detached_signer_uses_only_canonical_public_bytes_and_reference(self):
        with tenant_context(self.a):
            req=self.homreq();unsigned=self.generated(req.documento)
            signed=self.adapter.assinar(self.cred.referencia,unsigned,**self.context)
            signature.verificar(unsigned,signed,self.provider.identidade.return_value,cadeia=self.cert.chain,ancoras_sha256=self.cert.anchors)
        ref,data=self.provider.assinar_canonicalizado.call_args.args
        self.assertEqual(ref,self.cred.referencia);self.assertIn(b'SignedInfo',data)
        self.assertNotIn(b'PRIVATE KEY',data);self.provider.assinar.assert_not_called()

    def test_wrong_xml_issuer_never_reaches_signer(self):
        with tenant_context(self.a):
            req=self.homreq();unsigned=self.generated(req.documento).replace(self.branch.cnpj.encode(),b'11444777000161')
            with self.assertRaises(ValidationError):self.adapter.assinar(self.cred.referencia,unsigned,**self.context)
        self.provider.assinar_canonicalizado.assert_not_called()

    def test_invalid_signature_from_vault_sanitized(self):
        self.provider.assinar_canonicalizado.return_value=b'x'*256;self.provider.assinar_canonicalizado.side_effect=None
        with tenant_context(self.a):
            req=self.homreq()
            with self.assertRaises(ValidationError):self.adapter.assinar(self.cred.referencia,self.generated(req.documento),**self.context)

    def test_truthy_attestation_not_a_confirmation(self):
        self.provider.identidade.return_value=replace(self.provider.identidade.return_value,revogacao_verificada='yes')
        with tenant_context(self.a),self.assertRaises(ValidationError):self.adapter.identidade(self.cred.referencia,**self.context)

    def test_separate_transport_identity_and_policy_passed_to_double(self):
        with tenant_context(self.a):self.assertEqual(self.send(),self.good.body)
        reference,request=self.provider.executar_mtls.call_args.args
        self.assertEqual(reference,self.transport_credential.referencia);self.assertNotEqual(reference,self.cred.referencia);self.assertEqual(request.retries_automaticos,0);self.assertFalse(request.permitir_redirect)
        self.assertTrue(request.verificar_tls and request.verificar_hostname)
        self.provider.assinar_canonicalizado.assert_not_called()

    def test_unprovisioned_transport_does_not_fallback_to_signing_key(self):
        self.secure.referencia_transporte=None
        with tenant_context(self.a),self.assertRaises(ValidationError):self.send()
        self.provider.executar_mtls.assert_not_called()

    def test_motor_rejects_transport_reference_reuse(self):
        with tenant_context(self.a):
            req=self.homreq();self.secure.referencia_transporte=req.documento.credencial_fiscal.referencia
            motor=MotorNFCeHomologacao(cofre=self.adapter,schema=self.schema,transporte=self.secure)
            with self.assertRaisesMessage(ValidationError,'Referência mTLS deve ser distinta'):
                motor.emitir(req.documento,self.generated(req.documento))
            self.provider.executar_mtls.assert_not_called()

    def test_wsdls_not_downloaded_during_dispatch(self):
        self.secure.wsdl_pins={}
        with tenant_context(self.a),self.assertRaises(ValidationError):self.send()
        self.provider.executar_mtls.assert_not_called()

    def test_default_disabled_before_cofre_or_network(self):
        self.secure.habilitado=False
        with tenant_context(self.a),self.assertRaises(ValidationError):self.send()
        self.provider.identidade.assert_not_called();self.provider.executar_mtls.assert_not_called()

    def test_feature_flag_alone_cannot_activate_transport(self):
        with tenant_context(self.a),override_settings(FISCAL_NFCE_SEFAZ_APPROVED=False),self.assertRaises(ValidationError):self.send()
        self.provider.executar_mtls.assert_not_called()

    def test_tenant_branch_environment_mismatch_blocks_before_mtls(self):
        for change in ({'organization_id':self.b.pk},{'estabelecimento_id':99999},{'ambiente':'PRODUCAO'},{'emitente_cnpj':'11444777000161'}):
            with tenant_context(self.a),self.subTest(change=change),self.assertRaises(ValidationError):self.send(**change)
        self.provider.executar_mtls.assert_not_called()

    def test_wrong_tls_fingerprint_host_status_content_type_or_size_blocked(self):
        for changes in ({'tls_validado':False},{'hostname_validado':False},{'mtls_fingerprint':'0'*64},{'endpoint':'https://example.invalid'}, {'status':302},{'content_type':'text/html'},{'body':b'x'*2_000_001}):
            self.provider.executar_mtls.return_value=replace(self.good,**changes)
            with tenant_context(self.a),self.subTest(changes=list(changes)),self.assertRaises(ValidationError):self.send()

    def test_soap_fault_never_authorizes(self):
        root=parse(self.good.body);body=root.find('{'+SOAP+'}Body');body.remove(body[0]);etree.SubElement(body,'{'+SOAP+'}Fault')
        self.provider.executar_mtls.return_value=replace(self.good,body=etree.tostring(root))
        with tenant_context(self.a),self.assertRaises(ValidationError):self.send()

    def test_transport_timeout_does_not_retry(self):
        self.provider.executar_mtls.side_effect=TimeoutError('DO-NOT-EXPOSE')
        with tenant_context(self.a),self.assertRaises(TimeoutError) as caught:self.send()
        self.assertNotIn('DO-NOT-EXPOSE',str(caught.exception));self.assertEqual(self.provider.executar_mtls.call_count,1)

    def test_transport_exception_does_not_expose_secret(self):
        self.provider.executar_mtls.side_effect=RuntimeError('DO-NOT-EXPOSE')
        with tenant_context(self.a),self.assertRaises(ValidationError) as caught:self.send()
        self.assertNotIn('DO-NOT-EXPOSE',str(caught.exception))
