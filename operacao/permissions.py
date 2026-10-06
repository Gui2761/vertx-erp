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
    from platform_core.modules import require_capability
    return require_capability(user, capability, ROLES[capability])

def portal_clients(user):
    require(user, 'portal')
    return m.PortalCliente.objects.filter(usuario=user, ativo=True).values_list('cliente_id', flat=True)

def document_allowed(user, document, writing=False):
    from platform_core.context import current_organization
    from platform_core.access import has_erp_access
    org = current_organization()
    if not org or document.organization_id != org.pk or not has_erp_access(user):
        return False
    role = effective_role(user)
    from platform_core.modules import module_enabled, has_capability
    if not module_enabled('documentos'):
        return False
    if role in ['ADMIN', 'GESTOR']:
        return True
    if document.funcionario_id:
        return has_capability(user,'rh')
    if role in ['PDV','VENDEDOR']:
        return has_capability(user,'pdv') and bool(document.venda_id) and (document.venda.criado_por_id==user.pk or document.venda.vendedor_id==user.pk) and not any([document.fiscal_id,document.compra_id,document.contrato_id,document.orcamento_id,document.fornecedor_id])
    if document.compra_id and role in ['ESTOQUE','COMPRAS']:
        return has_capability(user,'compras') and not any([document.fiscal_id,document.cliente_id,document.ordem_id,document.contrato_id,document.orcamento_id,document.venda_id])
    if role == 'CLIENTE':
        return not writing and document.disponivel_portal and document.cliente_id in portal_clients(user)
    if document.fiscal_id:
        return allowed(user, 'financeiro_escrever' if writing else 'financeiro')
    if role == 'TECNICO' and not any([document.contrato_id, document.orcamento_id, document.fornecedor_id,document.compra_id,document.venda_id]):
        from ordens.services import visiveis
        from .technician_access import scoped_records
        for field in ['cliente', 'unidade', 'equipamento']:
            record = getattr(document, field)
            if record and not scoped_records(user, type(record).objects.filter(pk=record.pk), field).exists():
                return False
        if document.tecnico_id and document.tecnico.usuario_id != user.pk:
            return False
        if document.chamado_id and not (document.chamado.tecnico_id and document.chamado.tecnico.usuario_id == user.pk or document.chamado.ordem_id and visiveis(user).filter(pk=document.chamado.ordem_id).exists()):
            return False
        return not document.ordem_id or visiveis(user).filter(pk=document.ordem_id).exists()
    if role == 'ESTOQUE':
        return bool(document.fornecedor_id or document.peca_id) and not any([document.cliente_id, document.unidade_id, document.equipamento_id, document.tecnico_id, document.chamado_id, document.ordem_id, document.contrato_id, document.orcamento_id,document.venda_id])
    return False

def documents(user):
    from django.db.models import Q
    role = effective_role(user)
    qs = m.Documento.objects.select_related('ordem__tecnico', 'cliente')
    from platform_core.modules import module_enabled, has_capability
    if not module_enabled('documentos'): return qs.none()
    if role in ['ADMIN', 'GESTOR']:
        return qs
    if role=='RH' and has_capability(user,'rh'): return qs.filter(funcionario__isnull=False)
    qs=qs.filter(funcionario__isnull=True)
    if role in ['PDV','VENDEDOR']:
        return qs.filter(venda__isnull=False,fiscal__isnull=True,compra__isnull=True,contrato__isnull=True,orcamento__isnull=True,fornecedor__isnull=True).filter(Q(venda__criado_por=user)|Q(venda__vendedor=user)) if has_capability(user,'pdv') else qs.none()
    if role=='COMPRAS': return qs.filter(compra__isnull=False,fiscal__isnull=True,cliente__isnull=True,ordem__isnull=True,contrato__isnull=True,orcamento__isnull=True,venda__isnull=True) if has_capability(user,'compras') else qs.none()
    if role == 'CLIENTE':
        return qs.filter(disponivel_portal=True, cliente_id__in=portal_clients(user))
    if role == 'TECNICO':
        from ordens.services import visiveis
        from .technician_access import scoped_records
        from clientes.models import Cliente, Unidade
        from equipamentos.models import Equipamento
        for field, model in [('cliente',Cliente),('unidade',Unidade),('equipamento',Equipamento)]:
            qs=qs.filter(Q(**{field+'__isnull':True}) | Q(**{field+'__in':scoped_records(user,model.objects.all(),field)}))
        return qs.filter(fiscal__isnull=True, contrato__isnull=True, orcamento__isnull=True, fornecedor__isnull=True,compra__isnull=True,venda__isnull=True).filter(Q(tecnico__isnull=True) | Q(tecnico__usuario=user)).filter(Q(ordem__isnull=True) | Q(ordem__in=visiveis(user))).filter(Q(chamado__isnull=True) | Q(chamado__tecnico__usuario=user) | Q(chamado__ordem__in=visiveis(user)))
    if role == 'ESTOQUE':
        return qs.filter(fiscal__isnull=True, cliente__isnull=True, unidade__isnull=True, equipamento__isnull=True, tecnico__isnull=True, chamado__isnull=True, ordem__isnull=True, contrato__isnull=True, orcamento__isnull=True,venda__isnull=True).filter(Q(fornecedor__isnull=False)|Q(peca__isnull=False)|Q(compra__isnull=False))
    if role in ['FINANCEIRO', 'CONTABILIDADE']:
        return qs.filter(fiscal__isnull=False)
    return qs.none()
