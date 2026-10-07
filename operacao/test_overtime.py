import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from platform_core.context import tenant_context
from platform_core.models import PermissaoMembership, OrganizationMembership
from . import models as m, overtime as o, workforce as w
from .test_block3_workforce import WorkforceData

class OvertimeFixture(WorkforceData):
    def setup_overtime(self):
        self.setup_workforce()
        self.manager=self.user('ot-gestor',self.a,'GESTOR')
        self.other_manager=self.user('ot-outro-gestor',self.a,'GESTOR')
        self.rh=self.user('ot-rh',self.a,'RH')
        with tenant_context(self.a):
            self.employee.gestor=self.manager;self.employee.save()
            self.journey.semana={str(i):{'entrada':'12:00','inicio_intervalo':'16:00','fim_intervalo':'17:00','saida':'21:00'} for i in range(5)}
            self.journey.compensar_deficit=False;self.journey.save()
    def excess(self,minute=0):
        return [self.marker('ENTRADA',12),self.marker('SAIDA_INTERVALO',16),self.marker('RETORNO_INTERVALO',17),self.marker('SAIDA',22,minute)]
    def day_row(self,user=None):
        return next(row for row in w.mirror(user or self.worker,self.employee.public_id,self.day.year,self.day.month)['dias'] if row['data']==self.day.isoformat())
    def request(self,minutes=60,key=None):
        return o.request_overtime(self.worker,self.day,minutes,'Fechamento da loja e atendimento de cliente',key or uuid.uuid4())

class OvertimeTests(OvertimeFixture,TestCase):
    def setUp(self): self.setup_overtime()
    def test_excess_is_not_approved_or_automatically_banked(self):
        with tenant_context(self.a):
            self.excess();day=self.day_row()
            self.assertEqual((day['previsto'],day['trabalhado'],day['extra'],day['extra_aprovada'],day['banco']),(480,540,60,0,0))
            self.assertEqual(day['saida_prevista'],'21:00')
    def test_request_pending_snapshot_and_idempotency(self):
        with tenant_context(self.a):
            marks=self.excess();key=uuid.uuid4();row=self.request(key=key)
            self.assertEqual(row.status,'PENDENTE')
            self.assertEqual((row.snapshot['previsto'],row.snapshot['trabalhado'],row.snapshot['extra']),(480,540,60))
            self.assertEqual(len(row.snapshot['originais']),4)
            self.assertEqual(row.snapshot['originais'][0]['sha256'],marks[0].sha256)
            self.assertEqual(self.request(key=key).pk,row.pk)
            with self.assertRaises(ValidationError): self.request(key=key,minutes=30)
            with self.assertRaises(ValidationError): self.request()
            self.assertEqual(m.SolicitacaoHoraExtra.objects.count(),1)
            self.assertEqual(self.day_row()['extra_pendente'],60)
    def test_manager_approves_partial_amount_and_bank_indicators(self):
        with tenant_context(self.a):
            self.excess();row=self.request()
            o.decide_overtime(self.manager,row.public_id,True,45,'Conferido: 45 minutos autorizados')
            row.refresh_from_db();day=self.day_row()
            self.assertEqual(row.status,'APROVADA')
            self.assertEqual((day['extra'],day['extra_pendente'],day['extra_aprovada'],day['banco']),(60,0,45,45))
            self.assertEqual(row.decisao.usuario_id,self.manager.pk)
            self.assertIsNotNone(row.decisao.criado_em)
    def test_refusal_records_reason_and_never_banks_extra(self):
        with tenant_context(self.a):
            self.excess();row=self.request()
            o.decide_overtime(self.manager,row.public_id,False,None,'Permanência não autorizada')
            row.refresh_from_db();day=self.day_row()
            self.assertEqual((row.status,day['extra_recusada'],day['extra_aprovada'],day['banco']),('RECUSADA',60,0,0))
            self.assertEqual(row.decisao.motivo,'Permanência não autorizada')
    def test_self_approval_and_unassigned_manager_denied(self):
        with tenant_context(self.a):
            self.excess();row=self.request()
            with self.assertRaises(PermissionDenied): o.decide_overtime(self.worker,row.public_id,True,60,'Própria')
            with self.assertRaises(m.SolicitacaoHoraExtra.DoesNotExist): o.decide_overtime(self.other_manager,row.public_id,True,60,'Sem responsabilidade')
            own=m.Funcionario.objects.create(usuario=self.manager,matricula='GESTOR',nome='Gestor',jornada=self.journey)
            with patch('operacao.workforce.timezone.now',return_value=self.instant(12)): w.mark(self.manager,'ENTRADA',uuid.uuid4())
            with patch('operacao.workforce.timezone.now',return_value=self.instant(22)): w.mark(self.manager,'SAIDA',uuid.uuid4())
            req=o.request_overtime(self.manager,self.day,60,'Trabalho próprio',uuid.uuid4())
            with self.assertRaises(m.SolicitacaoHoraExtra.DoesNotExist): o.decide_overtime(self.manager,req.public_id,True,60,'Própria')
            self.assertEqual(req.status,'PENDENTE')
    def test_records_and_original_marks_are_immutable(self):
        with tenant_context(self.a):
            marks=self.excess();before=[(r.pk,r.data_hora,r.sha256,r.hash_anterior) for r in marks]
            row=self.request();snapshot=copy.deepcopy(row.snapshot)
            o.decide_overtime(self.admin,row.public_id,True,60,'Conferido')
            row.refresh_from_db()
            for record in [*marks,row,row.referencia,row.decisao]:
                with self.assertRaises(ValidationError): record.save()
                with self.assertRaises(ValidationError): record.delete()
            self.assertEqual(list(self.employee.marcacoes.values_list('pk','data_hora','sha256','hash_anterior')),before)
            row.refresh_from_db();self.assertEqual(row.snapshot,snapshot)
    def test_cross_organization_service_routes_and_filters_denied(self):
        with tenant_context(self.a): self.excess();row=self.request()
        with tenant_context(self.b):
            with self.assertRaises(m.SolicitacaoHoraExtra.DoesNotExist): o.decide_overtime(self.admin_b,row.public_id,True,60,'Outra empresa')
            self.assertFalse(m.SolicitacaoHoraExtra.objects.exists())
        self.client.force_login(self.admin_b)
        response=self.client.post(reverse('operacao:rh_overtime'),{'solicitacao':row.public_id,'decisao':'aprovar','minutos':60,'motivo':'Outra empresa'})
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.client.get(reverse('operacao:rh_overtime'),{'funcionario':self.employee.pk}).status_code,400)
    def test_pwa_technician_requests_and_cannot_access_management(self):
        with tenant_context(self.a): self.excess()
        self.client.force_login(self.worker)
        home=self.client.get(reverse('operacao:ponto_home'))
        self.assertContains(home,reverse('operacao:ponto_overtime'))
        page=self.client.get(reverse('operacao:ponto_overtime'),{'data':self.day.isoformat()})
        self.assertEqual(page.status_code,200)
        self.assertNotContains(page,'href="/financeiro/"')
        self.assertNotContains(page,'href="/rh/horas-extras/"')
        response=self.client.post(reverse('operacao:ponto_overtime'),{'data':self.day.isoformat(),'minutos':60,'motivo':'Atendimento em campo','request_id':uuid.uuid4()})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a): self.assertEqual(m.SolicitacaoHoraExtra.objects.get().status,'PENDENTE')
        self.assertEqual(self.client.get(reverse('operacao:rh_overtime')).status_code,403)
        self.assertEqual(self.client.post(reverse('operacao:rh_overtime'),{}).status_code,403)
    def test_seller_self_service_preserves_pdv_exclusivity(self):
        seller=self.user('ot-vendedor',self.a,'VENDEDOR')
        with tenant_context(self.a):
            self.employee.usuario=seller;self.employee.save()
            self.worker=seller;self.excess()
        self.client.force_login(seller)
        self.assertEqual(self.client.get(reverse('operacao:ponto_overtime')).status_code,200)
        response=self.client.post(reverse('operacao:ponto_overtime'),{'data':self.day.isoformat(),'minutos':60,'motivo':'Fechamento','request_id':uuid.uuid4()})
        self.assertEqual(response.status_code,302)
        for url in ('/financeiro/','/rh/horas-extras/','/contas/usuarios/'):
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.get('/vertyx/').url,'/vendedor/')
    def test_journey_changes_do_not_change_recorded_reference(self):
        with tenant_context(self.a):
            self.excess();row=self.request();before=self.day_row()
            self.journey.semana={'0':{'entrada':'08:00','saida':'20:00'}};self.journey.banco_horas_habilitado=False;self.journey.save()
            next_journey=m.JornadaTrabalho.objects.create(nome='Outra jornada',semana={'0':{'entrada':'09:00','saida':'17:00'}})
            self.employee.jornada=next_journey;self.employee.save()
            after=self.day_row()
            for key in ('previsto','extra','saida_prevista','jornada_nome'): self.assertEqual(after[key],before[key])
            o.decide_overtime(self.manager,row.public_id,True,60,'Referência original conferida')
            self.assertEqual(self.day_row()['banco'],60)
    def test_minutes_aggregate_seconds_without_rounding_periods(self):
        with tenant_context(self.a):
            for kind,at in [('ENTRADA',self.instant(12)),('SAIDA_INTERVALO',self.instant(16)+timedelta(seconds=30)),('RETORNO_INTERVALO',self.instant(17)),('SAIDA',self.instant(21)+timedelta(seconds=30))]:
                with patch('operacao.workforce.timezone.now',return_value=at): w.mark(self.worker,kind,uuid.uuid4())
            day=self.day_row()
            self.assertEqual((day['trabalhado'],day['trabalhado_segundos'],day['extra']),(481,28860,1))
            self.assertIn('21:00:30',day['marcacoes'])
            self.request(minutes=1)
            for value in ('0','1.5',2):
                with self.assertRaises(ValidationError): o.request_overtime(self.worker,self.day,value,'Inválido',uuid.uuid4())
    def test_no_journey_incomplete_future_and_overclaim_rejected(self):
        with tenant_context(self.a):
            self.marker('ENTRADA',12)
            with self.assertRaises(ValidationError): self.request()
            self.marker('SAIDA',22)
            with self.assertRaises(ValidationError): self.request(minutes=999)
            with self.assertRaises(ValidationError): o.request_overtime(self.worker,timezone.localdate()+timedelta(days=1),1,'Futura',uuid.uuid4())
            self.day+=timedelta(days=1);self.employee.jornada=None;self.employee.save()
            self.marker('ENTRADA',12);self.marker('SAIDA',22)
            with self.assertRaises(ValidationError): self.request()
    def test_notification_recipients_status_reason_and_permissions(self):
        with tenant_context(self.a):
            self.excess();row=self.request()
            notices=m.Notificacao.objects.filter(chave=f'hora-extra:{row.pk}:PENDENTE')
            self.assertSetEqual(set(notices.values_list('usuario_id',flat=True)),{self.admin.pk,self.manager.pk,self.rh.pk})
            o.decide_overtime(self.rh,row.public_id,False,0,'Não autorizado')
            notice=m.Notificacao.objects.get(chave=f'hora-extra:{row.pk}:RECUSADA')
            self.assertEqual(notice.usuario_id,self.worker.pk)
            self.assertIn('Não autorizado',notice.mensagem)
            self.assertFalse(notices.filter(resolvida_em__isnull=True).exists())
        self.client.force_login(self.other_manager)
        self.assertNotContains(self.client.get('/notificacoes/'),'Fechamento da loja')
    def test_disabled_approval_capability_prevents_decision_and_notice(self):
        member=OrganizationMembership.objects.get(user=self.manager,organization=self.a)
        with tenant_context(self.a):
            PermissaoMembership.objects.create(membership=member,capacidade='ajuste_ponto',permitido=False)
            self.excess();row=self.request()
            self.assertFalse(m.Notificacao.objects.filter(chave=f'hora-extra:{row.pk}:PENDENTE',usuario=self.manager).exists())
            with self.assertRaises(PermissionDenied): o.decide_overtime(self.manager,row.public_id,True,60,'Não permitido')
    def test_indicators_and_all_report_filters(self):
        with tenant_context(self.a):
            department=m.Departamento.objects.create(nome='Comercial')
            self.employee.departamento=department;self.employee.cargo='Fechamento';self.employee.save()
            self.excess();row=self.request();o.decide_overtime(self.manager,row.public_id,True,60,'Conferido')
        self.client.force_login(self.manager)
        filters={'inicio':self.day.isoformat(),'fim':self.day.isoformat(),'funcionario':self.employee.pk,'departamento':department.pk,'cargo':'Fechamento','jornada':self.journey.pk,'status':'APROVADA'}
        response=self.client.get(reverse('operacao:rh_overtime'),filters)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['totals'],{'previsto':480,'trabalhado':540,'extra':60,'extra_pendente':0,'extra_aprovada':60,'extra_recusada':0})
        self.assertEqual(len(response.context['report']),1)
        filters['status']='RECUSADA';self.assertEqual(self.client.get(reverse('operacao:rh_overtime'),filters).context['totals']['extra_aprovada'],0)
        self.assertEqual(self.client.get(reverse('operacao:rh_overtime'),{'inicio':'2000-01-01','fim':'2026-01-01'}).status_code,400)
    def test_decision_validates_amount_reason_and_is_idempotent(self):
        with tenant_context(self.a):
            self.excess();row=self.request()
            for amount,reason in [(61,'Excesso'),(0,'Zero'),('1.5','Decimal'),(60,'')]:
                with self.assertRaises(ValidationError): o.decide_overtime(self.manager,row.public_id,True,amount,reason)
            with self.assertRaises(ValidationError): o.decide_overtime(self.manager,row.public_id,False,None,'')
            o.decide_overtime(self.manager,row.public_id,True,60,'Autorizado')
            o.decide_overtime(self.manager,row.public_id,True,60,'Autorizado')
            self.assertEqual(m.DecisaoHoraExtra.objects.count(),1)
            self.assertEqual(m.Notificacao.objects.filter(chave=f'hora-extra:{row.pk}:APROVADA').count(),1)
            with self.assertRaises(ValidationError): o.decide_overtime(self.manager,row.public_id,False,None,'Trocar decisão')
    def test_pending_blocks_closure_and_closed_month_blocks_new_request(self):
        with tenant_context(self.a):
            self.excess();row=self.request()
            with self.assertRaises(ValidationError): w.close_month(self.admin,self.employee.public_id,2026,9)
            o.decide_overtime(self.manager,row.public_id,True,60,'Conferido')
            closed=w.close_month(self.admin,self.employee.public_id,2026,9)
            self.assertEqual(closed.variacao_minutos,60)
            before=copy.deepcopy(closed.snapshot)
            self.journey.semana={'0':{'entrada':'09:00','saida':'16:00'}};self.journey.save()
            self.assertEqual(w.mirror(self.worker,self.employee.public_id,2026,9)['dias'],before['dias'])
            with self.assertRaises(ValidationError): self.request()
    def test_adjustment_cannot_invalidate_previously_approved_overtime(self):
        with tenant_context(self.a):
            marks=self.excess();row=self.request();o.decide_overtime(self.manager,row.public_id,True,60,'Conferido')
            correction=w.request_adjustment(self.worker,'SAIDA',self.instant(21),'Saída corrigida',marks[-1].pk)
            with self.assertRaises(ValidationError): w.decide_adjustment(self.admin,correction.public_id,True,'Conferido')
            correction.refresh_from_db();self.assertEqual(correction.status,'PENDENTE')
            self.assertEqual(self.day_row()['extra'],60)
    def test_overnight_and_folga_use_correct_schedule(self):
        with tenant_context(self.a):
            self.day=datetime(2026,9,26).date()
            self.journey.virada_dia=True
            self.journey.semana={'5':{'entrada':'22:00','inicio_intervalo':'01:00','fim_intervalo':'02:00','saida':'06:00'}};self.journey.save()
            for kind,at in [('ENTRADA',self.instant(22)),('SAIDA_INTERVALO',self.instant(1)+timedelta(days=1)),('RETORNO_INTERVALO',self.instant(2)+timedelta(days=1)),('SAIDA',self.instant(7)+timedelta(days=1))]:
                with patch('operacao.workforce.timezone.now',return_value=at): w.mark(self.worker,kind,uuid.uuid4())
            self.assertEqual((self.day_row()['previsto'],self.day_row()['trabalhado'],self.day_row()['extra']),(420,480,60))
            self.request()
    def test_approval_failure_rolls_back_decision_audit_and_notifications(self):
        with tenant_context(self.a):
            self.excess();row=self.request();count=m.Notificacao.objects.count()
            with patch('operacao.overtime.notify',side_effect=RuntimeError('falha simulada')):
                with self.assertRaises(RuntimeError): o.decide_overtime(self.manager,row.public_id,True,60,'Conferido')
            row.refresh_from_db();self.assertEqual(row.status,'PENDENTE')
            self.assertFalse(m.DecisaoHoraExtra.objects.exists());self.assertEqual(m.Notificacao.objects.count(),count)

@skipUnless(connection.vendor=='postgresql','PostgreSQL row locks')
class OvertimeConcurrencyTests(OvertimeFixture,TransactionTestCase):
    def test_simultaneous_requests_and_decisions_do_not_duplicate(self):
        self.setup_overtime()
        with tenant_context(self.a): self.excess()
        barrier=Barrier(2);key=uuid.uuid4()
        def request_worker(_):
            try:
                with tenant_context(self.a): barrier.wait(timeout=20);return self.request(key=key).pk
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool: ids=list(pool.map(request_worker,range(2)))
        self.assertEqual(ids[0],ids[1])
        with tenant_context(self.a): row=m.SolicitacaoHoraExtra.objects.get()
        barrier=Barrier(2)
        def decision_worker(approve):
            try:
                with tenant_context(self.a):
                    barrier.wait(timeout=20)
                    try: o.decide_overtime(self.manager,row.public_id,approve,60,'Decisão concorrente');return 'ok'
                    except ValidationError: return 'already'
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(decision_worker,[True,False]))
        self.assertCountEqual(results,['ok','already'])
        with tenant_context(self.a): self.assertEqual(m.DecisaoHoraExtra.objects.count(),1)

@skipUnless(connection.vendor=='postgresql','Migration preservation on PostgreSQL')
class OvertimeMigrationTests(OvertimeFixture,TransactionTestCase):
    def test_additive_migration_preserves_legacy_marks_closed_snapshot_and_tenants(self):
        self.setup_overtime()
        executor=MigrationExecutor(connection);latest=executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('operacao','0015_funcionario_contato')])
            apps=executor.loader.project_state([('operacao','0015_funcionario_contato')]).apps
            Mark=apps.get_model('operacao','MarcacaoPonto');Closure=apps.get_model('operacao','FechamentoPonto')
            before=[]
            for kind,hour in [('ENTRADA',12),('SAIDA',22)]:
                row=Mark._base_manager.create(organization_id=self.a.pk,funcionario_id=self.employee.pk,tipo=kind,data_hora=self.instant(hour),request_id=uuid.uuid4(),origem='WEB',sha256='hash-preservado-'+kind,hash_anterior='anterior')
                before.append((row.pk,row.data_hora,row.sha256,row.hash_anterior))
            legacy={'dias':[],'politica':'fechamento histórico preservado'}
            closed=Closure._base_manager.create(organization_id=self.a.pk,funcionario_id=self.employee.pk,ano=2026,mes=8,snapshot=legacy,saldo_anterior_minutos=0,variacao_minutos=17,saldo_final_minutos=17,usuario_id=self.admin.pk,sha256='hash-fechamento-preservado')
            executor=MigrationExecutor(connection);executor.migrate(latest)
            with tenant_context(self.a):
                self.assertEqual(list(self.employee.marcacoes.values_list('pk','data_hora','sha256','hash_anterior')),before)
                reference=self.employee.referencias_jornada.get(data=self.day)
                self.assertEqual((reference.snapshot['previsto'],reference.snapshot['horarios']['saida']),(480,'21:00'))
                preserved=m.FechamentoPonto.objects.get(pk=closed.pk)
                self.assertEqual((preserved.snapshot,preserved.sha256,preserved.saldo_final_minutos),(legacy,'hash-fechamento-preservado',17))
                self.assertFalse(m.DecisaoHoraExtra.objects.exists())
            with tenant_context(self.b): self.assertFalse(m.ReferenciaJornadaPonto.objects.exists())
        finally: MigrationExecutor(connection).migrate(latest)
