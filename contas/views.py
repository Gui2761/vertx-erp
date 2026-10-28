from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import generic
from django.db import transaction
from django.utils import timezone
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership, MembershipERP, ERPCatalog, PlatformAudit
from platform_core.audit import previous_values, record_write

from .forms import EmailOrUsernameAuthenticationForm, TecnicoForm, UsuarioCreationForm, UsuarioEdicaoForm
from .models import Tecnico, Usuario
from .permissions import PerfilRequeridoMixin


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    form_class = EmailOrUsernameAuthenticationForm

    def get_success_url(self):
        from platform_core.saas_models import AdministradorPlataforma
        if self.request.user.is_authenticated and self.request.user.is_active and AdministradorPlataforma.objects.filter(
            user=self.request.user, active=True,
        ).exists():
            return '/vertyx/saas/'
        # The post-login destination is derived from active product grants, not
        # from the tenant role alone. A multi-product membership must choose.
        memberships = self.request.user.memberships.filter(status='ATIVO', organization__status='ATIVA').select_related('organization')
        selected = self.request.session.get('organization_id')
        membership = memberships.filter(organization_id=selected).first() if isinstance(selected, int) else None
        if membership is None:
            candidates = list(memberships[:2])
            if len(candidates) > 1:
                return '/vertyx/?organizacoes=1'
            membership = candidates[0] if candidates else None
        if membership:
            products = list(ERPCatalog.objects.filter(
                active=True,
                organizationerp__organization=membership.organization,
                organizationerp__enabled=True,
                membershiperp__membership=membership,
                membershiperp__enabled=True,
            ).distinct().values_list('code', flat=True))
            # Installed PWAs have independent entry points. Keep the user in
            # the experience from which authentication started, and evaluate
            # that experience's capability separately. A permission to run
            # the cash register must never redirect the Seller PWA into PDV,
            # or vice versa.
            route_name = getattr(getattr(self.request, 'resolver_match', None), 'url_name', None)
            if route_name in {'seller_login', 'pdv_login'}:
                from platform_core.context import tenant_context
                from platform_core.modules import has_capability
                capability = 'central_vendedor' if route_name == 'seller_login' else 'operar_pdv'
                target = 'operacao:seller_home' if route_name == 'seller_login' else 'operacao:pdv_home'
                with tenant_context(membership.organization):
                    allowed = 'assistencia' in products and has_capability(self.request.user, capability)
                if allowed:
                    self.request.session['organization_id'] = membership.organization_id
                    return str(reverse_lazy(target))
                # Do not silently fall through to the other installed app if
                # this user is not entitled to the requested PWA.
                return '/vertyx/'
            if len(products) > 1:
                self.request.session['organization_id'] = membership.organization_id
                return '/vertyx/'
            product = products[0] if products else None
            if product == 'gestao-publica':
                # Municipal authorization remains independent from generic
                # ADMIN/GESTOR roles and checks its own scope and permission.
                from platform_core.context import tenant_context
                from rh_municipal.public_services import has_municipal_permission
                with tenant_context(membership.organization):
                    can_open_municipal_home = has_municipal_permission(
                        self.request.user, 'dashboard.view',
                    )
                if can_open_municipal_home:
                    self.request.session['organization_id'] = membership.organization_id
                    return '/gestao-publica/'
                return '/vertyx/'
            if product == 'assistencia' and membership.role == 'TECNICO':
                from platform_core.access import has_erp_access
                if has_erp_access(self.request.user, membership.organization, code=product):
                    return str(reverse_lazy('operacao:tecnico'))
            if product == 'assistencia' and membership.role in {'ADMIN', 'GESTOR'}:
                return '/assistencia/'
            if product == 'assistencia':
                from platform_core.context import tenant_context
                from platform_core.modules import has_capability
                with tenant_context(membership.organization):
                    if membership.role == 'PDV' and has_capability(self.request.user, 'operar_pdv'):
                        return str(reverse_lazy('operacao:pdv_home'))
                    if membership.role == 'VENDEDOR' and has_capability(self.request.user, 'central_vendedor'):
                        return str(reverse_lazy('operacao:seller_home'))
            if product:
                return '/vertyx/'
        if membership is None and memberships.exists():
            return '/vertyx/?organizacoes=1'
        return super().get_success_url()


class LogoutView(auth_views.LogoutView):
    # The normal navigation posts here; GET is intentionally rejected by
    # Django's LogoutView so logout cannot be triggered by a cross-site link.
    pass


class MunicipalLoginView(LoginView):
    """Authenticate only users with effective Gestão Pública access."""
    template_name = "rh_municipal/public_login.html"

    def get_success_url(self):
        return str(reverse_lazy("rh_municipal_public:home"))

    def form_valid(self, form):
        from platform_core.context import tenant_context
        from platform_core.models import OrganizationMembership
        from rh_municipal.public_services import has_municipal_permission

        user = form.get_user()
        memberships = OrganizationMembership.objects.filter(
            user=user,
            status=OrganizationMembership.Status.ACTIVE,
            organization__status="ATIVA",
        ).select_related("organization")
        eligible = []
        for membership in memberships:
            with tenant_context(membership.organization):
                if has_municipal_permission(user, "dashboard.view"):
                    eligible.append(membership)

        selected_id = self.request.session.get("organization_id")
        selected = next((row for row in eligible if row.organization_id == selected_id), None)
        if selected is None and len(eligible) == 1:
            selected = eligible[0]
        if selected is None:
            if len(eligible) > 1:
                message = "Sua conta possui acesso a mais de uma Prefeitura. Selecione a organização correta antes de entrar."
            else:
                message = "Esta conta não possui acesso ativo ao ERP Gestão Pública. Solicite acesso ao administrador da Prefeitura."
            form.add_error(None, message)
            return self.form_invalid(form)

        self.request.session["organization_id"] = selected.organization_id
        return super().form_valid(form)


class UsuarioListView(LoginRequiredMixin, PerfilRequeridoMixin, generic.ListView):
    perfis_permitidos = ("ADMIN",)
    model = Usuario
    template_name = "contas/usuario_list.html"
    context_object_name = "usuarios"
    paginate_by = 20

    def get_queryset(self):
        from django.db.models import F
        qs = Usuario.objects.filter(memberships__organization=current_organization()).annotate(org_role=F('memberships__role'), org_status=F('memberships__status')).order_by("first_name", "username")
        busca = self.request.GET.get("q")
        if busca:
            qs = qs.filter(username__icontains=busca) | qs.filter(first_name__icontains=busca)
        return qs


class UsuarioCreateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.CreateView):
    perfis_permitidos = ("ADMIN",)
    model = Usuario
    form_class = UsuarioCreationForm
    template_name = "contas/usuario_form.html"
    success_url = reverse_lazy("contas:usuario_list")

    @transaction.atomic
    def form_valid(self, form):
        from platform_core.saas_services import verificar_limite
        from django.core.exceptions import ValidationError
        try:
            verificar_limite(self.request.organization, 'usuarios')
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
            return self.form_invalid(form)
        self.object = form.save()
        membership = OrganizationMembership.objects.create(organization=self.request.organization, user=self.object, role=form.cleaned_data['perfil'])
        erp = ERPCatalog.objects.get(code='assistencia')
        MembershipERP.objects.create(membership=membership, erp=erp, enabled=form.cleaned_data['acesso_assistencia'], visualizar_painel_operacional=form.cleaned_data['visualizar_painel_operacional'])
        PlatformAudit.objects.create(organization=self.request.organization, erp=erp, user=self.request.user, action='MEMBERSHIP_CRIADO', record=f'membership:{membership.pk}', changes={'usuario': self.object.pk, 'role': membership.role, 'acesso_assistencia': form.cleaned_data['acesso_assistencia'], 'visualizar_painel_operacional': form.cleaned_data['visualizar_painel_operacional']})
        messages.success(self.request, "Usuário e vínculo com a organização criados com sucesso.")
        return redirect(self.success_url)


class UsuarioUpdateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.FormView):
    perfis_permitidos = ("ADMIN",)
    form_class = UsuarioEdicaoForm
    template_name = "contas/usuario_form.html"
    success_url = reverse_lazy("contas:usuario_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        self.membership = get_object_or_404(OrganizationMembership, organization=self.request.organization, user_id=self.kwargs['pk'])
        kwargs['membership'] = self.membership
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['object'] = self.membership.user
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        membership = OrganizationMembership.objects.select_for_update().get(pk=self.membership.pk, organization=self.request.organization)
        data = form.cleaned_data
        if membership.user_id == self.request.user.pk and (data['perfil'] != 'ADMIN' or data['status'] != 'ATIVO' or not data['acesso_assistencia']):
            form.add_error(None, 'Seu próprio vínculo administrativo não pode ser desativado nesta tela.')
            return self.form_invalid(form)
        erp = ERPCatalog.objects.get(code='assistencia')
        before = {'visualizar_painel_operacional': membership.erp_accesses.filter(erp=erp, visualizar_painel_operacional=True).exists(), 'role': membership.role, 'status': membership.status, 'acesso_assistencia': membership.erp_accesses.filter(erp=erp, enabled=True).exists()}
        membership.role, membership.status = data['perfil'], data['status']
        membership.left_at = timezone.now() if membership.status != 'ATIVO' else None
        membership.save()
        MembershipERP.objects.update_or_create(membership=membership, erp=erp, defaults={'enabled': data['acesso_assistencia'], 'visualizar_painel_operacional': data['visualizar_painel_operacional']})
        after = {'visualizar_painel_operacional': data['visualizar_painel_operacional'], 'role': membership.role, 'status': membership.status, 'acesso_assistencia': data['acesso_assistencia']}
        PlatformAudit.objects.create(organization=self.request.organization, erp=erp, user=self.request.user, action='MEMBERSHIP_ALTERADO', record=f'membership:{membership.pk}', changes={key: {'anterior': before[key], 'posterior': after[key]} for key in before if before[key] != after[key]})
        messages.success(self.request, 'Vínculo atualizado somente nesta organização.')
        return redirect(self.success_url)


class TecnicoListView(LoginRequiredMixin, PerfilRequeridoMixin, generic.ListView):
    perfis_permitidos = ("ADMIN", "GESTOR")
    model = Tecnico
    template_name = "contas/tecnico_list.html"
    context_object_name = "tecnicos"
    paginate_by = 20

    def get_queryset(self):
        qs = Tecnico.objects.all()
        busca = self.request.GET.get("q")
        if busca:
            qs = qs.filter(nome__icontains=busca)
        return qs


class TecnicoCreateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.CreateView):
    perfis_permitidos = ("ADMIN", "GESTOR")
    model = Tecnico
    form_class = TecnicoForm
    template_name = "contas/tecnico_form.html"
    success_url = reverse_lazy("contas:tecnico_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario_logado"] = self.request.user
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        messages.success(self.request, "Técnico cadastrado com sucesso.")
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response


class TecnicoUpdateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.UpdateView):
    perfis_permitidos = ("ADMIN", "GESTOR")
    model = Tecnico
    form_class = TecnicoForm
    template_name = "contas/tecnico_form.html"
    success_url = reverse_lazy("contas:tecnico_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario_logado"] = self.request.user
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        messages.success(self.request, "Técnico atualizado com sucesso.")
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response
