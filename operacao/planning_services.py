"""Uma agenda derivada das OS e das duas origens de preventiva já existentes."""
from datetime import datetime, time
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse
from platform_core.access import require_erp, effective_role, membership_for, has_erp_access
from platform_core.context import current_organization
from platform_core.models import MembershipERP, Organization
from contas.models import Tecnico
from ordens.models import OrdemServico
from ordens.services import auditar, salvar_transicao, gestor
from .models import ENCERRADAS, PreventivaProgramada, Chamado
from gestao.models import AgendaPreventiva

PLANNERS = ('ADMIN', 'GESTOR', 'PLANEJADOR', 'ATENDIMENTO')

def require_planning(user, writing=False):
    return require_erp(user, roles=PLANNERS if writing else PLANNERS + ('TECNICO',))

def can_tv(user):
    member = membership_for(user)
    return bool(member and member.role != 'CLIENTE' and has_erp_access(user) and MembershipERP.objects.filter(membership=member, erp__code='assistencia', enabled=True, visualizar_painel_operacional=True).exists())

def require_tv(user):
    if not can_tv(user):
        raise PermissionDenied('Permissão Visualizar painel operacional necessária nesta organização.')

def television_rows(user):
    require_tv(user)
    return _orders(), Tecnico.objects.filter(ativo=True).order_by('nome','pk')

def _orders():
    from django.db.models import Prefetch
    return OrdemServico.objects.select_related('cliente','unidade__cliente','equipamento','tecnico','contrato','agenda_contrato__contrato','preventivaprogramada__plano__contrato').prefetch_related(Prefetch('auxiliares', queryset=Tecnico.objects.filter(ativo=True)))

def orders_for(user, television=False):
    if television:
        require_tv(user)
    else:
        require_planning(user)
    rows = _orders()
    if television or effective_role(user) in PLANNERS:
        return rows
    from ordens.services import visiveis
    return rows.filter(pk__in=visiveis(user).values('pk'))

def technicians_for(user, television=False):
    if television:
        require_tv(user)
    else:
        require_planning(user)
    rows = Tecnico.objects.filter(ativo=True).order_by('nome', 'pk')
    return rows if television or effective_role(user) in PLANNERS else rows.filter(usuario=user)

def late(row, now=None):
    now = now or timezone.now()
    return row.status not in ENCERRADAS and bool(row.prazo and row.prazo < now or row.agendada_para and row.agendada_para < now and not row.inicio or row.agendada_ate and row.agendada_ate < now)

def overlap(start, end, other_start, other_end):
    # Sem duração, só é possível identificar coincidência/ponto dentro de intervalo.
    if not start or not other_start:
        return False
    if not end and not other_end:
        return start == other_start
    if not end:
        return other_start <= start < other_end
    if not other_end:
        return start <= other_start < end
    return start < other_end and other_start < end

def conflicts(row, auxiliary_ids=None, exclude_call_id=None):
    team = set(auxiliary_ids or [])
    if isinstance(row, OrdemServico) and row.pk and auxiliary_ids is None:
        team.update(tech.pk for tech in row.auxiliares.all())
    if row.tecnico_id:
        team.add(row.tecnico_id)
    if not team or not row.agendada_para or row.status in ENCERRADAS or row.status == 'CANCELADO':
        return []
    rows = OrdemServico.objects.filter(Q(tecnico_id__in=team) | Q(auxiliares__pk__in=team), agendada_para__isnull=False).exclude(status__in=ENCERRADAS).distinct()
    if isinstance(row, OrdemServico):
        rows = rows.exclude(pk=row.pk)
    # Limite superior evita leitura do histórico futuro inteiro. Intervalos longos
    # iniciados anteriormente são mantidos, inclusive os que atravessam meia-noite.
    upper = row.agendada_ate or row.agendada_para
    rows = rows.filter(agendada_para__lte=upper).filter(Q(agendada_ate__gt=row.agendada_para) | Q(agendada_ate__isnull=True, agendada_para__gte=row.agendada_para))
    calls = Chamado.objects.filter(tecnico_id__in=team, ordem__isnull=True, agendada_para__isnull=False).exclude(status__in=['CANCELADO', 'CONCLUIDO'])
    if isinstance(row, Chamado):
        calls = calls.exclude(pk=row.pk)
    elif exclude_call_id:
        calls = calls.exclude(pk=exclude_call_id)
    calls = calls.filter(agendada_para__lte=upper).filter(Q(agendada_ate__gt=row.agendada_para) | Q(agendada_ate__isnull=True, agendada_para__gte=row.agendada_para))
    return [other for other in list(rows.order_by('agendada_para', 'pk')) + list(calls.order_by('agendada_para', 'pk')) if overlap(row.agendada_para, row.agendada_ate, other.agendada_para, other.agendada_ate)]

def conflict_map(rows):
    result = {}
    grouped = {}
    for row in rows:
        if row.tecnico_id and row.agendada_para and row.status not in ENCERRADAS:
            grouped.setdefault(row.tecnico_id, []).append(row)
            for tech_id in (tech.pk for tech in row.auxiliares.all()):
                if tech_id != row.tecnico_id:
                    grouped.setdefault(tech_id, []).append(row)
    for group in grouped.values():
        group.sort(key=lambda row: row.agendada_para)
        for index, row in enumerate(group):
            for other in group[index + 1:]:
                if other.agendada_para > (row.agendada_ate or row.agendada_para):
                    break
                if overlap(row.agendada_para, row.agendada_ate, other.agendada_para, other.agendada_ate):
                    result.setdefault(row.pk, set()).add(other.numero)
                    result.setdefault(other.pk, set()).add(row.numero)
    return result

def origin(row):
    occurrence = getattr(row, 'preventivaprogramada', None)
    agenda = getattr(row, 'agenda_contrato', None)
    contract = row.contrato or (occurrence.plano.contrato if occurrence else None) or (agenda.contrato if agenda else None)
    return contract, 'Plano preventivo' if occurrence else 'Visita contratual' if agenda else 'OS'

def order_event(row, conflict=None):
    contract, source = origin(row)
    scheduled = row.agendada_para
    reference = row.conclusao if row.status in ['FINALIZADA','APROVADA','FATURADA'] and row.conclusao else scheduled or row.inicio
    day = timezone.localdate(reference) if reference else None
    return {'id': row.pk, 'kind': 'OS', 'numero': row.numero, 'title': f'{row.numero} · {row.cliente}',
            'cliente': str(row.cliente), 'cliente_id': row.cliente_id, 'unidade': str(row.unidade or 'Sem unidade'), 'unidade_id': row.unidade_id,
            'equipamento': row.equipamento.nome, 'equipamento_id': row.equipamento_id,
            'tecnico': row.tecnico.nome if row.tecnico_id else 'Não atribuído', 'tecnico_id': row.tecnico_id,
            'tecnico_ids': ([row.tecnico_id] if row.tecnico_id else []) + [tech.pk for tech in row.auxiliares.all()],
            'tipo': row.get_tipo_atendimento_display(), 'tipo_code': row.tipo_atendimento,
            'prioridade': row.get_prioridade_display(), 'prioridade_code': row.prioridade,
            'status': row.get_status_display(), 'status_code': row.status, 'source': source,
            'contrato': contract.numero if contract else '', 'contrato_id': contract.pk if contract else None,
            'date': day, 'time': timezone.localtime(reference).strftime('%H:%M') if reference else '',
            'time_origin':'Conclusão' if reference and reference==row.conclusao else 'Agendamento' if scheduled else 'Início' if row.inicio else '',
            'start': scheduled.isoformat() if scheduled else None, 'end': row.agendada_ate.isoformat() if row.agendada_ate else None,
            'late': late(row), 'unplanned': row.status not in ENCERRADAS+['EXECUCAO'] and (not scheduled or not row.tecnico_id), 'conflicts': sorted(conflict or []),
            'inicio': row.inicio.isoformat() if row.inicio else None, 'conclusao': row.conclusao.isoformat() if row.conclusao else None,
            'abertura_label':timezone.localtime(row.abertura).strftime('%d/%m/%Y %H:%M'), 'prazo_label':timezone.localtime(row.prazo).strftime('%d/%m/%Y %H:%M') if row.prazo else '',
            'prazo': row.prazo.isoformat() if row.prazo else None, 'abertura': row.abertura.isoformat(), 'revisao': row.revisao}

def preventive_events(user, television=False):
    first = PreventivaProgramada.objects.filter(plano__ativo=True, cancelada=False, ordem__isnull=True).select_related('plano__cliente', 'plano__tecnico', 'plano__contrato', 'equipamento__unidade__cliente').prefetch_related('plano__equipe')
    second = AgendaPreventiva.objects.filter(cancelada=False, ordem__isnull=True).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO']).select_related('contrato__cliente', 'tecnico', 'equipamento__unidade__cliente')
    if not television and effective_role(user) == 'TECNICO':
        first = first.filter(Q(plano__tecnico__usuario=user) | Q(plano__equipe__usuario=user, plano__equipe__ativo=True)).distinct()
        second = second.filter(tecnico__usuario=user)
    items = []
    today = timezone.localdate()
    for rows, kind in [(first, 'PREVENTIVA'), (second, 'VISITA')]:
        for row in rows:
            plan = row.plano if kind == 'PREVENTIVA' else None
            contract = plan.contrato if plan else row.contrato
            customer = plan.cliente if plan else contract.cliente
            tech = plan.tecnico if plan else row.tecnico
            day = row.data if plan else row.data_prevista
            url = reverse('operacao:plano_detalhe', args=[plan.pk]) if plan else reverse('gestao:planejamento')
            items.append({'id': row.pk, 'kind': kind, 'numero': f'PREV-{row.pk}' if plan else f'VISITA-{row.pk}', 'title': plan.nome if plan else contract.numero,
                          'cliente': str(customer), 'cliente_id': customer.pk, 'unidade': str(row.equipamento.unidade or 'Sem unidade'), 'unidade_id': row.equipamento.unidade_id,
                          'equipamento': row.equipamento.nome, 'equipamento_id': row.equipamento_id, 'tecnico': tech.nome if tech else 'Não atribuído', 'tecnico_id': tech.pk if tech else None,
                          'tecnico_ids': ([tech.pk] if tech else []) + ([aux.pk for aux in plan.equipe.all() if aux.ativo] if plan else []),
                          'tipo': 'Preventiva' if plan else 'Visita contratual', 'tipo_code': plan.tipo_manutencao or 'PREVENTIVA' if plan else 'PREVENTIVA', 'prioridade': 'Normal', 'prioridade_code': 'NORMAL',
                          'status': 'Preventiva pendente', 'status_code': 'PREVENTIVA', 'source': 'Plano preventivo' if plan else 'Visita contratual',
                          'contrato': contract.numero if contract else '', 'contrato_id': contract.pk if contract else None, 'date': day, 'time': '',
                          'start': None, 'end': None, 'late': day < today, 'unplanned': not tech, 'conflicts': [], 'url': url})
    return items

def call_events(user, television=False):
    if television:
        require_tv(user)
    else:
        require_planning(user)
    qs = Chamado.objects.filter(ordem__isnull=True).exclude(status__in=['CANCELADO', 'CONCLUIDO']).select_related('cliente', 'unidade', 'equipamento', 'tecnico', 'contrato')
    if not television and effective_role(user) == 'TECNICO':
        qs = qs.filter(tecnico__usuario=user)
    events = []
    for row in qs:
        scheduled = row.agendada_para
        events.append({'id': row.pk, 'kind': 'CHAMADO', 'numero': row.numero, 'title': row.titulo, 'cliente': str(row.cliente), 'cliente_id': row.cliente_id,
            'unidade': str(row.unidade or 'Sem unidade'), 'unidade_id': row.unidade_id, 'equipamento': row.equipamento.nome if row.equipamento_id else 'Não informado', 'equipamento_id': row.equipamento_id,
            'tecnico': row.tecnico.nome if row.tecnico_id else 'Não atribuído', 'tecnico_id': row.tecnico_id, 'tipo': row.get_tipo_display() or 'Chamado', 'tipo_code': row.tipo,
            'prioridade': row.get_prioridade_display(), 'prioridade_code': row.prioridade, 'status': row.get_status_display(), 'status_code': row.status, 'source': 'Chamado',
            'contrato': row.contrato.numero if row.contrato_id else '', 'contrato_id': row.contrato_id, 'date': timezone.localdate(scheduled) if scheduled else None, 'time': timezone.localtime(scheduled).strftime('%H:%M') if scheduled else '',
            'start': scheduled.isoformat() if scheduled else None, 'end': row.agendada_ate.isoformat() if row.agendada_ate else None, 'late': bool(row.prazo and row.prazo < timezone.now()), 'unplanned': not scheduled or not row.tecnico_id,
            'conflicts': [other.numero for other in conflicts(row)], 'url': reverse('operacao:chamado_detalhe', args=[row.pk]), 'inicio': None, 'conclusao': None, 'abertura': row.criado_em.isoformat()})
    return events

def lock_planning():
    # Uma alteração de agenda por organização; protege conflitos inclusive quando
    # duas sessões criam a primeira OS simultaneamente, sem tabela paralela.
    Organization.objects.select_for_update().get(pk=current_organization().pk)

def validate_conflicts(user, row, override=False, reason='', auxiliary_ids=None, exclude_call_id=None):
    found = conflicts(row, auxiliary_ids=auxiliary_ids, exclude_call_id=exclude_call_id)
    if found and (not override or not gestor(user) or not reason.strip()):
        raise ValidationError('Conflito com ' + ', '.join(other.numero for other in found) + '. ADMIN/GESTOR pode autorizar no planejamento com justificativa.')
    return [{'id': other.pk, 'numero': other.numero, 'duracao_informada': bool(other.agendada_ate)} for other in found]

def validate_call_conflicts(user, call):
    return validate_conflicts(user, call)

@transaction.atomic
def save_plan(user, form, pk=None):
    require_planning(user, writing=True)
    lock_planning()
    old = OrdemServico.objects.select_for_update().get(pk=pk) if pk else None
    if old and (old.status in ENCERRADAS or old.status == 'EXECUCAO'):
        raise ValidationError('OS encerrada ou em execução não pode ser reprogramada. Use os fluxos existentes.')
    if old and form.cleaned_data['revisao'] != old.revisao:
        raise ValidationError('A OS mudou em outra sessão. Recarregue antes de salvar.')
    fields = ['tecnico', 'agendada_para', 'agendada_ate', 'prioridade']
    before = {name: str(getattr(old, name)) if getattr(old, name) is not None else '' for name in fields} if old else {}
    row = old or form.save(commit=False)
    if old:
        for name in fields:
            setattr(row, name, form.cleaned_data[name])
        row.revisao += 1
    found = validate_conflicts(user, row, form.cleaned_data.get('autorizar_conflito'), form.cleaned_data.get('justificativa', ''))
    if row.status in ['ABERTA', 'AGENDADA']:
        row.status = 'AGENDADA' if row.agendada_para and row.tecnico_id else 'ABERTA'
    salvar_transicao(row)
    # Mantém os vínculos anteriores de preventiva, sem gerar outra ocorrência/OS.
    agenda = AgendaPreventiva.objects.filter(ordem=row).first()
    if agenda and agenda.tecnico_id != row.tecnico_id:
        agenda.tecnico = row.tecnico
        agenda.save()
    after = {name: str(getattr(row, name)) if getattr(row, name) is not None else '' for name in fields}
    auditar(row, user, 'PLANEJAMENTO' if old else 'CRIACAO', {'agenda': {'anterior': before, 'posterior': after}, 'conflitos_autorizados': found}, form.cleaned_data.get('justificativa', ''))
    return row

def timeline_rows(technicians, events, day):
    result = []
    zone = timezone.get_current_timezone()
    lower = timezone.make_aware(datetime.combine(day, time(7)), zone)
    upper = timezone.make_aware(datetime.combine(day, time(17)), zone)
    for tech in technicians:
        own = [event for event in events if tech.pk in event.get('tecnico_ids', [event['tecnico_id']]) and event['date'] == day]
        bars = []
        hours = 0
        for event in own:
            if event.get('start'):
                start = datetime.fromisoformat(event['start'])
                end = datetime.fromisoformat(event['end']) if event.get('end') else None
                if end:
                    hours += (end-start).total_seconds()/3600
                if start < upper and (not end and start >= lower or end and end > lower):
                    bars.append(dict(event, left=max(0, (start-lower).total_seconds()/36000*100), width=max(0,(min(end,upper)-max(start,lower)).total_seconds()/36000*100) if end else 0))
        result.append({'tecnico': tech.nome, 'id': tech.pk, 'events': own, 'bars': bars, 'total': len(own), 'horas': round(hours, 2),
                       'sem_duracao': sum(not event.get('end') for event in own), 'concluidas': sum(event['status_code'] in ['FINALIZADA','APROVADA','FATURADA'] for event in own),
                       'pendentes': sum(event['status_code'] not in ENCERRADAS for event in own), 'atrasadas': sum(event['late'] for event in own),
                       'conflito': any(event['conflicts'] for event in own), 'sobrecarga': hours > 10})
    return result
