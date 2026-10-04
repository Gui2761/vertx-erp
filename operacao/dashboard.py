from django.db.models import Count
from django.utils import timezone
from gestao.models import Contrato
from gestao.permissions import allowed
from gestao.reporting import financial_dashboard
from ordens.services import visiveis
from ordens.models import Status
from .models import PreventivaProgramada, ENCERRADAS

def indicators(user):
    today = timezone.localdate()
    orders = visiveis(user)
    ctx = {'os_abertas': orders.filter(status__in=['ABERTA','AGENDADA']).count(), 'os_andamento': orders.filter(status__in=['EXECUCAO','DESLOCAMENTO','AG_PECA','AG_CLIENTE','AG_APROVACAO']).count(), 'os_atrasadas': orders.filter(prazo__lt=timezone.now()).exclude(status__in=ENCERRADAS).count(), 'os_concluidas_mes': orders.filter(status__in=['FINALIZADA','APROVADA','FATURADA'], conclusao__date__range=(today.replace(day=1), today)).count()}
    occurrences = PreventivaProgramada.objects.filter(plano__ativo=True, cancelada=False).exclude(ordem__status__in=ENCERRADAS)
    if not allowed(user, 'contratos'):
        occurrences = occurrences.filter(plano__tecnico__usuario=user)
    ctx['novas_preventivas_proximas'] = occurrences.filter(data__range=(today, today + timezone.timedelta(days=30))).count()
    ctx['preventivas_atrasadas'] = occurrences.filter(data__lt=today).count()
    if allowed(user, 'contratos'):
        ctx['contratos_ativos'] = Contrato.objects.exclude(status__in=['SUSPENSO','ENCERRADO']).filter(data_inicial__lte=today, data_final__gte=today).count()
    if allowed(user, 'financeiro'):
        ctx['financeiro_kpis'] = financial_dashboard(today.replace(day=1), today)
        ctx['financeiro_receber'] = ctx['financeiro_kpis']['a_receber']
    totals = {row['status']: row['total'] for row in orders.values('status').annotate(total=Count('pk'))}
    max_total = max(totals.values(), default=1) or 1
    ctx['status_chart'] = [{'name': label, 'value': totals.get(code,0), 'width': round(100 * totals.get(code,0)/max_total)} for code,label in Status.choices]
    productivity = list(orders.filter(conclusao__date__range=(today.replace(day=1),today), status__in=['FINALIZADA','APROVADA','FATURADA']).values('tecnico__nome').annotate(total=Count('pk')).order_by('-total')[:10])
    maximum = max([row['total'] for row in productivity],default=1)
    ctx['productivity'] = [{'name':row['tecnico__nome'], 'value':row['total'], 'width': round(100*row['total']/maximum)} for row in productivity]
    ctx.update(operational_metrics(user, today.replace(day=1), today))
    return ctx

def operational_metrics(user, start, end):
    from django.db.models import Q
    from platform_core.access import effective_role
    from equipamentos.models import Equipamento
    from gestao.models import AgendaPreventiva, Peca
    from .models import Chamado, Compra
    from .stock import metrics
    orders = visiveis(user)
    scope = orders.filter(abertura__date__range=(start, end))
    finished = scope.filter(status__in=['FINALIZADA', 'APROVADA', 'FATURADA'])
    calls = Chamado.objects.exclude(status__in=['CONCLUIDO', 'CANCELADO'])
    plans = PreventivaProgramada.objects.filter(plano__ativo=True, cancelada=False)
    visits = AgendaPreventiva.objects.filter(cancelada=False).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO'])
    role = effective_role(user)
    if role == 'TECNICO':
        calls = calls.filter(Q(tecnico__usuario=user) | Q(ordem__in=orders))
        plans = plans.filter(Q(plano__tecnico__usuario=user) | Q(plano__equipe__usuario=user)).distinct()
        visits = visits.filter(tecnico__usuario=user)
    elif role not in ['ADMIN', 'GESTOR']:
        calls, plans, visits = calls.none(), plans.none(), visits.none()
    planned = list(plans.select_related('ordem').filter(data__range=(start, end))) + list(visits.select_related('ordem').filter(data_prevista__range=(start, end)))
    today = timezone.localdate()
    pending_plans = plans.exclude(ordem__status__in=ENCERRADAS)
    pending_visits = visits.exclude(ordem__status__in=ENCERRADAS)
    on_time = sum(bool(item.ordem_id and item.ordem.status in ['FINALIZADA', 'APROVADA', 'FATURADA'] and item.ordem.conclusao and timezone.localdate(item.ordem.conclusao) <= (item.data if isinstance(item, PreventivaProgramada) else item.data_prevista)) for item in planned)
    completed = sum(item.situacao == 'CONCLUIDA' for item in planned)
    start_hours = [(row.inicio - row.abertura).total_seconds() / 3600 for row in scope if row.inicio and row.inicio >= row.abertura]
    finish_hours = [(row.conclusao - row.inicio).total_seconds() / 3600 for row in finished if row.inicio and row.conclusao and row.conclusao >= row.inicio]
    cards = [('Chamados abertos', calls.count(), '/chamados/'), ('Aguardando peças', orders.filter(status='AG_PECA').count(), '/estoque/necessidades/'), ('Aguardando aprovação', orders.filter(status='AG_APROVACAO').count(), '/ordens/?status=AG_APROVACAO'),
             ('Preventivas vencidas', pending_plans.filter(data__lt=today).count() + pending_visits.filter(data_prevista__lt=today).count(), '/planejamento/?grupo=PREVENTIVAS_ATRASADAS'),
             ('Preventivas próximas (30 dias)', pending_plans.filter(data__range=(today, today + timezone.timedelta(days=30))).count() + pending_visits.filter(data_prevista__range=(today, today + timezone.timedelta(days=30))).count(), '/planejamento/?grupo=PREVENTIVAS')]
    if role in ['ADMIN', 'GESTOR']:
        cards += [('Contratos próximos (30 dias)', Contrato.objects.exclude(status__in=['SUSPENSO', 'ENCERRADO']).filter(data_final__range=(today, today + timezone.timedelta(days=30))).count(), '/relatorios/contratos_proximos/'),
                  ('Equipamentos ativos classificados', Equipamento.objects.filter(situacao_cadastro='ATIVO').count(), '/equipamentos/'),
                  ('Compras pendentes', Compra.objects.filter(status__in=['APROVADA', 'PEDIDO']).count(), '/relatorios/compras_pendentes/'),
                  ('Produtos em estoque crítico', sum(metrics(part)['disponivel'] <= part.estoque_minimo for part in Peca.objects.filter(ativo=True)), '/estoque/ocorrencias/?tipo=REPOSICAO')]
    def chart(field, identity=None):
        values = list(scope.values(*([identity, field] if identity else [field])).annotate(total=Count('pk')).order_by('-total')[:10])
        maximum = max((row['total'] for row in values), default=1)
        return [{'name': row[field] or 'Não informado', 'value': row['total'], 'width': round(100 * row['total'] / maximum)} for row in values]
    return {'operational_cards': cards, 'operational_charts': [('OS por tipo', chart('tipo_atendimento')), ('OS por cliente', chart('cliente__nome_razao_social', 'cliente_id')), ('Ocorrências por equipamento', chart('equipamento__nome', 'equipamento_id'))],
            'operational_summary': {'inicio': start, 'fim': end, 'total_os': scope.count(), 'concluidas': finished.count(), 'taxa_conclusao': round(100 * finished.count() / scope.count(), 1) if scope.exists() else None,
                                    'preventivas_previstas': len(planned), 'preventivas_realizadas': completed, 'preventivas_no_prazo': on_time, 'preventivas_atrasadas': sum(item.situacao not in ['CONCLUIDA', 'CANCELADA'] and (item.data if isinstance(item, PreventivaProgramada) else item.data_prevista) < today for item in planned),
                                    'horas_ate_atendimento': round(sum(start_hours) / len(start_hours), 2) if start_hours else None, 'horas_execucao': round(sum(finish_hours) / len(finish_hours), 2) if finish_hours else None}}
