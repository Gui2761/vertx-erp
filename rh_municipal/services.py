from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
import uuid

from platform_core.access import has_erp_access, membership_for
from platform_core.context import current_organization
from platform_core.models import ERPCatalog, PlatformAudit

from .models import (
    AcessoRH, DecisaoSolicitacaoServidor, HistoricoServidor,
    PontoServidor, PRODUCT_CODE, Servidor, SolicitacaoServidor,
)


MANAGE_ROLES = {AcessoRH.Papel.ADMIN_MUNICIPAL, AcessoRH.Papel.GESTOR_RH, AcessoRH.Papel.RH_OPERADOR}
ADMIN_ROLES = {AcessoRH.Papel.ADMIN_MUNICIPAL}


def roles_for(user):
    membership = membership_for(user)
    if not membership or not has_erp_access(user, membership.organization, code=PRODUCT_CODE):
        return set()
    return set(AcessoRH.objects.filter(membership=membership, ativo=True).values_list('papel', flat=True))


def require_roles(user, allowed):
    membership = membership_for(user)
    if not membership or not has_erp_access(user, membership.organization, code=PRODUCT_CODE):
        raise PermissionDenied('Acesso ao ERP Gestão Pública não autorizado nesta organização.')
    roles = roles_for(user)
    if not roles.intersection(allowed):
        raise PermissionDenied('Permissão municipal insuficiente.')
    return membership, roles


def audit(user, action, record, changes):
    organization = current_organization()
    erp = ERPCatalog.objects.filter(code=PRODUCT_CODE).first()
    if organization is None or erp is None:
        raise ValidationError('Contexto municipal incompleto para auditoria.')
    PlatformAudit.objects.create(
        organization=organization, erp=erp, user=user,
        action=action, record=f'{record._meta.label}:{record.pk}', changes=changes,
    )


@transaction.atomic
def grant_access(actor, membership, papel):
    _, roles = require_roles(actor, ADMIN_ROLES)
    if not roles:
        raise PermissionDenied('Somente o administrador municipal pode atribuir papéis.')
    if membership.organization_id != current_organization().pk:
        raise ValidationError('Membership pertence a outra organização.')
    row = AcessoRH(membership=membership, papel=papel, atribuido_por=actor)
    row.save()
    audit(actor, 'RH_MUNICIPAL_ACESSO_ATRIBUIDO', row, {'papel': papel, 'membership': membership.pk})
    return row


@transaction.atomic
def create_server(actor, form):
    require_roles(actor, MANAGE_ROLES)
    server = form.save(commit=False)
    server.save()
    history = HistoricoServidor(
        servidor=server, acao='CADASTRO', depois={'matricula': server.matricula, 'nome': server.nome},
        usuario=actor,
    )
    history._service_write = True
    history.save()
    audit(actor, 'RH_MUNICIPAL_SERVIDOR_CRIADO', server, {'matricula': server.matricula})
    return server


@transaction.atomic
def create_request(user, tipo, descricao, dados=None, request_id=None):
    require_roles(user, {AcessoRH.Papel.SERVIDOR})
    valid_types = {choice for choice, _ in SolicitacaoServidor._meta.get_field('tipo').choices}
    if tipo not in valid_types or not descricao.strip():
        raise ValidationError('Tipo e descrição da solicitação são obrigatórios.')
    server = Servidor.objects.select_for_update().get(usuario=user)
    key = uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
    existing = SolicitacaoServidor.objects.filter(request_id=key).first()
    if existing:
        if existing.servidor_id != server.pk:
            raise ValidationError('Identificador de solicitação já usado por outro servidor.')
        return existing
    row = SolicitacaoServidor(servidor=server, request_id=key, tipo=tipo, descricao=descricao.strip(), dados=dados or {})
    row._service_write = True
    row.save()
    audit(user, 'RH_MUNICIPAL_SOLICITACAO_CRIADA', row, {'tipo': tipo})
    return row


@transaction.atomic
def mark_point(user, tipo, request_id):
    require_roles(user, {AcessoRH.Papel.SERVIDOR})
    valid_types = {choice for choice, _ in PontoServidor._meta.get_field('tipo').choices}
    if tipo not in valid_types:
        raise ValidationError('Tipo de marcação municipal inválido.')
    server = Servidor.objects.select_for_update().get(usuario=user)
    key = uuid.UUID(str(request_id))
    existing = PontoServidor.objects.filter(request_id=key).first()
    if existing:
        if existing.servidor_id != server.pk or existing.tipo != tipo:
            raise ValidationError('Identificador de ponto já utilizado em outra operação.')
        return existing
    row = PontoServidor(servidor=server, request_id=key, tipo=tipo)
    row._service_write = True
    row.save()
    audit(user, 'RH_MUNICIPAL_PONTO_MARCADO', row, {'tipo': tipo, 'request_id': str(key)})
    return row


@transaction.atomic
def decide_request(actor, public_id, approved, reason):
    require_roles(actor, MANAGE_ROLES)
    row = SolicitacaoServidor.objects.select_for_update().get(public_id=public_id)
    if DecisaoSolicitacaoServidor.objects.filter(solicitacao=row).exists():
        raise ValidationError('Esta solicitação já possui decisão registrada.')
    decision = DecisaoSolicitacaoServidor(
        solicitacao=row, aprovada=bool(approved), motivo=reason.strip(), usuario=actor,
    )
    decision._service_write = True
    decision.save()
    audit(actor, 'RH_MUNICIPAL_SOLICITACAO_DECIDIDA', decision, {'solicitacao': row.pk, 'aprovada': bool(approved)})
    return decision
