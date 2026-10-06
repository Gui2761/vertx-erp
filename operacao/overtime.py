"""Attendance excess is evidence, never an automatic overtime authorization."""
import copy
import re
from datetime import date
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from platform_core.access import effective_role
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership
from platform_core.modules import has_capability, require_capability
from gestao import services as gs
from . import models as m

def snapshot_schedule(employee, day):
    from .workforce import expected
    scales={s.data:s for s in employee.escala.filter(data=day).select_related('jornada')}
    planned,start,journey=expected(employee,day,scales)
    row=copy.deepcopy(journey.semana.get(str(day.weekday()),{})) if journey else {}
    if planned==0: row={}
    return {'versao':1,'previsto':planned,'inicio':start,'horarios':row,
            'jornada_nome':journey.nome if journey else '',
            'banco_horas_habilitado':bool(journey and journey.banco_horas_habilitado),
            'compensar_deficit':bool(journey and journey.compensar_deficit),
            'tolerancia_atraso_minutos':journey.tolerancia_atraso_minutos if journey else 0,
            'virada_dia':bool(journey and journey.virada_dia),
            'escala':scales[day].get_tipo_display() if day in scales else '',
            'departamento_id':employee.departamento_id,'departamento':str(employee.departamento) if employee.departamento_id else '',
            'cargo':employee.cargo},journey

def freeze_schedule(employee, day, origin='MARCACAO'):
    """Caller holds the employee lock; immutable reference survives later edits."""
    existing=employee.referencias_jornada.filter(data=day).first()
    if existing: return existing
    data,journey=snapshot_schedule(employee,day)
    return gs.write(m.ReferenciaJornadaPonto(funcionario=employee,data=day,jornada=journey,snapshot=data,origem=origin))

def approver(user, employee=None):
    if not has_capability(user,'ajuste_ponto') or effective_role(user) not in ('ADMIN','GESTOR','RH'): return False
    if employee is None: return True
    if employee.usuario_id==user.pk: return False
    return effective_role(user) in ('ADMIN','RH') or employee.gestor_id==user.pk

def managed_employees(user):
    require_capability(user,'ajuste_ponto')
    if not approver(user): raise PermissionDenied('Perfil não autorizado a gerir horas extras.')
    rows=m.Funcionario.objects.exclude(usuario=user)
    return rows.filter(gestor=user) if effective_role(user)=='GESTOR' else rows

def requests_for(user, management=False):
    if management:
        return m.SolicitacaoHoraExtra.objects.filter(funcionario__in=managed_employees(user))
    require_capability(user,'ponto')
    return m.SolicitacaoHoraExtra.objects.filter(funcionario__usuario=user)

def integer_minutes(value):
    if isinstance(value,bool) or not re.fullmatch(r'\d+',str(value)): raise ValidationError('Informe minutos inteiros, sem arredondamento.')
    return int(value)

def notify(row, decision=False):
    """Existing recipient-scoped internal delivery; no external transport."""
    members=OrganizationMembership.objects.filter(organization=current_organization(),status='ATIVO',user__is_active=True).select_related('user')
    users=[member.user for member in members if (member.user_id==row.funcionario.usuario_id and has_capability(member.user,'ponto'))] if decision else [member.user for member in members if approver(member.user,row.funcionario)]
    for user in users:
        key=f'hora-extra:{row.pk}:{row.status}'
        title='Hora extra '+('solicitada' if not decision else row.status.lower())
        message=f'{row.funcionario.nome} · {row.data:%d/%m/%Y} · {row.minutos_solicitados} minutos solicitados.'
        if decision: message+=f' {row.decisao.minutos_aprovados} minutos aprovados. Motivo: {row.decisao.motivo}'
        m.Notificacao.objects.get_or_create(usuario=user,chave=key,defaults={'titulo':title,'mensagem':message,'link':'/ponto/horas-extras/' if decision else '/rh/horas-extras/'})
    if decision:
        for notice in m.Notificacao.objects.filter(chave=f'hora-extra:{row.pk}:PENDENTE',resolvida_em__isnull=True):
            notice.resolvida_em=timezone.now();notice.save()

def day_data(user, employee, day):
    from .workforce import mirror
    data=mirror(user,employee.public_id,day.year,day.month)
    return next(item for item in data['dias'] if item['data']==day.isoformat()),bool(data.get('fechado'))

@transaction.atomic
def request_overtime(user, day, minutes, reason, request_id):
    from .workforce import employee_for
    from .commerce import token
    employee=employee_for(user)
    employee=m.Funcionario.objects.select_for_update().get(pk=employee.pk,ativo=True)
    if not isinstance(day,date) or day>timezone.localdate() or not 2000<=day.year<=2100: raise ValidationError('Informe uma data registrada até hoje.')
    minutes=integer_minutes(minutes)
    reason=reason.strip()
    if not reason: raise ValidationError('Informe o motivo da solicitação.')
    key=token(request_id)
    old=m.SolicitacaoHoraExtra.objects.filter(request_id=key).first()
    if old:
        if (old.funcionario_id,old.data,old.minutos_solicitados,old.motivo)!=(employee.pk,day,minutes,reason): raise ValidationError('Identificador utilizado por outra solicitação.')
        return old
    if employee.solicitacoes_hora_extra.filter(data=day).exists(): raise ValidationError('Este dia já possui solicitação. Consulte o histórico; não envie duplicada.')
    data,closed=day_data(user,employee,day)
    if closed: raise ValidationError('Competência fechada: histórico preservado.')
    if data['inconsistente'] or not data['marcacoes']: raise ValidationError('Conclua as marcações e resolva inconsistências antes de solicitar.')
    if data['extra'] is None or not 0<minutes<=data['extra']: raise ValidationError('Quantidade deve estar entre 1 minuto e o excedente identificado.')
    reference=freeze_schedule(employee,day,'SOLICITACAO')
    from .workforce import effective_marks
    evidence=[];current=None
    for r in effective_marks(employee):
        if r['tipo']=='ENTRADA' or current is None: current=timezone.localdate(r['at'])
        if current==day: evidence.append({'id':r['id'],'tipo':r['tipo'],'data_hora':r['at'].isoformat(),'ajuste':r.get('ajuste',False)})
        if r['tipo']=='SAIDA': current=None
    ids={r['id'] for r in evidence if r['id']}
    snapshot={**copy.deepcopy(data),'jornada':reference.snapshot,'evidencias':evidence,
              'originais':[{'id':r.pk,'sha256':r.sha256,'data_hora':r.data_hora.isoformat(),'tipo':r.tipo} for r in employee.marcacoes.filter(pk__in=ids)]}
    row=gs.write(m.SolicitacaoHoraExtra(funcionario=employee,referencia=reference,data=day,minutos_solicitados=minutes,motivo=reason,snapshot=snapshot,request_id=key))
    gs.audit(user,'HORA_EXTRA_SOLICITADA',row,{'funcionario':employee.pk,'data':day.isoformat(),'minutos':minutes,'excedente':data['extra'],'referencia':reference.pk,'motivo':reason})
    notify(row)
    return row

@transaction.atomic
def decide_overtime(user, public_id, approve, minutes, reason):
    candidate=requests_for(user,management=True).get(public_id=public_id)
    employee=m.Funcionario.objects.select_for_update().get(pk=candidate.funcionario_id)
    row=m.SolicitacaoHoraExtra.objects.select_for_update(of=('self',)).select_related('decisao').get(pk=candidate.pk)
    if not approver(user,employee): raise PermissionDenied('Responsável não autorizado; não pode decidir a própria solicitação.')
    minutes=integer_minutes(minutes) if approve else 0
    reason=reason.strip()
    if not reason: raise ValidationError('Toda decisão exige justificativa, incluindo a recusa.')
    if row.status!='PENDENTE':
        if (row.decisao.aprovado,row.decisao.minutos_aprovados,row.decisao.motivo,row.decisao.usuario_id)!=(bool(approve),minutes,reason,user.pk): raise ValidationError('Solicitação já decidida. O histórico é imutável.')
        return row
    data,closed=day_data(user,employee,row.data)
    if closed: raise ValidationError('Competência fechada: não altere o histórico.')
    if approve and (data['inconsistente'] or data['extra'] is None or not 0<minutes<=min(row.minutos_solicitados,data['extra'])): raise ValidationError('Quantidade aprovada deve respeitar a solicitada e o excedente atual válido.')
    gs.write(m.DecisaoHoraExtra(solicitacao=row,aprovado=bool(approve),minutos_aprovados=minutes,usuario=user,motivo=reason))
    # Clear the cached absence from select_related before resolving the property.
    row._state.fields_cache.pop('decisao',None)
    gs.audit(user,'HORA_EXTRA_'+row.status,row,{'responsavel':user.pk,'minutos_aprovados':minutes,'motivo':reason,'referencia':row.referencia_id,'ponto_conferido':data})
    notify(row,decision=True)
    return row
