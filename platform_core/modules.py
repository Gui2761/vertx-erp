"""One module/capability policy for routes and services; legacy defaults preserved."""
from django.core.exceptions import PermissionDenied
from .access import membership_for, has_erp_access
from .context import current_organization
from .models import ModuloOrganizacao, PermissaoMembership

CAPABILITIES = {
    'estoque': ('estoque', ('ADMIN', 'GESTOR', 'ESTOQUE', 'TECNICO')),
    'estoque_escrever': ('estoque', ('ADMIN', 'GESTOR', 'ESTOQUE')),
    'inventario_aprovar': ('estoque', ('ADMIN', 'GESTOR')),
    'compras': ('compras', ('ADMIN', 'GESTOR', 'ESTOQUE', 'COMPRAS')),
    'pdv': ('pdv', ('ADMIN', 'GESTOR', 'PDV', 'VENDEDOR')),
    'pdv_cliente_cadastrar': ('pdv', ('ADMIN', 'GESTOR', 'PDV', 'VENDEDOR')),
    'desconto_supervisor': ('pdv', ('ADMIN', 'GESTOR')),
    'devolucao': ('pdv', ('ADMIN', 'GESTOR')),
    'caixa_supervisor': ('pdv', ('ADMIN', 'GESTOR', 'FINANCEIRO')),
    'rh': ('rh', ('ADMIN', 'GESTOR', 'RH')),
    'ponto': ('ponto', ('ADMIN', 'GESTOR', 'TECNICO', 'ESTOQUE', 'PDV', 'VENDEDOR', 'COMPRAS', 'FINANCEIRO', 'RH', 'PLANEJADOR', 'ATENDIMENTO', 'CONTABILIDADE')),
    'ajuste_ponto': ('ponto', ('ADMIN', 'GESTOR', 'RH')),
    'config_empresa': ('', ('ADMIN',)),
    'executivo': ('', ('ADMIN','GESTOR')),
    'credito_cliente': ('', ('ADMIN','GESTOR')),
    'financeiro': ('financeiro', ('ADMIN', 'GESTOR', 'FINANCEIRO', 'CONTABILIDADE')),
    'financeiro_escrever': ('financeiro', ('ADMIN', 'GESTOR', 'FINANCEIRO')),
    'contratos': ('contratos', ('ADMIN', 'GESTOR')),
    'orcamentos': ('pdv', ('ADMIN', 'GESTOR')),
    'planejamento': ('assistencia', ('ADMIN', 'GESTOR', 'TECNICO', 'PLANEJADOR', 'ATENDIMENTO')),
    'operacional': ('assistencia', ('ADMIN', 'GESTOR', 'TECNICO')),
    'gestao': ('assistencia', ('ADMIN', 'GESTOR')),
    'portal': ('portal', ('CLIENTE',)),
    'relatorios': ('', ('ADMIN', 'GESTOR', 'TECNICO', 'ESTOQUE', 'FINANCEIRO', 'CONTABILIDADE')),
}

def module_enabled(code):
    if not code:
        return True
    if current_organization() is None:
        return False
    # No flag means legacy access, not an invented commercial subscription.
    return not ModuloOrganizacao.objects.filter(codigo=code, habilitado=False).exists()

def has_capability(user, code, roles=None):
    membership = membership_for(user)
    if membership is None or not has_erp_access(user):
        return False
    if membership.role in {'VENDEDOR','PDV'} and code in {
        'estoque','estoque_escrever','inventario_aprovar','compras','desconto_supervisor',
        'devolucao','caixa_supervisor','rh','ajuste_ponto','config_empresa','executivo',
        'credito_cliente','financeiro','financeiro_escrever','contratos','orcamentos',
        'planejamento','operacional','gestao','relatorios',
    }:
        return False
    if membership.role == 'TECNICO' and code in {
        'estoque_escrever','inventario_aprovar','compras','pdv','desconto_supervisor',
        'devolucao','caixa_supervisor','rh','ajuste_ponto','config_empresa','executivo',
        'credito_cliente','financeiro','financeiro_escrever','contratos','orcamentos','gestao',
    }:
        return False
    module, defaults = CAPABILITIES.get(code, ('', roles or ()))
    if not module_enabled(module):
        return False
    override = PermissaoMembership.objects.filter(membership=membership, capacidade=code).first()
    return override.permitido if override else membership.role in (defaults if code in CAPABILITIES else roles or ())

def require_capability(user, code, roles=None):
    if not has_capability(user, code, roles):
        raise PermissionDenied('Módulo ou capacidade não autorizada nesta organização.')
    return membership_for(user)

def module_for_path(path):
    if path.startswith('/vendedor/'):
        return 'pdv'
    mapping = [('/estoque/fornecedores/', 'compras'), ('/configuracoes/estoque', 'estoque'), ('/pdv/', 'pdv'), ('/vendas/', 'pdv'), ('/estoque/', 'estoque'), ('/depositos/', 'estoque'), ('/inventarios/', 'estoque'), ('/transferencias/', 'estoque'), ('/compras/', 'compras'), ('/financeiro/', 'financeiro'), ('/bancos/', 'financeiro'), ('/ponto/', 'ponto'), ('/rh/', 'rh'), ('/portal/', 'portal'), ('/contratos/', 'contratos'), ('/fiscal/', 'fiscal'), ('/documentos/', 'documentos'), ('/ordens/', 'assistencia'), ('/chamados/', 'assistencia'), ('/preventivas/', 'assistencia'), ('/planejamento/', 'assistencia'), ('/tecnico/', 'assistencia'), ('/equipamentos/', 'assistencia'), ('/painel-operacional/', 'assistencia')]
    return next((code for prefix,code in mapping if path.startswith(prefix)), '')
