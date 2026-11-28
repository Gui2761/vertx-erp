"""Middlewares de Defesa Cibernética do VERTYX ERP.

Inclui:
1. HackerProbeBlockerMiddleware: Bloqueio ativo de scanners, bots e tentativas de invasão (OWASP A01, A05).
2. SecurityHeadersMiddleware: Injeção de cabeçalhos de segurança avançados (CSP, Permissions-Policy, HSTS, COOP).
3. RateLimitAndBruteForceMiddleware: Proteção ativa contra força bruta e credential stuffing (OWASP A07).
"""
from __future__ import annotations

from django.http import HttpResponse, HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin
from .security_services import (
    get_client_ip,
    is_malicious_probe,
    check_login_rate_limit,
    record_security_event,
)

AUTH_PATH_PREFIXES = (
    '/contas/login/',
    '/pdv/entrar/',
    '/vendedor/entrar/',
    '/primeiro-acesso/',
)


class HackerProbeBlockerMiddleware(MiddlewareMixin):
    """Camada 0 de Proteção: Intercepta e neutraliza varreduras automatizadas e scanners ofensivos."""

    def process_request(self, request):
        path = request.path
        query_string = request.META.get('QUERY_STRING', '')
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        is_probe, reason = is_malicious_probe(path, query_string, user_agent)
        if is_probe:
            ip = get_client_ip(request)
            record_security_event(
                event_type='SCANNER_PROBE_BLOCKED',
                request=request,
                ip_address=ip,
                path=path,
                details={'reason': reason, 'user_agent': user_agent[:150]},
                severity='WARNING',
            )
            # Retorna 403 Forbidden estrito sem tocar nas rotas ou banco
            html = (
                '<!DOCTYPE html><html lang="pt-br"><head><title>403 Acesso Negado</title>'
                '<meta charset="utf-8"></head><body style="font-family:sans-serif;text-align:center;padding:50px;'
                'background:#0b111d;color:#f8fafc;"><h1>403 Forbidden</h1>'
                '<p>Requisição bloqueada pelo sistema de proteção cibernética do VERTYX ERP.</p>'
                '</body></html>'
            )
            return HttpResponseForbidden(html, content_type='text/html; charset=utf-8')

        return None


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Injeta cabeçalhos HTTP de segurança estritos para proteção dos navegadores dos clientes."""

    CSP_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https: blob:; "
        "font-src 'self' data: https://cdn.jsdelivr.net; "
        "connect-src 'self' https:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    def process_response(self, request, response):
        # 1. Content-Security-Policy (CSP)
        if 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = self.CSP_POLICY

        # 2. Permissions-Policy (restringe APIs sensíveis do navegador)
        # Permite 'camera' na mesma origem para leitores de código de barras do PDV / Ordens
        if 'Permissions-Policy' not in response:
            response['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=(), payment=()'

        # 3. Prevenção de MIME-Sniffing
        response['X-Content-Type-Options'] = 'nosniff'

        # 4. Anti-Clickjacking
        response['X-Frame-Options'] = 'DENY'

        # 5. Referrer Policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # 6. Cross-Origin Opener Policy
        response['Cross-Origin-Opener-Policy'] = 'same-origin'

        # 7. X-XSS-Protection (modo estrito para navegadores legados)
        response['X-XSS-Protection'] = '1; mode=block'

        return response


class RateLimitAndBruteForceMiddleware(MiddlewareMixin):
    """Proteção ativa contra ataques de dicionário, força bruta e credential stuffing."""

    def process_request(self, request):
        if request.method == 'POST' and any(request.path.startswith(prefix) for prefix in AUTH_PATH_PREFIXES):
            ip = get_client_ip(request)
            username = request.POST.get('username', '').strip() or None

            is_blocked, remaining = check_login_rate_limit(ip, username)
            if is_blocked:
                record_security_event(
                    event_type='BRUTE_FORCE_INTERCEPTED',
                    request=request,
                    ip_address=ip,
                    username=username,
                    details={'retry_after': remaining},
                    severity='CRITICAL',
                )
                msg = (
                    f'Muitas tentativas de autenticação inválidas consecutivas. '
                    f'Por segurança cibernética, o acesso deste IP foi temporariamente restringido por {remaining // 60} minutos. '
                    f'Tente novamente mais tarde.'
                )
                resp = HttpResponse(msg, status=429, content_type='text/plain; charset=utf-8')
                resp['Retry-After'] = str(remaining)
                return resp

        return None
