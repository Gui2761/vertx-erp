"""Jornada contratual real no PostgreSQL; sem substituir os 404 testes anteriores."""
import copy
import hashlib
from decimal import Decimal
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from django.utils import timezone
from gestao import models as g, services as gs
from ordens import services as os
from ordens.models import OrdemServico, DocumentoOSAssinado
from ordens.forms import AssinaturaForm
from ordens.reports import gerar_pdf
from platform_core.tests import sample_signature
from platform_core.context import tenant_context
from .test_block2 import Block2Fixtures
from . import contract_workday as w, services as ops


class PilotData(Block2Fixtures):
    def prepare_pilot(self):
        self.setup_operations()
        self.techuser=self.users['TECNICO']; self.order=self.da['order']
        with tenant_context(self.a):
            self.contract=g.Contrato.objects.create(numero='PILOTO',cliente=self.da['customer'],data_inicial=self.today-timezone.timedelta(days=1),data_final=self.today+timezone.timedelta(days=100),valor=0)
            g.ContratoEquipamento.objects.create(contrato=self.contract,equipamento=self.da['equipment'])
            self.order.contrato=self.contract; self.order.defeito='DETALHE OPERACIONAL RESTRITO'; self.order.save()
            self.cfg=w.Config.objects.create(contrato=self.contract,habilitada=True,exigir_inicio=True,tarifas={'Assistência técnica':'137.43'})
        self.base=timezone.now()-timezone.timedelta(hours=4)

    def start(self):
        with patch('operacao.contract_workday.timezone.now',return_value=self.base):
            return w.start(self.techuser,self.order.pk,origin='Base sintética',gps={'resultado':'NEGADA'})

    def ev(self,row,kind,minutes):
        with patch('operacao.contract_workday.timezone.now',return_value=self.base+timezone.timedelta(minutes=minutes)):
            return w.event(self.techuser,row.pk,kind,gps={'resultado':'TIMEOUT'})

    def close(self,row):
        self.ev(row,'CHEGADA',20); return self.ev(row,'FIM',120)

    def finish_order(self,order):
        os.iniciar(self.techuser,order.pk,{'resultado':'NEGADA','latitude':None,'longitude':None,'precisao':None})
        order.refresh_from_db(); order.diagnostico='Teste funcional'; order.servico_executado='Serviço executado'; order.condicao_final='OK'; order.save()
        conf=os.preparar(self.techuser,order.pk,{'resultado':'NEGADA','latitude':None,'longitude':None,'precisao':None})
        form=AssinaturaForm({'token':'teste','nome':'Cliente sintético','cargo':'Responsável','imagem':sample_signature(),'imagem_tecnico':sample_signature(),'confirmacao':True})
        self.assertTrue(form.is_valid(),form.errors)
        return os.finalizar(self.techuser,order.pk,conf.pk,form.cleaned_data)


class PilotContractTests(PilotData,TestCase):
    def setUp(self): self.prepare_pilot()

    def test_common_contract_keeps_existing_operation(self):
        with tenant_context(self.a):
            self.cfg.habilitada=False; self.cfg.exigir_inicio=False; self.cfg.save()
            os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
            self.order.refresh_from_db(); self.assertEqual(self.order.status,'EXECUCAO')
            self.assertFalse(w.Jornada.objects.exists())

    def test_admin_can_plan_before_technician_starts_workday(self):
        with tenant_context(self.a):
            order,invalid=os.editar(self.admin,self.order.pk,{'cliente':self.order.cliente_id,'unidade':self.order.unidade_id,'equipamento':self.order.equipamento_id,'tecnico':self.order.tecnico_id,'contrato':self.contract.pk,'tipo_atendimento':'CORRETIVA','prioridade':'NORMAL','defeito':self.order.defeito,'revisao':self.order.revisao,'agendada_para':timezone.now().isoformat()})
            self.assertIsNone(invalid,invalid.errors if invalid else None)
            self.assertIsNotNone(order.agendada_para); self.assertEqual(order.status,'ABERTA')
            self.assertFalse(w.Jornada.objects.exists())

    def test_required_contract_blocks_service_and_direct_get_post(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied): os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
        self.client.force_login(self.techuser)
        for name in ['detalhe','editar','iniciar','preparar','finalizar','foto_adicionar']:
            url=reverse('ordens:'+name,args=[self.order.pk])
            response=self.client.get(url) if name in ['detalhe','editar'] else self.client.post(url,{'resultado':'NEGADA'})
            self.assertEqual(response.status_code,403,name); self.assertContains(response,w.MESSAGE,status_code=403)

    def test_destination_is_only_projection_before_start(self):
        self.client.force_login(self.techuser)
        response=self.client.get(reverse('operacao:tecnico'))
        self.assertContains(response,'ATENDIMENTO EXTERNO PROGRAMADO')
        self.assertNotContains(response,self.order.defeito)
        self.assertNotContains(response,self.order.numero)
        self.assertNotContains(response,self.da['equipment'].nome)
        self.assertTrue(response.context['groups'][3][1][0]['blocked'])
        self.assertNotIn('order',response.context['groups'][3][1][0])

    def test_start_unlocks_and_links_order_without_changing_os_clock(self):
        with tenant_context(self.a):
            row=self.start(); os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
            self.order.refresh_from_db()
            self.assertEqual(row.ordens_vinculadas.get().ordem_id,self.order.pk)
            self.assertGreater(self.order.inicio,row.inicio)
            self.assertFalse(w.blocked(self.techuser,self.order))

    def test_server_time_ignores_injected_payload(self):
        self.client.force_login(self.techuser)
        with patch('operacao.contract_workday.timezone.now',return_value=self.base):
            response=self.client.post(reverse('operacao:contract_activity',args=[self.order.pk]),{'acao':'INICIO','categoria':'Assistência técnica','resultado':'NEGADA','inicio':'2000-01-01T00:00'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a): self.assertEqual(w.Jornada.objects.get().inicio,self.base)

    def test_immutable_original_cannot_be_directly_edited_or_deleted(self):
        with tenant_context(self.a):
            row=self.start(); row.inicio-=timezone.timedelta(hours=1)
            with self.assertRaises(ValidationError): row.save()
            with self.assertRaises(ValidationError): w.Jornada.objects.filter(pk=row.pk).update(inicio=row.inicio)
            with self.assertRaises(ValidationError): row.delete()
            self.assertEqual(w.Jornada.objects.get().inicio,self.base)

    def test_double_start_and_end_are_idempotent(self):
        with tenant_context(self.a):
            row=self.start(); self.assertEqual(self.start().pk,row.pk)
            self.close(row); first=row.eventos.get(tipo='FIM')
            self.assertEqual(w.event(self.techuser,row.pk,'FIM').pk,first.pk)
            self.assertEqual(w.Jornada.objects.count(),1)

    def test_open_order_prevents_pause_return_and_end(self):
        with tenant_context(self.a):
            row=self.start(); self.ev(row,'CHEGADA',20)
            os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
            for kind in ['PAUSA','RETORNO','FIM']:
                with self.assertRaises(ValidationError): w.event(self.techuser,row.pk,kind)
            self.assertIsNone(row.fim)

    def test_finalized_order_allows_end_and_originals_preserved(self):
        with tenant_context(self.a):
            row=self.start(); self.ev(row,'CHEGADA',20); self.finish_order(self.order)
            original=OrdemServico.objects.get(pk=self.order.pk).inicio
            w.event(self.techuser,row.pk,'FIM'); self.order.refresh_from_db()
            self.assertEqual(self.order.inicio,original); self.assertIsNotNone(row.fim)

    def test_multiple_orders_share_workday(self):
        with tenant_context(self.a):
            row=self.start()
            other=OrdemServico.objects.create(cliente=self.da['customer'],unidade=self.da['unit'],equipamento=self.da['equipment'],tecnico=self.da['tech'],contrato=self.contract,defeito='Outra OS')
            self.finish_order(self.order); self.finish_order(other)
            self.assertEqual(row.ordens_vinculadas.count(),2)
            self.assertEqual(w.Jornada.objects.count(),1)

    def test_approved_correction_preserves_original_events(self):
        with tenant_context(self.a):
            row=self.start(); self.close(row); original=row.fim
            correction=w.request_correction(self.techuser,row.pk,row.inicio,original+timezone.timedelta(minutes=10),'Justificativa da correção')
            w.decide(self.admin,correction.pk,True,'Conferido pelo administrador')
            row.refresh_from_db(); self.assertEqual(row.inicio,self.base); self.assertEqual(row.fim,original)
            self.assertEqual(w.effective_times(row)[1],original+timezone.timedelta(minutes=10))

    def test_rejected_correction_does_not_affect_measurement(self):
        with tenant_context(self.a):
            row=self.start(); self.close(row); original=row.fim
            correction=w.request_correction(self.techuser,row.pk,row.inicio,original+timezone.timedelta(minutes=10),'Justificativa da correção')
            w.decide(self.admin,correction.pk,False,'Não comprovada a diferença')
            self.assertEqual(w.effective_times(row),(row.inicio,original))

    def test_correction_requires_admin_separate_actor_and_unique_decision(self):
        with tenant_context(self.a):
            row=self.start(); self.close(row)
            c=w.request_correction(self.techuser,row.pk,row.inicio,row.fim,'Justificativa da correção')
            with self.assertRaises(PermissionDenied): w.decide(self.techuser,c.pk,True,'Justificativa de aprovação')
            w.decide(self.admin,c.pk,True,'Justificativa de aprovação')
            with self.assertRaises(ValidationError): w.decide(self.admin,c.pk,False,'Outra decisão não permitida')

    def test_correction_rejects_future_or_wrong_day(self):
        with tenant_context(self.a):
            row=self.start(); self.close(row)
            with self.assertRaises(ValidationError): w.request_correction(self.techuser,row.pk,row.inicio,timezone.now()+timezone.timedelta(days=1),'Correção indevida de horário')

    def test_snapshot_rules_preserved_when_contract_reconfigured(self):
        with tenant_context(self.a):
            row=self.start(); self.close(row); before=w.measurement(row)
            self.cfg.tarifas={'Assistência técnica':'999.00'}; self.cfg.save()
            self.assertEqual(w.measurement(row)['valor'],before['valor'])
            self.assertEqual(w.measurement(row)['tarifa'],Decimal('137.43'))

    def test_decimal_travel_pause_return_rounding_and_daily_limit(self):
        with tenant_context(self.a):
            self.cfg.inicio_contagem='BASE'; self.cfg.deslocamento_faturavel=True; self.cfg.retorno_faturavel=False
            self.cfg.arredondamento='CIMA'; self.cfg.fracao_minutos=15; self.cfg.limite_diario_minutos=90; self.cfg.save()
            row=self.start(); self.ev(row,'CHEGADA',20); self.ev(row,'PAUSA',40); self.ev(row,'RETOMADA',50); self.ev(row,'RETORNO',110); self.ev(row,'FIM',120)
            result=w.measurement(row)
            self.assertEqual((result['ida'],result['retorno'],result['intervalos']),(20,10,10))
            self.assertEqual(result['horas'],Decimal('1.5000')); self.assertEqual(result['valor'],Decimal('206.15'))

    def test_destination_start_excludes_outward_even_if_marked_billable(self):
        with tenant_context(self.a):
            self.cfg.deslocamento_faturavel=True; self.cfg.save()
            row=self.start(); self.close(row)
            self.assertEqual(w.measurement(row)['horas'],Decimal('1.6667'))

    def test_measurement_excludes_outside_allowed_hours_and_overlapping_break_only(self):
        from datetime import datetime,time
        with tenant_context(self.a):
            self.base=timezone.make_aware(datetime.combine(self.today,time(8)))
            self.cfg.horario_inicial=time(8); self.cfg.horario_final=time(9)
            self.cfg.inicio_contagem='BASE'; self.cfg.deslocamento_faturavel=True; self.cfg.save()
            row=self.start(); self.ev(row,'CHEGADA',20); self.ev(row,'PAUSA',40); self.ev(row,'RETOMADA',50); self.ev(row,'RETORNO',110); self.ev(row,'FIM',120)
            result=w.measurement(row)
            self.assertEqual(result['horas'],Decimal('.8333'))
            self.assertEqual(result['valor'],Decimal('114.53'))
            self.assertIn('Encerramento fora da faixa contratual',result['divergencias'])

    def test_allowed_hours_and_invalid_tariffs_rejected(self):
        with tenant_context(self.a):
            from datetime import time
            self.cfg.horario_inicial=time(0); self.cfg.horario_final=time(0,1); self.cfg.save()
            with self.assertRaises(ValidationError): self.start()
            self.cfg.tarifas={'Assistência técnica':'NaN'}
            with self.assertRaises(ValidationError): self.cfg.save()

    def test_gps_variants_and_invalid_obtained_coordinate(self):
        for state in ['OBTIDA','NEGADA','INDISPONIVEL','TIMEOUT']:
            data={'resultado':state}
            if state=='OBTIDA': data.update(latitude='-9.5',longitude='-36.2',precisao='15')
            self.assertEqual(w.geo(data)['resultado'],state)
        with self.assertRaises(ValidationError): w.geo({'resultado':'OBTIDA','latitude':'99','longitude':'0'})

    def test_paused_or_returning_journey_blocks_execution(self):
        with tenant_context(self.a):
            row=self.start(); self.ev(row,'CHEGADA',20); self.ev(row,'PAUSA',30)
            with self.assertRaises(PermissionDenied): os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
            self.ev(row,'RETOMADA',40); self.ev(row,'RETORNO',60)
            with self.assertRaises(PermissionDenied): os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})

    def test_administrative_start_cannot_bypass_required_journey(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError): os.iniciar(self.admin,self.order.pk,{'resultado':'NEGADA'})

    def test_stock_need_and_transition_cannot_bypass_gate(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied): ops.transicao_os(self.techuser,self.order.pk,'deslocamento')
            self.incoming(2)
            with self.assertRaises(PermissionDenied): gs.movimentar(self.techuser,self.part.pk,'OS',1,origem_id=self.depot.pk,ordem_id=self.order.pk)
            self.part.refresh_from_db(); self.assertEqual(self.part.quantidade_atual,2)

    def test_technician_cannot_view_admin_config_or_measurement(self):
        self.client.force_login(self.techuser)
        for url in [reverse('operacao:contract_measurement'),reverse('operacao:contract_configuration',args=[self.contract.pk])]:
            self.assertEqual(self.client.get(url).status_code,403)

    def test_technician_activity_projection_omits_financial_data(self):
        with tenant_context(self.a): self.start()
        self.client.force_login(self.techuser)
        response=self.client.get(reverse('operacao:contract_activity',args=[self.order.pk]))
        self.assertEqual(response.status_code,200)
        for token in ['137.43','tarifas','valor/hora','horas computadas','deslocamento_faturavel']:
            self.assertNotContains(response,token)
        self.assertNotIn('regras',response.context['activity'])

    def test_tenant_isolation_and_idor(self):
        with tenant_context(self.a): row=self.start()
        with tenant_context(self.b):
            self.assertFalse(w.Jornada.objects.exists())
            with self.assertRaises(w.Jornada.DoesNotExist): w.event(self.tech_b,row.pk,'FIM')
            with self.assertRaises(ValidationError): w.measurement(row)
        self.client.force_login(self.tech_b)
        self.assertEqual(self.client.get(reverse('operacao:contract_activity',args=[self.order.pk])).status_code,404)
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('operacao:contract_configuration',args=[self.contract.pk])).status_code,404)

    def test_measurement_screen_and_pdf_administrative_only(self):
        with tenant_context(self.a): row=self.start(); self.close(row)
        response=self.client.get(reverse('operacao:contract_measurement'))
        self.assertContains(response,'137,43'); self.assertContains(response,'PILOTO')
        response=self.client.get(reverse('operacao:contract_measurement'),{'inicio':self.today,'fim':self.today,'formato':'pdf'})
        self.assertEqual(response.status_code,200); self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_has_tenant_and_no_internal_cost_or_contract_measurement(self):
        with tenant_context(self.a):
            self.start(); self.incoming(2,cost=Decimal('73.37'))
            gs.movimentar(self.techuser,self.part.pk,'OS',1,origem_id=self.depot.pk,ordem_id=self.order.pk)
            signature=self.finish_order(self.order)
            data=signature.conferencia.dados
            self.assertEqual(data['pdf_modelo'],2)
            for forbidden in ['valor_cobranca','horas','deslocamento_km','jornada','tarifas']:
                self.assertNotIn(forbidden,data)
            self.assertNotIn('custo_total',str(data)); self.assertNotIn('custo_unitario',str(data))
            # Sem compressão apenas neste teste: inspeciona texto efetivamente
            # emitido, sem introduzir leitor PDF na aplicação/requirements.
            with patch('reportlab.rl_config.pageCompression',0):
                pdf=gerar_pdf(signature)
            text=pdf.decode('latin-1')
            self.assertIn(self.a.display_name,text); self.assertNotIn(self.b.display_name,text)
            for forbidden in ['73.37','137.43','valor/hora','custo_total','Medição do Contrato','Horas computadas']:
                self.assertNotIn(forbidden,text)
            self.assertIn('Assinaturas e integridade',text); self.assertIn(signature.conferencia.digest,text)

    def test_emitted_pdf_is_immutable_after_reopen_and_issuer_change(self):
        with tenant_context(self.a):
            self.start(); signature=self.finish_order(self.order); before=gerar_pdf(signature)
            os.reabrir(self.admin,self.order.pk,'Nova avaliação solicitada')
            self.a.nome_fantasia='NOME ALTERADO APÓS EMISSÃO'; self.a.save()
            self.assertEqual(gerar_pdf(signature),before)
            doc=DocumentoOSAssinado.objects.get(assinatura=signature)
            self.assertEqual(doc.sha256,hashlib.sha256(before).hexdigest())
            with self.assertRaises(ValidationError): doc.save()

    def test_pdf_detects_signature_and_snapshot_tampering(self):
        with tenant_context(self.a):
            self.start(); signature=self.finish_order(self.order); gerar_pdf(signature)
            signature.conferencia.dados['cliente']='ALTERADO'
            with self.assertRaises(ValidationError): gerar_pdf(signature)

    def test_invalid_technical_signature_rejected(self):
        form=AssinaturaForm({'token':'teste','nome':'Cliente','cargo':'Gestor','imagem':sample_signature(),'imagem_tecnico':'invalid','confirmacao':True})
        self.assertFalse(form.is_valid()); self.assertIn('imagem_tecnico',form.errors)

    def test_required_workday_requires_technical_signature(self):
        with tenant_context(self.a):
            self.start(); os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
            self.order.refresh_from_db(); self.order.diagnostico='Diagnóstico'; self.order.servico_executado='Serviço'; self.order.save()
            conf=os.preparar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
            form=AssinaturaForm({'token':'teste','nome':'Cliente','cargo':'Gestor','imagem':sample_signature(),'confirmacao':True})
            self.assertTrue(form.is_valid(),form.errors)
            with self.assertRaises(ValidationError): os.finalizar(self.techuser,self.order.pk,conf.pk,form.cleaned_data)
            self.order.refresh_from_db(); self.assertEqual(self.order.status,'EXECUCAO')

    def test_client_portal_never_receives_workday_financial_data(self):
        from .models import PortalCliente
        with tenant_context(self.a):
            self.start(); signature=self.finish_order(self.order)
            user=self.user('pilot-client',self.a,'CLIENTE')
            PortalCliente.objects.create(usuario=user,cliente=self.da['customer'])
        self.client.force_login(user)
        response=self.client.get(reverse('operacao:portal_os',args=[self.order.pk]))
        self.assertEqual(response.status_code,200)
        for secret in ['137.43','tarifas','custo_total','horas computadas','Jornadas externas']:
            self.assertNotContains(response,secret)
        self.assertEqual(self.client.get(reverse('operacao:contract_measurement')).status_code,403)
        self.assertEqual(self.client.get(reverse('operacao:contract_activity',args=[self.order.pk])).status_code,403)

    def test_technical_audit_does_not_expose_prior_internal_cost(self):
        from ordens.models import Auditoria
        with tenant_context(self.a):
            self.start()
            Auditoria.objects.create(ordem=self.order,usuario=self.admin,acao='LEGADO',alteracoes={'custo_total':'SEGREDO_FINANCEIRO_TESTE'})
        self.client.force_login(self.techuser)
        response=self.client.get(reverse('ordens:detalhe',args=[self.order.pk]))
        self.assertEqual(response.status_code,200); self.assertNotContains(response,'SEGREDO_FINANCEIRO_TESTE')


class PilotConcurrencyTests(PilotData,TransactionTestCase):
    def setUp(self): self.prepare_pilot()

    def test_concurrent_start_creates_one_workday(self):
        barrier=Barrier(2)
        def execute():
            connections.close_all()
            try:
                with tenant_context(self.a):
                    barrier.wait(timeout=20)
                    return w.start(self.techuser,self.order.pk,gps={'resultado':'NEGADA'}).pk
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(lambda _:execute(),range(2)))
        self.assertEqual(ids[0],ids[1])
        with tenant_context(self.a): self.assertEqual(w.Jornada.objects.count(),1)

    def test_concurrent_order_start_and_workday_end_cannot_leave_orphan_execution(self):
        with tenant_context(self.a): row=w.start(self.techuser,self.order.pk,gps={'resultado':'NEGADA'})
        barrier=Barrier(2)
        def execute(kind):
            connections.close_all()
            try:
                with tenant_context(self.a):
                    barrier.wait(timeout=20)
                    try:
                        if kind=='OS': os.iniciar(self.techuser,self.order.pk,{'resultado':'NEGADA'})
                        else: w.event(self.techuser,row.pk,'FIM')
                        return 'OK'
                    except (PermissionDenied,ValidationError): return 'BLOCKED'
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(execute,['OS','FIM']))
        self.assertEqual(sorted(result),['BLOCKED','OK'])
        with tenant_context(self.a):
            self.order.refresh_from_db()
            self.assertFalse(row.fim and self.order.status=='EXECUCAO')
