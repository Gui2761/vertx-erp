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
from .modules import active_contract_items
from .saas_models import (
    AssinaturaSaaS, AuditoriaSaaS, ContratoSaaS, HistoricoPlanoSaaS, ItemContratoSaaS,
    PlanoSaaS, PrimeiroAcessoSaaS,
)


def registrar(actor, action, record, *, organization=None, details=None):
    return AuditoriaSaaS.objects.create(
        actor=actor, organization=organization, action=action,
        record=str(record)[:160], details=details or {},
    )


@transaction.atomic
def alterar_status_contrato(*, actor, contract_id, action):
    """Activate/suspend a multi-ERP contract without granting user memberships."""
    from django.core.exceptions import PermissionDenied
    from .models import ERPProductModule
    from .saas_models import AdministradorPlataforma

    if not (actor and actor.is_authenticated and actor.is_active) or not (
        actor.is_superuser or AdministradorPlataforma.objects.filter(user=actor, active=True).exists()
    ):
        raise PermissionDenied('Somente a administração interna VERTYX pode alterar contratos.')
    contract = ContratoSaaS.objects.select_for_update().select_related('organization').filter(pk=contract_id).first()
    if contract is None:
        raise ValidationError('Contrato não encontrado.')
    Organization.objects.select_for_update().get(pk=contract.organization_id)
    lines = list(contract.itens.select_for_update().select_related('erp', 'plano').order_by('erp__code', 'pk'))
    if action == 'ativar':
        if contract.status not in {ContratoSaaS.Status.RASCUNHO, ContratoSaaS.Status.SUSPENSO}:
            raise ValidationError('Somente contratos em rascunho ou suspensos podem ser ativados.')
        if contract.organization.status != Organization.Status.ACTIVE:
            raise ValidationError('Reative a organização antes de ativar um contrato.')
        if contract.fim_em and contract.fim_em < timezone.localdate():
            raise ValidationError('A data final do contrato já passou; revise a vigência antes de ativar.')
        if not lines or not any(line.ativo for line in lines):
            raise ValidationError('O contrato precisa conter ao menos um produto ativo.')
        active_by_code = {}
        for line in lines:
            if not line.ativo:
                continue
            if not line.erp.active or not line.plano.ativo or line.plano.erp_id != line.erp_id:
                raise ValidationError('O produto ou plano de uma linha está inativo ou incompatível.')
            codes = set(line.modulos_snapshot or ())
            registered = set(ERPProductModule.objects.filter(erp=line.erp, active=True).values_list('code', flat=True))
            plan_codes = set(line.plano.modulos_produto.filter(modulo__active=True).values_list('modulo__code', flat=True))
            if codes - registered or codes - plan_codes:
                raise ValidationError('O snapshot contém módulos inexistentes, inativos ou não incluídos no plano contratado.')
            if line.erp_id in active_by_code:
                raise ValidationError('O contrato contém mais de uma linha para o mesmo produto.')
            active_by_code[line.erp_id] = line
            other_active = active_contract_items(contract.organization, line.erp.code).exclude(contrato=contract)
            if other_active.exists():
                raise ValidationError(f'Já existe outro contrato ativo para {line.erp.name}; resolva o conflito antes da ativação.')
            legacy = AssinaturaSaaS.objects.filter(organization=contract.organization).select_related('plano', 'plano__erp').first()
            legacy_covers = bool(legacy and (
                legacy.plano.erp_id == line.erp_id or
                legacy.plano.erp_id is None and line.erp.code == 'assistencia'
            ))
            if legacy_covers:
                raise ValidationError(f'{line.erp.name} ainda possui uma assinatura legada. Migre o vínculo comercial antes de ativar o contrato multierp.')
        before = {'status': contract.status, 'produtos': [
            {'erp': line.erp.code, 'ativo': line.ativo, 'modulos': line.modulos_snapshot,
             'limites': line.limites_snapshot, 'indicadores': line.nivel_indicadores_snapshot}
            for line in lines
        ]}
        contract.status = ContratoSaaS.Status.ATIVO
        if contract.inicio_em is None:
            contract.inicio_em = timezone.localdate()
        contract.full_clean()
        contract.save(update_fields=['status', 'inicio_em', 'atualizado_em'])
        for line in active_by_code.values():
            access, _ = OrganizationERP.objects.get_or_create(
                organization=contract.organization, erp=line.erp,
                defaults={'enabled': True, 'enabled_at': timezone.now()},
            )
            if not access.enabled:
                access.enabled = True
                access.disabled_at = None
                access.enabled_at = timezone.now()
                access.save(update_fields=['enabled', 'disabled_at', 'enabled_at'])
        registrar(actor, 'CONTRATO_SAAS_ATIVADO', f'contrato:{contract.pk}', organization=contract.organization,
                  details={'anterior': before, 'posterior_status': contract.status,
                           'membership_erp_alterado': False})
        return contract

    if action == 'suspender':
        if contract.status != ContratoSaaS.Status.ATIVO:
            raise ValidationError('Somente um contrato ativo pode ser suspenso.')
        before_status = contract.status
        contract.status = ContratoSaaS.Status.SUSPENSO
        contract.save(update_fields=['status', 'atualizado_em'])
        disabled = []
        for line in lines:
            if not line.ativo or active_contract_items(contract.organization, line.erp.code).exists():
                continue
            access = OrganizationERP.objects.select_for_update().filter(
                organization=contract.organization, erp=line.erp, enabled=True,
            ).first()
            if access:
                access.enabled = False
                access.disabled_at = timezone.now()
                access.save(update_fields=['enabled', 'disabled_at'])
                disabled.append(line.erp.code)
        registrar(actor, 'CONTRATO_SAAS_SUSPENSO', f'contrato:{contract.pk}', organization=contract.organization,
                  details={'status_anterior': before_status, 'status_novo': contract.status,
                           'produtos_desabilitados': disabled, 'membership_erp_alterado': False})
        return contract
    raise ValidationError('Ação de contrato inválida.')


@transaction.atomic
def bootstrap_administrador_prefeitura(*, actor, organization_id, membership_id):
    """Grant the first municipal administrator through the platform boundary.

    This deliberately does not enable products or memberships. Those are
    separate SaaS entitlements and must already be enabled before bootstrap.
    """
    from django.core.exceptions import PermissionDenied
    from rh_municipal.models import AcessoMunicipal, PRODUCT_CODE
    from .saas_models import AdministradorPlataforma

    if not (actor and actor.is_authenticated and actor.is_active):
        raise PermissionDenied('Autenticação administrativa necessária.')
    if not actor.is_superuser and not AdministradorPlataforma.objects.filter(user=actor, active=True).exists():
        raise PermissionDenied('Somente a administração interna VERTYX pode executar o bootstrap.')

    organization = Organization.objects.select_for_update().filter(pk=organization_id).first()
    if organization is None or organization.status != Organization.Status.ACTIVE:
        raise ValidationError('Selecione uma organização ativa.')

    erp = ERPCatalog.objects.filter(code=PRODUCT_CODE, active=True).first()
    if erp is None or not OrganizationERP.objects.filter(
        organization=organization, erp=erp, enabled=True,
    ).exists():
        raise ValidationError('O produto Gestão Pública não está habilitado para esta organização. Nenhum acesso foi concedido.')

    # Product entitlement, contract module, membership entitlement and
    # municipal role are distinct gates. Never infer one from another.
    from .modules import module_enabled
    with tenant_context(organization):
        if not module_enabled('gestao_publica'):
            raise ValidationError('O módulo Gestão Pública não está contratado/ativo no plano desta organização.')

    membership = OrganizationMembership.objects.select_for_update().filter(
        pk=membership_id, organization=organization,
        status=OrganizationMembership.Status.ACTIVE, user__is_active=True,
    ).select_related('user').first()
    if membership is None:
        raise ValidationError('Selecione um usuário ativo com membership ativo nesta organização.')
    if not MembershipERP.objects.filter(membership=membership, erp=erp, enabled=True).exists():
        raise ValidationError('O usuário ainda não possui acesso MembershipERP ao produto Gestão Pública.')

    # Treat inactive/history rows as existing too: bootstrap must never create
    # a second municipal identity or silently reactivate a prior assignment.
    existing = AcessoMunicipal.all_objects.select_for_update().filter(
        membership__organization=organization,
    ).first()
    if existing:
        raise ValidationError('Esta organização já possui um AcessoMunicipal. Use a administração municipal para alterar acessos; o bootstrap é somente para o primeiro acesso.')

    with tenant_context(organization):
        access = AcessoMunicipal.all_objects.create(
            membership=membership,
            papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
            escopo=AcessoMunicipal.Escopo.PREFEITURA,
            atribuido_por=actor,
        )
    registrar(
        actor, 'BOOTSTRAP_ADMIN_PREFEITURA', f'acesso-municipal:{access.pk}',
        organization=organization,
        details={
            'membership_id': membership.pk,
            'user_id': membership.user_id,
            'papel': AcessoMunicipal.Papel.ADMIN_PREFEITURA,
            'escopo': AcessoMunicipal.Escopo.PREFEITURA,
        },
    )
    return access


@transaction.atomic
def criar_prefeitura_homologacao(*, actor, razao_social, nome_fantasia, administrador_nome, administrador_email):
    """Create a separate municipal tenant with its explicit first-access gates.

    This is an internal platform action for a proposal-based municipal tenant;
    it intentionally creates no commercial subscription/plan and no password.
    """
    from django.core.exceptions import PermissionDenied
    from rh_municipal.models import AcessoMunicipal, PRODUCT_CODE
    from .saas_models import AdministradorPlataforma

    if not (actor and actor.is_authenticated and actor.is_active):
        raise PermissionDenied('Autenticação administrativa necessária.')
    if not actor.is_superuser and not AdministradorPlataforma.objects.filter(user=actor, active=True).exists():
        raise PermissionDenied('Somente a administração interna VERTYX pode criar uma Prefeitura.')

    User = get_user_model()
    email = administrador_email.strip().casefold()
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({'administrador_email': 'Este e-mail já possui uma conta VERTYX. Nenhum usuário foi criado.'})
    if Organization.objects.filter(razao_social__iexact=razao_social.strip()).exists() or Organization.objects.filter(
        nome_fantasia__iexact=nome_fantasia.strip(),
    ).exclude(nome_fantasia='').exists():
        raise ValidationError('Já existe uma organização com esse nome. Revise o cadastro antes de continuar.')

    erp = ERPCatalog.objects.filter(code=PRODUCT_CODE, active=True).first()
    if erp is None:
        raise ValidationError('O catálogo ativo Gestão Pública não está configurado; nenhum tenant foi criado.')

    base = slugify(razao_social)[:45].strip('-') or 'prefeitura'
    slug = f'{base}-{secrets.token_hex(3)}'
    organization = Organization.objects.create(
        slug=slug,
        razao_social=razao_social.strip(),
        nome_fantasia=nome_fantasia.strip(),
        # CNPJ, endereço, município e UF permanecem em branco até serem
        # fornecidos oficialmente; não inventar dados cadastrais.
        status=Organization.Status.ACTIVE,
    )
    OrganizationERP.objects.create(organization=organization, erp=erp, enabled=True)
    with tenant_context(organization):
        ModuloOrganizacao.objects.create(
            organization=organization, codigo='gestao_publica', habilitado=True,
        )

    full_name = administrador_nome.strip()
    parts = full_name.split(None, 1)
    user = User(
        username=_username_for(email), email=email,
        first_name=parts[0][:150], last_name=parts[1][:150] if len(parts) > 1 else '',
        is_active=True,
    )
    user.set_unusable_password()
    user.save()
    membership = OrganizationMembership.objects.create(
        organization=organization, user=user,
        role='SERVIDOR_PUBLICO', status=OrganizationMembership.Status.ACTIVE,
    )
    MembershipERP.objects.create(membership=membership, erp=erp, enabled=True)
    with tenant_context(organization):
        access = AcessoMunicipal.all_objects.create(
            membership=membership,
            papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
            escopo=AcessoMunicipal.Escopo.PREFEITURA,
            atribuido_por=actor,
        )

    raw_token = secrets.token_urlsafe(40)
    first_access = PrimeiroAcessoSaaS(
        organization=organization, user=user,
        token_digest=PrimeiroAcessoSaaS.digest(raw_token),
        expira_em=timezone.now() + timedelta(hours=48),
    )
    first_access.full_clean()
    first_access.save()
    registrar(actor, 'PREFEITURA_HOMOLOGACAO_CRIADA', f'organization:{organization.pk}',
              organization=organization, details={
                  'membership_id': membership.pk, 'user_id': user.pk,
                  'acesso_municipal_id': access.pk,
                  'erp': PRODUCT_CODE, 'plano_saas': None,
                  'primeiro_acesso_id': first_access.pk,
                  'expira_em': first_access.expira_em.isoformat(),
              })
    return {
        'organization': organization, 'user': user, 'membership': membership,
        'access': access, 'token': raw_token, 'token_id': first_access.pk,
        'expires_at': first_access.expira_em,
    }


def plano_snapshot(plan):
    return {
        'id': plan.pk, 'slug': plan.slug, 'nome': plan.nome,
        'erp': ({'id': plan.erp_id, 'code': plan.erp.code, 'name': plan.erp.name}
                if plan.erp_id else None),
        'preco': str(plan.preco) if plan.preco is not None else None,
        'periodicidade': plan.periodicidade, 'modulos': sorted(plan.modulos),
        'modulos_produto': sorted(plan.modulos_produto.values_list('modulo__code', flat=True)),
        'limites': plan.limites,
        'nivel_indicadores': plan.nivel_indicadores,
        'plano_comercial': ({'id': plan.plano_comercial_id,
                             'slug': plan.plano_comercial.slug,
                             'nome': plan.plano_comercial.nome}
                            if plan.plano_comercial_id else None),
        'publico_ativo': plan.publico_ativo,
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
    from .saas_models import CORE_SAAS_MODULES
    enabled = set(plan.modulos) | set(CORE_SAAS_MODULES)
    # Expand each plan-declared module once. Some legacy aliases are emitted
    # for compatibility (for example financeiro_basico -> financeiro); they
    # must not be recursively interpreted as a grant of the complete tier.
    implications = {
        'estoque_completo': {'estoque_basico', 'estoque'},
        'estoque_basico': {'estoque'},
        'estoque': {'estoque_basico', 'estoque_completo'},
        'financeiro_completo': {'financeiro_basico', 'financeiro'},
        'financeiro_basico': {'financeiro'},
        'financeiro': {'financeiro_basico', 'financeiro_completo'},
        'rh_asst_completo': {'rh_asst_basico', 'rh', 'ponto'},
        'rh_asst_basico': {'rh', 'ponto'},
        'rh': {'rh_asst_basico', 'rh_asst_completo', 'ponto'},
        'ponto': {'rh_asst_basico'},
        'documentos_completos': {'documentos_basicos', 'documentos'},
        'documentos_basicos': {'documentos'},
        'documentos': {'documentos_basicos', 'documentos_completos'},
        'relatorios_completos': {'relatorios_basicos'},
    }
    declared = set(plan.modulos) | set(CORE_SAAS_MODULES)
    for code in declared:
        enabled.update(implications.get(code, ()))
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
    # Seed only the tenant's payment-method catalog. Money is ready by default;
    # bank-settled methods remain inactive until the client maps a tenant account.
    from gestao.payment_methods import ensure_default_pdv_methods
    ensure_default_pdv_methods(org)
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


def _contract_quota(organization, key, erp_code):
    """Return (contract-controls-product, configured-limit) for one ERP line."""
    if not erp_code:
        return False, None
    lines = list(active_contract_items(organization, erp_code)[:2])
    if len(lines) > 1:
        raise ValidationError('Há contratos ativos conflitantes para este produto; a operação foi bloqueada.')
    if lines:
        return True, lines[0].limites_snapshot.get(key)
    controlled = ItemContratoSaaS.objects.filter(
        contrato__organization=organization, erp__code=erp_code,
        contrato__status__in=[ContratoSaaS.Status.ATIVO, ContratoSaaS.Status.SUSPENSO, ContratoSaaS.Status.ENCERRADO],
    ).exists()
    return controlled, None


def _legacy_quota_limit(organization, key, erp_code=None):
    subscription = AssinaturaSaaS.objects.filter(organization=organization).select_related('plano', 'plano__erp').first()
    if not subscription:
        return None
    if erp_code:
        plan_erp = subscription.plano.erp.code if subscription.plano.erp_id else None
        if plan_erp and plan_erp != erp_code:
            return None
        if plan_erp is None and erp_code != 'assistencia':
            return None
    return subscription.plano.limites.get(key)


def metricas_uso(organization, *, erp_code=None):
    keys = ('usuarios', 'filiais', 'vendas_mes', 'ordens_mes', 'armazenamento_mb')
    result = {}
    for key in keys:
        try:
            used = uso_quota(organization, key)
        except Exception:
            used = None
        conflicted = False
        try:
            contract_controls, limit = _contract_quota(organization, key, erp_code)
        except ValidationError:
            contract_controls, limit, conflicted = True, None, True
        if not contract_controls:
            limit = _legacy_quota_limit(organization, key, erp_code)
        if key == 'armazenamento_mb' and used is not None:
            used_display = used
        else:
            used_display = used
        if used is None:
            display = 'Medição não disponível'
        elif conflicted:
            display = 'Contrato conflitante · regularização necessária'
        elif contract_controls and limit is None:
            display = f'{used} · limite sem configuração' if key != 'armazenamento_mb' else 'Medição disponível · limite sem configuração'
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


def metricas_uso_por_produto(organization):
    """Return authoritative tenant usage against each current contracted ERP."""
    today = timezone.localdate()
    lines = active_contract_items(organization, today=today).select_related('erp').order_by('erp__name', 'pk')
    product_codes = list(dict.fromkeys(lines.values_list('erp__code', flat=True)))
    return [
        {'code': code, 'name': lines.filter(erp__code=code).first().erp.name,
         'metrics': metricas_uso(organization, erp_code=code)}
        for code in product_codes
    ]


@transaction.atomic
def verificar_limite(organization, key, *, incremento=1, erp_code=None):
    """Lock the organization and enforce every configured, authoritatively measured quota."""
    Organization.objects.select_for_update().get(pk=organization.pk)
    contract_controls, limit = _contract_quota(organization, key, erp_code)
    if contract_controls:
        if not list(active_contract_items(organization, erp_code)[:1]):
            raise ValidationError('Não há contrato vigente para este produto; a operação foi bloqueada.')
    else:
        limit = _legacy_quota_limit(organization, key, erp_code)
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
