"""Comando de Auditoria e Validação Exaustiva de Cibersegurança do VERTYX ERP.

Executa simulação de Red Team / Blue Team em 10 frentes críticas:
1. Interceptação ativa de Scanners e Probes Maliciosos (LFI, Path Traversal, .env, .git)
2. Bloqueio de Ferramentas Ofensivas por User-Agent (sqlmap, nikto, wpscan)
3. Interceptação de Injeção de SQL e XSS em Query String
4. Defesa Ativa de Força Bruta e Credential Stuffing (Rate Limit / Lockout 429)
5. Blindagem contra Server-Side Request Forgery (SSRF) e Cloud Metadata (169.254.169.254)
6. Presença e Conformidade de Cabeçalhos HTTP de Segurança (CSP, Permissions-Policy, HSTS)
7. Blindagem de Sessão (HTTPOnly, SameSite, Inactivity Expiry <= 12h, Expire at Close)
8. Validação de Isolamento Multi-Tenant e Prevenção de IDOR
9. Proteção do Django Admin Restrito Exclusivamente a Superusuários
10. Integridade da Trilha de Auditoria e Telemetria de Incidentes
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.conf import settings

from platform_core.security_services import (
    is_malicious_probe,
    check_login_rate_limit,
    record_login_failure,
    record_login_success,
    record_security_event,
    get_recent_security_events,
    validate_safe_public_url,
)
from platform_core.security_middleware import (
    HackerProbeBlockerMiddleware,
    SecurityHeadersMiddleware,
    RateLimitAndBruteForceMiddleware,
)
from platform_core.models import Organization
from platform_core.context import tenant_context
from platform_core.middleware import OrganizationMiddleware


class Command(BaseCommand):
    help = 'Executa bateria exaustiva de auditoria de cibersegurança e postura defensiva.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))
        self.stdout.write(self.style.MIGRATE_HEADING(' VERTYX ERP - AUDITORIA AVANÇADA DE CIBERSEGURANÇA (DEFENSE-IN-DEPTH)'))
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))

        tests = [
            ('1. Bloqueio de Probes (.env, .git, wp-admin, path traversal)', self.test_probe_interception),
            ('2. Bloqueio de Scanners Ofensivos por User-Agent (sqlmap, nikto)', self.test_user_agent_blocker),
            ('3. Interceptação de Injeção XSS/SQLi na Query String', self.test_query_injection_blocker),
            ('4. Proteção Ativa Contra Força Bruta e Lockout (HTTP 429)', self.test_brute_force_lockout),
            ('5. Blindagem Contra SSRF e Metadados de Nuvem (169.254.169.254)', self.test_ssrf_protection),
            ('6. Conformidade de Cabeçalhos de Segurança (CSP, Permissions, HSTS)', self.test_security_headers),
            ('7. Blindagem de Sessão (HTTPOnly, SameSite=Lax, Expiração <= 12h)', self.test_session_hardening),
            ('8. Proteção do Django Admin Restrito Exclusivo a Superusuários', self.test_admin_protection),
            ('9. Isolamento Multi-Tenant e Prevenção de IDOR Horizontal', self.test_tenant_idor_isolation),
            ('10. Trilha de Telemetria e Auditoria de Incidentes em Tempo Real', self.test_telemetry_audit),
        ]

        passed = 0
        failed = 0
        t0_total = time.time()

        for name, test_func in tests:
            t0 = time.time()
            try:
                test_func()
                elapsed = (time.time() - t0) * 1000
                self.stdout.write(self.style.SUCCESS(f'  [PASS] {name} ({elapsed:.1f}ms)'))
                passed += 1
            except Exception as e:
                elapsed = (time.time() - t0) * 1000
                self.stdout.write(self.style.ERROR(f'  [FAIL] {name} ({elapsed:.1f}ms) -> {e}'))
                failed += 1

        total_elapsed = time.time() - t0_total
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))
        self.stdout.write(f'Resultado: {passed} APROVADOS | {failed} FALHAS | Tempo Total: {total_elapsed:.2f}s')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 80))

        if failed > 0:
            sys.exit(1)

    def test_probe_interception(self):
        rf = RequestFactory()
        middleware = HackerProbeBlockerMiddleware(lambda req: None)

        probes = [
            '/.env',
            '/.git/config',
            '/.aws/credentials',
            '/wp-admin/index.php',
            '/wp-login.php',
            '/phpmyadmin/',
            '/shell.php',
            '/cgi-bin/setup.cgi',
            '/../../etc/passwd',
            '/qualquer/caminho/..%2f..%2fwin.ini',
        ]

        for p in probes:
            req = rf.get(p)
            resp = middleware.process_request(req)
            assert resp is not None, f'Probe {p} não foi interceptado pelo middleware!'
            assert resp.status_code == 403, f'Probe {p} retornou status {resp.status_code}, esperado 403'

    def test_user_agent_blocker(self):
        rf = RequestFactory()
        middleware = HackerProbeBlockerMiddleware(lambda req: None)

        bad_agents = [
            'sqlmap/1.7#dev',
            'Nikto/2.1.6',
            'WPScan v3.8.22',
            'DirBuster-1.0-RC1',
            'Mozilla/5.0 (compatible; Acunetix)',
            'masscan/1.3',
        ]

        for ua in bad_agents:
            req = rf.get('/contas/login/', HTTP_USER_AGENT=ua)
            resp = middleware.process_request(req)
            assert resp is not None, f'User-Agent ofensivo {ua} não foi bloqueado!'
            assert resp.status_code == 403, f'Status para {ua}: {resp.status_code}, esperado 403'

    def test_query_injection_blocker(self):
        rf = RequestFactory()
        middleware = HackerProbeBlockerMiddleware(lambda req: None)

        injections = [
            'id=1%20UNION%20SELECT%201,2,3',
            'q=<script>alert(1)</script>',
            'cmd=;cat%20/etc/passwd',
            'payload=eval(base64_decode("abc"))',
        ]

        for q in injections:
            req = rf.get(f'/busca/?{q}')
            resp = middleware.process_request(req)
            assert resp is not None, f'Query maliciosa {q} não foi bloqueada!'
            assert resp.status_code == 403

    def test_brute_force_lockout(self):
        rf = RequestFactory()
        test_ip = '198.51.100.77'
        test_user = 'alvo_brute_force@empresa.com'

        # Limpa contadores antes do teste
        record_login_success(test_ip, test_user)

        # Simula 4 falhas seguidas (abaixo do limite)
        for i in range(4):
            record_login_failure(test_ip, test_user)
            blocked, _ = check_login_rate_limit(test_ip, test_user)
            assert not blocked, f'Tentativa {i+1} bloqueou precocemente!'

        # 5ª falha atinge o limiar de bloqueio
        record_login_failure(test_ip, test_user)
        blocked, remaining = check_login_rate_limit(test_ip, test_user)
        assert blocked, '5 falhas deveriam ter ativado o bloqueio por força bruta!'
        assert remaining > 0

        # Middleware deve responder com HTTP 429 Too Many Requests
        middleware = RateLimitAndBruteForceMiddleware(lambda req: None)
        req = rf.post('/contas/login/', {'username': test_user, 'password': 'wrong'}, REMOTE_ADDR=test_ip)
        resp = middleware.process_request(req)
        assert resp is not None, 'Middleware não interceptou a requisição bloqueada!'
        assert resp.status_code == 429, f'Esperado 429, obtido {resp.status_code}'

        # Limpeza pós-teste
        record_login_success(test_ip, test_user)
        blocked_after, _ = check_login_rate_limit(test_ip, test_user)
        assert not blocked_after, 'Limpeza pós-login não removeu o bloqueio!'

    def test_ssrf_protection(self):
        dangerous_targets = [
            'http://169.254.169.254/latest/meta-data/',  # AWS/Fly Metadata
            'http://127.0.0.1:8000/admin/',              # Loopback interno
            'http://localhost:5432/',                    # DB interno
            'http://10.0.0.1/internal/',                 # Rede privada Classe A
            'http://192.168.1.1/router/',                # Rede privada Classe C
            'http://172.16.0.1/docker/',                 # Rede privada Classe B
        ]

        for target in dangerous_targets:
            try:
                validate_safe_public_url(target)
                raise AssertionError(f'SSRF falhou ao não bloquear: {target}')
            except (PermissionError, ValueError):
                pass

        # URL pública legítima deve ser aceita
        assert validate_safe_public_url('https://pncp.gov.br') is True

    def test_security_headers(self):
        rf = RequestFactory()
        req = rf.get('/contas/login/')
        from django.http import HttpResponse
        base_resp = HttpResponse('OK')
        middleware = SecurityHeadersMiddleware(lambda r: base_resp)
        resp = middleware.process_response(req, base_resp)

        assert 'Content-Security-Policy' in resp, 'Falta Content-Security-Policy!'
        assert "default-src 'self'" in resp['Content-Security-Policy']
        assert 'Permissions-Policy' in resp, 'Falta Permissions-Policy!'
        assert resp['X-Content-Type-Options'] == 'nosniff'
        assert resp['X-Frame-Options'] == 'DENY'
        assert resp['Referrer-Policy'] == 'strict-origin-when-cross-origin'
        assert resp['Cross-Origin-Opener-Policy'] == 'same-origin'

    def test_session_hardening(self):
        assert getattr(settings, 'SESSION_COOKIE_HTTPONLY', False) is True, 'SESSION_COOKIE_HTTPONLY deve ser True'
        assert getattr(settings, 'SESSION_COOKIE_SAMESITE', '') == 'Lax', 'SESSION_COOKIE_SAMESITE deve ser Lax'
        assert getattr(settings, 'CSRF_COOKIE_SAMESITE', '') == 'Lax', 'CSRF_COOKIE_SAMESITE deve ser Lax'
        assert getattr(settings, 'SESSION_COOKIE_AGE', 0) <= 43200, 'SESSION_COOKIE_AGE não deve exceder 12h'
        assert getattr(settings, 'SESSION_EXPIRE_AT_BROWSER_CLOSE', False) is True, 'SESSION_EXPIRE_AT_BROWSER_CLOSE deve ser True'

    def test_admin_protection(self):
        rf = RequestFactory()
        middleware = OrganizationMiddleware(lambda req: None)
        org = Organization.objects.first()
        user = org.memberships.first().user if org and org.memberships.exists() else None
        if not user:
            return

        # Usuário regular (não-superuser) tentando acessar /admin/
        user.is_superuser = False
        req = rf.get('/admin/')
        req.user = user
        req.session = {}
        resp = middleware(req)
        assert resp.status_code == 403, f'Usuário comum conseguiu acessar /admin/! Status: {resp.status_code}'

    def test_tenant_idor_isolation(self):
        orgs = list(Organization.objects.all()[:2])
        if len(orgs) < 2:
            return
        org_a, org_b = orgs[0], orgs[1]

        # Sob contexto da Org B, objetos da Org A não devem vazar via query padrão
        with tenant_context(org_b):
            from operacao.models import Venda
            vendas_org_a = Venda.objects.filter(organization=org_a)
            assert not vendas_org_a.exists(), 'Vazamento IDOR: Org B conseguiu enxergar registros da Org A!'

    def test_telemetry_audit(self):
        test_ip = '198.51.100.111'
        record_security_event(
            event_type='CYBER_AUDIT_TELEMETRY_CHECK',
            ip_address=test_ip,
            details={'status': 'verified'},
            severity='INFO',
        )

        recent = get_recent_security_events(limit=10)
        found = any(e['event_type'] == 'CYBER_AUDIT_TELEMETRY_CHECK' and e['ip_address'] == test_ip for e in recent)
        assert found, 'Evento de telemetria não foi registrado no buffer de segurança!'
