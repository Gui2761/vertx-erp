"""Validate the XMLDSig returned by the future backend vault; never handle a key."""
import base64
import hashlib
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree
from django.core.exceptions import ValidationError
from .schema import parse, NFE
from .certificates import cnpj_certificado, verificar_cadeia

DS='http://www.w3.org/2000/09/xmldsig#'
C14N='http://www.w3.org/TR/2001/REC-xml-c14n-20010315'


def verificar(unsigned, signed, identity, *, cadeia=(), ancoras_sha256=(), ensaio_sintetico=False):
    try:
        if ensaio_sintetico:
            from .services import local
            local()
        before=parse(unsigned);after=parse(signed)
        info=after.find('{'+NFE+'}infNFe')
        if info is None:info=after.find('.//{'+NFE+'}infEvento')
        # Avoid lxml truth-value dependence for childless nodes.
        if info is None:raise ValueError()
        original=before.find('{'+NFE+'}infNFe')
        if original is None:original=before.find('.//{'+NFE+'}infEvento')
        if original is None or etree.tostring(info,method='c14n')!=etree.tostring(original,method='c14n'):
            raise ValueError()
        identifier=info.get('Id')
        if not identifier or len(after.xpath('//*[@Id=$id]',id=identifier))!=1:
            raise ValueError()
        if len(after.findall('.//'+info.tag))!=1:
            raise ValueError()
        signatures=after.findall('.//{'+DS+'}Signature')
        if len(signatures)!=1:raise ValueError()
        sig=signatures[0];si=sig.find('{'+DS+'}SignedInfo');ref=si.find('{'+DS+'}Reference')
        if len(si.findall('{'+DS+'}Reference'))!=1 or ref.get('URI')!='#'+info.get('Id'):
            raise ValueError()
        transforms=ref.findall('{'+DS+'}Transforms/{'+DS+'}Transform')
        if [x.get('Algorithm') for x in transforms]!=[DS+'enveloped-signature',C14N]:raise ValueError()
        if si.find('{'+DS+'}CanonicalizationMethod').get('Algorithm')!=C14N or si.find('{'+DS+'}SignatureMethod').get('Algorithm')!=DS+'rsa-sha1' or ref.find('{'+DS+'}DigestMethod').get('Algorithm')!=DS+'sha1':raise ValueError()
        digest=base64.b64decode(ref.findtext('{'+DS+'}DigestValue'),validate=True)
        if digest!=hashlib.sha1(etree.tostring(info,method='c14n')).digest():raise ValueError()
        certificates=sig.findall('{'+DS+'}KeyInfo/{'+DS+'}X509Data/{'+DS+'}X509Certificate')
        if len(certificates)!=1:raise ValueError()
        der=base64.b64decode(certificates[0].text,validate=True)
        if hashlib.sha256(der).hexdigest()!=identity.sha256_certificado or not identity.vigente or not identity.icp_brasil and not ensaio_sintetico:raise ValueError()
        cert=x509.load_der_x509_certificate(der);now=datetime.now(timezone.utc)
        if not cert.not_valid_before_utc<=now<=cert.not_valid_after_utc:raise ValueError()
        if cnpj_certificado(cert)!=identity.cnpj:raise ValueError()
        if cadeia or ancoras_sha256:verificar_cadeia(der,cadeia,ancoras_sha256)
        public=cert.public_key()
        if not isinstance(public,rsa.RSAPublicKey) or public.key_size<2048:raise ValueError()
        public.verify(base64.b64decode(sig.findtext('{'+DS+'}SignatureValue'),validate=True),etree.tostring(si,method='c14n'),padding.PKCS1v15(),hashes.SHA1())
        # Everything other than the one signature must be byte-semantically unchanged.
        sig.getparent().remove(sig)
        if etree.tostring(before,method='c14n')!=etree.tostring(after,method='c14n'):raise ValueError()
        return {'xmldsig':'VALIDADA','referencia':ref.get('URI'),'algoritmo':'RSA-SHA1',
                'canonicalizacao':C14N,'digest':'SHA1','fingerprint':identity.sha256_certificado,
                'cadeia':'VALIDADA' if cadeia else 'NÃO FORNECIDA',
                'ensaio_sintetico':ensaio_sintetico}
    except Exception:
        raise ValidationError('Assinatura/certificado incompatível ou XML alterado; transmissão bloqueada.') from None
