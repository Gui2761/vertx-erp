from platform_core.access import require_erp, effective_role
from gestao.permissions import allowed
from . import models as m

ROLES = {
    'operacional': ('ADMIN', 'GESTOR', 'TECNICO'),
    'gestao': ('ADMIN', 'GESTOR'),
    'compras': ('ADMIN', 'GESTOR', 'ESTOQUE'),
    'financeiro': ('ADMIN', 'GESTOR', 'FINANCEIRO', 'CONTABILIDADE'),
    'financeiro_escrever': ('ADMIN', 'GESTOR', 'FINANCEIRO'),
    'portal': ('CLIENTE',),
}

def require(user, capability):
    return require_erp(user, roles=ROLES[capability])

def portal_clients(user):
    require(user, 'portal')
    return m.PortalCliente.objects.filter(usuario=user, ativo=True).values_list('cliente_id', flat=True)

def document_allowed(user, document, writing=False):
    role = effective_role(user)
    if role in ['ADMIN', 'GESTOR']:
        return True
    if role == 'CLIENTE':
        return not writing and document.disponivel_portal and document.cliente_id in portal_clients(user)
    if document.fiscal_id:
        return allowed(user, 'financeiro_escrever' if writing else 'financeiro')
    if role == 'TECNICO' and not any([document.contrato_id, document.orcamento_id]):
        return not document.ordem_id or bool(document.ordem.tecnico_id and document.ordem.tecnico.usuario_id == user.pk)
    return False

def documents(user):
    from django.db.models import Q
    role = effective_role(user)
    qs = m.Documento.objects.select_related('ordem__tecnico', 'cliente')
    if role in ['ADMIN', 'GESTOR']:
        return qs
    if role == 'CLIENTE':
        return qs.filter(disponivel_portal=True, cliente_id__in=portal_clients(user))
    if role == 'TECNICO':
        return qs.filter(fiscal__isnull=True, contrato__isnull=True, orcamento__isnull=True).filter(Q(ordem__isnull=True) | Q(ordem__tecnico__usuario=user))
    if role in ['FINANCEIRO', 'CONTABILIDADE']:
        return qs.filter(fiscal__isnull=False)
    return qs.none()
