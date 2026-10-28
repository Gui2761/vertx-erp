from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from platform_core.models import Organization, OrganizationMembership, ModuloOrganizacao, ConfiguracaoEmpresa
from platform_core.context import tenant_context
from platform_core.saas_forms import PlanoSaaSForm
from platform_core.saas_models import CORE_SAAS_MODULES, AdministradorPlataforma, AssinaturaSaaS, AuditoriaSaaS, PlanoSaaS, PrimeiroAcessoSaaS
from .models import PlanoComercial
from .catalog import DEFAULT_PLANS, DEFAULT_RESOURCES


def valid_cnpj(base):
    digits=''.join(str(value) for value in base)
    def check(values, weights):
        remainder=sum(int(value)*weight for value,weight in zip(values,weights))%11
        return '0' if remainder<2 else str(11-remainder)
    first=check(digits,[5,4,3,2,9,8,7,6,5,4,3,2])
    second=check(digits+first,[6,5,4,3,2,9,8,7,6,5,4,3,2])
    return digits+first+second


class PublicSaaSSignupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for values in DEFAULT_PLANS:
            PlanoComercial.objects.update_or_create(
                slug=values['slug'],defaults={**values,'recursos':dict(DEFAULT_RESOURCES)},
            )
        cls.professional=PlanoComercial.objects.get(slug='profissional')
        # Public signup must use explicitly configured SaaS plans. The test
        # fixture mirrors those prerequisites instead of inferring SaaS setup
        # from commercial prices or relying on database seed records.
        limits = {'basico':(3,1), 'profissional':(10,3), 'empresarial':(30,10)}
        for slug, (users, branches) in limits.items():
            offer=PlanoComercial.objects.get(slug=slug)
            PlanoSaaS.objects.update_or_create(
                slug=slug,
                defaults={
                    'nome': offer.nome, 'plano_comercial': offer,
                    'preco': Decimal(offer.preco), 'periodicidade': 'MENSAL',
                    'publico_ativo': True, 'modulos': list(CORE_SAAS_MODULES),
                    'limites': {'usuarios':users,'filiais':branches,'armazenamento_mb':None,
                                'vendas_mes':None,'ordens_mes':None},
                },
            )

    def make_saas_plan(self, slug='profissional', price='249.00', modules=None):
        plan=PlanoSaaS.objects.get(slug=slug)
        plan.nome='Profissional';plan.preco=Decimal(price);plan.periodicidade='MENSAL'
        plan.plano_comercial=self.professional;plan.publico_ativo=True
        plan.modulos=list(dict.fromkeys([*CORE_SAAS_MODULES, *(modules or [])]))
        plan.limites={'usuarios':10,'filiais':None,'armazenamento_mb':None,
                      'vendas_mes':None,'ordens_mes':None}
        plan.save()
        return plan

    def signup_data(self, cnpj_base='128765430001', *, company='Empresa de Homologação A', admin_email='owner-a@example.test'):
        return {
            'plano':'profissional','periodo':'MENSAL',
            'razao_social':company,'nome_fantasia':company,'cnpj':valid_cnpj(cnpj_base),
            'email':f'{cnpj_base}@empresa.example.test','telefone':'(11) 99999-1010',
            'endereco':'Rua Sintética, 100','cidade':'São Paulo','uf':'SP',
            'admin-nome':'Administradora Inicial','admin-email':admin_email,
            'admin-whatsapp':'(11) 98888-1010',
        }

    def test_approved_monthly_offers_show_online_signup_and_custom_stays_contact_only(self):
        response=self.client.get('/planos/')
        self.assertEqual(response.status_code,200)
        cards={card['plan'].slug:card for card in response.context['plans']}
        self.assertEqual({slug:cards[slug]['price'] for slug in ('basico','profissional','empresarial')},
                         {'basico':'149','profissional':'249','empresarial':'399'})
        for slug in ('basico','profissional','empresarial'):
            self.assertTrue(cards[slug]['contracting_available'])
            self.assertIn('/cadastro/?plano='+slug,cards[slug]['cta'])
        self.assertFalse(cards['personalizado']['contracting_available'])
        self.assertIn('/demonstracao/',cards['personalizado']['cta'])
        self.assertEqual((cards['basico']['limit_users'],cards['basico']['limit_branches']),(3,1))
        self.assertEqual((cards['profissional']['limit_users'],cards['profissional']['limit_branches']),(10,3))
        self.assertEqual((cards['empresarial']['limit_users'],cards['empresarial']['limit_branches']),(30,10))

    def test_signup_referrer_policy_keeps_same_origin_csrf_and_rejects_opaque_origin(self):
        self.make_saas_plan()
        client=Client(enforce_csrf_checks=True)
        page=client.get('/cadastro/?plano=profissional&periodo=MENSAL')
        self.assertEqual(page.status_code,200)
        self.assertEqual(page['Referrer-Policy'],'strict-origin-when-cross-origin')
        self.assertIn('csrftoken',client.cookies)
        token=client.cookies['csrftoken'].value
        before=Organization.objects.count()
        valid_origin=client.post('/cadastro/',{
            'csrfmiddlewaretoken':token,'plano':'profissional','periodo':'MENSAL',
        },HTTP_ORIGIN='http://testserver')
        self.assertEqual(valid_origin.status_code,400)  # Form validation; CSRF passed.
        self.assertEqual(Organization.objects.count(),before)

        opaque=Client(enforce_csrf_checks=True)
        opaque.get('/cadastro/?plano=profissional&periodo=MENSAL')
        rejected=opaque.post('/cadastro/',{
            'csrfmiddlewaretoken':opaque.cookies['csrftoken'].value,
            'plano':'profissional','periodo':'MENSAL',
        },HTTP_ORIGIN='null')
        self.assertEqual(rejected.status_code,403)
        self.assertEqual(Organization.objects.count(),before)

    def test_sem_correspondencia_saas_nao_apresenta_contratacao_e_nao_cria_empresa(self):
        plan=PlanoSaaS.objects.get(slug='profissional')
        plan.publico_ativo=False
        plan.save()
        organizations_before=Organization.objects.count()
        response=self.client.get('/planos/')
        card=next(card for card in response.context['plans'] if card['plan'].slug=='profissional')
        self.assertFalse(card['contracting_available'])
        self.assertEqual(card['cta'],'/demonstracao/?plano=profissional&periodo=MENSAL')
        self.assertEqual(self.client.get('/cadastro/?plano=profissional&periodo=MENSAL').status_code,409)
        self.assertEqual(Organization.objects.count(),organizations_before)
        self.assertEqual(AssinaturaSaaS.objects.count(),0)

    def test_admin_saas_configura_vinculo_explicitamente_e_nao_infere_modulos_ou_limites(self):
        data={'slug':'profissional','nome':'Profissional','descricao':'',
              'plano_comercial':str(self.professional.pk),'preco':'249.00',
              'periodicidade':'MENSAL','publico_ativo':'on','ativo':'on',
              'nivel_indicadores':'BASICO',
              'modulos':['assistencia'],'limite_usuarios':'',
              'limite_filiais':'','limite_armazenamento_mb':'',
              'limite_vendas_mes':'','limite_ordens_mes':''}
        form=PlanoSaaSForm(data,instance=PlanoSaaS.objects.get(slug='profissional'))
        self.assertTrue(form.is_valid(),form.errors)
        plan=form.save()
        self.assertEqual(plan.plano_comercial,self.professional)
        self.assertTrue(plan.publico_ativo)
        self.assertEqual(set(plan.modulos),set(CORE_SAAS_MODULES))
        self.assertEqual(plan.limites,{'usuarios':None,'filiais':None,'armazenamento_mb':None,
                                       'vendas_mes':None,'ordens_mes':None})
        data['slug']='outro-plano';data['preco']='248.00'
        mismatch=PlanoSaaSForm(data)
        self.assertFalse(mismatch.is_valid())
        self.assertIn('preco',mismatch.errors)

    def test_public_offer_includes_fiscal_module_without_enabling_transmission(self):
        data={'slug':'profissional','nome':'Profissional','descricao':'',
              'plano_comercial':str(self.professional.pk),'preco':'249.00',
              'periodicidade':'MENSAL','publico_ativo':'on','ativo':'on',
              'nivel_indicadores':'BASICO',
              'modulos':['assistencia','fiscal'],'limite_usuarios':'10',
              'limite_filiais':'3','limite_armazenamento_mb':'',
              'limite_vendas_mes':'','limite_ordens_mes':''}
        form=PlanoSaaSForm(data,instance=PlanoSaaS.objects.get(slug='profissional'))
        self.assertTrue(form.is_valid(),form.errors)
        self.assertIn('fiscal',form.cleaned_data['modulos'])
        plan=form.save()
        self.assertIn('fiscal',plan.modulos)
        data['modulos']=['assistencia','gestao_publica','rh_municipal']
        form=PlanoSaaSForm(data,instance=PlanoSaaS.objects.get(slug='profissional'))
        self.assertFalse(form.is_valid())
        self.assertIn('modulos',form.errors)

    def test_correspondencia_exige_mesmo_preco_periodicidade_e_plano_ativo(self):
        self.make_saas_plan(price='249.00')
        plan=PlanoSaaS.objects.get(slug='profissional')
        plan.publico_ativo=False;plan.preco=Decimal('248.00');plan.save()
        self.assertEqual(self.client.get('/cadastro/?plano=profissional&periodo=MENSAL').status_code,409)
        plan.preco=Decimal('249.00');plan.save()
        plan.publico_ativo=True;plan.save()
        card=next(card for card in self.client.get('/planos/').context['plans'] if card['plan'].slug=='profissional')
        self.assertTrue(card['contracting_available'])
        self.assertEqual(card['cta'],'/cadastro/?plano=profissional&periodo=MENSAL')
        plan.publico_ativo=False;plan.ativo=False;plan.save()
        self.assertEqual(self.client.get('/cadastro/?plano=profissional&periodo=MENSAL').status_code,409)

    def test_fluxo_publico_cria_tenant_admin_subscription_hash_e_primeiro_acesso(self):
        plan=self.make_saas_plan()
        page=self.client.get('/cadastro/?plano=profissional&periodo=MENSAL')
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'Profissional')
        self.assertContains(page,'R$ 249,00')
        response=self.client.post('/cadastro/',self.signup_data())
        self.assertRedirects(response,'/cadastro/confirmacao/')
        organization=Organization.objects.get(razao_social='Empresa de Homologação A')
        user=get_user_model().objects.get(email='owner-a@example.test')
        membership=OrganizationMembership.objects.get(user=user,organization=organization)
        subscription=AssinaturaSaaS.objects.get(organization=organization)
        self.assertEqual(subscription.plano,plan)
        self.assertEqual(subscription.status,AssinaturaSaaS.Status.IMPLANTACAO)
        self.assertEqual(membership.role,'ADMIN')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(AdministradorPlataforma.objects.filter(user=user).exists())
        self.assertEqual(
            set(ModuloOrganizacao.all_objects.filter(
                organization=organization,habilitado=True,
            ).values_list('codigo',flat=True)),
            set(CORE_SAAS_MODULES) | {'estoque','financeiro'},
        )
        with tenant_context(organization):
            self.assertEqual(ConfiguracaoEmpresa.objects.get(organization=organization).limites,{'usuarios':10})
        self.assertEqual(subscription.plano.limites,plan.limites)
        row=PrimeiroAcessoSaaS.objects.get(user=user,organization=organization)
        token=self.client.session['public_saas_pending_access']['token']
        self.assertEqual(row.token_digest,PrimeiroAcessoSaaS.digest(token))
        self.assertNotIn(token,row.token_digest)
        self.assertEqual(AuditoriaSaaS.objects.filter(organization=organization).count(),4)
        self.assertTrue(AuditoriaSaaS.objects.filter(organization=organization,actor__isnull=True).exists())
        confirmation=self.client.get('/cadastro/confirmacao/')
        self.assertEqual(confirmation.status_code,200)
        self.assertEqual(confirmation['Cache-Control'],'private, no-store')
        self.assertEqual(confirmation['Referrer-Policy'],'no-referrer')
        first_access=self.client.get('/cadastro/primeiro-acesso/')
        first_access_url=reverse('platform_core:saas_first_access',args=[token])
        self.assertRedirects(first_access,first_access_url,fetch_redirect_response=False)
        self.assertEqual(self.client.post(first_access_url,{
            'new_password1':'Synthetic!Pass123','new_password2':'Synthetic!Pass123',
        }).status_code,200)
        row.refresh_from_db();user.refresh_from_db()
        self.assertIsNotNone(row.usado_em)
        self.assertTrue(user.has_usable_password())
        self.assertNotIn('public_saas_pending_access',self.client.session)
        login=self.client.post('/login/',{'username':user.username,'password':'Synthetic!Pass123'},follow=True)
        self.assertTrue(login.wsgi_request.user.is_authenticated)

    def test_dois_cadastros_independentes_e_isolamento_de_memberships(self):
        self.make_saas_plan()
        organizations_before=Organization.objects.count()
        first=self.client.post('/cadastro/',self.signup_data())
        self.assertEqual(first.status_code,302)
        self.client.get('/cadastro/confirmacao/')
        second_data=self.signup_data('128765430002',company='Empresa de Homologação B',admin_email='owner-b@example.test')
        second=self.client.post('/cadastro/',second_data)
        self.assertEqual(second.status_code,302)
        self.assertEqual(Organization.objects.count(),organizations_before+2)
        org_a=Organization.objects.get(razao_social='Empresa de Homologação A')
        org_b=Organization.objects.get(razao_social='Empresa de Homologação B')
        user_a=get_user_model().objects.get(email='owner-a@example.test')
        user_b=get_user_model().objects.get(email='owner-b@example.test')
        self.assertEqual(list(user_a.memberships.values_list('organization_id',flat=True)),[org_a.pk])
        self.assertEqual(list(user_b.memberships.values_list('organization_id',flat=True)),[org_b.pk])
        self.assertFalse(user_a.memberships.filter(organization=org_b).exists())
        self.assertFalse(user_b.memberships.filter(organization=org_a).exists())

    def test_post_nao_pode_adulterar_plano_ou_periodo(self):
        self.make_saas_plan()
        organizations_before=Organization.objects.count()
        data=self.signup_data();data['plano']='personalizado'
        self.assertEqual(self.client.post('/cadastro/',data).status_code,409)
        self.assertEqual(Organization.objects.count(),organizations_before)
        data=self.signup_data();data['periodo']='ANUAL'
        self.assertEqual(self.client.post('/cadastro/',data).status_code,409)
        self.assertEqual(Organization.objects.count(),organizations_before)

    def test_duplicidade_de_cnpj_ou_email_nao_cria_registro_parcial(self):
        self.make_saas_plan()
        organizations_before=Organization.objects.count()
        users_before=get_user_model().objects.count()
        data=self.signup_data()
        self.assertEqual(self.client.post('/cadastro/',data).status_code,302)
        self.client.get('/cadastro/confirmacao/')
        duplicate_cnpj=self.client.post('/cadastro/',{**data,'admin-email':'owner-c@example.test'})
        self.assertEqual(duplicate_cnpj.status_code,400)
        duplicate_email=self.client.post('/cadastro/',self.signup_data('128765430002',company='Empresa B'))
        self.assertEqual(duplicate_email.status_code,400)
        self.assertEqual(Organization.objects.count(),organizations_before+1)
        self.assertEqual(get_user_model().objects.count(),users_before+1)
        self.assertEqual(AssinaturaSaaS.objects.count(),1)
