"""Dados e verificações do navegador; somente PostgreSQL sintético em localhost."""
import json, os, sys, uuid
from datetime import datetime,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
values=json.loads((root/'tmp/provision/https_test_environment.json').read_text())
assert values['DATABASE_URL'].split('@')[1]=='127.0.0.1:55432/vertyx_homologation'
os.environ.update(values)
os.environ['DJANGO_SETTINGS_MODULE']='tecnolmed.settings'
import django
django.setup()
from django.utils import timezone
from platform_core.context import tenant_context
from platform_core.models import Organization,OrganizationMembership,MembershipERP,ERPCatalog
from contas.models import Usuario,Tecnico
from ordens.models import OrdemServico
from gestao.tests import Dados
from operacao.models import Configuracao,PlanoPreventivo,PlanoEquipamento,PreventivaProgramada
from operacao.planning_services import orders_for
from operacao import models as m,stock
from gestao import models as g,services as gs
fixture=root/'tmp/validation/planning-browser.json'
mode=sys.argv[1] if len(sys.argv)>1 else 'prepare'
if mode!='prepare':
    f=json.loads(fixture.read_text())
    org=Organization.objects.get(pk=f['organization_id'])
    with tenant_context(org):
        if mode=='afterquick':
            row=OrdemServico.objects.filter(defeito=f['description']).latest('pk')
            assert row.tecnico_id is None and row.agendada_para is None
            f.update(created_os=row.pk,created_numero=row.numero)
        elif mode=='verify_schedule':
            row=OrdemServico.objects.get(pk=f['created_os'])
            assert row.status=='AGENDADA' and row.prioridade=='URGENTE'
            assert row.historico.filter(acao='PLANEJAMENTO',justificativa='Ensaio consciente com equipe de apoio').exists()
            assert row.historico.get(acao='PLANEJAMENTO').alteracoes['conflitos_autorizados']
        elif mode=='finish':
            user=Usuario.objects.get(username=f['username'])
            from ordens import services as os_services
            from ordens.forms import AssinaturaForm
            from platform_core.tests import sample_signature
            row=OrdemServico.objects.get(pk=f['ready_os'])
            assert row.status=='EXECUCAO'
            row.diagnostico='Diagnóstico sintético'
            row.servico_executado='Atendimento sintético concluído'
            row.save()
            conference=os_services.preparar(user,row.pk,dict(resultado='NEGADA',latitude=None,longitude=None,precisao=None))
            signature=AssinaturaForm(dict(token='local',nome='Responsável sintético',cargo='Gestor',imagem=sample_signature(),confirmacao=True))
            assert signature.is_valid()
            os_services.finalizar(user,row.pk,conference.pk,signature.cleaned_data)
        elif mode=='verify_finished':
            assert OrdemServico.objects.get(pk=f['ready_os']).status=='FINALIZADA'
        fixture.write_text(json.dumps(f),encoding='utf-8')
    print('PASS: verificação operacional somente na base local.')
    raise SystemExit()
f=json.loads((root/'tmp/validation/modules-browser.json').read_text())
org=Organization.objects.get(slug='ensaio-modulos-local')
erp=ERPCatalog.objects.get(code='assistencia')
user=Usuario.objects.get(username=f['username'])
grant=MembershipERP.objects.get(membership__user=user,membership__organization=org,erp=erp)
grant.visualizar_painel_operacional=True
grant.save()
suffix=uuid.uuid4().hex[:8]
f.update(organization_id=org.pk,description='BROWSER-OPS-'+suffix+' · SIGILO CLINICO <script>alert(1)</script>')
for role in ['TECNICO','PLANEJADOR','ATENDIMENTO','PAINEL']:
    login='ops-'+role.lower()+'-'+suffix
    account=Usuario.objects.create_user(login,password=f['password'],perfil=role)
    member=OrganizationMembership.objects.create(organization=org,user=account,role=role)
    MembershipERP.objects.create(membership=member,erp=erp,visualizar_painel_operacional=role=='PAINEL')
    f[role]=login
with tenant_context(org):
    config,_=Configuracao.objects.get_or_create()
    config.painel_intervalo=15
    config.save()
    tech=Tecnico.objects.create(usuario=Usuario.objects.get(username=f['TECNICO']),nome='Equipe Operações '+suffix)
    from clientes.models import Cliente,Unidade
    from equipamentos.models import Equipamento
    customer=Cliente.objects.get(pk=f['cliente'])
    unit=Unidade.objects.get(pk=f['unidade'])
    equipment=Equipamento.objects.get(pk=f['equipamento'])
    tomorrow=timezone.localdate()+timezone.timedelta(days=1)
    start=timezone.make_aware(datetime.combine(tomorrow,time(9)))
    common=dict(cliente=customer,unidade=unit,equipamento=equipment,tecnico=tech,defeito='Bancada operações')
    conflict=OrdemServico.objects.create(**common,agendada_para=start,agendada_ate=start+timezone.timedelta(hours=1),status='AGENDADA')
    ready=OrdemServico.objects.create(**common,agendada_para=timezone.now()+timezone.timedelta(minutes=30),agendada_ate=timezone.now()+timezone.timedelta(hours=1),status='AGENDADA')
    urgent=OrdemServico.objects.create(**common,prioridade='URGENTE',status='EXECUCAO',inicio=timezone.now()-timezone.timedelta(minutes=25),agendada_para=timezone.now()-timezone.timedelta(minutes=30),agendada_ate=timezone.now()+timezone.timedelta(hours=1))
    wait=OrdemServico.objects.create(**common,status='AG_PECA')
    depot=m.Deposito.objects.create(nome='OPS depósito '+suffix)
    part=g.Peca.objects.create(sku='OPS-'+suffix,descricao='Peça operacional '+suffix,estoque_minimo=2)
    gs.movimentar(user,part.pk,'ENTRADA',5,'Ensaio operações',destino_id=depot.pk)
    stock.reserve(user,part.pk,depot.pk,2,'Aguardando separação',order_id=wait.pk)
    plan=PlanoPreventivo.objects.create(nome='OPS preventiva '+suffix,cliente=customer,tecnico=tech,inicio=timezone.localdate()-timezone.timedelta(days=5),fim=tomorrow+timezone.timedelta(days=30))
    PlanoEquipamento.objects.create(plano=plan,equipamento=equipment)
    PreventivaProgramada.objects.create(plano=plan,equipamento=equipment,data=timezone.localdate()-timezone.timedelta(days=1))
    f.update(tecnico=tech.pk,tech_name=tech.nome,tomorrow=tomorrow.isoformat(),start=start.isoformat(),end=(start+timezone.timedelta(hours=1)).isoformat(),conflict_os=conflict.pk,conflict_number=conflict.numero,ready_os=ready.pk,ready_number=ready.numero,urgent_os=urgent.pk,wait_os=wait.pk,part_sku=part.sku)
fixture.write_text(json.dumps(f),encoding='utf-8')
print('Fixture operacional sintética preparada em localhost, sem infraestrutura externa.')
