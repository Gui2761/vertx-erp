"""One module/capability policy for routes and services; legacy defaults preserved."""
from django.core.exceptions import PermissionDenied
from .access import membership_for, has_erp_access
from .context import current_organization
from .models import ModuloOrganizacao, PermissaoMembership

CAPABILITIES = {
    'migracao': ('', ('ADMIN', 'GESTOR')),
    'fiscal_consultar': ('fiscal', ('ADMIN', 'GESTOR', 'FINANCEIRO', 'CONTABILIDADE')),
    'fiscal_emitir': ('fiscal', ('ADMIN', 'GESTOR', 'FINANCEIRO')),
    'fiscal_cancelar': ('fiscal', ('ADMIN', 'GESTOR', 'FINANCEIRO')),
    'fiscal_configurar': ('fiscal', ('ADMIN', 'GESTOR')),
    'fiscal_gerenciar_credenciais': ('fiscal', ('ADMIN',)),
    'estoque': ('estoque', ('ADMIN', 'GESTOR', 'ESTOQUE', 'TECNICO')),
    'estoque_escrever': ('estoque', ('ADMIN', 'GESTOR', 'ESTOQUE')),
    'inventario_aprovar': ('estoque', ('ADMIN', 'GESTOR')),
    'compras': ('compras', ('ADMIN', 'GESTOR', 'ESTOQUE', 'COMPRAS')),
    'pdv': ('pdv', ('ADMIN', 'GESTOR', 'PDV')),
    'operar_pdv': ('pdv', ('ADMIN', 'GESTOR', 'PDV')),
    'central_vendedor': ('', ('ADMIN', 'GESTOR', 'PDV', 'VENDEDOR')),
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
    if code.startswith('fiscal_') and membership.role not in {'ADMIN', 'GESTOR', 'FINANCEIRO', 'CONTABILIDADE'}:
        return False
    if code=='pdv':
        return has_capability(user,'operar_pdv')
    if code=='pdv_cliente_cadastrar' and not has_capability(user,'operar_pdv'):
        return False
    if code=='operar_pdv':
        if membership.role not in {'ADMIN','GESTOR','PDV','VENDEDOR'} or not module_enabled('pdv'):
            return False
        override=PermissaoMembership.objects.filter(membership=membership,capacidade='operar_pdv').first()
        if override:
            return override.permitido
        # Preserve explicit legacy restrictions for existing cash operators.
        # A seller requires the NEW explicit grant; legacy pdv never grants it.
        if membership.role=='VENDEDOR':
            return False
        legacy=PermissaoMembership.objects.filter(membership=membership,capacidade='pdv').first()
        return legacy.permitido if legacy else membership.role in CAPABILITIES['operar_pdv'][1]
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
    if path.startswith('/gestao-publica/'):
        return ''  # The ERP catalog and Municipal RH grants are the authority.
    if path.startswith('/vendedor/'):
        return ''
    mapping = [('/estoque/fornecedores/', 'compras'), ('/configuracoes/estoque', 'estoque'), ('/pdv/', 'pdv'), ('/vendas/', 'pdv'), ('/estoque/', 'estoque'), ('/depositos/', 'estoque'), ('/inventarios/', 'estoque'), ('/transferencias/', 'estoque'), ('/compras/', 'compras'), ('/financeiro/', 'financeiro'), ('/bancos/', 'financeiro'), ('/ponto/', 'ponto'), ('/rh/', 'rh'), ('/portal/', 'portal'), ('/contratos/', 'contratos'), ('/fiscal/', 'fiscal'), ('/documentos/', 'documentos'), ('/ordens/', 'assistencia'), ('/chamados/', 'assistencia'), ('/preventivas/', 'assistencia'), ('/planejamento/', 'assistencia'), ('/tecnico/', 'assistencia'), ('/equipamentos/', 'assistencia'), ('/painel-operacional/', 'assistencia')]
    return next((code for prefix,code in mapping if path.startswith(prefix)), '')
