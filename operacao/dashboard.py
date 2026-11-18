from django.db.models import Count
from django.utils import timezone
from gestao.models import Contrato
from gestao.permissions import allowed
from gestao.reporting import financial_dashboard
from ordens.services import visiveis
from ordens.models import Status
from .models import PreventivaProgramada, ENCERRADAS

def indicators(user):
    from django.db.models import Q
    today = timezone.localdate()
    now = timezone.now()
    month_start = today.replace(day=1)
    orders = visiveis(user)
    totals = {row['status']: row['total'] for row in orders.values('status').annotate(total=Count('pk'))}
    extra_os = orders.aggregate(
        atrasadas=Count('pk', filter=Q(prazo__lt=now) & ~Q(status__in=ENCERRADAS)),
        concluidas_mes=Count('pk', filter=Q(status__in=['FINALIZADA','APROVADA','FATURADA'], conclusao__date__range=(month_start, today))),
    )
    ctx = {
        'os_abertas': totals.get('ABERTA', 0) + totals.get('AGENDADA', 0),
        'os_andamento': sum(totals.get(s, 0) for s in ('EXECUCAO','DESLOCAMENTO','AG_PECA','AG_CLIENTE','AG_APROVACAO')),
        'os_atrasadas': extra_os['atrasadas'],
        'os_concluidas_mes': extra_os['concluidas_mes'],
    }
    occurrences = PreventivaProgramada.objects.filter(plano__ativo=True, cancelada=False).exclude(ordem__status__in=ENCERRADAS)
    if not allowed(user, 'contratos'):
        occurrences = occurrences.filter(plano__tecnico__usuario=user)
    occ_agg = occurrences.aggregate(
        proximas=Count('pk', filter=Q(data__range=(today, today + timezone.timedelta(days=30)))),
        atrasadas=Count('pk', filter=Q(data__lt=today)),
    )
    ctx['novas_preventivas_proximas'] = occ_agg['proximas']
    ctx['preventivas_atrasadas'] = occ_agg['atrasadas']
    if allowed(user, 'contratos'):
        ctx['contratos_ativos'] = Contrato.objects.exclude(status__in=['SUSPENSO','ENCERRADO']).filter(data_inicial__lte=today, data_final__gte=today).count()
    if allowed(user, 'financeiro'):
        ctx['financeiro_kpis'] = financial_dashboard(month_start, today)
        ctx['financeiro_receber'] = ctx['financeiro_kpis']['a_receber']
    max_total = max(totals.values(), default=1) or 1
    ctx['status_chart'] = [{'name': label, 'value': totals.get(code,0), 'width': round(100 * totals.get(code,0)/max_total)} for code,label in Status.choices]
    productivity = list(orders.filter(conclusao__date__range=(month_start,today), status__in=['FINALIZADA','APROVADA','FATURADA']).values('tecnico__nome').annotate(total=Count('pk')).order_by('-total')[:10])
    maximum = max([row['total'] for row in productivity],default=1)
    ctx['productivity'] = [{'name':row['tecnico__nome'], 'value':row['total'], 'width': round(100*row['total']/maximum)} for row in productivity]
    ctx.update(operational_metrics(user, month_start, today, status_totals=totals))
    return ctx

def operational_metrics(user, start, end, status_totals=None):
    from django.db.models import Q
    from platform_core.access import effective_role
    from equipamentos.models import Equipamento
    from gestao.models import AgendaPreventiva, Peca
    from .models import Chamado, Compra
    orders = visiveis(user)
    scope_list = list(orders.filter(abertura__date__range=(start, end)))
    finished_list = [r for r in scope_list if r.status in ('FINALIZADA', 'APROVADA', 'FATURADA')]
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
    start_hours = [(row.inicio - row.abertura).total_seconds() / 3600 for row in scope_list if row.inicio and row.inicio >= row.abertura]
    finish_hours = [(row.conclusao - row.inicio).total_seconds() / 3600 for row in finished_list if row.inicio and row.conclusao and row.conclusao >= row.inicio]
    ag_peca_cnt = status_totals.get('AG_PECA', 0) if status_totals is not None else orders.filter(status='AG_PECA').count()
    ag_aprov_cnt = status_totals.get('AG_APROVACAO', 0) if status_totals is not None else orders.filter(status='AG_APROVACAO').count()
    pp_agg = pending_plans.aggregate(
        vencidas=Count('pk', filter=Q(data__lt=today)),
        proximas=Count('pk', filter=Q(data__range=(today, today + timezone.timedelta(days=30)))),
    )
    pv_agg = pending_visits.aggregate(
        vencidas=Count('pk', filter=Q(data_prevista__lt=today)),
        proximas=Count('pk', filter=Q(data_prevista__range=(today, today + timezone.timedelta(days=30)))),
    )
    cards = [('Chamados abertos', calls.count(), '/chamados/'), ('Aguardando peças', ag_peca_cnt, '/estoque/necessidades/'), ('Aguardando aprovação', ag_aprov_cnt, '/ordens/?status=AG_APROVACAO'),
             ('Preventivas vencidas', pp_agg['vencidas'] + pv_agg['vencidas'], '/planejamento/?grupo=PREVENTIVAS_ATRASADAS'),
             ('Preventivas próximas (30 dias)', pp_agg['proximas'] + pv_agg['proximas'], '/planejamento/?grupo=PREVENTIVAS')]
    if role in ['ADMIN', 'GESTOR']:
        from .stock import available_map
        avail_by_id = available_map(today)
        critical_count = sum(
            avail_by_id.get(pk, 0) <= minimo
            for pk, minimo in Peca.objects.filter(ativo=True).values_list('pk', 'estoque_minimo')
        )
        cards += [('Contratos próximos (30 dias)', Contrato.objects.exclude(status__in=['SUSPENSO', 'ENCERRADO']).filter(data_final__range=(today, today + timezone.timedelta(days=30))).count(), '/relatorios/contratos_proximos/'),
                  ('Equipamentos ativos classificados', Equipamento.objects.filter(situacao_cadastro='ATIVO').count(), '/equipamentos/'),
                  ('Compras pendentes', Compra.objects.filter(status__in=['APROVADA', 'PEDIDO']).count(), '/relatorios/compras_pendentes/'),
                  ('Produtos em estoque crítico', critical_count, '/estoque/ocorrencias/?tipo=REPOSICAO')]
    scope = orders.filter(abertura__date__range=(start, end))
    def chart(field, identity=None):
        values = list(scope.values(*([identity, field] if identity else [field])).annotate(total=Count('pk')).order_by('-total')[:10])
        maximum = max((row['total'] for row in values), default=1)
        return [{'name': row[field] or 'Não informado', 'value': row['total'], 'width': round(100 * row['total'] / maximum)} for row in values]
    total_os_cnt = len(scope_list)
    concluidas_cnt = len(finished_list)
    return {'operational_cards': cards, 'operational_charts': [('OS por tipo', chart('tipo_atendimento')), ('OS por cliente', chart('cliente__nome_razao_social', 'cliente_id')), ('Ocorrências por equipamento', chart('equipamento__nome', 'equipamento_id'))],
            'operational_summary': {'inicio': start, 'fim': end, 'total_os': total_os_cnt, 'concluidas': concluidas_cnt, 'taxa_conclusao': round(100 * concluidas_cnt / total_os_cnt, 1) if total_os_cnt else None,
                                    'preventivas_previstas': len(planned), 'preventivas_realizadas': completed, 'preventivas_no_prazo': on_time, 'preventivas_atrasadas': sum(item.situacao not in ['CONCLUIDA', 'CANCELADA'] and (item.data if isinstance(item, PreventivaProgramada) else item.data_prevista) < today for item in planned),
                                    'horas_ate_atendimento': round(sum(start_hours) / len(start_hours), 2) if start_hours else None, 'horas_execucao': round(sum(finish_hours) / len(finish_hours), 2) if finish_hours else None}}
