"""Dados e verificações do ensaio de estoque; executa exclusivamente em localhost."""
import json, os, sys, uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
values=json.loads((root/'tmp/provision/https_test_environment.json').read_text())
assert values['DATABASE_URL'].split('@')[1]=='127.0.0.1:55432/vertyx_homologation'
assert values['S3_ENDPOINT_URL']=='https://127.0.0.1:9501'
os.environ.update(values)
os.environ['DJANGO_SETTINGS_MODULE']='tecnolmed.settings'
import django
django.setup()
from django.utils import timezone
from contas.models import Usuario
from platform_core.models import Organization, OrganizationMembership, MembershipERP, ERPCatalog
from platform_core.context import tenant_context
from gestao import models as g
from operacao import models as m, stock, stock_scheduler
output=root/'tmp/validation'
f=json.loads((output/'final-browser.json').read_text())
org=Organization.objects.get(slug='ensaio-modulos-local')
user=Usuario.objects.get(username=f['username'])
erp=ERPCatalog.objects.get(code='assistencia')
mode=sys.argv[1] if len(sys.argv)>1 else 'prepare'
with tenant_context(org):
    if mode=='prepare':
        roles={}
        for role in ['GESTOR','ESTOQUE','TECNICO']:
            member_user,_=Usuario.objects.get_or_create(username='stock-local-'+role.lower())
            member_user.set_password(values['BROWSER_TEST_PASSWORD']);member_user.save()
            member,_=OrganizationMembership.objects.get_or_create(user=member_user,organization=org,defaults={'role':role})
            MembershipERP.objects.get_or_create(membership=member,erp=erp)
            roles[role]=member_user.username
        part=g.Peca.objects.create(sku='LOT-'+uuid.uuid4().hex[:10],descricao='[TESTE LOCAL] Luva com validade',estoque_minimo=7,estoque_maximo=20,controla_validade=True,custo_aquisicao='12.50',preco_venda=20)
        supplier=g.Fornecedor.objects.create(nome='[TESTE LOCAL] Fornecedor de lotes')
        depot=m.Deposito.objects.create(nome='[TESTE LOCAL] Almoxarifado '+str(part.pk))
        pending=m.Compra.objects.create(deposito=depot,fornecedor=supplier,necessidade='[TESTE LOCAL] Compra pendente',vencimento=timezone.localdate(),criado_por=user)
        m.ItemCompra.objects.create(compra=pending,peca=part,quantidade=2,custo_unitario='12.50')
        data={**f,'roles':roles,'part':part.pk,'depot':depot.pk,'supplier':supplier.pk,'sku':part.sku,'dates':{key:(timezone.localdate()+timezone.timedelta(days=days)).isoformat() for key,days in [('near',7),('far',180),('expired',-1),('received',365)]}}
        (output/'stock-browser.json').write_text(json.dumps(data),encoding='utf-8')
    else:
        data=json.loads((output/'stock-browser.json').read_text())
        part=g.Peca.objects.get(pk=data['part'])
        if mode=='tick':
            config,_=m.Configuracao.objects.get_or_create()
            config.ultima_verificacao_estoque=None
            config.relatorio_dia_semana=0
            config.relatorio_horario=timezone.datetime.min.time()
            config.save()
            result=stock_scheduler.tick(user)
            report=m.RelatorioEstoque.objects.filter(automatico=True).first()
            # Se já houver snapshot da semana de um ensaio anterior, manter o histórico
            # e gerar uma análise manual atual, em vez de alterar o relatório antigo.
            if not report.itens.filter(peca=part).exists():
                report=stock.generate_report(user,automatic=False)
            line=report.itens.get(peca=part)
            data.update(report=report.pk,line=line.pk,suggested=line.dados['sugerido'])
            (output/'stock-browser.json').write_text(json.dumps(data),encoding='utf-8')
            assert m.LoteEstoque.objects.get(peca=part,numero='PROXIMO').quantidade==0
            assert stock.metrics(part)['disponivel']==6
            assert stock.metrics(part)['em_compra']==2
            assert line.dados['sugerido']=='12.000'
        elif mode=='verify':
            purchase=m.Compra.objects.get(relatorio_estoque_id=data['report'],itens__peca=part)
            assert purchase.status=='RECEBIDA'
            assert purchase.itens.get().quantidade==11
            assert purchase.conta.valor==purchase.total
            assert m.LoteEstoque.objects.get(item_compra__compra=purchase).numero=='RECEBIMENTO'
            assert stock.metrics(part)['fisico']==22
            assert stock.total(part.lotes.all())==22
            assert stock.total(m.SaldoDeposito.objects.filter(peca=part))==22
            stock.scan_stock(user)
            assert not m.OcorrenciaEstoque.objects.filter(peca=part,tipo='REPOSICAO',resolvida_em__isnull=True).exists()
            assert m.ItemRelatorioEstoque.objects.get(pk=data['line']).dados['sugerido']=='12.000'
            data.update(purchase=purchase.pk,sale=m.Venda.objects.get(itens__peca=part).pk)
            (output/'stock-browser.json').write_text(json.dumps(data),encoding='utf-8')
        else:
            raise ValueError('Modo de ensaio inválido.')
print('PASS: fixtures/validação de estoque somente localhost; sem saída de credenciais.')
