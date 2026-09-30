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

from .forms import TecnicoForm, UsuarioCreationForm, UsuarioEdicaoForm
from .models import Tecnico, Usuario
from .permissions import PerfilRequeridoMixin


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"


class LogoutView(auth_views.LogoutView):
    pass


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
        self.object = form.save()
        membership = OrganizationMembership.objects.create(organization=self.request.organization, user=self.object, role=form.cleaned_data['perfil'])
        erp = ERPCatalog.objects.get(code='assistencia')
        MembershipERP.objects.create(membership=membership, erp=erp, enabled=form.cleaned_data['acesso_assistencia'])
        PlatformAudit.objects.create(organization=self.request.organization, erp=erp, user=self.request.user, action='MEMBERSHIP_CRIADO', record=f'membership:{membership.pk}', changes={'usuario': self.object.pk, 'role': membership.role, 'acesso_assistencia': form.cleaned_data['acesso_assistencia']})
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
        before = {'role': membership.role, 'status': membership.status, 'acesso_assistencia': membership.erp_accesses.filter(erp=erp, enabled=True).exists()}
        membership.role, membership.status = data['perfil'], data['status']
        membership.left_at = timezone.now() if membership.status != 'ATIVO' else None
        membership.save()
        MembershipERP.objects.update_or_create(membership=membership, erp=erp, defaults={'enabled': data['acesso_assistencia']})
        after = {'role': membership.role, 'status': membership.status, 'acesso_assistencia': data['acesso_assistencia']}
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
