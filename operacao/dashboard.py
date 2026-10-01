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
    ctx = {'os_abertas': orders.filter(status__in=['ABERTA','AGENDADA']).count(), 'os_andamento': orders.filter(status__in=['EXECUCAO','AG_PECA','AG_CLIENTE']).count(), 'os_atrasadas': orders.filter(prazo__lt=timezone.now()).exclude(status__in=ENCERRADAS).count(), 'os_concluidas_mes': orders.filter(status__in=['FINALIZADA','APROVADA','FATURADA'], conclusao__date__range=(today.replace(day=1), today)).count()}
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
    return ctx
