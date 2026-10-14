"""Synthetic certificate/signing fixture ONLY. Keys generated in memory, never exported.

No relationship to TECNOLMED's real A1 or ICP-Brasil. Not a vault implementation.
"""
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import NameOID, ObjectIdentifier
from lxml import etree
from fiscal.nfce.schema import parse, NFE
from fiscal.nfce.signature import DS, C14N
from fiscal.nfce.contracts import IdentidadeCertificado


def certificate(subject, public, issuer, issuer_key, *, cnpj=None, ca=False, expired=False):
    now = datetime.now(timezone.utc)
    builder = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(public)
    builder = builder.serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=3))
    builder = builder.not_valid_after(now+timedelta(days=-1 if expired else 3))
    builder = builder.add_extension(x509.BasicConstraints(ca=ca, path_length=1 if ca else None), critical=True)
    builder = builder.add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
        key_encipherment=False, data_encipherment=False, key_agreement=False,
        key_cert_sign=ca, crl_sign=ca, encipher_only=None, decipher_only=None), critical=True)
    if cnpj:
        builder = builder.add_extension(x509.SubjectAlternativeName([
            x509.OtherName(ObjectIdentifier('2.16.76.1.3.3'), b'\x0c\x0e'+cnpj.encode('ascii'))]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


class SyntheticCertificate:
    def __init__(self, cnpj='11222333000181', *, expired=False, missing_cnpj=False):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'QA SYNTHETIC ROOT — NOT ICP-BRASIL')])
        root = certificate(name, root_key.public_key(), name, root_key, ca=True)
        holder = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'QA SYNTHETIC ISSUER')])
        self.cert = certificate(holder, self.key.public_key(), name, root_key,
                                cnpj=None if missing_cnpj else cnpj, expired=expired)
        self.der = self.cert.public_bytes(serialization.Encoding.DER)
        self.chain = (root.public_bytes(serialization.Encoding.DER),)
        self.anchors = (hashlib.sha256(self.chain[0]).hexdigest(),)
        self.fingerprint = hashlib.sha256(self.der).hexdigest()
        self.cnpj = cnpj

    def identity(self, org=1, branch=1):
        return IdentidadeCertificado(org, 'HOMOLOGACAO', self.cnpj, True, False, branch,
            self.fingerprint, self.cert.subject.rfc4514_string(), self.cert.not_valid_before_utc, self.cert.not_valid_after_utc,
            certificado_der=self.der, cadeia_der=self.chain)

    def sign(self, unsigned):
        root = parse(unsigned)
        info = root.find('{'+NFE+'}infNFe')
        ds = '{'+DS+'}'
        signature = etree.SubElement(root, ds+'Signature', nsmap={None:DS})
        si = etree.SubElement(signature, ds+'SignedInfo')
        etree.SubElement(si, ds+'CanonicalizationMethod', Algorithm=C14N)
        etree.SubElement(si, ds+'SignatureMethod', Algorithm=DS+'rsa-sha1')
        reference = etree.SubElement(si, ds+'Reference', URI='#'+info.get('Id'))
        transforms = etree.SubElement(reference, ds+'Transforms')
        for algorithm in (DS+'enveloped-signature', C14N):
            etree.SubElement(transforms, ds+'Transform', Algorithm=algorithm)
        etree.SubElement(reference, ds+'DigestMethod', Algorithm=DS+'sha1')
        etree.SubElement(reference, ds+'DigestValue').text = base64.b64encode(hashlib.sha1(etree.tostring(info, method='c14n')).digest()).decode()
        etree.SubElement(signature, ds+'SignatureValue').text = base64.b64encode(self.key.sign(
            etree.tostring(si, method='c14n'), padding.PKCS1v15(), hashes.SHA1())).decode()
        data = etree.SubElement(etree.SubElement(signature, ds+'KeyInfo'), ds+'X509Data')
        etree.SubElement(data, ds+'X509Certificate').text = base64.b64encode(self.der).decode()
        return etree.tostring(root, encoding='utf-8', xml_declaration=True)
