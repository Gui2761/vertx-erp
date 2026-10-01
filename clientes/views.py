from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import generic
from contas.permissions import PerfilRequeridoMixin
from django.db import transaction
from platform_core.audit import previous_values, record_write

from .forms import ClienteForm, ContatoFormSet, UnidadeForm
from .models import Cliente, Unidade


class ClienteListView(LoginRequiredMixin, generic.ListView):
    model = Cliente
    template_name = "clientes/cliente_list.html"
    context_object_name = "clientes"
    paginate_by = 20

    def get_queryset(self):
        qs = Cliente.objects.all()
        busca = self.request.GET.get("q")
        if busca:
            qs = qs.filter(nome_razao_social__icontains=busca) | qs.filter(cpf_cnpj__icontains=busca)
        situacao = self.request.GET.get("situacao")
        if situacao == "ativos":
            qs = qs.filter(ativo=True)
        elif situacao == "inativos":
            qs = qs.filter(ativo=False)
        return qs


class ClienteDetailView(LoginRequiredMixin, generic.DetailView):
    model = Cliente
    template_name = "clientes/cliente_detail.html"
    context_object_name = "cliente"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["unidades"] = self.object.unidades.all()
        ctx["contatos"] = self.object.contatos.all()
        ctx["equipamentos"] = self.object.equipamentos.all() if hasattr(self.object, "equipamentos") else []
        from operacao.history import related
        ctx.update(related(self.request.user, self.object))
        return ctx


class ClienteCreateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.CreateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = Cliente
    form_class = ClienteForm
    template_name = "clientes/cliente_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["contato_formset"] = ContatoFormSet(self.request.POST, instance=ctx['form'].instance)
        else:
            ctx["contato_formset"] = ContatoFormSet(instance=ctx['form'].instance)
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        ctx = self.get_context_data(form=form)
        contato_formset = ctx["contato_formset"]
        if contato_formset.is_valid():
            previous = previous_values(form)
            self.object = form.save()
            contato_formset.instance = self.object
            contato_formset.save()
            record_write(self.request, self.object, previous)
            messages.success(self.request, "Cliente cadastrado com sucesso.")
            return redirect("clientes:cliente_detail", pk=self.object.pk)
        return self.render_to_response(self.get_context_data(form=form))


class ClienteUpdateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.UpdateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = Cliente
    form_class = ClienteForm
    template_name = "clientes/cliente_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["contato_formset"] = ContatoFormSet(self.request.POST, instance=self.object)
        else:
            ctx["contato_formset"] = ContatoFormSet(instance=self.object)
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        ctx = self.get_context_data()
        contato_formset = ctx["contato_formset"]
        if contato_formset.is_valid():
            previous = previous_values(form)
            self.object = form.save()
            contato_formset.instance = self.object
            contato_formset.save()
            record_write(self.request, self.object, previous)
            messages.success(self.request, "Cliente atualizado com sucesso.")
            return redirect("clientes:cliente_detail", pk=self.object.pk)
        return self.render_to_response(self.get_context_data(form=form))


class UnidadeCreateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.CreateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = Unidade
    form_class = UnidadeForm
    template_name = "clientes/unidade_form.html"

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response

    def get_initial(self):
        initial = super().get_initial()
        cliente_id = self.request.GET.get("cliente")
        if cliente_id:
            initial["cliente"] = cliente_id
        return initial

    def get_success_url(self):
        messages.success(self.request, "Unidade cadastrada com sucesso.")
        return reverse_lazy("clientes:cliente_detail", kwargs={"pk": self.object.cliente_id})


class UnidadeUpdateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.UpdateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = Unidade
    form_class = UnidadeForm
    template_name = "clientes/unidade_form.html"

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response

    def get_success_url(self):
        messages.success(self.request, "Unidade atualizada com sucesso.")
        return reverse_lazy("clientes:cliente_detail", kwargs={"pk": self.object.cliente_id})
