"""Ensaio local PostgreSQL + HTTPS + S3 Moto; não cria infraestrutura externa.

Requer PostgreSQL local de teste em tmp/provision, provisionado separadamente.
Material criptográfico/dados sintéticos ficam em tmp e nunca entram no pacote.
O servidor WSGI deste arquivo serve exclusivamente ao ensaio, não à produção.
"""
import datetime
import ipaddress
import json
import logging
import os
import secrets
import ssl
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
directory = root / 'tmp/provision'
environment_path = directory / 'https_test_environment.json'
certificate = directory / 'local-test.crt'
key_path = directory / 'local-test.key'
mode = sys.argv[1]

if mode == 'setup':
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'VERTYX local test')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=2)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256())
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    values = json.loads((directory / 'local_test_environment.json').read_text())
    values.update(DEBUG='False', SECRET_KEY=secrets.token_urlsafe(64), UPLOAD_STORAGE='s3', ALLOWED_HOSTS='127.0.0.1,localhost', CSRF_TRUSTED_ORIGINS='https://127.0.0.1:8765,https://localhost:8765', S3_BUCKET_NAME='vertyx-local-simulator-only', S3_ENDPOINT_URL='https://127.0.0.1:9501', S3_REGION_NAME='us-east-1', AWS_ACCESS_KEY_ID=secrets.token_hex(10), AWS_SECRET_ACCESS_KEY=secrets.token_urlsafe(32), AWS_CA_BUNDLE=str(certificate), BROWSER_TEST_PASSWORD=secrets.token_urlsafe(32))
    environment_path.write_text(json.dumps(values), encoding='utf-8')
    print('Configuração/certificado sintéticos preparados somente para localhost.')
    raise SystemExit()

values = json.loads(environment_path.read_text())
assert values['S3_ENDPOINT_URL'] == 'https://127.0.0.1:9501'
assert values['DATABASE_URL'].split('@')[1] == '127.0.0.1:55432/vertyx_homologation'
os.environ.update(values)
os.environ['DJANGO_SETTINGS_MODULE'] = 'tecnolmed.settings'

if mode == 's3':
    from moto.server import DomainDispatcherApplication, create_backend_app
    from werkzeug.serving import make_server
    logging.basicConfig(level=logging.ERROR)
    server = make_server('127.0.0.1', 9501, DomainDispatcherApplication(create_backend_app), threaded=True, ssl_context=(str(certificate), str(key_path)))
    print('Simulador S3 local HTTPS pronto.', flush=True)
    server.serve_forever()

import django
django.setup()

if mode == 'web':
    from wsgiref.simple_server import make_server, WSGIRequestHandler
    from django.core.wsgi import get_wsgi_application
    class LocalTLSHandler(WSGIRequestHandler):
        def get_environ(self):
            environ = super().get_environ()
            environ['HTTPS'] = 'on'
            environ['wsgi.url_scheme'] = 'https'
            return environ
        def log_message(self, *args):
            pass  # Não registrar URLs privadas/token no ensaio.
    server = make_server('127.0.0.1', 8765, get_wsgi_application(), handler_class=LocalTLSHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print('Aplicação de ensaio local HTTPS pronta, DEBUG=False.', flush=True)
    server.serve_forever()
elif mode == 'fixtures':
    import boto3
    from botocore.exceptions import ClientError
    from django.core.management import call_command
    from contas.models import Usuario, Tecnico
    from clientes.models import Cliente, Unidade
    from equipamentos.models import CategoriaEquipamento, Equipamento
    from ordens.models import OrdemServico
    from platform_core.models import Organization, OrganizationERP, OrganizationMembership, MembershipERP, ERPCatalog
    from platform_core.context import tenant_context
    call_command('migrate_locked', noinput=True, verbosity=0)
    s3 = boto3.client('s3', endpoint_url=values['S3_ENDPOINT_URL'], region_name=values['S3_REGION_NAME'])
    try:
        s3.head_bucket(Bucket=values['S3_BUCKET_NAME'])
    except ClientError as exc:
        if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404:
            raise
        s3.create_bucket(Bucket=values['S3_BUCKET_NAME'])
    slug = sys.argv[2] if len(sys.argv) > 2 else 'tecnolmed'
    assert slug in ['tecnolmed', 'homologacao-local-b']
    organization, _ = Organization.objects.get_or_create(slug=slug, defaults={'razao_social': '[TESTE] Empresa B', 'nome_fantasia': '[TESTE] Empresa B'})
    erp = ERPCatalog.objects.get(code='assistencia')
    OrganizationERP.objects.get_or_create(organization=organization, erp=erp)
    user, _ = Usuario.objects.get_or_create(username='browser-homolog-' + slug)
    user.set_password(values['BROWSER_TEST_PASSWORD'])
    user.save()
    membership, _ = OrganizationMembership.objects.get_or_create(organization=organization, user=user, defaults={'role': 'TECNICO'})
    MembershipERP.objects.get_or_create(membership=membership, erp=erp)
    with tenant_context(organization):
        tech, _ = Tecnico.objects.get_or_create(usuario=user, defaults={'nome': '[TESTE] Técnico'})
        customer, _ = Cliente.objects.get_or_create(cpf_cnpj='LOCAL-BROWSER-TEST', defaults={'nome_razao_social': '[TESTE] Hospital', 'cidade': 'Maceió', 'uf': 'AL'})
        unit, _ = Unidade.objects.get_or_create(cliente=customer, nome='[TESTE] Unidade')
        category, _ = CategoriaEquipamento.objects.get_or_create(nome='[TESTE] Hospitalar')
        equipment, _ = Equipamento.objects.get_or_create(cliente=customer, nome='[TESTE] Monitor', defaults={'unidade': unit, 'categoria': category})
        order = OrdemServico.objects.create(cliente=customer, unidade=unit, equipamento=equipment, tecnico=tech, defeito='Ensaio local: equipamento não liga.')
    output = root / 'tmp/validation'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'browser.json').write_text(json.dumps({'ordem': order.pk, 'organization': organization.display_name, 'username': user.username, 'password': values['BROWSER_TEST_PASSWORD'], 'base_url': 'https://127.0.0.1:8765'}), encoding='utf-8')
    print('Fixtures sintéticas de navegador preparadas na base local isolada.')
elif mode == 'probe':
    import hashlib
    import requests
    from ordens.models import OrdemServico
    from ordens.services import digest
    from platform_core.context import tenant_context
    result = json.loads((root / 'tmp/validation/browser-result.json').read_text())
    session = requests.Session()
    for cookie in result['cookies']:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])
    order = OrdemServico.all_objects.select_related('organization').get(pk=result['ordem'])
    with tenant_context(order.organization):
        photo = order.fotos.first()
        signature = order.assinaturas.first()
        paths = {'photo': f'/ordens/{order.pk}/fotos/{photo.pk}/', 'signature': f'/ordens/{order.pk}/assinaturas/{signature.pk}/imagem/', 'pdf': result['pdf_path']}
        contents = {}
        for name, path in paths.items():
            response = session.get('https://127.0.0.1:8765' + path, verify=str(certificate), timeout=30)
            assert response.status_code == 200, (name, response.status_code)
            contents[name] = response.content
        assert hashlib.sha256(contents['photo']).hexdigest() == photo.sha256
        assert hashlib.sha256(contents['signature']).hexdigest() == signature.imagem_sha256
        assert contents['pdf'].startswith(b'%PDF-')
        assert digest(signature.conferencia.dados) == signature.conferencia.digest
        print(json.dumps({'probe': 'PASS', 'organization': order.organization.display_name, 'photo_hash': 'PASS', 'signature_hash': 'PASS', 'snapshot_digest': 'PASS', 'pdf': 'PASS'}))
elif mode == 'cross':
    import requests
    from ordens.models import OrdemServico
    from platform_core.context import tenant_context
    results = [json.loads((root / 'tmp/validation' / filename).read_text()) for filename in ['browser-result-a.json', 'browser-result-b.json']]
    for own, other in [results, list(reversed(results))]:
        session = requests.Session()
        for cookie in own['cookies']:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])
        order = OrdemServico.all_objects.select_related('organization').get(pk=other['ordem'])
        with tenant_context(order.organization):
            photo = order.fotos.first()
            signature = order.assinaturas.first()
        for path in [f'/ordens/{order.pk}/', f'/ordens/{order.pk}/fotos/{photo.pk}/', f'/ordens/{order.pk}/assinaturas/{signature.pk}/imagem/', other['pdf_path']]:
            response = session.get('https://127.0.0.1:8765' + path, verify=str(certificate), timeout=30)
            assert response.status_code == 404, response.status_code
    print('PASS: oito tentativas HTTPS entre empresas (OS, foto, assinatura e PDF, nos dois sentidos) retornaram 404.')
elif mode == 'check':
    from django.core.management import call_command
    call_command('check', deploy=True, fail_level='ERROR')
else:
    raise ValueError('Modo de ensaio desconhecido.')
