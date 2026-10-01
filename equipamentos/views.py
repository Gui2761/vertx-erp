from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import generic
from contas.permissions import PerfilRequeridoMixin
from django.db import transaction
from platform_core.audit import previous_values, record_write

from clientes.models import Unidade
from .forms import EquipamentoForm, CategoriaForm
from .models import CategoriaEquipamento, Equipamento


class EquipamentoListView(LoginRequiredMixin, generic.ListView):
    model = Equipamento
    template_name = "equipamentos/equipamento_list.html"
    context_object_name = "equipamentos"
    paginate_by = 20

    def get_queryset(self):
        qs = Equipamento.objects.select_related("cliente", "unidade", "categoria")
        busca = self.request.GET.get("q")
        if busca:
            qs = qs.filter(nome__icontains=busca) | qs.filter(codigo_interno__icontains=busca) | qs.filter(
                numero_serie__icontains=busca
            )
        cliente_id = self.request.GET.get("cliente")
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        categoria_id = self.request.GET.get("categoria")
        if categoria_id:
            qs = qs.filter(categoria_id=categoria_id)
        situacao = self.request.GET.get("situacao")
        if situacao:
            qs = qs.filter(situacao_operacional=situacao)
        return qs.order_by("nome")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categorias"] = CategoriaEquipamento.objects.all()
        return ctx


class EquipamentoDetailView(LoginRequiredMixin, generic.DetailView):
    model = Equipamento
    template_name = "equipamentos/equipamento_detail.html"
    context_object_name = "equipamento"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from operacao.history import related
        ctx.update(related(self.request.user, self.object.cliente, self.object))
        return ctx


class EquipamentoCreateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.CreateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = Equipamento
    form_class = EquipamentoForm
    template_name = "equipamentos/equipamento_form.html"

    @transaction.atomic
    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.save()
        self.object.gerar_qr_code(base_url=self.request.build_absolute_uri("/").rstrip("/"))
        self.object.save()
        messages.success(self.request, "Equipamento cadastrado com sucesso.")
        record_write(self.request, self.object, {})
        return redirect("equipamentos:equipamento_detail", pk=self.object.pk)


class EquipamentoUpdateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.UpdateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = Equipamento
    form_class = EquipamentoForm
    template_name = "equipamentos/equipamento_form.html"

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response

    def get_success_url(self):
        messages.success(self.request, "Equipamento atualizado com sucesso.")
        return reverse_lazy("equipamentos:equipamento_detail", kwargs={"pk": self.object.pk})


class EquipamentoQrRedirectView(EquipamentoDetailView):
    """
    Destino do QR Code impresso na etiqueta. Exige login: quem escanear
    sem ter conta/permissão no sistema não acessa a ficha.
    """

    model = Equipamento
    slug_field = "codigo_publico"
    slug_url_kwarg = "codigo_publico"
    template_name = "equipamentos/equipamento_detail.html"
    context_object_name = "equipamento"


@login_required
def unidades_por_cliente(request):
    """Endpoint simples usado via HTMX para popular o combo de unidades."""
    cliente_id = request.GET.get("cliente")
    unidades = Unidade.objects.filter(cliente_id=cliente_id, ativo=True) if cliente_id and cliente_id.isdigit() else []
    return JsonResponse(
        {"unidades": [{"id": u.id, "nome": u.nome} for u in unidades]}
    )


class CategoriaCreateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.CreateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = CategoriaEquipamento
    form_class = CategoriaForm
    template_name = 'ordens/form.html'
    extra_context = {'titulo': 'Nova categoria de equipamento'}
    success_url = reverse_lazy('equipamentos:equipamento_list')

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response


class CategoriaUpdateView(LoginRequiredMixin, PerfilRequeridoMixin, generic.UpdateView):
    perfis_permitidos = ('ADMIN', 'GESTOR')
    model = CategoriaEquipamento
    form_class = CategoriaForm
    template_name = 'ordens/form.html'
    success_url = reverse_lazy('equipamentos:equipamento_list')
    extra_context = {'titulo': 'Editar categoria de equipamento'}

    @transaction.atomic
    def form_valid(self, form):
        previous = previous_values(form)
        response = super().form_valid(form)
        record_write(self.request, self.object, previous)
        return response
