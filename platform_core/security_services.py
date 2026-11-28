"""Módulo Central de Serviços de Cibersegurança e Defesa em Profundidade do VERTYX ERP.

Implementa proteções contra OWASP Top 10 2025:
1. Interceptação de Scanners, Bots e Probes Maliciosos (Recon / Path Traversal / LFI)
2. Defesa Ativa contra Ataques de Força Bruta e Credential Stuffing (Rate Limit / Lockout)
3. Proteção contra Server-Side Request Forgery (SSRF)
4. Trilha de Auditoria e Telemetria de Eventos de Segurança
"""
from __future__ import annotations

import logging
import re
import socket
import urllib.parse
import ipaddress
from typing import Any

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('security')

# Padrões conhecidos de ferramentas ofensivas e scanners automatizados
MALICIOUS_USER_AGENTS = re.compile(
    r'(sqlmap|nikto|wpscan|dirbuster|acunetix|masscan|zgrab|nmap|havij|netsparker|openvas|nessus|gobuster|ffuf)',
    re.IGNORECASE
)

# Caminhos e assinaturas típicas de varreduras automatizadas e exploits
MALICIOUS_PATH_PATTERNS = [
    re.compile(r'/\.env', re.IGNORECASE),
    re.compile(r'/\.git', re.IGNORECASE),
    re.compile(r'/\.aws', re.IGNORECASE),
    re.compile(r'/\.ssh', re.IGNORECASE),
    re.compile(r'/wp-admin|/wp-login|/xmlrpc\.php', re.IGNORECASE),
    re.compile(r'/phpmyadmin|/pma|/adminer', re.IGNORECASE),
    re.compile(r'/actuator|/api-docs|/swagger', re.IGNORECASE),
    re.compile(r'/cgi-bin|/setup\.cgi', re.IGNORECASE),
    re.compile(r'\.(php|asp|aspx|jsp|cgi|sh|bash|exe|bat)$', re.IGNORECASE),
    re.compile(r'(\.\./|\.\.\\|%2e%2e|%00)', re.IGNORECASE),  # Path Traversal / Null Byte
    re.compile(r'(etc/passwd|win\.ini|boot\.ini)', re.IGNORECASE),
]

# Assinaturas de injeção em Query String
MALICIOUS_QUERY_PATTERNS = [
    re.compile(r'(<script|javascript:|data:text/html)', re.IGNORECASE),
    re.compile(r'(\bUNION\b.+\bSELECT\b|\bSELECT\b.+\bFROM\b.+\bWHERE\b|\bDROP\b.+\bTABLE\b)', re.IGNORECASE),
    re.compile(r'(\bexec\b|\bsystem\b|\bpassthru\b|\beval\b)\s*\(', re.IGNORECASE),
    re.compile(r'(;|\s+)(cat|id|whoami|uname|curl|wget)\s+', re.IGNORECASE),
]

# Configurações de Força Bruta
BRUTE_FORCE_MAX_ATTEMPTS = 5
BRUTE_FORCE_WINDOW_SECONDS = 300  # 5 minutos
BRUTE_FORCE_LOCKOUT_SECONDS = 300  # 5 minutos


def get_client_ip(request) -> str:
    """Extrai o endereço IP real do cliente com tratamento seguro de proxies reversos."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Pega o primeiro IP da cadeia (cliente original)
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1').strip()
    return ip


def is_malicious_probe(path: str, query_string: str = '', user_agent: str = '') -> tuple[bool, str]:
    """Detecta se uma requisição possui assinatura de scanner ou ataque exploratório."""
    # 1. User-Agent Malicioso
    if user_agent and MALICIOUS_USER_AGENTS.search(user_agent):
        return True, f'Scanner ofensivo detectado no User-Agent: {user_agent[:60]}'

    # 2. Caminhos suspeitos de varredura
    for pattern in MALICIOUS_PATH_PATTERNS:
        if pattern.search(path):
            return True, f'Tentativa de acesso a caminho protegido/inexistente: {path[:80]}'

    # 3. Injeções na Query String
    if query_string:
        decoded_qs = urllib.parse.unquote(query_string)
        for pattern in MALICIOUS_QUERY_PATTERNS:
            if pattern.search(decoded_qs):
                return True, 'Assinatura de injeção maliciosa (XSS/SQLi/RCE) na Query String'

    return False, ''


def _cache_key_ip(ip: str) -> str:
    return f'sec:bf:ip:{ip}'


def _cache_key_user(username: str) -> str:
    import hashlib
    h = hashlib.sha256(username.strip().lower().encode('utf-8')).hexdigest()[:16]
    return f'sec:bf:usr:{h}'


def check_login_rate_limit(ip: str, username: str | None = None) -> tuple[bool, int]:
    """Verifica se o IP ou usuário atingiu o limite de tentativas de login incorretas.
    
    Retorna (is_blocked: bool, remaining_seconds: int).
    """
    ip_attempts = cache.get(_cache_key_ip(ip), 0)
    if ip_attempts >= BRUTE_FORCE_MAX_ATTEMPTS:
        return True, BRUTE_FORCE_LOCKOUT_SECONDS

    if username:
        user_attempts = cache.get(_cache_key_user(username), 0)
        if user_attempts >= BRUTE_FORCE_MAX_ATTEMPTS:
            return True, BRUTE_FORCE_LOCKOUT_SECONDS

    return False, 0


def record_login_failure(ip: str, username: str | None = None) -> int:
    """Registra uma falha de autenticação e incrementa os contadores."""
    key_ip = _cache_key_ip(ip)
    current_ip = cache.get(key_ip, 0) + 1
    cache.set(key_ip, current_ip, timeout=BRUTE_FORCE_WINDOW_SECONDS)

    if username:
        key_user = _cache_key_user(username)
        current_user = cache.get(key_user, 0) + 1
        cache.set(key_user, current_user, timeout=BRUTE_FORCE_WINDOW_SECONDS)

    if current_ip >= BRUTE_FORCE_MAX_ATTEMPTS:
        record_security_event(
            event_type='BRUTE_FORCE_BLOCKED',
            ip_address=ip,
            username=username,
            details={'attempts': current_ip, 'blocked_window': BRUTE_FORCE_LOCKOUT_SECONDS},
            severity='CRITICAL',
        )

    return current_ip


def record_login_success(ip: str, username: str | None = None) -> None:
    """Limpa contadores de falha após autenticação bem-sucedida."""
    cache.delete(_cache_key_ip(ip))
    if username:
        cache.delete(_cache_key_user(username))


def record_security_event(
    event_type: str,
    request=None,
    ip_address: str | None = None,
    username: str | None = None,
    path: str | None = None,
    details: dict[str, Any] | None = None,
    severity: str = 'WARNING',
) -> None:
    """Registra um evento de telemetria de segurança nos logs e no buffer em memória."""
    ip = ip_address or (get_client_ip(request) if request else '0.0.0.0')
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:200] if request else ''
    req_path = path or (request.path if request else '')

    payload = {
        'timestamp': timezone.now().isoformat(),
        'event_type': event_type,
        'severity': severity,
        'ip_address': ip,
        'username': username or (str(request.user) if request and hasattr(request, 'user') and request.user.is_authenticated else None),
        'path': req_path,
        'user_agent': user_agent,
        'details': details or {},
    }

    # Log estruturado
    log_msg = f"[CYBERSECURITY] [{severity}] {event_type} | IP: {ip} | Path: {req_path} | User: {payload['username']}"
    if severity == 'CRITICAL':
        logger.critical(log_msg, extra=payload)
    elif severity == 'WARNING':
        logger.warning(log_msg, extra=payload)
    else:
        logger.info(log_msg, extra=payload)

    # Manter buffer dos últimos 200 eventos no cache para auditoria em tempo real
    event_buffer = cache.get('sec:event_buffer', [])
    event_buffer.append(payload)
    if len(event_buffer) > 200:
        event_buffer = event_buffer[-200:]
    cache.set('sec:event_buffer', event_buffer, timeout=86400 * 7)


def get_recent_security_events(limit: int = 50) -> list[dict[str, Any]]:
    """Recupera os eventos de segurança mais recentes registrados no sistema."""
    buffer = cache.get('sec:event_buffer', [])
    return list(reversed(buffer))[:limit]


def validate_safe_public_url(url: str) -> bool:
    """Proteção contra SSRF (Server-Side Request Forgery).
    
    Verifica se uma URL aponta estritamente para a Internet pública e nunca para
    redes locais, loopback ou endpoints de metadados da nuvem (ex: 169.254.169.254).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f'Esquema inválido: {parsed.scheme}. Apenas http e https são permitidos.')

    hostname = parsed.hostname
    if not hostname:
        raise ValueError('Hostname não especificado.')

    # Bloquear nomes locais óbvios
    if hostname.lower() in ('localhost', 'metadata.google.internal', 'instance-data'):
        raise PermissionError('Acesso bloqueado: Hostname local ou de metadados.')

    try:
        # Resolve todos os endereços IP vinculados ao hostname
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f'Não foi possível resolver o hostname {hostname}: {e}')

    for family, socktype, proto, canonname, sockaddr in addr_info:
        raw_ip = sockaddr[0]
        ip = ipaddress.ip_address(raw_ip)

        # Regras estritas de validação: nenhum IP privado, loopback ou reservado
        if ip.is_private:
            raise PermissionError(f'SSRF Bloqueado: O host resolve para rede privada ({raw_ip}).')
        if ip.is_loopback:
            raise PermissionError(f'SSRF Bloqueado: O host resolve para endereço de loopback ({raw_ip}).')
        if ip.is_link_local:
            raise PermissionError(f'SSRF Bloqueado: O host resolve para endereço link-local ({raw_ip}).')
        if ip.is_multicast:
            raise PermissionError(f'SSRF Bloqueado: O host resolve para endereço multicast ({raw_ip}).')
        if ip.is_reserved:
            raise PermissionError(f'SSRF Bloqueado: O host resolve para endereço reservado ({raw_ip}).')

        # Bloqueio explícito do endereço de metadados da AWS/Fly/Cloud (169.254.169.254)
        if raw_ip == '169.254.169.254':
            raise PermissionError('SSRF Bloqueado: Tentativa de consulta a metadados de nuvem (169.254.169.254).')

    return True
