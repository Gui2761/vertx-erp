import uuid
from unittest.mock import patch
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from platform_core.context import tenant_context
from . import models as m, workforce as w
from .test_block2 import Block2Fixtures

class WorkforceData(Block2Fixtures):
    def setup_workforce(self):
        self.setup_operations()
        self.worker=self.user('ponto-b3',self.a,'TECNICO')
        with tenant_context(self.a):
            self.journey=m.JornadaTrabalho.objects.create(nome='Administrativa',semana={str(i):{'entrada':'08:00','saida':'17:00','inicio_intervalo':'12:00','fim_intervalo':'13:00'} for i in range(5)},banco_horas_habilitado=True,compensar_deficit=True)
            self.employee=m.Funcionario.objects.create(usuario=self.worker,matricula='F001',nome='Funcionário sintético',jornada=self.journey)
        self.day=datetime(2026,9,28).date()
    def instant(self,hour,minute=0): return timezone.make_aware(datetime.combine(self.day,datetime.min.time()).replace(hour=hour,minute=minute))
    def marker(self,kind,hour,minute=0,key=None,**kwargs):
        with patch('operacao.workforce.timezone.now',return_value=self.instant(hour,minute)):
            return w.mark(self.worker,kind,key or uuid.uuid4(),**kwargs)

class WorkforceTests(WorkforceData,TestCase):
    def setUp(self): self.setup_workforce()

    def test_localized_year_links_inputs_and_exports_remain_machine_readable(self):
        from html.parser import HTMLParser
        class Page(HTMLParser):
            def __init__(self,content):
                super().__init__();self.links={};self.inputs=[];self.anchor=None
                self.feed(content.decode())
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='a':self.anchor=attrs.get('href')
                if tag=='input':self.inputs.append(attrs)
            def handle_data(self,text):
                if self.anchor and text.strip():self.links[text.strip()]=self.anchor
            def handle_endtag(self,tag):
                if tag=='a':self.anchor=None
        self.client.force_login(self.worker)
        home=self.client.get(reverse('operacao:ponto_home'))
        self.assertEqual(home.status_code,200)
        route=Page(home.content).links['Meu espelho mensal']
        self.assertNotIn('2.026',route)
        response=self.client.get(route)
        self.assertEqual(response.status_code,200)
        mirror=Page(response.content)
        self.assertEqual(next(i['value'] for i in mirror.inputs if i.get('name')=='ano'),str(timezone.localdate().year))
        for label,prefix in (('PDF',b'%PDF'),('Excel',b'PK')):
            href=mirror.links[label]
            export=self.client.get(route.split('?')[0]+href)
            self.assertEqual(export.status_code,200)
            self.assertTrue(export.content.startswith(prefix))
        self.client.force_login(self.admin)
        response=self.client.get(route)
        mirror=Page(response.content)
        self.assertEqual(next(i['value'] for i in mirror.inputs if i.get('name')=='ano' and i.get('type')=='hidden'),str(timezone.localdate().year))

    def test_missing_journey_does_not_invent_overtime_or_absence(self):
        with tenant_context(self.a):
            self.employee.jornada=None;self.employee.save()
            self.marker('ENTRADA',8);self.marker('SAIDA',17)
            data=w.mirror(self.worker,self.employee.public_id,2026,9)
            day=next(row for row in data['dias'] if row['data']==self.day.isoformat())
            self.assertEqual((day['previsto'],day['extra'],day['falta']),(None,None,None))
            self.assertEqual(day['trabalhado'],540)
            with self.assertRaises(ValidationError):w.close_month(self.admin,self.employee.public_id,2026,9)

    def test_month_closure_is_immutable_and_retains_configuration(self):
        with tenant_context(self.a):
            self.marker('ENTRADA',8);self.marker('SAIDA',17)
            closed=w.close_month(self.admin,self.employee.public_id,2026,9)
            self.assertEqual(w.close_month(self.admin,self.employee.public_id,2026,9).pk,closed.pk)
            self.assertEqual(closed.snapshot['jornada']['semana'],self.journey.semana)
            self.journey.semana={'0':{'entrada':'09:00','saida':'16:00'}};self.journey.save()
            self.employee.nome='Nome posterior';self.employee.save()
            mirror=w.mirror(self.worker,self.employee.public_id,2026,9)
            self.assertEqual(mirror['funcionario_nome'],'Funcionário sintético')
            self.assertEqual(mirror['saldo_final_minutos'],closed.saldo_final_minutos)
            with self.assertRaises(ValidationError): closed.save()
            with self.assertRaises(ValidationError): w.request_adjustment(self.worker,'ENTRADA',self.instant(8),'Correção tardia')
            with self.assertRaises(PermissionDenied): w.close_month(self.worker,self.employee.public_id,2026,9)

    def test_closure_rejects_open_marks_pending_adjustments_and_current_month(self):
        with tenant_context(self.a):
            first=self.marker('ENTRADA',8)
            with self.assertRaises(ValidationError): w.close_month(self.admin,self.employee.public_id,2026,9)
            self.marker('SAIDA',17)
            w.request_adjustment(self.worker,'ENTRADA',self.instant(9),'Ajuste aberto',first.pk)
            with self.assertRaises(ValidationError): w.close_month(self.admin,self.employee.public_id,2026,9)
            now=timezone.localdate()
            with self.assertRaises(ValidationError): w.close_month(self.admin,self.employee.public_id,now.year,now.month)

    def test_four_server_marks_mirror_and_hash_chain(self):
        with tenant_context(self.a):
            rows=[self.marker('ENTRADA',8),self.marker('SAIDA_INTERVALO',12),self.marker('RETORNO_INTERVALO',13),self.marker('SAIDA',17)]
            self.assertEqual(rows[1].hash_anterior,rows[0].sha256)
            self.assertEqual(rows[0].data_hora,self.instant(8))
            mirror=w.mirror(self.worker,self.employee.public_id,2026,9)
            day=next(row for row in mirror['dias'] if row['data']==self.day.isoformat())
            self.assertEqual((day['previsto'],day['trabalhado'],day['extra'],day['inconsistente']),(480,480,0,False))
            self.assertEqual(rows[0].funcionario.usuario,self.worker)

    def test_duplicate_mark_idempotent_and_invalid_sequence_denied(self):
        with tenant_context(self.a):
            key=uuid.uuid4();first=self.marker('ENTRADA',8,key=key)
            self.assertEqual(self.marker('ENTRADA',9,key=key).pk,first.pk)
            with self.assertRaises(ValidationError): self.marker('ENTRADA',9)
            with self.assertRaises(ValidationError): self.marker('SAIDA',9,key=key)
            self.assertEqual(m.MarcacaoPonto.objects.count(),1)

    def test_immutable_original_adjustment_approval_with_event(self):
        with tenant_context(self.a):
            first=self.marker('ENTRADA',9);self.marker('SAIDA',17)
            original_hash=first.sha256
            request=w.request_adjustment(self.worker,'ENTRADA',self.instant(8),'Horário incorreto',first.pk)
            decided=w.decide_adjustment(self.admin,request.public_id,True,'Conferido pelo gestor')
            first.refresh_from_db();self.assertEqual((first.data_hora,first.sha256),(self.instant(9),original_hash))
            self.assertEqual(decided.status,'APROVADO')
            self.assertEqual(w.effective_marks(self.employee)[0]['at'],self.instant(8))
            with self.assertRaises(ValidationError): first.save()
            with self.assertRaises(ValidationError): first.delete()
            self.assertEqual(w.decide_adjustment(self.admin,request.public_id,True,'Conferido pelo gestor').pk,request.pk)

    def test_worker_cannot_approve_and_cross_org_cannot_see_uuid(self):
        with tenant_context(self.a):
            first=self.marker('ENTRADA',9)
            request=w.request_adjustment(self.worker,'ENTRADA',self.instant(8),'Correção',first.pk)
            with self.assertRaises(PermissionDenied): w.decide_adjustment(self.worker,request.public_id,True,'Próprio')
        with tenant_context(self.b):
            with self.assertRaises(m.Funcionario.DoesNotExist): w.mirror(self.admin_b,self.employee.public_id,2026,9)
            with self.assertRaises(m.SolicitacaoAjustePonto.DoesNotExist): w.decide_adjustment(self.admin_b,request.public_id,True,'Outro tenant')

    def test_gps_optional_and_requires_explicit_authorization(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError): self.marker('ENTRADA',8,latitude=0,longitude=0,geo_consent=True)
            self.employee.autoriza_geolocalizacao=True;self.employee.save()
            with self.assertRaises(ValidationError): self.marker('ENTRADA',8,latitude=0,longitude=0)
            point=self.marker('ENTRADA',8)
            self.assertIsNone(point.latitude)

    def test_schedule_folga_tolerance_and_extra_are_configurable(self):
        with tenant_context(self.a):
            self.journey.tolerancia_atraso_minutos=5;self.journey.save()
            self.marker('ENTRADA',8,3);self.marker('SAIDA',18)
            data=w.mirror(self.worker,self.employee.public_id,2026,9)
            day=next(row for row in data['dias'] if row['data']==self.day.isoformat())
            self.assertEqual((day['atraso'],day['trabalhado'],day['extra']),(0,597,117))
            m.EscalaFuncionario.objects.create(funcionario=self.employee,data=self.day,tipo='FOLGA',motivo='Folga configurada')
            data=w.mirror(self.worker,self.employee.public_id,2026,9)
            self.assertEqual(next(row['previsto'] for row in data['dias'] if row['data']==self.day.isoformat()),0)

    def test_invalid_schedule_and_foreign_user_rejected(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError): m.JornadaTrabalho.objects.create(nome='Inválida',semana={'0':{'entrada':'08:00','saida':'07:00'}})
            with self.assertRaises(ValidationError): m.Funcionario.objects.create(usuario=self.admin_b,matricula='X',nome='Outro tenant')

    def test_mirror_exports_authorization_and_no_locations_in_pdf(self):
        self.client.force_login(self.worker)
        route=reverse('operacao:ponto_mirror',args=[self.employee.public_id])
        for format in ('pdf','xlsx'):
            response=self.client.get(route,{'formato':format,'ano':2026,'mes':9})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.content.startswith(b'%PDF' if format=='pdf' else b'PK'))
        self.client.force_login(self.admin_b);self.assertEqual(self.client.get(route).status_code,404)

    def test_rejected_adjustment_preserves_effective_original(self):
        with tenant_context(self.a):
            first=self.marker('ENTRADA',9)
            request=w.request_adjustment(self.worker,'ENTRADA',self.instant(8),'Correção',first.pk)
            w.decide_adjustment(self.admin,request.public_id,False,'Não confirmado')
            self.assertEqual(w.effective_marks(self.employee)[0]['at'],first.data_hora)
