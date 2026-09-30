from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from clientes.models import Cliente
from equipamentos.models import Equipamento, SituacaoOperacional


class PainelView(LoginRequiredMixin, TemplateView):
    """
    Painel principal. Nesta Etapa 1, mostra os indicadores de cadastro
    já existentes (clientes e equipamentos). Os indicadores de Ordens
    de Serviço (abertas, agendadas, em execução, aguardando peça,
    atrasadas etc.) entram na Etapa 2, quando o app de OS existir —
    não fazia sentido simular esses números aqui.
    """

    template_name = "core/painel.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_clientes"] = Cliente.objects.filter(ativo=True).count()
        ctx["total_equipamentos"] = Equipamento.objects.count()
        ctx["equipamentos_inoperantes"] = Equipamento.objects.filter(
            situacao_operacional=SituacaoOperacional.INOPERANTE
        ).count()
        ctx["equipamentos_restricao"] = Equipamento.objects.filter(
            situacao_operacional=SituacaoOperacional.RESTRICAO
        ).count()

        equipamentos_com_preventiva = [
            e for e in Equipamento.objects.all() if e.proxima_preventiva
        ]
        equipamentos_com_preventiva.sort(key=lambda e: e.proxima_preventiva)
        ctx["proximas_preventivas"] = equipamentos_com_preventiva[:8]

        return ctx
