import json
from decimal import Decimal
from datetime import datetime, time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.test import TestCase, TransactionTestCase
from django.db import connection, connections
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from django.utils import timezone
from gestao.tests import Dados
from gestao import models as g, services as gs
from ordens.models import OrdemServico, Status
from ordens import services as os_services
from platform_core.context import tenant_context
from platform_core.models import MembershipERP
from . import models as m, planning_services as ps, operational_panel as tv
from .planning_forms import QuickOrderForm, ScheduleForm

class PlanningData(Dados):
    def setup_planning(self):
        self.prepare_data()
        self.today=timezone.localdate()
        self.start=timezone.make_aware(datetime.combine(self.today,time(9)))
        self.planner=self.user('planner',self.a,'PLANEJADOR')
        self.attendant=self.user('attendant',self.a,'ATENDIMENTO')
        self.viewer=self.user('tv',self.a,'PAINEL')
    def grant(self,user,enabled=True):
        MembershipERP.objects.filter(membership__user=user,membership__organization=self.a).update(visualizar_painel_operacional=enabled)
    def order(self,**kwargs):
        values=dict(cliente=self.da['customer'],unidade=self.da['unit'],equipamento=self.da['equipment'],tecnico=self.da['tech'],defeito='SEGREDO CLINICO',agendada_para=self.start,agendada_ate=self.start+timezone.timedelta(hours=1))
        values.update(kwargs)
        return OrdemServico.objects.create(**values)
    def quick_data(self,**kwargs):
        values=dict(cliente=self.da['customer'].pk,unidade=self.da['unit'].pk,equipamento=self.da['equipment'].pk,tipo_atendimento='CORRETIVA',prioridade='NORMAL',defeito='Pedido rápido',tecnico='',agendada_para='',agendada_ate='')
        values.update(kwargs)
        return values
    def schedule_data(self,order,**kwargs):
        values=dict(tecnico=order.tecnico_id or '',agendada_para=order.agendada_para.isoformat() if order.agendada_para else '',agendada_ate=order.agendada_ate.isoformat() if order.agendada_ate else '',prioridade=order.prioridade,revisao=order.revisao)
        values.update(kwargs)
        return values
    def plan(self,**kwargs):
        values=dict(nome='Plano real',cliente=self.da['customer'],tecnico=self.da['tech'],inicio=self.today-timezone.timedelta(days=15),fim=self.today+timezone.timedelta(days=60))
        values.update(kwargs)
        plan=m.PlanoPreventivo.objects.create(**values)
        m.PlanoEquipamento.objects.create(plano=plan,equipamento=self.da['equipment'])
        return plan

class PlanningTests(PlanningData,TestCase):
    def setUp(self):
        self.setup_planning()

    def test_quick_without_technician_or_date_uses_existing_os(self):
        response=self.client.post(reverse('operacao:planning_quick'),self.quick_data())
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            row=OrdemServico.objects.get(defeito='Pedido rápido')
            self.assertIsNone(row.tecnico_id)
            self.assertIsNone(row.agendada_para)
            self.assertEqual(row.status,'ABERTA')
            self.assertEqual(row.historico.get().acao,'CRIACAO')
            self.assertEqual(os_services.snapshot(row)['tecnico'],'Não atribuído')
            self.assertEqual(self.client.get(reverse('ordens:detalhe',args=[row.pk])).status_code,200)

    def test_quick_assigned_and_scheduled(self):
        self.client.post(reverse('operacao:planning_quick'),self.quick_data(tecnico=self.da['tech'].pk,agendada_para=self.start.isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=2)).isoformat()))
        with tenant_context(self.a):
            row=OrdemServico.objects.get(defeito='Pedido rápido')
            self.assertEqual(row.status,'AGENDADA')
            self.assertEqual(row.agendada_ate-row.agendada_para,timezone.timedelta(hours=2))

    def test_cross_company_quick_fk_rejected(self):
        response=self.client.post(reverse('operacao:planning_quick'),self.quick_data(tecnico=self.db['tech'].pk))
        self.assertEqual(response.status_code,400)
        with tenant_context(self.a):
            self.assertFalse(OrdemServico.objects.filter(defeito='Pedido rápido').exists())

    def test_equipment_customer_and_unit_validation(self):
        with tenant_context(self.a):
            form=QuickOrderForm(self.quick_data(unidade=''),user=self.admin)
            self.assertFalse(form.is_valid())
            self.assertIn('unidade',form.errors)

    def test_end_before_start_rejected(self):
        with tenant_context(self.a):
            form=QuickOrderForm(self.quick_data(agendada_para=self.start.isoformat(),agendada_ate=self.start.isoformat()),user=self.admin)
            self.assertFalse(form.is_valid())

    def test_assignment_schedule_priority_audited(self):
        with tenant_context(self.a):
            row=self.order(tecnico=None,agendada_para=None,agendada_ate=None)
            form=ScheduleForm(self.schedule_data(row,tecnico=self.da['tech'].pk,agendada_para=self.start.isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=1)).isoformat(),prioridade='URGENTE'),instance=row,user=self.planner)
            self.assertTrue(form.is_valid(),form.errors)
            saved=ps.save_plan(self.planner,form,row.pk)
            self.assertEqual(saved.status,'AGENDADA')
            self.assertEqual(saved.prioridade,'URGENTE')
            self.assertEqual(saved.historico.get().usuario,self.planner)

    def test_revision_prevents_lost_update(self):
        with tenant_context(self.a):
            row=self.order()
            form=ScheduleForm(self.schedule_data(row,revisao=0),instance=row,user=self.admin)
            self.assertTrue(form.is_valid())
            with self.assertRaises(ValidationError):ps.save_plan(self.admin,form,row.pk)
            row.refresh_from_db()
            self.assertEqual(row.revisao,1)

    def test_overlapping_intervals_rejected(self):
        with tenant_context(self.a):
            existing=self.order()
            form=QuickOrderForm(self.quick_data(tecnico=self.da['tech'].pk,agendada_para=(self.start+timezone.timedelta(minutes=30)).isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=2)).isoformat()),user=self.admin)
            self.assertTrue(form.is_valid())
            with self.assertRaisesMessage(ValidationError,existing.numero):ps.save_plan(self.admin,form)

    def test_adjacent_intervals_not_conflict(self):
        with tenant_context(self.a):
            self.order()
            candidate=self.order(agendada_para=self.start+timezone.timedelta(hours=1),agendada_ate=self.start+timezone.timedelta(hours=2))
            self.assertEqual(ps.conflicts(candidate),[])

    def test_unknown_duration_is_point_and_no_invented_hours(self):
        with tenant_context(self.a):
            row=self.order(agendada_ate=None)
            event=ps.order_event(row)
            timeline=ps.timeline_rows([row.tecnico],[event],self.today)[0]
            self.assertEqual(timeline['horas'],0)
            self.assertEqual(timeline['sem_duracao'],1)
            self.assertEqual(timeline['bars'][0]['width'],0)

    def test_same_point_is_conflict(self):
        with tenant_context(self.a):
            self.order(agendada_ate=None)
            other=self.order(agendada_ate=None)
            self.assertEqual(len(ps.conflicts(other)),1)

    def test_conflict_override_requires_manager_and_reason(self):
        with tenant_context(self.a):
            self.order()
            row=self.order()
            for user,reason in [(self.planner,'Motivo'),(self.admin,'')]:
                with self.assertRaises(ValidationError):ps.validate_conflicts(user,row,True,reason)
            self.assertEqual(len(ps.validate_conflicts(self.admin,row,True,'Emergência com equipe de apoio')),1)

    def test_override_saved_with_ids_and_reason(self):
        with tenant_context(self.a):
            original=self.order()
            row=self.order(agendada_para=None,agendada_ate=None)
            form=ScheduleForm(self.schedule_data(row,agendada_para=self.start.isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=1)).isoformat(),autorizar_conflito=True,justificativa='Equipe de apoio'),instance=row,user=self.admin)
            self.assertTrue(form.is_valid())
            saved=ps.save_plan(self.admin,form,row.pk)
            record=saved.historico.get()
            self.assertEqual(record.justificativa,'Equipe de apoio')
            self.assertEqual(record.alteracoes['conflitos_autorizados'][0]['id'],original.pk)

    def test_existing_full_os_create_cannot_bypass_conflict(self):
        from ordens.forms import OrdemForm
        with tenant_context(self.a):
            self.order()
            form=OrdemForm(self.quick_data(tecnico=self.da['tech'].pk,agendada_para=self.start.isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=1)).isoformat()))
            self.assertTrue(form.is_valid(),form.errors)
            with self.assertRaises(ValidationError):os_services.criar(self.admin,form)

    def test_started_or_closed_os_cannot_be_rescheduled(self):
        with tenant_context(self.a):
            row=self.order()
            os_services.iniciar(self.admin,row.pk,dict(resultado='NEGADA',latitude=None,longitude=None,precisao=None))
            row.refresh_from_db()
            form=ScheduleForm(self.schedule_data(row),instance=row,user=self.admin)
            self.assertTrue(form.is_valid())
            with self.assertRaises(ValidationError):ps.save_plan(self.admin,form,row.pk)

    def test_unassigned_cannot_start(self):
        with tenant_context(self.a):
            row=self.order(tecnico=None)
            with self.assertRaises(ValidationError):os_services.iniciar(self.admin,row.pk,{})

    def test_calendar_month_day_overflow_and_search(self):
        with tenant_context(self.a):
            for _ in range(4):self.order()
        response=self.client.get(reverse('operacao:calendario'),dict(visao='MES',modo='CALENDARIO'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'outras · ver dia')
        response=self.client.get(reverse('operacao:calendario'),dict(modo='LISTA',q='inexistente'))
        self.assertEqual(response.context['events'],[])

    def test_list_filters_service_priority_status_contract(self):
        with tenant_context(self.a):
            row=self.order(tipo_atendimento='INSTALACAO',prioridade='URGENTE')
        response=self.client.get(reverse('operacao:calendario'),dict(modo='LISTA',tipo='INSTALACAO',prioridade='URGENTE',status='ABERTA'))
        self.assertEqual([event['id'] for event in response.context['events']],[row.pk])

    def test_late_and_unplanned_filters_not_limited_to_week(self):
        with tenant_context(self.a):
            row=self.order(agendada_para=self.start-timezone.timedelta(days=40),agendada_ate=None)
        response=self.client.get(reverse('operacao:calendario'),dict(grupo='ATRASADAS',modo='LISTA'))
        self.assertIn(row.pk,[event['id'] for event in response.context['events']])
        response=self.client.get(reverse('operacao:calendario'),dict(grupo='NAO_PLANEJADAS',modo='LISTA'))
        self.assertEqual(response.context['queue'][0]['id'],self.da['order'].pk)

    def test_timeline_workload_and_conflict_summaries(self):
        with tenant_context(self.a):
            self.order()
            self.order()
        response=self.client.get(reverse('operacao:calendario'),dict(modo='TIMELINE',visao='DIA'))
        row=response.context['timeline'][0]
        self.assertEqual(row['total'],2)
        self.assertEqual(row['horas'],2)
        self.assertTrue(row['conflito'])
        self.assertEqual(next(summary['total'] for summary in response.context['summaries'] if summary['label']=='Conflitos'),2)

    def test_preventive_not_duplicated_when_converted(self):
        with tenant_context(self.a):
            plan=self.plan()
            item=m.PreventivaProgramada.objects.create(plano=plan,equipamento=self.da['equipment'],data=self.today)
            self.assertEqual(len(ps.preventive_events(self.admin)),1)
            item.ordem=self.order(tipo_atendimento='PREVENTIVA')
            item.save()
            self.assertEqual(ps.preventive_events(self.admin),[])
            self.assertEqual(ps.order_event(item.ordem)['source'],'Plano preventivo')

    def test_contract_origin_and_conversion_dedup(self):
        with tenant_context(self.a):
            form=self.contract_form()
            self.assertTrue(form.is_valid())
            contract=gs.salvar_contrato(self.admin,form)
            agenda=g.AgendaPreventiva.objects.filter(contrato=contract).first()
            count=len(ps.preventive_events(self.admin))
            agenda.ordem=self.order()
            agenda.tecnico=self.da['tech']
            agenda.save()
            self.assertEqual(len(ps.preventive_events(self.admin)),count-1)
            self.assertEqual(ps.order_event(agenda.ordem)['contrato'],contract.numero)

    def test_technical_own_agenda_and_option_isolation(self):
        with tenant_context(self.a):
            from contas.models import Tecnico
            other=Tecnico.objects.create(nome='Técnico invisível')
            row=self.order(tecnico=other)
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get(reverse('operacao:calendario'))
        self.assertNotContains(response,'Técnico invisível')
        self.assertEqual(self.client.get(reverse('operacao:planning_detail',args=[row.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('operacao:planning_schedule',args=[self.da['order'].pk]),{}).status_code,403)

    def test_all_views_and_options_respect_organization(self):
        for mode in ['CALENDARIO','LISTA','TIMELINE']:
            response=self.client.get(reverse('operacao:calendario'),dict(modo=mode))
            self.assertNotContains(response,self.db['customer'].nome_razao_social)
            self.assertNotContains(response,self.db['tech'].nome)
        for name in ['planning_detail','planning_schedule']:
            self.assertEqual(self.client.get(reverse('operacao:'+name,args=[self.db['order'].pk])).status_code,404)

    def test_planners_can_plan_but_not_finance_stock_or_full_os(self):
        for user in [self.planner,self.attendant]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('operacao:calendario')).status_code,200)
            self.assertEqual(self.client.get(reverse('operacao:planning_quick')).status_code,200)
            self.assertEqual(self.client.get('/financeiro/').status_code,403)
            self.assertEqual(self.client.get('/estoque/').status_code,403)
            self.assertEqual(self.client.get(reverse('ordens:detalhe',args=[self.da['order'].pk])).status_code,403)

    def test_stock_finance_contability_no_planning_permissions(self):
        for role in ['ESTOQUE','FINANCEIRO','CONTABILIDADE']:
            self.client.force_login(self.users[role])
            self.assertEqual(self.client.get(reverse('operacao:calendario')).status_code,403)
            self.assertEqual(self.client.get(reverse('operacao:planning_quick')).status_code,403)

    def test_detail_has_operational_equipment_and_no_prices(self):
        response=self.client.get(reverse('operacao:planning_detail',args=[self.da['order'].pk]))
        self.assertEqual(response.status_code,200)
        self.assertIn('fabricante',response.json())
        self.assertEqual(response.json()['pecas'],[])
        self.assertNotIn('valor_cobranca',response.json())

    def test_my_agenda_includes_completed_original_os(self):
        with tenant_context(self.a):self.finalize(self.da['order'])
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get(reverse('operacao:tecnico'))
        self.assertContains(response,'Concluídas hoje')
        self.assertContains(response,self.da['order'].numero)

    def test_unscheduled_started_and_finished_visible_by_real_timestamps(self):
        with tenant_context(self.a):
            row=self.da['order']
            os_services.iniciar(self.admin,row.pk,dict(resultado='NEGADA',latitude=None,longitude=None,precisao=None))
            row.refresh_from_db()
            event=ps.order_event(row)
            self.assertEqual(event['date'],self.today)
            self.assertFalse(event['unplanned'])
            self.assertEqual(event['time_origin'],'Início')
        response=self.client.get(reverse('operacao:calendario'),dict(visao='DIA',modo='LISTA',status='EXECUCAO'))
        self.assertEqual(response.context['events'][0]['id'],row.pk)

    def test_expected_end_overdue_flags_running_os(self):
        with tenant_context(self.a):
            row=self.order(status='EXECUCAO',inicio=timezone.now()-timezone.timedelta(hours=3),agendada_para=timezone.now()-timezone.timedelta(hours=3),agendada_ate=timezone.now()-timezone.timedelta(hours=1))
            self.assertTrue(ps.late(row))

    def test_stock_reserved_pending_reuses_current_metrics(self):
        from . import stock
        with tenant_context(self.a):
            depot=m.Deposito.objects.create(nome='Depósito integrado')
            part=self.da['part']
            gs.movimentar(self.admin,part.pk,'ENTRADA',5,'Entrada',destino_id=depot.pk)
            stock.reserve(self.admin,part.pk,depot.pk,2,'Separação',order_id=self.da['order'].pk)
            supplier=g.Fornecedor.objects.create(nome='Fornecedor integrado')
            purchase=m.Compra.objects.create(deposito=depot,fornecedor=supplier,necessidade='Reposição',vencimento=self.today,criado_por=self.admin)
            m.ItemCompra.objects.create(compra=purchase,peca=part,quantidade=4,custo_unitario=10)
            self.assertEqual(stock.metrics(part)['em_compra'],0)
            from .services import compra_acao
            compra_acao(self.admin,purchase.pk,'aprovar')
        response=self.client.get(reverse('operacao:planning_detail',args=[self.da['order'].pk]))
        part=response.json()['pecas'][0]
        self.assertEqual(part['reservado_os'],'2.000')
        self.assertEqual(part['disponivel'],'3.000')
        self.assertEqual(Decimal(part['em_compra']),Decimal('4'))
        self.assertNotIn('custo',part)

    def test_existing_create_conflict_shows_error_without_http500(self):
        with tenant_context(self.a):self.order()
        response=self.client.post(reverse('ordens:criar'),self.quick_data(tecnico=self.da['tech'].pk,agendada_para=self.start.isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=1)).isoformat()))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Conflito')

    def test_calendar_completed_without_planned_date(self):
        with tenant_context(self.a):self.finalize(self.da['order'])
        response=self.client.get(reverse('operacao:calendario'),dict(visao='DIA',modo='LISTA',status='FINALIZADA'))
        self.assertEqual(response.context['events'][0]['id'],self.da['order'].pk)

    def test_own_preventive_without_os_is_filterable_by_technician(self):
        from clientes.models import Cliente,Unidade
        from equipamentos.models import Equipamento
        with tenant_context(self.a):
            customer=Cliente.objects.create(nome_razao_social='Outro cliente da preventiva',cpf_cnpj='PREVENTIVA-OWN')
            equipment=Equipamento.objects.create(nome='Equipamento sem OS',categoria=self.da['equipment'].categoria,cliente=customer)
            plan=m.PlanoPreventivo.objects.create(nome='Plano próprio sem OS',cliente=customer,tecnico=self.da['tech'],fim=self.today+timezone.timedelta(days=30))
            m.PlanoEquipamento.objects.create(plano=plan,equipamento=equipment)
            m.PreventivaProgramada.objects.create(plano=plan,equipamento=equipment,data=self.today)
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get(reverse('operacao:calendario'),dict(cliente=customer.pk))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,customer.nome_razao_social)

class PanelTests(PlanningData,TestCase):
    def setUp(self):self.setup_planning()

    def test_explicit_permission_default_denied_even_admin(self):
        self.assertEqual(self.client.get(reverse('operacao:operational_panel')).status_code,403)
        self.assertEqual(self.client.get(reverse('operacao:panel_data')).status_code,403)

    def test_tv_readonly_user_cannot_enter_other_modules(self):
        self.grant(self.viewer)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('operacao:operational_panel')).status_code,200)
        for path in ['/ordens/','/estoque/','/financeiro/','/configuracoes/','/planejamento/']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post(reverse('operacao:panel_data'),{}).status_code,405)

    def test_permission_revocation_checked_each_poll(self):
        self.grant(self.viewer)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('operacao:panel_data')).status_code,200)
        self.grant(self.viewer,False)
        self.assertEqual(self.client.get(reverse('operacao:panel_data')).status_code,403)

    def test_grant_is_bound_to_membership_in_selected_organization(self):
        from platform_core.models import OrganizationMembership
        self.grant(self.admin)
        member=OrganizationMembership.objects.create(organization=self.b,user=self.admin,role='PAINEL')
        other=MembershipERP.objects.create(membership=member,erp=self.erp)
        session=self.client.session
        session['organization_id']=self.b.pk
        session.save()
        self.assertEqual(self.client.get(reverse('operacao:panel_data')).status_code,403)
        other.visualizar_painel_operacional=True
        other.save()
        response=self.client.get(reverse('operacao:panel_data'))
        self.assertEqual(response.json()['organization'],self.b.display_name)
        self.assertNotContains(response,self.da['customer'].nome_razao_social)

    def test_admin_grants_permission_in_existing_users_ui_and_audits(self):
        response=self.client.post(reverse('contas:usuario_update',args=[self.viewer.pk]),dict(perfil='PAINEL',status='ATIVO',acesso_assistencia=True,visualizar_painel_operacional=True))
        self.assertEqual(response.status_code,302)
        self.assertTrue(MembershipERP.objects.get(membership__user=self.viewer).visualizar_painel_operacional)
        from platform_core.models import PlatformAudit
        change=PlatformAudit.objects.get(action='MEMBERSHIP_ALTERADO',organization=self.a)
        self.assertTrue(change.changes['visualizar_painel_operacional']['posterior'])

    def test_grant_does_not_widen_finance_existing_access(self):
        user=self.users['FINANCEIRO']
        self.grant(user)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('operacao:panel_data')).status_code,200)
        self.assertEqual(self.client.get(reverse('operacao:calendario')).status_code,403)

    def test_client_cannot_have_tv_even_with_grant(self):
        user=self.user('portal-tv',self.a,'CLIENTE')
        self.grant(user)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('operacao:panel_data')).status_code,403)

    def test_payload_privacy_and_other_organization(self):
        self.grant(self.admin)
        with tenant_context(self.a):
            self.order(prioridade='URGENTE',valor_cobranca=999,observacoes='SEGREDO CLINICO',diagnostico='SEGREDO DIAGNOSTICO')
        response=self.client.get(reverse('operacao:panel_data'))
        content=response.content.decode()
        for value in ['SEGREDO CLINICO','SEGREDO DIAGNOSTICO','valor_cobranca','cpf_cnpj','telefone','email','salario','custo_hora',self.db['customer'].nome_razao_social]:self.assertNotIn(value,content)
        self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertEqual(response.json()['organization'],self.a.display_name)

    def test_poll_reflects_start_and_conclusion_from_existing_flow(self):
        self.grant(self.admin)
        with tenant_context(self.a):
            row=self.order()
            before=tv.payload(self.admin)
            self.assertEqual(before['indicadores']['Em atendimento'],0)
            self.finalize(row)
            after=tv.payload(self.admin)
            self.assertEqual(after['indicadores']['Concluídas hoje'],1)
            self.assertEqual(after['concluidas'][0]['numero'],row.numero)

    def test_active_elapsed_and_next_real_order(self):
        self.grant(self.admin)
        with tenant_context(self.a):
            row=self.order()
            following=self.order(agendada_para=timezone.now()+timezone.timedelta(days=1),agendada_ate=None)
            os_services.iniciar(self.admin,row.pk,dict(resultado='NEGADA',latitude=None,longitude=None,precisao=None))
            data=tv.payload(self.admin)
            self.assertTrue(data['agora'][0]['inicio'])
            self.assertEqual(data['equipe'][0]['proxima']['numero'],following.numero)
            self.assertNotIn('localizacao',data['agora'][0])

    def test_team_availability_not_invented_presence_or_transit(self):
        self.grant(self.admin)
        with tenant_context(self.a):
            data=tv.payload(self.admin)
            self.assertEqual(data['equipe'][0]['status'],'Sem atendimento em execução')
            self.assertIsNone(data['equipe'][0]['proxima'])
            self.assertNotIn('online',json.dumps(data,default=str))

    def test_admin_tv_config_preserves_stock_and_audits(self):
        with tenant_context(self.a):m.Configuracao.objects.create(intervalo_alertas_minutos=45)
        response=self.client.post(reverse('operacao:panel_config'),dict(painel_intervalo=15,painel_tema='CLARO',painel_blocos=['agora','indicadores']))
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            config=m.Configuracao.objects.get()
            self.assertEqual(config.intervalo_alertas_minutos,45)
            self.assertEqual(config.painel_intervalo,15)
            from platform_core.models import PlatformAudit
            self.assertEqual(PlatformAudit.objects.filter(organization=self.a,action='PAINEL_OPERACIONAL_CONFIGURADO').count(),1)

    def test_bad_refresh_and_unknown_block_rejected(self):
        response=self.client.post(reverse('operacao:panel_config'),dict(painel_intervalo=1,painel_tema='CLARO',painel_blocos=['financeiro']))
        self.assertEqual(response.status_code,400)

    def test_manager_cannot_change_admin_config(self):
        self.client.force_login(self.users['GESTOR'])
        self.assertEqual(self.client.get(reverse('operacao:panel_config')).status_code,403)

    def test_query_count_not_proportional_to_number_of_orders(self):
        from django.test.utils import CaptureQueriesContext
        self.grant(self.admin)
        with tenant_context(self.a):
            for _ in range(12):self.order()
            with CaptureQueriesContext(connection) as captured:tv.payload(self.admin)
            self.assertLess(len(captured),25)

@skipUnless(connection.vendor=='postgresql','Locks exigem PostgreSQL')
class PlanningConcurrencyTests(PlanningData,TransactionTestCase):
    def setUp(self):self.setup_planning()

    def test_concurrent_same_technician_one_schedule_succeeds(self):
        barrier=Barrier(2)
        def run(index):
            connections.close_all()
            try:
                with tenant_context(self.a):
                    form=QuickOrderForm(self.quick_data(tecnico=self.da['tech'].pk,agendada_para=self.start.isoformat(),agendada_ate=(self.start+timezone.timedelta(hours=1)).isoformat(),defeito=f'Concorrente {index}'),user=self.admin)
                    assert form.is_valid(),form.errors
                    barrier.wait(timeout=15)
                    try:ps.save_plan(self.admin,form);return 'OK'
                    except ValidationError:return 'CONFLITO'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[1,2]))
        self.assertCountEqual(results,['OK','CONFLITO'])
        with tenant_context(self.a):self.assertEqual(OrdemServico.objects.filter(defeito__startswith='Concorrente').count(),1)
