"""Fixed SVRS/HOMOLOGAÇÃO transport adapter; no PFX or network fallback.

The provisioned secure backend executes HTTPS/mTLS. This application builds
SOAP 1.2 and validates the response. Default construction cannot call a server.
WSDL is pinned during provisioning, never fetched during an issuance.
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from .contracts import DependenciaFiscal
from .schema import parse
from . import transport

SOAP='http://www.w3.org/2003/05/soap-envelope'
WSDL='http://schemas.xmlsoap.org/wsdl/'
SOAP_BINDING='http://schemas.xmlsoap.org/wsdl/soap12/'


def validar_wsdl(data, operation, sha256):
    """Checks offline bytes against a backend pin and the exact service binding."""
    endpoint,service,method=transport.SERVICOS[operation]
    expected='http://www.portalfiscal.inf.br/nfe/wsdl/'+service
    root=parse(data)
    if hashlib.sha256(data).hexdigest()!=sha256 or root.tag!='{'+WSDL+'}definitions' or root.get('targetNamespace')!=expected:
        raise DependenciaFiscal('WSDL não confirmado/pinado para o serviço de homologação.')
    if root.findall('{'+WSDL+'}import') or root.findall('.//{http://www.w3.org/2001/XMLSchema}import') or root.findall('.//{http://www.w3.org/2001/XMLSchema}include'):
        raise DependenciaFiscal('WSDL com dependência externa exige pinagem controlada.')
    action=expected+'/'+method
    matches=[]
    for binding in root.findall('{'+WSDL+'}binding'):
        if binding.find('{'+SOAP_BINDING+'}binding') is None:continue
        for op in binding.findall('{'+WSDL+'}operation'):
            soap=op.find('{'+SOAP_BINDING+'}operation')
            body=op.find('{'+WSDL+'}input/{'+SOAP_BINDING+'}body')
            if op.get('name')==method and soap is not None and soap.get('soapAction')==action and body is not None and body.get('use')=='literal':
                matches.append(binding.get('name'))
    if len(matches)!=1:raise DependenciaFiscal('Binding SOAP 1.2/action do WSDL incompatível.')
    ports=root.findall('{'+WSDL+'}service/{'+WSDL+'}port')
    if not any(p.get('binding','').split(':')[-1]==matches[0] and p.find('{'+SOAP_BINDING+'}address') is not None and p.find('{'+SOAP_BINDING+'}address').get('location')==endpoint for p in ports):
        raise DependenciaFiscal('Endpoint do WSDL não corresponde à homologação SVRS.')
    return {'endpoint':endpoint,'action':action,'sha256':sha256,'soap':'1.2'}


@dataclass(frozen=True)
class RequisicaoSOAP:
    endpoint: str
    action: str
    body: bytes = field(repr=False)
    timeout_conexao: int = 10
    timeout_leitura: int = 30
    verificar_tls: bool = True
    verificar_hostname: bool = True
    tls_minimo: str = '1.2'
    permitir_redirect: bool = False
    retries_automaticos: int = 0
    limite_resposta: int = 2_000_000
    @property
    def headers(self):
        return {'Content-Type':'application/soap+xml; charset=utf-8; action="'+self.action+'"','Accept':'application/soap+xml'}


@dataclass(frozen=True)
class RespostaHTTPS:
    status: int
    content_type: str
    body: bytes = field(repr=False)
    endpoint: str
    tls_validado: bool
    hostname_validado: bool
    mtls_fingerprint: str


class TransporteSVRSHomologacao:
    def __init__(self, provider=None, *, cofre_transporte=None, referencia_transporte=None,
                 wsdl_pins=None, habilitado=False):
        # Separate transport reference/provider: never automatically reuse the
        # signing identity as a client TLS identity.
        self.provider=provider;self.cofre_transporte=cofre_transporte
        self.referencia_transporte=referencia_transporte
        self.wsdl_pins=wsdl_pins or {};self.habilitado=habilitado

    def contrato(self, operation):
        try:
            path,digest=self.wsdl_pins[operation]
            return validar_wsdl(Path(path).read_bytes(),operation,digest)
        except (KeyError,OSError):
            raise DependenciaFiscal('WSDL oficial não provisionado/pinado; transmissão bloqueada.') from None

    def enviar(self, operation, payload, **context):
        from .services import local
        local()
        if not self.habilitado or not getattr(settings,'FISCAL_NFCE_SEFAZ_APPROVED',False):
            raise DependenciaFiscal('Transmissão SEFAZ não autorizada; nenhuma conexão realizada.')
        if operation not in ('AUTORIZAR','CONSULTAR','RECIBO','CANCELAR') or context.get('ambiente')!='HOMOLOGACAO':
            raise ValidationError('Somente operações NFC-e de homologação são permitidas.')
        contract=self.contrato(operation)
        if not self.provider or not self.cofre_transporte or not self.referencia_transporte:
            raise DependenciaFiscal('mTLS específico não provisionado; não será reutilizado automaticamente o A1 de assinatura.')
        identity=self.cofre_transporte.identidade(self.referencia_transporte,**context)
        body,action=transport.envelope(operation,payload)
        request=RequisicaoSOAP(contract['endpoint'],action,body)
        try:
            result=self.provider.executar_mtls(self.referencia_transporte,request,**context)
        except TimeoutError:
            raise TimeoutError('Timeout fiscal; consultar sem novo envio/numeração.') from None
        except Exception:
            raise DependenciaFiscal('Falha no transporte seguro; detalhes do provedor não expostos.') from None
        if not isinstance(result,RespostaHTTPS) or result.endpoint!=request.endpoint or result.tls_validado is not True or result.hostname_validado is not True or result.mtls_fingerprint!=identity.sha256_certificado:
            raise DependenciaFiscal('HTTPS/mTLS não atestado para a identidade de transporte.')
        if not isinstance(result.body,bytes) or len(result.body)>request.limite_resposta or result.status!=200 or result.content_type.split(';')[0].strip().lower()!='application/soap+xml':
            raise DependenciaFiscal('Resposta HTTPS/SOAP inválida; resultado deve ser reconciliado.')
        root=parse(result.body)
        soap_body=root.find('{'+SOAP+'}Body')
        if root.tag!='{'+SOAP+'}Envelope' or soap_body is None or len(soap_body)!=1 or soap_body.find('{'+SOAP+'}Fault') is not None:
            raise DependenciaFiscal('Falha SOAP; nenhuma autorização presumida.')
        service=transport.SERVICOS[operation][1]
        wrapper=soap_body[0]
        if etree_namespace(wrapper)!='http://www.portalfiscal.inf.br/nfe/wsdl/'+service:
            raise DependenciaFiscal('Resposta SOAP de outro serviço.')
        return result.body


def etree_namespace(node):
    from lxml import etree
    return etree.QName(node).namespace
