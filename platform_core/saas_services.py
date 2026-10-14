import secrets
from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .context import tenant_context
from .models import (
    Organization, OrganizationERP, OrganizationMembership, MembershipERP,
    ERPCatalog, ModuloOrganizacao, ConfiguracaoEmpresa,
)
from .saas_models import (
    AssinaturaSaaS, AuditoriaSaaS, HistoricoPlanoSaaS,
    PlanoSaaS, PrimeiroAcessoSaaS,
)


def registrar(actor, action, record, *, organization=None, details=None):
    return AuditoriaSaaS.objects.create(
        actor=actor, organization=organization, action=action,
        record=str(record)[:160], details=details or {},
    )


def plano_snapshot(plan):
    return {
        'id': plan.pk, 'slug': plan.slug, 'nome': plan.nome,
        'preco': str(plan.preco) if plan.preco is not None else None,
        'periodicidade': plan.periodicidade, 'modulos': sorted(plan.modulos),
        'limites': plan.limites,
    }


def _slug_for(name, cnpj):
    base = slugify(name)[:45].strip('-') or 'cliente'
    suffix = cnpj[-6:]
    candidate = f'{base}-{suffix}'
    number = 2
    while Organization.objects.filter(slug=candidate).exists():
        candidate = f'{base}-{suffix}-{number}'
        number += 1
    return candidate


def _tenant_limits(plan):
    # ConfiguracaoEmpresa currently provides enforcement/storage for these
    # core quotas. Other meters remain configurable but not falsely measured.
    return {key: plan.limites[key] for key in ('usuarios', 'filiais', 'armazenamento_mb')
            if plan.limites.get(key) is not None}


def reemitir_primeiro_acesso(*, actor, organization):
    """Rotate an unused first-access link without ever storing its raw token."""
    from django.contrib.auth import get_user_model
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization.pk)
        current = PrimeiroAcessoSaaS.objects.select_for_update().filter(
            organization=organization, usado_em__isnull=True,
        ).order_by('-criado_em').first()
        if current is None:
            raise ValidationError('Não há um primeiro acesso pendente para reemitir.')
        user = get_user_model().objects.select_for_update().get(pk=current.user_id)
        if user.has_usable_password() or not user.is_active:
            raise ValidationError('O primeiro acesso já foi concluído; a reemissão não pode redefinir a conta.')
        if not user.memberships.filter(organization=organization, role='ADMIN', status='ATIVO').exists():
            raise ValidationError('O administrador inicial não possui vínculo ativo neste cliente.')
        previous_id = current.pk
        current.usado_em = timezone.now()  # same one-use terminal state; immutable history stays intact
        current.save(update_fields=['usado_em'])
        raw_token = secrets.token_urlsafe(48)
        replacement = PrimeiroAcessoSaaS.objects.create(
            organization=organization, user=user,
            token_digest=PrimeiroAcessoSaaS.digest(raw_token),
            expira_em=timezone.now() + timedelta(hours=48),
        )
        registrar(actor, 'PRIMEIRO_ACESSO_REEMITIDO', f'primeiro-acesso:{replacement.pk}',
                  organization=organization, details={
                      'user_id': user.pk, 'token_anterior_invalidado_id': previous_id,
                      'novo_acesso_id': replacement.pk,
                      'emitido_em': replacement.criado_em.isoformat(),
                      'expira_em': replacement.expira_em.isoformat(),
                  })
        return {'token': raw_token, 'token_id': replacement.pk, 'user': user,
                'invalidated_token_id': previous_id, 'created_at': replacement.criado_em,
                'expires_at': replacement.expira_em}


def aplicar_modulos(organization, plan):
    enabled = set(plan.modulos)
    choices = {value for value, _label in ModuloOrganizacao._meta.get_field('codigo').choices}
    if enabled - choices:
        raise ValidationError('O plano possui módulo que não existe no catálogo operacional.')
    with tenant_context(organization):
        for code in choices:
            row = ModuloOrganizacao.objects.filter(organization=organization, codigo=code).first()
            if row is None:
                ModuloOrganizacao.objects.create(organization=organization, codigo=code, habilitado=code in enabled)
            elif row.habilitado != (code in enabled):
                row.habilitado = code in enabled
                row.save(update_fields=['habilitado'])


def _username_for(email):
    User = get_user_model()
    local = slugify(email.split('@', 1)[0]).replace('-', '_')[:120] or 'admin'
    candidate, suffix = local, 2
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f'{local[:130]}_{suffix}'
        suffix += 1
    return candidate


@transaction.atomic
def criar_cliente(*, actor, company, admin, plan_id):
    """Atomically creates the organization, subscription, modules and initial access."""
    User = get_user_model()
    plan = PlanoSaaS.objects.select_for_update().get(pk=plan_id, ativo=True)
    email = admin['email'].strip().casefold()
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({'admin_email': 'Este e-mail já possui uma conta; escolha o fluxo de vínculo de usuário existente.'})
    org = Organization.objects.create(
        slug=_slug_for(company['razao_social'], company['cnpj']),
        razao_social=company['razao_social'].strip(),
        nome_fantasia=company.get('nome_fantasia', '').strip(),
        cnpj=company['cnpj'], email=company['email'].strip().casefold(),
        telefone=company['telefone'].strip(), endereco=company['endereco'].strip(),
        cidade=company['cidade'].strip(), uf=company['uf'].strip().upper(),
        status=Organization.Status.ACTIVE,
    )
    subscription = AssinaturaSaaS.objects.create(
        organization=org, plano=plan, status=AssinaturaSaaS.Status.IMPLANTACAO,
        periodicidade=plan.periodicidade,
    )
    aplicar_modulos(org, plan)
    with tenant_context(org):
        ConfiguracaoEmpresa.objects.create(organization=org, limites=_tenant_limits(plan))

    erp, _ = ERPCatalog.objects.get_or_create(
        code='assistencia', defaults={'name': 'Assistência', 'active': True},
    )
    OrganizationERP.objects.create(organization=org, erp=erp, enabled=True)
    UserModel = User
    full_name = admin['nome'].strip()
    parts = full_name.split(None, 1)
    user = UserModel(
        username=_username_for(email), email=email,
        first_name=parts[0][:150], last_name=(parts[1][:150] if len(parts) > 1 else ''),
        telefone=admin['whatsapp'].strip(), is_active=True,
    )
    user.set_unusable_password()
    user.save()
    membership = OrganizationMembership.objects.create(
        organization=org, user=user, role='ADMIN', status=OrganizationMembership.Status.ACTIVE,
    )
    MembershipERP.objects.create(membership=membership, erp=erp, enabled=True)

    limits = plan.limites
    secret_limit = limits.get('usuarios')
    if secret_limit is not None and secret_limit < 1:
        raise ValidationError('O limite de usuários precisa comportar o administrador inicial.')

    raw_token = secrets.token_urlsafe(40)
    token = PrimeiroAcessoSaaS.objects.create(
        organization=org, user=user,
        token_digest=PrimeiroAcessoSaaS.digest(raw_token),
        expira_em=timezone.now() + timedelta(hours=48),
    )
    registrar(actor, 'CLIENTE_CRIADO', f'organization:{org.pk}', organization=org,
              details={'plano': plan.slug, 'assinatura': subscription.pk, 'status': org.status})
    registrar(actor, 'PLANO_VINCULADO', f'assinatura:{subscription.pk}', organization=org,
              details={'plano': plano_snapshot(plan), 'status': subscription.status})
    registrar(actor, 'ADMIN_INICIAL_CRIADO', f'membership:{membership.pk}', organization=org,
              details={'user_id': user.pk, 'email': user.email, 'role': membership.role})
    registrar(actor, 'PRIMEIRO_ACESSO_GERADO', f'token:{token.pk}', organization=org,
              details={'user_id': user.pk, 'expira_em': token.expira_em.isoformat()})
    return {'organization': org, 'subscription': subscription, 'user': user,
            'membership': membership, 'token': raw_token, 'token_id': token.pk}


@transaction.atomic
def alterar_plano(*, actor, organization, plan_id, reason=''):
    sub = AssinaturaSaaS.objects.select_for_update().select_related('plano').get(organization=organization)
    new_plan = PlanoSaaS.objects.select_for_update().get(pk=plan_id, ativo=True)
    old_plan = sub.plano
    before = plano_snapshot(old_plan)
    after = plano_snapshot(new_plan)
    if old_plan.pk == new_plan.pk:
        raise ValidationError('Selecione um plano diferente do atual.')
    HistoricoPlanoSaaS.objects.create(
        assinatura=sub, plano_anterior=old_plan, plano_novo=new_plan,
        anterior=before, posterior=after, motivo=reason.strip(), alterado_por=actor,
    )
    sub.plano = new_plan
    sub.periodicidade = new_plan.periodicidade
    sub.save(update_fields=['plano', 'periodicidade', 'atualizado_em'])
    aplicar_modulos(organization, new_plan)
    with tenant_context(organization):
        config = ConfiguracaoEmpresa.objects.filter(organization=organization).first()
        if config:
            config.limites = _tenant_limits(new_plan)
            config.save(update_fields=['limites'])
    registrar(actor, 'PLANO_ALTERADO', f'assinatura:{sub.pk}', organization=organization,
              details={'anterior': before, 'posterior': after, 'motivo': reason.strip()})
    return sub


@transaction.atomic
def atualizar_cliente(*, actor, organization, values):
    locked = Organization.objects.select_for_update().get(pk=organization.pk)
    before = {key: getattr(locked, key) for key in values}
    for key, value in values.items():
        setattr(locked, key, value)
    locked.save()
    after = {key: getattr(locked, key) for key in values}
    registrar(actor, 'CLIENTE_EDITADO', f'organization:{locked.pk}', organization=locked,
              details={'anterior': before, 'posterior': after})
    return locked


@transaction.atomic
def alterar_status_cliente(*, actor, organization, activate):
    locked = Organization.objects.select_for_update().get(pk=organization.pk)
    subscription = AssinaturaSaaS.objects.select_for_update().filter(organization=locked).first()
    if activate:
        locked.status = Organization.Status.ACTIVE
        if subscription:
            subscription.status = AssinaturaSaaS.Status.ACTIVE
            subscription.save(update_fields=['status', 'atualizado_em'])
        action = 'CLIENTE_REATIVADO'
    else:
        locked.status = Organization.Status.SUSPENDED
        if subscription:
            subscription.status = AssinaturaSaaS.Status.SUSPENDED
            subscription.save(update_fields=['status', 'atualizado_em'])
        action = 'CLIENTE_SUSPENSO'
    locked.save(update_fields=['status', 'updated_at'])
    registrar(actor, action, f'organization:{locked.pk}', organization=locked,
              details={'status': locked.status, 'assinatura': subscription.status if subscription else None})
    return locked


def _month_range():
    today = timezone.localdate()
    return today.replace(day=1), today.replace(day=monthrange(today.year, today.month)[1])


def _storage_usage_bytes(organization):
    """Sum private objects under this tenant's isolated storage prefix."""
    from ordens.storage import private_storage
    prefix = f'organizations/{organization.public_id}/'
    total = 0
    try:
        backend = private_storage.backend
        pending = [prefix.rstrip('/')]
        while pending:
            directory = pending.pop()
            try:
                directories, files = backend.listdir(directory)
            except FileNotFoundError:
                continue
            pending.extend(f'{directory}/{name}' for name in directories)
            for name in files:
                key = f'{directory}/{name}'
                if key.startswith(prefix):
                    total += backend.size(key)
    except Exception:
        # Storage failures must never be represented as zero usage.
        return None
    return total


def uso_quota(organization, key):
    """Return authoritative tenant-local usage, or None when it cannot be measured."""
    from .context import tenant_context
    start, end = _month_range()
    if key == 'usuarios':
        return OrganizationMembership.objects.filter(organization=organization, status='ATIVO').count()
    if key == 'filiais':
        from .models import FilialEmpresa
        with tenant_context(organization):
            return FilialEmpresa.objects.filter(organization=organization, ativo=True).count()
    if key == 'vendas_mes':
        from operacao.models import Venda
        with tenant_context(organization):
            confirmed = ['CONFIRMADA', 'FINALIZADA', 'PARCIALMENTE_DEVOLVIDA', 'DEVOLVIDA']
            return Venda.objects.filter(status__in=confirmed).filter(
                Q(finalizada_em__date__range=(start, end)) |
                Q(finalizada_em__isnull=True, status='CONFIRMADA', criado_em__date__range=(start, end))
            ).count()
    if key == 'ordens_mes':
        from ordens.models import OrdemServico
        with tenant_context(organization):
            # Every formally created OS consumes quota, including later-cancelled
            # records: cancellation preserves the official record and cannot evade the meter.
            return OrdemServico.objects.filter(abertura__date__range=(start, end)).count()
    if key == 'armazenamento_mb':
        return _storage_usage_bytes(organization)
    return None


def metricas_uso(organization):
    subscription = AssinaturaSaaS.objects.filter(organization=organization).select_related('plano').first()
    keys = ('usuarios', 'filiais', 'vendas_mes', 'ordens_mes', 'armazenamento_mb')
    result = {}
    for key in keys:
        try:
            used = uso_quota(organization, key)
        except Exception:
            used = None
        limit = subscription.plano.limites.get(key) if subscription else None
        if key == 'armazenamento_mb' and used is not None:
            used_display = used
        else:
            used_display = used
        if used is None:
            display = 'Medição não disponível'
        elif key == 'armazenamento_mb':
            used_gb = used / (1024 ** 3)
            limit_gb = limit / 1024 if limit is not None else None
            left = f'{used_gb:.1f} GB' if used_gb >= 1 else f'{used / (1024 ** 2):.0f} MB'
            right = f'{limit_gb:g} GB' if limit_gb is not None and limit_gb >= 1 else (f'{limit} MB' if limit is not None else 'A definir')
            display = f'{left} / {right}'
        else:
            display = f'{used} / {limit if limit is not None else "A definir"}'
        result[key] = {'used': used_display, 'limit': limit, 'available': used is not None,
                       'display': display}
    return result


@transaction.atomic
def verificar_limite(organization, key, *, incremento=1):
    """Lock the organization and enforce every configured, authoritatively measured quota."""
    Organization.objects.select_for_update().get(pk=organization.pk)
    subscription = AssinaturaSaaS.objects.filter(organization=organization).select_related('plano').first()
    if not subscription:
        return
    limit = subscription.plano.limites.get(key)
    if limit is None:
        return
    used = uso_quota(organization, key)
    if used is None:
        raise ValidationError('Medição não disponível; a operação foi bloqueada para evitar ultrapassar o limite.')
    if key == 'armazenamento_mb':
        try:
            increment = int(incremento)
        except (TypeError, ValueError):
            increment = 0
        over = used + increment > limit * 1024 * 1024
    else:
        over = used + incremento > limit
    if over:
        if key == 'usuarios':
            raise ValidationError('Limite de usuários do plano atingido.')
        if key == 'filiais':
            raise ValidationError('Limite de filiais do plano atingido.')
        if key == 'vendas_mes':
            raise ValidationError('Limite de vendas do plano atingido.')
        if key == 'ordens_mes':
            raise ValidationError('Limite de ordens de serviço do plano atingido.')
        raise ValidationError('Limite de armazenamento do plano atingido.')


def mrr_amount(subscription):
    plan = subscription.plano
    if plan.preco is None:
        return Decimal('0.00')
    return plan.preco / 12 if subscription.periodicidade == PlanoSaaS.Period.YEAR else plan.preco
