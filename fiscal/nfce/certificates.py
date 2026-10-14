"""Public certificate checks. No PFX, password, private key or trust discovery."""
import hashlib
import re
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import ObjectIdentifier
from django.core.exceptions import ValidationError


def cnpj_certificado(cert):
    """ICP-Brasil CNPJ otherName (2.16.76.1.3.3), never a filename or CN guess."""
    try:
        values = [v.value for v in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                  if isinstance(v, x509.OtherName) and v.type_id == ObjectIdentifier('2.16.76.1.3.3')]
        if len(values) != 1:
            raise ValueError()
        value = values[0]
        if len(value) != 16 or value[0] not in (0x0c, 0x13, 0x16, 0x04) or value[1] != 14:
            raise ValueError()
        cnpj = value[2:].decode('ascii')
        if not re.fullmatch(r'\d{14}', cnpj):
            raise ValueError()
        return cnpj
    except Exception:
        raise ValidationError('Identidade CNPJ do certificado ausente/ambígua/incompatível.') from None


def verificar_cadeia(leaf_der, intermediarias, ancoras_sha256):
    """Validate a supplied RSA chain against backend-pinned root fingerprints.

    A synthetic trusted root proves cryptography, NOT ICP-Brasil membership.
    Real anchors and current revocation verification remain provider obligations.
    No AIA/CRL/OCSP fetching here. Unknown critical extensions fail closed.
    """
    try:
        if not intermediarias or not ancoras_sha256 or len(intermediarias) > 8:
            raise ValueError()
        chain = [x509.load_der_x509_certificate(der) for der in (leaf_der, *intermediarias)]
        fingerprints = [hashlib.sha256(der).hexdigest() for der in (leaf_der, *intermediarias)]
        if len(set(fingerprints)) != len(chain) or fingerprints[-1] not in ancoras_sha256:
            raise ValueError()
        now = datetime.now(timezone.utc)
        known = {x509.ExtensionOID.BASIC_CONSTRAINTS, x509.ExtensionOID.KEY_USAGE,
                 x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME, x509.ExtensionOID.EXTENDED_KEY_USAGE,
                 x509.ExtensionOID.CERTIFICATE_POLICIES}
        for i, cert in enumerate(chain):
            if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
                raise ValueError()
            if any(ext.critical and ext.oid not in known for ext in cert.extensions):
                raise ValueError()
            constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
            usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
            if i == 0:
                if constraints.ca or not usage.digital_signature:
                    raise ValueError()
            elif not constraints.ca or not usage.key_cert_sign or constraints.path_length is not None and i - 1 > constraints.path_length:
                raise ValueError()
        for cert, issuer in zip(chain, [*chain[1:], chain[-1]]):
            public = issuer.public_key()
            if cert.issuer != issuer.subject or not isinstance(public, rsa.RSAPublicKey) or public.key_size < 2048:
                raise ValueError()
            public.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
        return {'cadeia': 'VALIDADA CRIPTOGRAFICAMENTE', 'ancora_sha256': fingerprints[-1],
                'revogacao': 'PENDENTE NO PROVEDOR', 'icp_brasil': 'NÃO INFERIDA'}
    except Exception:
        raise ValidationError('Cadeia do certificado inválida, expirada ou sem âncora confiável.') from None
