from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Organization, OrganizationMembership, ModuloOrganizacao
from .saas_models import (
    AdministradorPlataforma, AssinaturaSaaS, AuditoriaSaaS,
    HistoricoPlanoSaaS, PlanoSaaS, PrimeiroAcessoSaaS,
)
from .saas_forms import (
    AdminInicialForm, AlterarPlanoForm, DadosEmpresaForm,
    EditarClienteForm, PlanoSaaSForm,
)
from .saas_services import (
    alterar_plano, alterar_status_cliente, atualizar_cliente,
    criar_cliente, mrr_amount, plano_snapshot, registrar, verificar_limite,
    metricas_uso, reemitir_primeiro_acesso, uso_quota,
)


def _platform_admin(user):
    return bool(user.is_authenticated and user.is_active and AdministradorPlataforma.objects.filter(user=user, active=True).exists())


def _guard(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('contas:login')}?next={quote(request.get_full_path())}")
    if not _platform_admin(request.user):
        response = HttpResponseForbidden('Acesso restrito à administração da plataforma VERTYX.')
        response['Cache-Control'] = 'private, no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
    return None


def _render(request, template, context=None, status=200):
    response = render(request, template, context or {}, status=status)
    response['Cache-Control'] = 'private, no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _audit_redirect_error(request, error, form=None):
    if isinstance(error, ValidationError):
        text = '; '.join(error.messages)
    elif isinstance(error, IntegrityError):
        text = 'Não foi possível salvar: CNPJ, identificador ou vínculo duplicado.'
    else:
        text = 'Não foi possível concluir a operação.'
    messages.error(request, text)
    return form


@require_GET
def manifest(request):
    response = JsonResponse({
        'id': '/saas/', 'name': 'VERTYX Admin', 'short_name': 'VERTYX Admin',
        'description': 'Administração da plataforma VERTYX', 'lang': 'pt-BR',
        'start_url': '/saas/', 'scope': '/saas/', 'display': 'standalone',
        'background_color': '#f4f7fb', 'theme_color': '#10264b',
        'icons': [{'src': '/static/pwa/saas-icon.svg', 'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any'}],
    }, content_type='application/manifest+json')
    response['Cache-Control'] = 'public, max-age=300'
    return response


@require_GET
def service_worker(request):
    response = HttpResponse(
        """'use strict';
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET') return;
  event.respondWith(fetch(event.request,{cache:'no-store'}));
});
""", content_type='application/javascript; charset=utf-8')
    response['Service-Worker-Allowed'] = '/saas/'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_http_methods(['GET', 'POST'])
def primeiro_acesso(request, token):
    digest = PrimeiroAcessoSaaS.digest(token)
    row = PrimeiroAcessoSaaS.objects.select_related('user', 'organization').filter(token_digest=digest).first()
    valid = bool(row and row.usado_em is None and row.expira_em > timezone.now() and row.user.is_active)
    if not valid:
        return _render(request, 'platform_core/saas/first_access_expired.html', status=410)
    form = SetPasswordForm(row.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            locked = PrimeiroAcessoSaaS.objects.select_for_update().select_related('user').get(pk=row.pk)
            if locked.usado_em or locked.expira_em <= timezone.now():
                return _render(request, 'platform_core/saas/first_access_expired.html', status=410)
            user = get_user_model().objects.select_for_update().get(pk=locked.user_id)
            locked_form = SetPasswordForm(user, request.POST)
            if not locked_form.is_valid():
                return _render(request, 'platform_core/saas/first_access.html',
                               {'form': locked_form, 'organization': locked.organization}, status=400)
            locked_form.save()
            locked.usado_em = timezone.now()
            locked.save(update_fields=['usado_em'])
            registrar(None, 'PRIMEIRO_ACESSO_CONCLUIDO', f'primeiro-acesso:{locked.pk}', organization=locked.organization,
                      details={'user_id': user.pk})
        return _render(request, 'platform_core/saas/first_access_complete.html', {'email': row.user.email})
    return _render(request, 'platform_core/saas/first_access.html', {'form': form, 'organization': row.organization})


@require_GET
def inicio(request):
    denied = _guard(request)
    if denied:
        return denied
    orgs = Organization.objects.all()
    subscriptions = AssinaturaSaaS.objects.select_related('organization', 'plano')
    near_limit = []
    mrr = 0
    for sub in subscriptions:
        if sub.status == AssinaturaSaaS.Status.ACTIVE:
            mrr += mrr_amount(sub)
        limit = sub.plano.limites.get('usuarios')
        if limit:
            used = sub.organization.memberships.filter(status='ATIVO').count()
            if used >= max(1, int(limit * .8)):
                near_limit.append({'organization': sub.organization, 'plan': sub.plano, 'used': used, 'limit': limit})
    counts = {
        'total': orgs.count(),
        'ativas': orgs.filter(status=Organization.Status.ACTIVE).filter(
            Q(assinatura_saas__isnull=True) | Q(assinatura_saas__status=AssinaturaSaaS.Status.ACTIVE)
        ).count(),
        'suspensas': orgs.filter(status=Organization.Status.SUSPENDED).count(),
        'implantacao': AssinaturaSaaS.objects.filter(status=AssinaturaSaaS.Status.IMPLANTACAO).count(),
        'planos_ativos': PlanoSaaS.objects.filter(ativo=True).count(),
        'planos_inativos': PlanoSaaS.objects.filter(ativo=False).count(),
    }
    by_plan = PlanoSaaS.objects.annotate(clientes=Count('assinaturas')).order_by('nome')
    usage_rows = []
    for sub in subscriptions.select_related('organization', 'plano')[:100]:
        usage_rows.append({'organization': sub.organization, 'plan': sub.plano,
                           'metrics': metricas_uso(sub.organization)})
    return _render(request, 'platform_core/saas/dashboard.html', {
        'counts': counts, 'mrr': mrr, 'by_plan': by_plan,
        'near_limit': near_limit[:8], 'financeiro_saas_preparado': True,
        'usage_rows': usage_rows,
    })


@require_GET
def clientes(request):
    denied = _guard(request)
    if denied:
        return denied
    qs = Organization.objects.select_related('assinatura_saas__plano').prefetch_related('memberships__user').order_by('-created_at')
    term = request.GET.get('q', '').strip()
    if term:
        qs = qs.filter(Q(razao_social__icontains=term) | Q(nome_fantasia__icontains=term) | Q(cnpj__icontains=term) | Q(email__icontains=term))
    rows = []
    for organization in qs[:300]:
        admins = [m.user for m in organization.memberships.all() if m.status == 'ATIVO' and m.role == 'ADMIN']
        rows.append({'organization': organization, 'subscription': getattr(organization, 'assinatura_saas', None),
                     'admin': admins[0] if admins else None})
    return _render(request, 'platform_core/saas/clients.html', {'rows': rows, 'q': term})


@require_http_methods(['GET', 'POST'])
def novo_cliente(request, step=1):
    denied = _guard(request)
    if denied:
        return denied
    if step == 1:
        form = DadosEmpresaForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            request.session['saas_company_draft'] = form.cleaned_data
            return redirect('platform_core:saas_new_client_step2')
        return _render(request, 'platform_core/saas/new_client_company.html', {'form': form, 'step': 1}, status=400 if request.method == 'POST' else 200)
    draft = request.session.get('saas_company_draft')
    if not isinstance(draft, dict):
        messages.info(request, 'Comece pelas informações da empresa.')
        return redirect('platform_core:saas_new_client')
    form = AdminInicialForm(request.POST or None, prefix='admin')
    if request.method == 'POST':
        plan_id = request.POST.get('plano')
        try:
            plan = PlanoSaaS.objects.get(pk=plan_id, ativo=True)
        except (PlanoSaaS.DoesNotExist, ValueError, TypeError):
            plan = None
        if plan is None:
            form.add_error(None, 'Selecione um plano ativo.')
        if form.is_valid() and plan:
            try:
                result = criar_cliente(actor=request.user, company=draft, admin=form.cleaned_data, plan_id=plan.pk)
            except (ValidationError, IntegrityError) as exc:
                _audit_redirect_error(request, exc)
            else:
                pending = request.session.get('saas_pending_access', {})
                pending[str(result['organization'].public_id)] = {
                    'token': result['token'], 'token_id': result['token_id'],
                    'created_at': timezone.now().timestamp(), 'user_id': result['user'].pk,
                }
                request.session['saas_pending_access'] = pending
                request.session.pop('saas_company_draft', None)
                messages.success(request, 'Cliente criado. Compartilhe o link de primeiro acesso com o administrador inicial.')
                return redirect('platform_core:saas_client_detail', public_id=result['organization'].public_id)
    plans = PlanoSaaS.objects.filter(ativo=True).order_by('nome')
    return _render(request, 'platform_core/saas/new_client_plan.html', {
        'form': form, 'plans': plans, 'draft': draft, 'step': 2,
        'module_labels': dict(ModuloOrganizacao._meta.get_field('codigo').choices),
    }, status=400 if request.method == 'POST' else 200)


@require_GET
def cliente_detalhe(request, public_id):
    denied = _guard(request)
    if denied:
        return denied
    organization = get_object_or_404(Organization.objects.prefetch_related('memberships__user'), public_id=public_id)
    subscription = AssinaturaSaaS.objects.filter(organization=organization).select_related('plano').first()
    admins = [m.user for m in organization.memberships.all() if m.status == 'ATIVO' and m.role == 'ADMIN']
    modules = ModuloOrganizacao.objects.filter(organization=organization).order_by('codigo')
    audits = AuditoriaSaaS.objects.filter(organization=organization)[:20]
    success = None
    pending = request.session.get('saas_pending_access', {}).get(str(organization.public_id))
    if pending and timezone.now().timestamp() - pending.get('created_at', 0) < 1200:
        token_row = PrimeiroAcessoSaaS.objects.filter(pk=pending.get('token_id'), organization=organization,
                     user_id=pending.get('user_id'), usado_em__isnull=True, expira_em__gt=timezone.now()).first()
        if token_row:
            token_url = request.build_absolute_uri(reverse('platform_core:saas_first_access', args=[pending['token']]))
            admin = token_row.user
            text = (f"Olá, {admin.get_full_name() if admin else 'administrador'}. A empresa {organization.display_name} foi cadastrada no VERTYX. "
                    f"Acesse {token_url} com o usuário {admin.email if admin else ''} e defina sua própria senha. "
                    "O link é individual, de uso único e expira em 48 horas. Nenhuma senha foi criada ou enviada.")
            success = {'token_id': token_row.pk, 'url': token_url, 'message': text,
                       'expires': token_row.expira_em, 'issued': token_row.criado_em,
                       'reissued': bool(pending.get('reissued')),
                       'invalidated_id': pending.get('invalidated_token_id'),
                       'share_url': f"https://api.whatsapp.com/send?text={quote(text)}"}
        else:
            request.session.get('saas_pending_access', {}).pop(str(organization.public_id), None)
            request.session.modified = True
    initial_access = PrimeiroAcessoSaaS.objects.filter(
        organization=organization, usado_em__isnull=True,
    ).select_related('user').order_by('-criado_em').first()
    can_reissue = bool(initial_access and initial_access.user.is_active
                       and not initial_access.user.has_usable_password()
                       and initial_access.user.memberships.filter(
                           organization=organization, role='ADMIN', status='ATIVO').exists())
    quota_usage = metricas_uso(organization)
    return _render(request, 'platform_core/saas/client_detail.html', {
        'organization': organization, 'subscription': subscription,
        'admin': admins[0] if admins else None, 'modules': modules,
        'audits': audits, 'created_access': success, 'can_reissue_access': can_reissue,
        'quota_usage': quota_usage,
    })


@require_POST
def reemitir_acesso(request, public_id):
    denied = _guard(request)
    if denied:
        return denied
    organization = get_object_or_404(Organization, public_id=public_id)
    try:
        result = reemitir_primeiro_acesso(actor=request.user, organization=organization)
    except ValidationError as exc:
        _audit_redirect_error(request, exc)
        return redirect('platform_core:saas_client_detail', public_id=public_id)
    pending = request.session.get('saas_pending_access', {})
    pending[str(organization.public_id)] = {
        'token': result['token'], 'token_id': result['token_id'],
        'created_at': timezone.now().timestamp(), 'user_id': result['user'].pk,
        'reissued': True, 'invalidated_token_id': result['invalidated_token_id'],
    }
    request.session['saas_pending_access'] = pending
    request.session.modified = True
    messages.success(request, f"Novo acesso emitido em {timezone.localtime(result['created_at']):%d/%m/%Y %H:%M}. O link anterior foi invalidado.")
    return redirect('platform_core:saas_client_detail', public_id=public_id)


@require_POST
def compartilhar_acesso(request, public_id):
    denied = _guard(request)
    if denied:
        return denied
    organization = get_object_or_404(Organization, public_id=public_id)
    pending = request.session.get('saas_pending_access', {}).get(str(organization.public_id))
    if not pending or timezone.now().timestamp() - pending.get('created_at', 0) >= 1200:
        messages.error(request, 'O compartilhamento expirou. Gere um novo link de primeiro acesso.')
        return redirect('platform_core:saas_client_detail', public_id=public_id)
    token = PrimeiroAcessoSaaS.objects.filter(pk=pending.get('token_id'), organization=organization,
             user_id=pending.get('user_id'), usado_em__isnull=True, expira_em__gt=timezone.now()).first()
    if not token:
        messages.error(request, 'O link de primeiro acesso já foi usado ou expirou.')
        return redirect('platform_core:saas_client_detail', public_id=public_id)
    admin = token.user
    link = request.build_absolute_uri(reverse('platform_core:saas_first_access', args=[pending['token']]))
    message = (f"Olá, {admin.get_full_name() or admin.email}. A empresa {organization.display_name} foi cadastrada no VERTYX. "
               f"Acesse {link} com o usuário {admin.email} e defina sua própria senha. "
               "O link é individual, de uso único e expira em 48 horas. Nenhuma senha foi criada ou enviada.")
    registrar(request.user, 'LINK_WHATSAPP_ABERTO', f'primeiro-acesso:{token.pk}', organization=organization,
              details={'user_id': admin.pk, 'canal': 'compartilhamento manual', 'confirmado_envio': False})
    # The raw one-use token is removed from the server-side session after the
    # hand-off; the browser receives only the WhatsApp compose URL.
    pending_access = request.session.get('saas_pending_access', {})
    pending_access.pop(str(organization.public_id), None)
    request.session['saas_pending_access'] = pending_access
    request.session.modified = True
    response = redirect(f"https://api.whatsapp.com/send?text={quote(message)}")
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'private, no-store'
    return response


@require_http_methods(['GET', 'POST'])
def editar_cliente(request, public_id):
    denied = _guard(request)
    if denied:
        return denied
    organization = get_object_or_404(Organization, public_id=public_id)
    form = EditarClienteForm(request.POST or None, instance=organization)
    if request.method == 'POST' and form.is_valid():
        try:
            atualizar_cliente(actor=request.user, organization=organization, values=form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _audit_redirect_error(request, exc, form)
        else:
            messages.success(request, 'Cadastro atualizado; o histórico do cliente foi preservado.')
            return redirect('platform_core:saas_client_detail', public_id=organization.public_id)
    return _render(request, 'platform_core/saas/form.html', {'form': form, 'title': 'Editar cliente', 'back': reverse('platform_core:saas_client_detail', args=[organization.public_id])}, status=400 if request.method == 'POST' else 200)


@require_http_methods(['GET', 'POST'])
def alterar_plano_cliente(request, public_id):
    denied = _guard(request)
    if denied:
        return denied
    organization = get_object_or_404(Organization, public_id=public_id)
    subscription = get_object_or_404(AssinaturaSaaS.objects.select_related('plano'), organization=organization)
    form = AlterarPlanoForm(request.POST or None)
    form.fields['plano'].queryset = form.fields['plano'].queryset.exclude(pk=subscription.plano_id)
    before = set(subscription.plano.modulos)
    if request.method == 'POST' and form.is_valid():
        chosen = form.cleaned_data['plano']
        current_usage = metricas_uso(organization)
        quota_warnings = []
        quota_unavailable = []
        labels = {'usuarios': 'usuários', 'filiais': 'filiais', 'vendas_mes': 'vendas no mês',
                  'ordens_mes': 'OS no mês', 'armazenamento_mb': 'armazenamento'}
        for key, metric in current_usage.items():
            new_limit = chosen.limites.get(key)
            if new_limit is not None and not metric['available']:
                quota_unavailable.append(f"{labels[key]}: medição não disponível; a operação será bloqueada se não houver como confirmar a capacidade do plano.")
            elif new_limit is not None:
                used_value = metric['used'] / (1024 * 1024) if key == 'armazenamento_mb' else metric['used']
                if used_value > new_limit:
                    quota_warnings.append(f"{labels[key]}: utilização atual acima do novo limite ({used_value:.2f} / {new_limit} MB)." if key == 'armazenamento_mb'
                                          else f"{labels[key]}: utilização atual acima do novo limite ({used_value} / {new_limit}).")
        if (quota_warnings or quota_unavailable) and request.POST.get('confirmar_limites') != 'sim':
            return _render(request, 'platform_core/saas/change_plan.html', {
                'organization': organization, 'subscription': subscription, 'form': form,
                'added': sorted(set(chosen.modulos) - before), 'removed': sorted(before - set(chosen.modulos)),
                'module_labels': dict(ModuloOrganizacao._meta.get_field('codigo').choices),
                'current_plan': plano_snapshot(subscription.plano),
                'plans_data': [plano_snapshot(plan) for plan in PlanoSaaS.objects.filter(ativo=True).exclude(pk=subscription.plano_id)],
                'new_limits': chosen.limites, 'quota_warnings': quota_warnings,
                'quota_unavailable': quota_unavailable,
                'confirm_quota_overage': True,
            }, status=200)
        try:
            changed = alterar_plano(actor=request.user, organization=organization,
                                    plan_id=form.cleaned_data['plano'].pk, reason=form.cleaned_data['motivo'])
        except (ValidationError, IntegrityError) as exc:
            _audit_redirect_error(request, exc, form)
        else:
            messages.success(request, 'Plano alterado. Módulos e limites foram sincronizados sem mudar permissões individuais.')
            return redirect('platform_core:saas_client_detail', public_id=changed.organization.public_id)
    selected = form.cleaned_data.get('plano') if form.is_bound and not form.errors else None
    after = set(selected.modulos) if selected else set()
    return _render(request, 'platform_core/saas/change_plan.html', {
        'organization': organization, 'subscription': subscription, 'form': form,
        'added': sorted(after - before), 'removed': sorted(before - after),
        'module_labels': dict(ModuloOrganizacao._meta.get_field('codigo').choices),
        'current_plan': plano_snapshot(subscription.plano),
        'plans_data': [plano_snapshot(plan) for plan in PlanoSaaS.objects.filter(ativo=True).exclude(pk=subscription.plano_id)],
        'new_limits': selected.limites if selected else {},
        'quota_warnings': [],
        'quota_unavailable': [],
    }, status=400 if request.method == 'POST' and form.errors else 200)


@require_POST
def status_cliente(request, public_id, action):
    denied = _guard(request)
    if denied:
        return denied
    if action not in ('ativar', 'suspender', 'reativar'):
        return HttpResponseForbidden('Ação inválida.')
    organization = get_object_or_404(Organization, public_id=public_id)
    if request.POST.get('confirmar') != 'sim':
        messages.error(request, 'Confirme a operação para continuar.')
        return redirect('platform_core:saas_client_detail', public_id=public_id)
    try:
        locked = alterar_status_cliente(actor=request.user, organization=organization, activate=action in ('ativar', 'reativar'))
    except (ValidationError, IntegrityError) as exc:
        _audit_redirect_error(request, exc)
    else:
        messages.success(request, 'Acesso suspenso; dados e usuários foram preservados.' if action == 'suspender' else 'Assinatura ativada; acesso liberado e dados preservados.')
    return redirect('platform_core:saas_client_detail', public_id=public_id)


@require_GET
def planos(request):
    denied = _guard(request)
    if denied:
        return denied
    rows = PlanoSaaS.objects.annotate(clientes=Count('assinaturas')).order_by('nome')
    return _render(request, 'platform_core/saas/plans.html', {'plans': rows, 'module_labels': dict(ModuloOrganizacao._meta.get_field('codigo').choices)})


@require_http_methods(['GET', 'POST'])
def plano_form(request, pk=None):
    denied = _guard(request)
    if denied:
        return denied
    instance = get_object_or_404(PlanoSaaS, pk=pk) if pk else PlanoSaaS()
    linked = instance.assinaturas.count() if instance.pk else 0
    creating = instance.pk is None
    form = PlanoSaaSForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            candidate = form.save(commit=False)
            if linked and instance.pk:
                protected = ('preco', 'periodicidade', 'modulos', 'limites')
                if any(getattr(candidate, key) != getattr(instance, key) for key in protected):
                    raise ValidationError('Este plano já possui clientes. Para preservar os contratos atuais, crie uma nova versão do plano.')
            before = plano_snapshot(instance) if instance.pk else {}
            candidate.save()
            registrar(request.user, 'PLANO_CRIADO' if creating else 'PLANO_EDITADO', f'plano:{candidate.pk}',
                      details={'anterior': before, 'posterior': plano_snapshot(candidate)})
        except (ValidationError, IntegrityError) as exc:
            _audit_redirect_error(request, exc, form)
        else:
            messages.success(request, 'Plano salvo. Planos são distintos do catálogo público de marketing.')
            return redirect('platform_core:saas_plans')
    return _render(request, 'platform_core/saas/form.html', {
        'form': form, 'title': 'Novo plano' if not pk else 'Editar plano',
        'back': reverse('platform_core:saas_plans'), 'linked': linked,
        'module_form': True,
    }, status=400 if request.method == 'POST' and form.errors else 200)
