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
        from django.db.models import Q, Count
        ctx["total_clientes"] = Cliente.objects.filter(ativo=True).count()
        eq_agg = Equipamento.objects.aggregate(
            total=Count('pk'),
            inoperantes=Count('pk', filter=Q(situacao_operacional=SituacaoOperacional.INOPERANTE)),
            restricao=Count('pk', filter=Q(situacao_operacional=SituacaoOperacional.RESTRICAO)),
        )
        ctx["total_equipamentos"] = eq_agg["total"]
        ctx["equipamentos_inoperantes"] = eq_agg["inoperantes"]
        ctx["equipamentos_restricao"] = eq_agg["restricao"]
        candidatos = list(
            Equipamento.objects.select_related("cliente")
            .filter(
                Q(periodicidade_preventiva_meses__isnull=False, data_ultima_preventiva__isnull=False) |
                Q(preventivaprogramada__isnull=False) |
                Q(agendapreventiva__isnull=False)
            )
            .distinct()[:50]
        )
        equipamentos_com_preventiva = [e for e in candidatos if e.proxima_preventiva]
        equipamentos_com_preventiva.sort(key=lambda e: e.proxima_preventiva)
        ctx["proximas_preventivas"] = equipamentos_com_preventiva[:8]

        from django.utils import timezone
        from django.db.models import F, Sum
        from ordens.services import visiveis
        from gestao.models import AgendaPreventiva, Contrato, Peca, Lancamento
        from gestao.permissions import allowed
        today = timezone.localdate()
        orders = visiveis(self.request.user)
        agenda_qs = AgendaPreventiva.objects.select_related('equipamento', 'contrato').filter(data_prevista__gte=today, data_prevista__lte=today + timezone.timedelta(days=30), cancelada=False).exclude(ordem__status__in=['FINALIZADA','APROVADA','FATURADA','CANCELADA']).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO'])
        if not allowed(self.request.user, 'contratos'):
            agenda_qs = agenda_qs.filter(tecnico__usuario=self.request.user)
        ctx['agenda_proxima'] = list(agenda_qs[:8])
        agenda_total = len(ctx['agenda_proxima']) if len(ctx['agenda_proxima']) < 8 else agenda_qs.count()
        ctx['preventivas_proximas_total'] = agenda_total + sum(today <= e.proxima_preventiva <= today + timezone.timedelta(days=30) for e in equipamentos_com_preventiva)
        if allowed(self.request.user, 'contratos'):
            ctx['contratos_proximos'] = Contrato.objects.exclude(status__in=['SUSPENSO', 'ENCERRADO']).filter(data_final__gte=today, data_final__lte=today + timezone.timedelta(days=30)).count()
        if allowed(self.request.user, 'estoque'):
            ctx['estoque_minimo_total'] = Peca.objects.filter(ativo=True, quantidade_atual__lte=F('estoque_minimo')).count()
        if allowed(self.request.user, 'financeiro'):
            fin_agg = Lancamento.objects.filter(status__in=['PENDENTE', 'VENCIDO']).aggregate(
                receber=Sum('valor', filter=Q(tipo='RECEBER')),
                vencidas=Count('pk', filter=Q(vencimento__lt=today)),
            )
            ctx['financeiro_receber'] = fin_agg['receber'] or 0
            ctx['financeiro_vencidas'] = fin_agg['vencidas']

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
