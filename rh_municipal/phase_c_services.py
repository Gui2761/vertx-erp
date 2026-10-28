"""Audited services for municipal HR and Digital Timekeeping."""
import uuid
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from platform_core.context import current_organization

from .models import (
    AcessoMunicipal, DecisaoPontoMunicipal, EventoPontoDigital,
    JustificativaPontoMunicipal, MovimentacaoBancoHorasMunicipal,
    PeriodoPontoMunicipal, PontoServidor, Servidor,
    SnapshotFechamentoPontoMunicipal, SolicitacaoHoraExtraMunicipal,
)
from .public_services import has_municipal_permission, require_municipal_permission, scoped_queryset


def require_module_permission(user, capability, module='ponto_digital', record=None):
    require_municipal_permission(user, capability, module=module, record=record)
    return current_organization()


def own_server(user, organization=None, *, for_update=False):
    organization = organization or current_organization()
    if organization is None:
        raise PermissionDenied('Selecione uma Prefeitura autorizada.')
    rows = Servidor.objects.filter(organization=organization, usuario=user, ativo=True)
    if for_update:
        rows = rows.select_for_update()
    row = rows.first()
    if row is None:
        raise PermissionDenied('Não há ficha ativa vinculada à sua conta nesta Prefeitura.')
    return row


def _period_for(org, day):
    return PeriodoPontoMunicipal.objects.filter(organization=org, ano=day.year, mes=day.month).first()


def _ensure_period_open(org, day):
    period = _period_for(org, day)
    if period and period.status in {PeriodoPontoMunicipal.Status.AGUARDANDO_APROVACAO,
                                    PeriodoPontoMunicipal.Status.APROVADO,
                                    PeriodoPontoMunicipal.Status.FECHADO}:
        raise ValidationError('O período está aguardando aprovação ou já foi fechado; procure o responsável pelo Ponto.')


def _event(server, actor, action, entity, entity_id=None, before=None, after=None, reason=''):
    row = EventoPontoDigital(
        organization=server.organization, servidor=server, acao=action,
        entidade=entity, entidade_id=entity_id, antes=before or {},
        depois=after or {}, motivo=reason, ator=actor,
    )
    row._service_write = True
    row.save()
    return row


@transaction.atomic
def register_punch(user, kind, request_id, *, request=None, device='', latitude=None, longitude=None):
    org = current_organization()
    if not (has_municipal_permission(user, 'ponto.register', module='ponto_digital')
            or has_municipal_permission(user, 'servidor.portal', module='ponto_digital')):
        raise PermissionDenied('Você não possui autorização para registrar ponto nesta Prefeitura.')
    try:
        request_id = uuid.UUID(str(request_id))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError('Identificador da operação inválido.')
    server = own_server(user, org, for_update=True)
    prior = PontoServidor.objects.filter(organization=org, request_id=request_id).first()
    if prior:
        if prior.servidor_id != server.pk:
            raise PermissionDenied('O identificador já pertence a outro servidor.')
        return prior, False
    allowed = {'ENTRADA', 'SAIDA_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA'}
    if kind not in allowed:
        raise ValidationError('Tipo de marcação inválido.')
    now = timezone.now()
    local_now = timezone.localtime(now)
    _ensure_period_open(org, local_now.date())
    last = PontoServidor.objects.filter(organization=org, servidor=server,
                                       data_hora__date=local_now.date()).order_by('-data_hora', '-pk').first()
    sequence = {
        None: {'ENTRADA'}, 'SAIDA': {'ENTRADA'}, 'ENTRADA': {'SAIDA_INTERVALO', 'SAIDA'},
        'SAIDA_INTERVALO': {'RETORNO_INTERVALO'}, 'RETORNO_INTERVALO': {'SAIDA_INTERVALO', 'SAIDA'},
    }
    if kind not in sequence.get(last.tipo if last else None, set()):
        raise ValidationError('Esta marcação não corresponde à próxima etapa da jornada registrada hoje.')
    origin = 'WEB'
    user_agent = (request.META.get('HTTP_USER_AGENT', '') if request else '').lower()
    if any(marker in user_agent for marker in ('iphone', 'ipad', 'android', 'mobile')):
        origin = 'MOBILE'
    kwargs = {
        'organization': org, 'servidor': server, 'request_id': request_id,
        'tipo': kind, 'data_hora': now, 'origem': origin,
        'dispositivo': str(device or user_agent[:160])[:160],
        'endereco_ip': request.META.get('REMOTE_ADDR') if request else None,
        'registrado_por': user,
    }
    location_allowed = bool(getattr(settings, 'MUNICIPAL_POINT_LOCATION_ENABLED', False))
    if location_allowed and latitude not in (None, '') and longitude not in (None, ''):
        try:
            lat, lon = float(latitude), float(longitude)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
            kwargs.update(latitude=lat, longitude=lon)
        except (TypeError, ValueError):
            raise ValidationError('Localização inválida.')
    row = PontoServidor(**kwargs)
    row._service_write = True
    try:
        # Isolate the unique-key race in a savepoint so the surrounding
        # transaction remains queryable after a duplicate request.
        with transaction.atomic():
            row.save()
    except IntegrityError:
        existing = PontoServidor.objects.filter(organization=org, request_id=request_id, servidor=server).first()
        if existing:
            return existing, False
        raise
    _event(server, user, 'PONTO_REGISTRADO', 'PontoServidor', row.pk,
           after={'tipo': row.tipo, 'data_hora': row.data_hora.isoformat(), 'origem': row.origem})
    return row, True


@transaction.atomic
def register_manual_punch(user, *, server_id, kind, occurred_at, reason):
    """Add a manager-authorized correction as a separate immutable event."""
    require_module_permission(user, 'ponto.adjust')
    org = current_organization()
    server = scoped_queryset(user, Servidor.objects.select_for_update()).filter(
        organization=org, pk=server_id, ativo=True,
    ).first()
    if server is None:
        raise PermissionDenied('Servidor fora do seu escopo municipal.')
    require_module_permission(user, 'ponto.adjust', record=server)
    if kind not in {'ENTRADA', 'SAIDA_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA'}:
        raise ValidationError('Tipo de marcação inválido.')
    if not reason or not reason.strip():
        raise ValidationError('Informe o motivo do ajuste manual.')
    local_time = timezone.localtime(occurred_at)
    _ensure_period_open(org, local_time.date())
    last = PontoServidor.objects.filter(
        organization=org, servidor=server, data_hora__date=local_time.date(),
    ).order_by('-data_hora', '-pk').first()
    sequence = {
        None: {'ENTRADA'}, 'SAIDA': {'ENTRADA'},
        'ENTRADA': {'SAIDA_INTERVALO', 'SAIDA'},
        'SAIDA_INTERVALO': {'RETORNO_INTERVALO'},
        'RETORNO_INTERVALO': {'SAIDA_INTERVALO', 'SAIDA'},
    }
    if kind not in sequence.get(last.tipo if last else None, set()):
        raise ValidationError('A marcação manual não corresponde à sequência do dia informado.')
    row = PontoServidor(
        organization=org, servidor=server, request_id=uuid.uuid4(), tipo=kind,
        data_hora=occurred_at, origem='MANUAL', observacao=reason.strip(), registrado_por=user,
    )
    row._service_write = True
    row.save()
    _event(server, user, 'PONTO_AJUSTADO_MANUALMENTE', 'PontoServidor', row.pk,
           after={'tipo': kind, 'data_hora': occurred_at.isoformat(), 'origem': 'MANUAL'},
           reason=reason.strip())
    from .public_services import audit_public
    audit_public(user, 'PONTO_AJUSTE_MANUAL_REGISTRADO', row,
                 {'tipo': row.tipo, 'servidor': row.servidor_id, 'origem': 'MANUAL'})
    return row


@transaction.atomic
def request_justification(user, *, start, end=None, reason, description, document_key=''):
    require_module_permission(user, 'servidor.portal')
    server = own_server(user)
    _ensure_period_open(server.organization, timezone.localtime(start).date())
    record = JustificativaPontoMunicipal(
        organization=server.organization, servidor=server, inicio=start, fim=end,
        motivo=reason, descricao=description, documento_key=document_key,
        solicitado_por=user,
    )
    record.save()
    _event(server, user, 'JUSTIFICATIVA_ENVIADA', 'JustificativaPontoMunicipal', record.pk,
           after={'status': record.status, 'inicio': record.inicio.isoformat(), 'fim': record.fim.isoformat() if record.fim else None})
    return record


@transaction.atomic
def request_overtime(user, *, start, end, justification):
    require_module_permission(user, 'servidor.portal')
    server = own_server(user)
    _ensure_period_open(server.organization, timezone.localtime(start).date())
    minutes = int((end - start).total_seconds() // 60)
    if minutes < 1:
        raise ValidationError('Informe um período válido para a solicitação.')
    record = SolicitacaoHoraExtraMunicipal(
        organization=server.organization, servidor=server, inicio=start, fim=end,
        quantidade_minutos=minutes, justificativa=justification, solicitado_por=user,
    )
    record.save()
    _event(server, user, 'HORA_EXTRA_SOLICITADA', 'SolicitacaoHoraExtraMunicipal', record.pk,
           after={'status': record.status, 'minutos': minutes})
    return record


@transaction.atomic
def decide_request(user, *, request_type, request_id, approve, reason=''):
    require_module_permission(user, 'ponto.approve')
    org = current_organization()
    models = {
        'justificativa': JustificativaPontoMunicipal,
        'hora_extra': SolicitacaoHoraExtraMunicipal,
    }
    model = models.get(request_type)
    if model is None:
        raise ValidationError('Tipo de solicitação desconhecido.')
    row = scoped_queryset(user, model.objects.select_for_update()).filter(
        organization=org, pk=request_id, status='PENDENTE',
    ).first()
    if row is None:
        raise ValidationError('Solicitação pendente não encontrada no seu escopo.')
    require_module_permission(user, 'ponto.approve', record=row)
    before = {'status': row.status}
    row.status = 'APROVADA' if approve else 'REJEITADA'
    row.save(update_fields=['status'])
    decision = DecisaoPontoMunicipal(
        organization=org,
        solicitacao_hora_extra=row if request_type == 'hora_extra' else None,
        justificativa=row if request_type == 'justificativa' else None,
        aprovada=bool(approve), motivo=reason, usuario=user,
    )
    decision._service_write = True
    decision.save()
    _event(row.servidor, user, 'SOLICITACAO_DECIDIDA', model.__name__, row.pk,
           before=before, after={'status': row.status}, reason=reason)
    return row


@transaction.atomic
def post_bank_movement(user, *, servidor_id, kind, minutes, origin, justification, reference=''):
    require_module_permission(user, 'ponto.adjust')
    org = current_organization()
    row = scoped_queryset(user, Servidor.objects.select_for_update()).filter(organization=org, pk=servidor_id).first()
    if row is None:
        raise PermissionDenied('Servidor fora do seu escopo municipal.')
    require_module_permission(user, 'ponto.adjust', record=row)
    movement = MovimentacaoBancoHorasMunicipal(
        organization=org, servidor=row, tipo=kind, minutos=minutes,
        origem=origin, referencia=reference, justificativa=justification,
        aprovado_por=user,
    )
    movement._service_write = True
    movement.save()
    _event(row, user, 'BANCO_HORAS_MOVIMENTADO', 'MovimentacaoBancoHorasMunicipal', movement.pk,
           after={'tipo': kind, 'minutos': minutes, 'origem': origin}, reason=justification)
    return movement


def bank_balance_minutes(server):
    values = MovimentacaoBancoHorasMunicipal.objects.filter(organization=server.organization, servidor=server).values('tipo').annotate(total=Sum('minutos'))
    totals = {row['tipo']: row['total'] or 0 for row in values}
    return totals.get('CREDITO', 0) - totals.get('DEBITO', 0) - totals.get('COMPENSACAO', 0)


def _period_snapshot(user, period, version, reason=''):
    servers = scoped_queryset(user, Servidor.objects.filter(ativo=True)).order_by('matricula')
    first = date(period.ano, period.mes, 1)
    next_month = date(period.ano + (period.mes == 12), 1 if period.mes == 12 else period.mes + 1, 1)
    starts = timezone.make_aware(datetime.combine(first, time.min))
    ends = timezone.make_aware(datetime.combine(next_month, time.min))
    details = []
    for server in servers:
        punches = list(PontoServidor.objects.filter(organization=period.organization, servidor=server,
                           data_hora__gte=starts, data_hora__lt=ends).order_by('data_hora').values('id','tipo','data_hora','origem'))
        overtime = list(SolicitacaoHoraExtraMunicipal.objects.filter(organization=period.organization, servidor=server,
                             inicio__lt=ends, fim__gte=starts).values('id','status','quantidade_minutos'))
        justifications = list(JustificativaPontoMunicipal.objects.filter(organization=period.organization, servidor=server,
                                  inicio__lt=ends, fim__gte=starts).values('id','status','motivo'))
        details.append({'servidor_id': server.pk, 'matricula': server.matricula,
                        'jornada_id': server.jornada_id, 'registros': [dict(item, data_hora=item['data_hora'].isoformat()) for item in punches],
                        'horas_extras': overtime, 'justificativas': justifications,
                        'banco_horas_minutos': bank_balance_minutes(server),
                        'atrasos_faltas_calculo': 'A definir conforme regra municipal homologada'})
    snapshot = SnapshotFechamentoPontoMunicipal(
        organization=period.organization, periodo=period, versao=version,
        estado=period.status, dados={'ano': period.ano, 'mes': period.mes, 'servidores': details},
        criado_por=user, motivo=reason,
    )
    snapshot._service_write = True
    snapshot.save()
    return snapshot


@transaction.atomic
def transition_period(user, *, period_id, action, reason=''):
    org = current_organization()
    period = scoped_queryset(user, PeriodoPontoMunicipal.objects.select_for_update()).filter(organization=org, pk=period_id).first()
    if period is None:
        raise PermissionDenied('Período fora do seu escopo municipal.')
    transitions = {
        'conferir': ('ponto.close', PeriodoPontoMunicipal.Status.ABERTO, PeriodoPontoMunicipal.Status.EM_CONFERENCIA),
        'enviar_aprovacao': ('ponto.close', PeriodoPontoMunicipal.Status.EM_CONFERENCIA, PeriodoPontoMunicipal.Status.AGUARDANDO_APROVACAO),
        'aprovar': ('ponto.close', PeriodoPontoMunicipal.Status.AGUARDANDO_APROVACAO, PeriodoPontoMunicipal.Status.APROVADO),
        'fechar': ('ponto.close', PeriodoPontoMunicipal.Status.APROVADO, PeriodoPontoMunicipal.Status.FECHADO),
        'reabrir': ('ponto.reopen', PeriodoPontoMunicipal.Status.FECHADO, PeriodoPontoMunicipal.Status.EM_CONFERENCIA),
    }
    definition = transitions.get(action)
    if not definition:
        raise ValidationError('Transição de período inválida.')
    capability, before_status, after_status = definition
    require_module_permission(user, capability, record=period)
    if period.status != before_status:
        raise ValidationError('O período não está no estado necessário para esta ação.')
    if action == 'reabrir' and not reason.strip():
        raise ValidationError('Informe o motivo da reabertura para manter o histórico.')
    version = (period.versoes.order_by('-versao').values_list('versao', flat=True).first() or 0) + 1
    _period_snapshot(user, period, version, reason)
    period.status = after_status
    if action == 'fechar':
        period.fechado_em = timezone.now()
    elif action == 'reabrir':
        period.fechado_em = None
    period.save(update_fields=['status', 'fechado_em', 'atualizado_em'])
    for server in scoped_queryset(user, Servidor.objects.filter(ativo=True)):
        _event(server, user, 'PERIODO_PONTO_'+action.upper(), 'PeriodoPontoMunicipal', period.pk,
               before={'status': before_status}, after={'status': after_status, 'snapshot': version}, reason=reason)
    return period
