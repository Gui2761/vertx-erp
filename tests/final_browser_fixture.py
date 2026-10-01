"""Complementa o ensaio anterior com usuário de portal e dados novos, somente localhost."""
exec(compile((__import__('pathlib').Path(__file__).with_name('modules_browser_fixture.py')).read_text(encoding='utf-8'), __file__, 'exec'))
from operacao.models import PortalCliente
from gestao.models import Lancamento
with tenant_context(organization):
    portal_user,_=Usuario.objects.get_or_create(username='ensaio-portal-local')
    portal_user.set_password(values['BROWSER_TEST_PASSWORD'])
    portal_user.save()
    portal_member,_=OrganizationMembership.objects.get_or_create(user=portal_user,organization=organization,defaults={'role':'CLIENTE'})
    MembershipERP.objects.get_or_create(membership=portal_member,erp=erp)
    PortalCliente.objects.get_or_create(usuario=portal_user,cliente=customer)
    # Cliente da mesma organização, que o portal deve ocultar.
    restricted,_=Cliente.objects.get_or_create(cpf_cnpj='LOCAL-PRIVATE',defaults={'nome_razao_social':'[TESTE LOCAL] CLIENTE SEM ACESSO'})
    if not Lancamento.objects.filter(cliente=restricted,descricao='[TESTE LOCAL] RECEITA PRIVADA').exists():
        Lancamento.objects.create(cliente=restricted,tipo='RECEBER',descricao='[TESTE LOCAL] RECEITA PRIVADA',valor=33,vencimento=today,criado_por=user)
data.update(portal_username=portal_user.username)
(output/'final-browser.json').write_text(json.dumps(data),encoding='utf-8')
print('Portal e isolamento entre clientes preparados somente no ensaio local.')
