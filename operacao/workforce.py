"""Internal timekeeping; configurable arithmetic is not REP/legal certification."""
import calendar
import hashlib
import json
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils import timezone
from platform_core.modules import require_capability, has_capability
from gestao import services as gs
from . import models as m
from .commerce import token

def minute(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value): raise ValidationError('Horário deve estar em HH:MM.')
    hour,minutes=map(int,value.split(':'));return hour*60+minutes

def schedule_values(row,overnight=False):
    if not isinstance(row,dict) or set(row)-{'entrada','saida','inicio_intervalo','fim_intervalo'} or 'entrada' not in row or 'saida' not in row: raise ValidationError('Jornada exige entrada/saída e chaves de horário conhecidas.')
    start=minute(row['entrada']);end=minute(row['saida'])
    if end<=start:
        if not overnight: raise ValidationError('Saída deve ser após entrada; configure virada de dia quando aplicável.')
        end+=1440
    begin=finish=None
    if bool(row.get('inicio_intervalo'))!=bool(row.get('fim_intervalo')): raise ValidationError('Informe ambos os horários de intervalo.')
    if row.get('inicio_intervalo'):
        begin=minute(row['inicio_intervalo']);finish=minute(row['fim_intervalo'])
        if begin<start: begin+=1440
        if finish<=begin%1440 or finish<start: finish+=1440
        if not start<=begin<finish<=end: raise ValidationError('Intervalo precisa estar dentro da jornada.')
    return start,end,begin,finish

def validate_schedule(week,overnight=False):
    if not isinstance(week,dict) or set(week)-set('0123456'): raise ValidationError('Semana deve ser um objeto com dias 0 a 6.')
    for row in week.values(): schedule_values(row,overnight)

def employee_for(user,public_id=None,management=False):
    require_capability(user,'rh' if management else 'ponto')
    employee=m.Funcionario.objects.select_related('jornada','departamento').get(public_id=public_id) if public_id else m.Funcionario.objects.select_related('jornada','departamento').get(usuario=user,ativo=True)
    if employee.usuario_id!=user.pk and not has_capability(user,'rh'): raise PermissionDenied('Ponto pertence a outro funcionário.')
    return employee

def effective_marks(employee):
    rows=[{'id':row.pk,'tipo':row.tipo,'at':row.data_hora,'ajuste':False} for row in employee.marcacoes.all()]
    for request in employee.solicitacoes_ponto.filter(status='APROVADO').select_related('decisao'):
        if request.marcacao_id: rows=[row for row in rows if row['id']!=request.marcacao_id]
        rows.append({'id':request.marcacao_id,'tipo':request.tipo,'at':request.data_hora,'ajuste':True})
    return sorted(rows,key=lambda row:(row['at'],row['id'] or 0))

def sequence_valid(rows):
    transitions={None:('ENTRADA',),'ENTRADA':('SAIDA_INTERVALO','SAIDA'),'SAIDA_INTERVALO':('RETORNO_INTERVALO',),'RETORNO_INTERVALO':('SAIDA',),'SAIDA':('ENTRADA',)}
    previous=None
    for row in rows:
        if row['tipo'] not in transitions.get(previous,()): return False
        previous=row['tipo']
    return True

@transaction.atomic
def mark(user,kind,request_id,origin='WEB',device='',session='',ip=None,latitude=None,longitude=None,geo_consent=False):
    employee=employee_for(user)
    employee=m.Funcionario.objects.select_for_update().get(pk=employee.pk,ativo=True)
    key=token(request_id)
    if kind not in dict(m.MarcacaoPonto._meta.get_field('tipo').choices) or origin not in ('WEB','MOBILE'): raise ValidationError('Marcação/origem inválida.')
    lat=lon=None
    if latitude is not None or longitude is not None:
        if not employee.autoriza_geolocalizacao or not geo_consent or latitude is None or longitude is None: raise ValidationError('Localização exige autorização específica e consentimento nesta marcação.')
        from gestao.products import number
        lat=number(latitude).quantize(Decimal('.000001'));lon=number(longitude).quantize(Decimal('.000001'))
        if not -90<=lat<=90 or not -180<=lon<=180: raise ValidationError('Coordenadas inválidas.')
    old=m.MarcacaoPonto.objects.filter(request_id=key).first()
    if old:
        if (old.funcionario_id,old.tipo,old.origem,old.latitude,old.longitude)!=(employee.pk,kind,origin,lat,lon): raise ValidationError('Identificador já utilizado em outra marcação.')
        return old
    now=timezone.now()
    if employee.admissao and timezone.localdate(now)<employee.admissao or employee.desligamento and timezone.localdate(now)>employee.desligamento: raise ValidationError('Funcionário fora do período de vínculo.')
    rows=effective_marks(employee)
    if not sequence_valid(rows+[{'tipo':kind,'at':now,'id':None}]): raise ValidationError('Sequência inválida; revise a última marcação ou solicite ajuste.')
    previous=employee.marcacoes.order_by('-pk').first()
    data={'organization':employee.organization_id,'funcionario':employee.pk,'tipo':kind,'data_hora':now.isoformat(),'request_id':str(key),'origem':origin,'dispositivo':device[:160],'ip':ip,'latitude':str(lat) if lat is not None else None,'longitude':str(lon) if lon is not None else None,'hash_anterior':previous.sha256 if previous else ''}
    row=gs.write(m.MarcacaoPonto(funcionario=employee,tipo=kind,data_hora=now,request_id=key,origem=origin,dispositivo=device[:160],sessao_hash=hashlib.sha256(session.encode()).hexdigest() if session else '',ip=ip,latitude=lat,longitude=lon,geo_consentimento=bool(lat is not None),hash_anterior=data['hash_anterior'],sha256=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()))
    gs.audit(user,'PONTO_MARCADO',row,{'funcionario':employee.pk,'tipo':kind,'data_hora':now.isoformat(),'sha256':row.sha256,'com_geolocalizacao':lat is not None})
    return row

@transaction.atomic
def request_adjustment(user,kind,at,reason,mark_id=None):
    employee=employee_for(user)
    employee=m.Funcionario.objects.select_for_update().get(pk=employee.pk)
    if not reason.strip() or timezone.is_naive(at) or at>timezone.now(): raise ValidationError('Ajuste exige motivo e data/hora passada com timezone.')
    if employee.fechamentos_ponto.filter(ano=timezone.localtime(at).year,mes=timezone.localtime(at).month).exists(): raise ValidationError('Competência fechada é preservada; correção retroativa exige política auditada futura.')
    original=employee.marcacoes.get(pk=mark_id) if mark_id else None
    if original:
        date=timezone.localtime(original.data_hora)
        if employee.fechamentos_ponto.filter(ano=date.year,mes=date.month).exists(): raise ValidationError('Marcação original pertence a competência fechada.')
    if original and employee.solicitacoes_ponto.filter(marcacao=original,status__in=['PENDENTE','APROVADO']).exists(): raise ValidationError('Marcação já possui ajuste aberto/aprovado.')
    row=gs.write(m.SolicitacaoAjustePonto(funcionario=employee,marcacao=original,tipo=kind,data_hora=at,motivo=reason.strip()))
    gs.audit(user,'AJUSTE_PONTO_SOLICITADO',row,{'tipo':kind,'data_hora':at.isoformat(),'motivo':reason,'original':mark_id})
    return row

@transaction.atomic
def decide_adjustment(user,public_id,approve,reason):
    require_capability(user,'ajuste_ponto')
    candidate=m.SolicitacaoAjustePonto.objects.get(public_id=public_id)
    employee=m.Funcionario.objects.select_for_update().get(pk=candidate.funcionario_id)
    row=m.SolicitacaoAjustePonto.objects.select_for_update().get(pk=candidate.pk)
    if employee.usuario_id==user.pk: raise PermissionDenied('Ajuste próprio deve ser decidido por outro responsável autorizado.')
    if not reason.strip(): raise ValidationError('Decisão exige justificativa.')
    if row.status!='PENDENTE':
        if row.decisao.aprovado!=bool(approve) or row.decisao.motivo!=reason.strip(): raise ValidationError('Solicitação já decidida com outros dados.')
        return row
    before={'tipo':row.marcacao.tipo,'data_hora':row.marcacao.data_hora.isoformat()} if row.marcacao_id else {}
    after={'tipo':row.tipo,'data_hora':row.data_hora.isoformat()}
    if approve:
        original_date=timezone.localtime(row.marcacao.data_hora) if row.marcacao_id else timezone.localtime(row.data_hora)
        if employee.fechamentos_ponto.filter(ano=original_date.year,mes=original_date.month).exists() or employee.fechamentos_ponto.filter(ano=timezone.localtime(row.data_hora).year,mes=timezone.localtime(row.data_hora).month).exists(): raise ValidationError('Competência já fechada; não altere o espelho histórico.')
        rows=[item for item in effective_marks(employee) if not row.marcacao_id or item['id']!=row.marcacao_id]+[{'id':row.marcacao_id,'tipo':row.tipo,'at':row.data_hora}]
        if not sequence_valid(sorted(rows,key=lambda item:item['at'])): raise ValidationError('Ajuste resultaria em sequência inconsistente.')
    gs.write(m.DecisaoAjustePonto(solicitacao=row,aprovado=bool(approve),usuario=user,motivo=reason.strip(),antes=before,depois=after))
    row.status='APROVADO' if approve else 'REJEITADO';gs.write(row)
    gs.audit(user,'AJUSTE_PONTO_'+row.status,row,{'antes':before,'depois':after,'motivo':reason})
    return row

def expected(employee,date,scales):
    scale=scales.get(date)
    if scale and scale.tipo!='ESCALA': return 0,None,employee.jornada
    journey=scale.jornada if scale else employee.jornada
    if employee.admissao and date<employee.admissao or employee.desligamento and date>employee.desligamento: return 0,None,journey
    if journey is None: return None,None,None
    row=journey.semana.get(str(date.weekday())) if journey else None
    if not row: return 0,None,journey
    start,end,begin,finish=schedule_values(row,journey.virada_dia)
    return end-start-((finish-begin) if begin is not None else 0),start,journey

def mirror(user,public_id,year,month):
    employee=employee_for(user,public_id)
    if not 2000<=int(year)<=2100 or not 1<=int(month)<=12: raise ValidationError('Competência inválida.')
    closed=employee.fechamentos_ponto.filter(ano=int(year),mes=int(month)).first()
    if closed:
        return {**closed.snapshot,'funcionario':employee,'fechado':True,'saldo_anterior_minutos':closed.saldo_anterior_minutos,'saldo_final_minutos':closed.saldo_final_minutos}
    first=timezone.datetime(int(year),int(month),1).date();last=first+timedelta(days=calendar.monthrange(int(year),int(month))[1]-1)
    scales={row.data:row for row in employee.escala.filter(data__range=(first,last)).select_related('jornada')}
    all_rows=effective_marks(employee);groups={};current_day=None
    for row in all_rows:
        local=timezone.localtime(row['at'])
        if row['tipo']=='ENTRADA' or current_day is None: current_day=local.date()
        if first<=current_day<=last: groups.setdefault(current_day,[]).append(row)
        if row['tipo']=='SAIDA': current_day=None
    result=[];bank=0
    for index in range((last-first).days+1):
        date=first+timedelta(days=index);rows=groups.get(date,[])
        planned,start,journey=expected(employee,date,scales)
        worked=0;running=None
        for row in rows:
            if row['tipo'] in ('ENTRADA','RETORNO_INTERVALO'): running=row['at']
            elif running:
                worked+=max(0,int((row['at']-running).total_seconds()//60));running=None
        incomplete=bool(rows and (not sequence_valid(rows) or rows[-1]['tipo']!='SAIDA'))
        first_mark=next((r for r in rows if r['tipo']=='ENTRADA'),None)
        lateness=max(0,timezone.localtime(first_mark['at']).hour*60+timezone.localtime(first_mark['at']).minute-start) if first_mark and start is not None else 0
        if journey and lateness<=journey.tolerancia_atraso_minutos: lateness=0
        extra=max(0,worked-planned) if planned is not None else None
        missing=(max(0,planned-worked) if date<timezone.localdate() and not incomplete else 0) if planned is not None else None
        delta=(extra-(missing if journey and journey.compensar_deficit else 0)) if journey and journey.banco_horas_habilitado and not incomplete else 0
        bank+=delta
        result.append({'data':date.isoformat(),'marcacoes':' / '.join(timezone.localtime(row['at']).strftime('%H:%M')+' '+row['tipo']+(' (ajuste)' if row.get('ajuste') else '') for row in rows),'previsto':planned,'trabalhado':worked,'atraso':lateness,'extra':extra,'falta':missing,'banco':delta,'inconsistente':incomplete,'escala':scales[date].get_tipo_display() if date in scales else ''})
    return {'funcionario':employee,'ano':int(year),'mes':int(month),'dias':result,'saldo_banco_minutos':bank,'ressalva':'Espelho interno. Regras parametrizadas; não constitui certificação REP/conformidade trabalhista.'}

@transaction.atomic
def close_month(user,public_id,year,month):
    require_capability(user,'ajuste_ponto')
    employee=employee_for(user,public_id)
    employee=m.Funcionario.objects.select_for_update().get(pk=employee.pk)
    year,month=int(year),int(month)
    today=timezone.localdate()
    if not 2000<=year<=2100 or not 1<=month<=12 or (year,month)>=(today.year,today.month): raise ValidationError('Fechamento somente de competências anteriores encerradas.')
    previous=employee.fechamentos_ponto.order_by('-ano','-mes').first()
    if previous and (previous.ano,previous.mes)==(year,month): return previous
    if previous and (previous.ano,previous.mes)>(year,month): raise ValidationError('Fechamentos devem seguir ordem cronológica.')
    if employee.solicitacoes_ponto.filter(status='PENDENTE',data_hora__year=year,data_hora__month=month).exists(): raise ValidationError('Existem solicitações de ajuste pendentes nesta competência.')
    data=mirror(user,public_id,year,month)
    if any(row['previsto'] is None for row in data['dias']): raise ValidationError('Configure jornada/escala para apurar e fechar a competência.')
    if any(row['inconsistente'] for row in data['dias']): raise ValidationError('Resolva as marcações inconsistentes antes de fechar.')
    snapshot={key:value for key,value in data.items() if key!='funcionario'}
    snapshot['funcionario_nome']=employee.nome;snapshot['matricula']=employee.matricula
    snapshot['jornada']={'nome':employee.jornada.nome,'semana':employee.jornada.semana,'virada_dia':employee.jornada.virada_dia,'tolerancia_atraso_minutos':employee.jornada.tolerancia_atraso_minutos,'banco_horas_habilitado':employee.jornada.banco_horas_habilitado,'compensar_deficit':employee.jornada.compensar_deficit} if employee.jornada_id else None
    before=previous.saldo_final_minutos if previous else 0;delta=data['saldo_banco_minutos']
    snapshot['saldo_anterior_minutos']=before;snapshot['saldo_final_minutos']=before+delta
    row=gs.write(m.FechamentoPonto(funcionario=employee,ano=year,mes=month,snapshot=snapshot,saldo_anterior_minutos=before,variacao_minutos=delta,saldo_final_minutos=before+delta,usuario=user,sha256=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()))
    gs.audit(user,'PONTO_COMPETENCIA_FECHADA',row,{'funcionario':employee.pk,'competencia':f'{year}-{month:02d}','saldo_anterior':before,'variacao':delta,'saldo_final':before+delta,'sha256':row.sha256})
    return row
