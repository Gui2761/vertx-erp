"""Relógio do servidor e medição administrativa. Nenhum lançamento financeiro automático."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from contas.models import Tecnico
from gestao.services import write, audit
from platform_core.access import effective_role, require_erp
from platform_core.contingency import journey_suspended, require_journey_writable
from ordens.models import OrdemServico
from .contract_workday_models import (ConfiguracaoJornadaContrato as Config, JornadaContrato as Jornada,
    EventoJornadaContrato as Evento, OrdemJornadaContrato as Vinculo, CorrecaoJornadaContrato as Correcao,
    DecisaoJornadaContrato as Decisao)

MESSAGE = 'Você ainda não iniciou a atividade externa deste contrato. Inicie a atividade antes de prosseguir.'
CLOSED = ['FINALIZADA', 'APROVADA', 'FATURADA', 'CANCELADA']


def config(order):
    if journey_suspended():
        return None
    return Config.objects.filter(contrato_id=order.contrato_id, habilitada=True).first() if order.contrato_id else None


def own_technician(user):
    require_erp(user, roles=['TECNICO', 'ADMIN', 'GESTOR'])
    tech = Tecnico.objects.filter(usuario=user, ativo=True).first()
    if not tech:
        raise PermissionDenied('Seu usuário precisa estar vinculado a um técnico ativo.')
    return tech


def active(tech_id, contract_id):
    return Jornada.objects.filter(tecnico_id=tech_id, contrato_id=contract_id, data=timezone.localdate()).exclude(eventos__tipo='FIM').first()


def blocked(user, order):
    if effective_role(user) != 'TECNICO' or order.status in CLOSED:
        return False
    cfg = config(order)
    if not cfg or not cfg.exigir_inicio:
        return False
    tech = Tecnico.objects.filter(usuario=user, ativo=True).first()
    row = active(tech.pk, order.contrato_id) if tech else None
    return not row or not operational(row)


def operational(row):
    kinds = list(row.eventos.values_list('tipo', flat=True))
    return not kinds or kinds[-1] not in ['PAUSA', 'RETORNO', 'FIM']


def check(user, order):
    if blocked(user, order):
        raise PermissionDenied(MESSAGE)


def link_order(user, order):
    cfg = config(order)
    if not cfg:
        return
    if effective_role(user)=='TECNICO':
        tech=own_technician(user)
        if order.tecnico_id!=tech.pk and not order.auxiliares.filter(pk=tech.pk).exists():
            raise PermissionDenied('OS não atribuída ao seu técnico.')
        check(user,order)
    tech_id = own_technician(user).pk if effective_role(user)=='TECNICO' else order.tecnico_id
    if not tech_id:
        raise ValidationError('Atribua técnico à OS antes do atendimento.')
    # Mesma trava usada por iniciar/encerrar; protege gate e encerramento concorrentes.
    Tecnico.objects.select_for_update().get(pk=tech_id)
    row = active(tech_id, order.contrato_id)
    if cfg.exigir_inicio and (not row or not operational(row)):
        raise ValidationError(MESSAGE)
    if row and operational(row) and not Vinculo.objects.filter(jornada=row, ordem=order, ciclo=order.ciclo).exists():
        write(Vinculo(jornada=row, ordem=order, ciclo=order.ciclo))
        audit(user, 'JORNADA_OS_VINCULADA', row, {'ordem': order.pk, 'ciclo': order.ciclo})


def rules(cfg):
    return {name: (getattr(cfg,name).isoformat() if getattr(cfg,name) is not None and name.startswith('horario_') else getattr(cfg,name)) for name in ['deslocamento_faturavel','inicio_contagem','retorno_faturavel','descontar_intervalos','limite_diario_minutos','horario_inicial','horario_final','tarifas','fracao_minutos','arredondamento']}


def within_hours(rule, now):
    if rule.get('horario_inicial') and not rule['horario_inicial'] <= timezone.localtime(now).strftime('%H:%M:%S') <= rule['horario_final']:
        raise ValidationError('Fora do horário permitido pelo contrato. Solicite revisão administrativa.')


def geo(data):
    from ordens.forms import GeoForm
    form=GeoForm(data or {'resultado':'INDISPONIVEL'})
    if not form.is_valid():
        raise ValidationError('Localização inválida.')
    return {k:str(v) if v is not None and k!='resultado' else v for k,v in form.cleaned_data.items()}


@transaction.atomic
def start(user, order_id, origin='', gps=None, category=''):
    require_journey_writable()
    tech=own_technician(user)
    Tecnico.objects.select_for_update().get(pk=tech.pk)
    order=OrdemServico.objects.get(pk=order_id)
    if not (order.tecnico_id==tech.pk or order.auxiliares.filter(pk=tech.pk).exists()):
        raise PermissionDenied('Agenda não atribuída ao seu técnico.')
    cfg=config(order)
    now=timezone.now(); today=timezone.localdate(now)
    if not cfg or order.status in CLOSED or not order.contrato.data_inicial<=today<=order.contrato.data_final or order.contrato.status in ['SUSPENSO','ENCERRADO']:
        raise ValidationError('Contrato/agenda não permite iniciar atividade externa.')
    existing=Jornada.objects.filter(tecnico=tech, contrato=order.contrato, data=today).first()
    if existing:
        if not existing.fim:
            return existing  # duplo toque não cria outra atividade
        raise ValidationError('Atividade do dia encerrada; correções exigem solicitação auditada.')
    if Jornada.objects.filter(tecnico=tech).exclude(eventos__tipo='FIM').exists():
        raise ValidationError('Encerre a atividade externa anterior antes de iniciar outra.')
    policy=rules(cfg); within_hours(policy,now)
    selected=category or cfg.categoria_padrao
    if selected not in cfg.tarifas:
        raise ValidationError('Categoria não configurada no contrato.')
    target=order.unidade or order.cliente
    row=write(Jornada(contrato=order.contrato,tecnico=tech,usuario=user,data=today,inicio=now,origem=origin.strip(),municipio=target.cidade,destino=str(target)[:255],agenda=order,categoria=selected,regras=policy,gps=geo(gps)))
    audit(user,'JORNADA_CONTRATO_INICIADA',row,{'inicio':now.isoformat(),'agenda':order.pk,'gps_estado':row.gps['resultado'],'origem':row.origem})
    return row


def authorize_row(user,row, administrative=False):
    row.validate_tenant()
    require_erp(user,roles=['ADMIN','GESTOR'] if administrative else ['ADMIN','GESTOR','TECNICO'])
    if administrative:
        from gestao.permissions import require
        require(user,'contratos')
    if not administrative and row.usuario_id!=user.pk:
        raise PermissionDenied('A atividade deve ser registrada pelo próprio técnico.')


@transaction.atomic
def event(user,pk,kind,observation='',gps=None):
    require_journey_writable()
    row=Jornada.objects.get(pk=pk); authorize_row(user,row)
    Tecnico.objects.select_for_update().get(pk=row.tecnico_id)
    events=list(row.eventos.all()); kinds=[e.tipo for e in events]
    if row.fim:
        if kind=='FIM': return row.eventos.get(tipo='FIM')
        raise ValidationError('Atividade já encerrada.')
    last=kinds[-1] if kinds else 'INICIO'
    allowed={'INICIO':['CHEGADA','FIM'], 'CHEGADA':['PAUSA','RETORNO','FIM'], 'PAUSA':['RETOMADA'], 'RETOMADA':['PAUSA','RETORNO','FIM'], 'RETORNO':['FIM']}
    if kind not in allowed.get(last,[]) or kind=='CHEGADA' and 'CHEGADA' in kinds:
        raise ValidationError('Evento incompatível com a sequência da atividade.')
    # Uma OS nunca perde a jornada enquanto execução/interrupção permanece aberta.
    open_orders=row.ordens_vinculadas.exclude(ordem__status__in=CLOSED).exists()
    if kind in ['PAUSA','RETORNO','FIM'] and open_orders:
        raise ValidationError('Existem OS abertas nesta atividade. Finalize ou cancele pelo fluxo autorizado antes de pausar/retornar/encerrar.')
    now=timezone.now()
    if kind=='FIM' and now<=row.inicio:
        raise ValidationError('Encerramento deve ocorrer depois do início.')
    result=write(Evento(jornada=row,tipo=kind,horario=now,usuario=user,observacao=observation.strip(),gps=geo(gps)))
    audit(user,'JORNADA_CONTRATO_'+kind,row,{'evento':result.pk,'horario':now.isoformat(),'observacao':result.observacao,'gps_estado':result.gps['resultado']})
    return result


@transaction.atomic
def request_correction(user,pk,start_time,end_time,reason):
    require_journey_writable()
    row=Jornada.objects.get(pk=pk); authorize_row(user,row)
    Tecnico.objects.select_for_update().get(pk=row.tecnico_id)
    if not row.fim:
        raise ValidationError('Encerre a atividade antes de solicitar correção da medição.')
    validate_correction(row,start_time,end_time)
    if len(reason.strip())<10:
        raise ValidationError('Justificativa deve conter pelo menos 10 caracteres.')
    if row.correcoes.filter(decisao__isnull=True).exists():
        raise ValidationError('Já existe uma solicitação aguardando decisão.')
    correction=write(Correcao(jornada=row,inicio_solicitado=start_time,fim_solicitado=end_time,justificativa=reason.strip(),solicitante=user))
    audit(user,'JORNADA_CORRECAO_SOLICITADA',row,{'solicitacao':correction.pk,'original_inicio':row.inicio.isoformat(),'original_fim':row.fim.isoformat(),'inicio_solicitado':start_time.isoformat(),'fim_solicitado':end_time.isoformat(),'justificativa':reason})
    return correction


def validate_correction(row,start_time,end_time):
    if not start_time or not end_time or not timezone.is_aware(start_time) or not timezone.is_aware(end_time) or end_time<=start_time or end_time>timezone.now() or timezone.localdate(start_time)!=row.data or timezone.localdate(end_time)!=row.data:
        raise ValidationError('Correção deve pertencer ao dia da jornada, sem horário futuro e com fim posterior ao início.')
    within_hours(row.regras,start_time)
    if any(not start_time<=e.horario<=end_time for e in row.eventos.exclude(tipo='FIM')):
        raise ValidationError('Os eventos intermediários devem permanecer dentro da jornada corrigida.')
    for other in Jornada.objects.filter(tecnico=row.tecnico).exclude(pk=row.pk):
        a,b=effective_times(other)
        if start_time < (b or timezone.now()) and a < end_time:
            raise ValidationError('Correção sobrepõe outra jornada do técnico.')


@transaction.atomic
def decide(user,pk,approved,reason):
    require_journey_writable()
    correction=Correcao.objects.select_for_update().get(pk=pk); row=correction.jornada
    authorize_row(user,row,administrative=True)
    Tecnico.objects.select_for_update().get(pk=row.tecnico_id)
    if correction.solicitante_id==user.pk or Decisao.objects.filter(correcao=correction).exists() or len(reason.strip())<10:
        raise ValidationError('Decisão única, justificada e por pessoa distinta do solicitante.')
    if approved:
        validate_correction(row,correction.inicio_solicitado,correction.fim_solicitado)
    decision=write(Decisao(correcao=correction,aprovada=approved,justificativa=reason.strip(),aprovador=user))
    audit(user,'JORNADA_CORRECAO_DECIDIDA',row,{'solicitacao':pk,'aprovada':approved,'justificativa':reason,'original_preservado':True})
    return decision


def effective_times(row):
    correction=row.correcoes.filter(decisao__aprovada=True).order_by('-decisao__decidido_em','-pk').first()
    return (correction.inicio_solicitado,correction.fim_solicitado) if correction else (row.inicio,row.fim)


def minutes(a,b):
    return max(Decimal('0'),Decimal(str((b-a).total_seconds()))/Decimal('60')) if a and b else Decimal('0')


def measurement(row):
    row.validate_tenant()
    start_time,end_time=effective_times(row); cfg=row.regras
    events=list(row.eventos.all()); arrival=next((e.horario for e in events if e.tipo=='CHEGADA'),None)
    returning=next((e.horario for e in events if e.tipo=='RETORNO'),None)
    end=end_time or timezone.now(); total=minutes(start_time,end)
    outward=minutes(start_time,arrival or end); back=minutes(returning,end)
    pause_start=None; pause=Decimal('0'); pauses=[]
    for e in events:
        if e.tipo=='PAUSA': pause_start=e.horario
        elif e.tipo=='RETOMADA' and pause_start:
            pause+=minutes(pause_start,e.horario); pauses.append((pause_start,e.horario)); pause_start=None
    if pause_start:
        pause+=minutes(pause_start,end); pauses.append((pause_start,end))
    bill_start=start_time if cfg['inicio_contagem']=='BASE' and cfg['deslocamento_faturavel'] else arrival or end
    bill_end=end if cfg['retorno_faturavel'] else returning or end
    if cfg['horario_inicial']:
        from datetime import datetime,time
        allowed_start=timezone.make_aware(datetime.combine(row.data,time.fromisoformat(cfg['horario_inicial'])))
        allowed_end=timezone.make_aware(datetime.combine(row.data,time.fromisoformat(cfg['horario_final'])))
        bill_start=max(bill_start,allowed_start); bill_end=min(bill_end,allowed_end)
    bill=minutes(bill_start,bill_end)
    if cfg['descontar_intervalos']:
        bill-=sum((minutes(max(a,bill_start),min(b,bill_end)) for a,b in pauses),Decimal('0'))
    bill=max(Decimal('0'),bill)
    fraction=Decimal(cfg['fracao_minutos'])
    if cfg['arredondamento']!='EXATO':
        bill=max(fraction,(bill/fraction).quantize(Decimal('1'),rounding=ROUND_CEILING if cfg['arredondamento']=='CIMA' else ROUND_HALF_UP)*fraction) if bill else Decimal('0')
    if cfg['limite_diario_minutos']: bill=min(bill,Decimal(cfg['limite_diario_minutos']))
    rate=Decimal(str(cfg['tarifas'][row.categoria])); hours=bill/Decimal('60')
    order_time=Decimal('0'); orders=[]; divergences=[]
    for link in row.ordens_vinculadas.select_related('ordem'):
        order=link.ordem
        # Cada ciclo tem conferência própria; reabertura não muda os horários anteriores.
        conference=order.conferencias.filter(ciclo=link.ciclo).first()
        if conference:
            from datetime import datetime
            a=datetime.fromisoformat(conference.dados['inicio']) if conference.dados.get('inicio') else None
            b=datetime.fromisoformat(conference.dados['conclusao']) if conference.dados.get('conclusao') else None
        else:
            a,b=order.inicio,order.conclusao
        order_time+=minutes(max(a,start_time) if a else None,min(b or end,end))
        orders.append({'numero':order.numero,'id':order.pk,'ciclo':link.ciclo,'inicio':a,'fim':b,'status':order.get_status_display()})
        if order.status not in CLOSED: divergences.append(f'{order.numero} aberta')
    if not arrival: divergences.append('Chegada não registrada; percurso de ida sem término confirmado')
    if not end_time: divergences.append('Jornada aberta; medição provisória')
    if timezone.localdate(end)!=row.data: divergences.append('Jornada atravessou meia-noite; revisão administrativa necessária')
    if cfg['horario_final'] and timezone.localtime(end).strftime('%H:%M:%S')>cfg['horario_final']: divergences.append('Encerramento fora da faixa contratual')
    return {'row':row,'inicio':start_time,'fim':end_time,'duracao':total.quantize(Decimal('.01')),'ida':outward.quantize(Decimal('.01')),'retorno':back.quantize(Decimal('.01')),'intervalos':pause.quantize(Decimal('.01')),'tempo_os':order_time.quantize(Decimal('.01')),'horas':hours.quantize(Decimal('.0001')),'tarifa':rate,'valor':(hours*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP),'ordens':orders,'divergencias':divergences,'ajustes':row.correcoes.select_related('decisao').all(),'provisoria':not bool(end_time)}
