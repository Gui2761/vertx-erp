from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from clientes.models import Cliente
from equipamentos.models import Equipamento, SituacaoOperacional


class PainelView(LoginRequiredMixin, TemplateView):
    """Indicadores existentes e operacionais da organização, conforme permissões."""

    template_name = "core/painel.html"

    def get(self, request, *args, **kwargs):
        from django.shortcuts import redirect
        role = request.membership.role if request.membership else ''
        if role == 'TECNICO':
            return redirect('operacao:tecnico')
        if role in ['PLANEJADOR','ATENDIMENTO']:
            return redirect('operacao:calendario')
        if role == 'PAINEL':
            return redirect('operacao:operational_panel')
        return super().get(request,*args,**kwargs)

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

        from django.utils import timezone
        from django.db.models import F, Sum
        from ordens.services import visiveis
        from gestao.models import AgendaPreventiva, Contrato, Peca, Lancamento
        from gestao.permissions import allowed
        today = timezone.localdate()
        orders = visiveis(self.request.user)
        ctx['os_abertas'] = orders.filter(status='ABERTA').count()
        ctx['os_andamento'] = orders.filter(status='EXECUCAO').count()
        ctx['os_concluidas_mes'] = orders.filter(status='FINALIZADA', conclusao__date__gte=today.replace(day=1), conclusao__date__lte=today).count()
        agenda = AgendaPreventiva.objects.select_related('equipamento', 'contrato').filter(data_prevista__gte=today, data_prevista__lte=today + timezone.timedelta(days=30), cancelada=False).exclude(ordem__status__in=['FINALIZADA','APROVADA','FATURADA','CANCELADA']).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO'])
        if not allowed(self.request.user, 'contratos'):
            agenda = agenda.filter(tecnico__usuario=self.request.user)
        ctx['agenda_proxima'] = agenda[:8]
        ctx['preventivas_proximas_total'] = agenda.count() + sum(today <= e.proxima_preventiva <= today + timezone.timedelta(days=30) for e in equipamentos_com_preventiva)
        if allowed(self.request.user, 'contratos'):
            ctx['contratos_proximos'] = Contrato.objects.exclude(status__in=['SUSPENSO', 'ENCERRADO']).filter(data_final__gte=today, data_final__lte=today + timezone.timedelta(days=30)).count()
        if allowed(self.request.user, 'estoque'):
            ctx['estoque_minimo_total'] = Peca.objects.filter(ativo=True, quantidade_atual__lte=F('estoque_minimo')).count()
        if allowed(self.request.user, 'financeiro'):
            pending = Lancamento.objects.filter(status__in=['PENDENTE', 'VENCIDO'])
            ctx['financeiro_receber'] = pending.filter(tipo='RECEBER').aggregate(total=Sum('valor'))['total'] or 0
            ctx['financeiro_vencidas'] = pending.filter(vencimento__lt=today).count()

        from operacao.dashboard import indicators
        ctx.update(indicators(self.request.user))
        from platform_core.modules import module_enabled
        if allowed(self.request.user, 'executivo') and module_enabled('relatorios_basicos'):
            from operacao.executive import PeriodForm, context
            from platform_core.modules import analytics_level
            level = analytics_level()
            query = self.request.GET.copy()
            if not query.get('periodo'):
                query['periodo'] = 'MES'
            if not query.get('grafico'):
                query['grafico'] = '30'
            form = PeriodForm(query, analytics_level=level)
            if form.is_valid():
                ctx.update(context(self.request,form,orders))
            else:
                ctx.update(executive=True,period_form=form,executive_period_invalid=True)
        return ctx

    def render_to_response(self, context, **response_kwargs):
        if context.get('period_form') and context['period_form'].errors:
            response_kwargs['status'] = 400
        return super().render_to_response(context, **response_kwargs)
