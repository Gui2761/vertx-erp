from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, OrganizationERP, MembershipERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from . import phase_e_models as models
from . import phase_e_services as services
from .models import AcessoMunicipal, PermissaoMunicipal, Secretaria
from .public_services import has_municipal_permission, scoped_queryset
from .tests import MunicipalFixtures


PHASE_E_CODES = ('processo_digital', 'transparencia', 'ouvidoria', 'esic')


class MunicipalPhaseETests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.modules = {}
        self.modules['gestao_publica'] = ERPProductModule.objects.get_or_create(
            erp=self.publico, code='gestao_publica',
            defaults={'name': 'Gestão Pública', 'active': True, 'sort_order': 1},
        )[0]
        for order, code in enumerate(PHASE_E_CODES, 90):
            self.modules[code] = ERPProductModule.objects.get_or_create(
                erp=self.publico, code=code,
                defaults={'name': code.replace('_', ' ').title(), 'active': True, 'sort_order': order},
            )[0]
        self.plan = PlanoSaaS.objects.create(
            slug='fase-e-municipal-test', nome='Plano sintético Fase E', erp=self.publico, modulos=[],
        )
        for module in self.modules.values():
            PlanoProdutoModulo.objects.create(plano=self.plan, modulo=module)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.city_admin = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def _protocol(self, **overrides):
        data = {
            'origem': models.ProtocoloMunicipal.Origem.INTERNA,
            'interessado_nome': 'Interessado Sintético',
            'assunto': 'Solicitação de teste', 'resumo': 'Registro sintético de homologação.',
            'prioridade': models.ProtocoloMunicipal.Prioridade.NORMAL,
        }
        data.update(overrides)
        with tenant_context(self.c):
            return services.create_protocol(self.admin_c.user, data=data)

    def _process(self, **overrides):
        data = {'titulo': 'Processo sintético', 'assunto': 'Análise', 'descricao': 'Sem dados reais.'}
        data.update(overrides)
        with tenant_context(self.c):
            return services.create_process(self.admin_c.user, data=data)

    def test_phase_e_modules_require_active_explicit_entitlement(self):
        for code in PHASE_E_CODES:
            self.assertTrue(services.public_module_available(self.c, code))
        limited = PlanoSaaS.objects.create(slug='fase-e-sem-esic', nome='Sem E-SIC', erp=self.publico, modulos=[])
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['processo_digital'])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=limited)
        self.assertTrue(services.public_module_available(self.c, 'processo_digital'))
        self.assertFalse(services.public_module_available(self.c, 'esic'))
        AssinaturaSaaS.objects.filter(organization=self.c).update(status=AssinaturaSaaS.Status.SUSPENDED)
        self.assertFalse(services.public_module_available(self.c, 'processo_digital'))

    def test_rendered_phase_e_screens_are_permission_and_plan_gated(self):
        for name in ('processes_home', 'transparencia_home', 'ouvidoria_home', 'esic_home'):
            response = self.client.get(reverse(f'rh_municipal_public:{name}'))
            self.assertEqual(response.status_code, 200, name)
        denied = self._user('phase-e-no-access', self.c, self.publico, 'ADMIN')
        self.client.force_login(denied.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:processes_home')).status_code, 403)

    def test_protocol_and_process_numbers_are_tenant_scoped_and_transitions_are_validated(self):
        protocol = self._protocol()
        process = self._process(protocolo=protocol)
        self.assertTrue(protocol.numero.startswith('PRT-'))
        self.assertTrue(process.numero.startswith('PROC-'))
        with tenant_context(self.c):
            services.transition_process(self.admin_c.user, process.pk, status=models.ProcessoDigitalMunicipal.Status.DISTRIBUIDO)
            with self.assertRaises(ValidationError):
                services.transition_process(self.admin_c.user, process.pk, status=models.ProcessoDigitalMunicipal.Status.ARQUIVADO)
            self.assertEqual(process.tramitacoes.count(), 2)

    def test_foreign_tenant_hierarchy_reference_is_rejected(self):
        foreign_product = OrganizationERP.objects.get_or_create(organization=self.a, erp=self.publico)[0]
        foreign_product.enabled = True
        foreign_product.save(update_fields=['enabled'])
        MembershipERP.objects.get_or_create(membership=self.admin_a, erp=self.publico)
        with tenant_context(self.a):
            foreign_secretary = Secretaria.objects.create(organization=self.a, codigo='SEC-X', nome='Secretaria Externa')
        with tenant_context(self.c), self.assertRaises(ValidationError):
            services.create_protocol(self.admin_c.user, data={
                'origem': 'INTERNA', 'assunto': 'Teste', 'resumo': 'Teste', 'secretaria': foreign_secretary,
            })

    def test_process_visibility_respects_tenant_and_confidential_scope(self):
        process = self._process(
            sigilo=models.ProcessoDigitalMunicipal.Sigilo.SENSIVEL,
            unidade=self.structure[3],
        )
        # A different tenant cannot retrieve the process through a scoped queryset.
        with tenant_context(self.a):
            self.assertFalse(scoped_queryset(self.admin_a.user, models.ProcessoDigitalMunicipal.objects.filter(pk=process.pk)).exists())
        with tenant_context(self.c):
            access = AcessoMunicipal.objects.create(
                membership=self.server_user, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='process.dispatch')
            self.assertFalse(has_municipal_permission(
                self.server_user.user, 'process.sensitive', module='processo_digital', record=process,
            ))
            with self.assertRaises(PermissionDenied):
                services.transition_process(self.server_user.user, process.pk, status=models.ProcessoDigitalMunicipal.Status.DISTRIBUIDO)

    def test_public_ombudsman_keeps_only_tracking_hash_and_is_not_cached(self):
        secret = services.create_tracking_secret()
        with tenant_context(self.c):
            row = services.submit_ombudsman(organization=self.c, data={
                'tipo': models.ManifestacaoOuvidoriaMunicipal.Tipo.RECLAMACAO,
                'assunto': 'Atendimento sintético', 'relato': 'Relato sem dado real.', 'anonima': True,
            }, tracking_secret=secret)
        self.assertEqual(row.nome, '')
        self.assertTrue(services.tracking_secret_matches(secret, row.chave_acompanhamento_digest))
        self.assertNotEqual(secret, row.chave_acompanhamento_digest)
        response = self.client.get(reverse('rh_municipal_public:public_ombudsman_form', args=[self.c.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'csrfmiddlewaretoken')
        response = self.client.post(reverse('rh_municipal_public:public_tracking', args=[self.c.slug, 'ouvidoria']), {
            'protocolo': row.protocolo, 'chave': secret,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')

    def test_public_intake_is_blocked_without_explicit_product_module(self):
        limited = PlanoSaaS.objects.create(slug='fase-e-publico-off', nome='Sem Ouvidoria', erp=self.publico, modulos=[])
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['processo_digital'])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=limited)
        response = self.client.get(reverse('rh_municipal_public:public_ombudsman_form', args=[self.c.slug]))
        self.assertEqual(response.status_code, 404)

    def test_transparency_rejects_personal_data_and_requires_separate_reviewer(self):
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                services.create_transparency_publication(self.admin_c.user, data={
                    'categoria': models.PublicacaoTransparenciaMunicipal.Categoria.OUTRO,
                    'titulo': 'Snapshot', 'conteudo_publico': {'cpf': '00000000000'},
                })
            draft = services.create_transparency_publication(self.admin_c.user, data={
                'categoria': models.PublicacaoTransparenciaMunicipal.Categoria.OUTRO,
                'titulo': 'Snapshot sintético', 'conteudo_publico': {'total': 12},
            })
            services.submit_transparency_for_review(self.admin_c.user, draft.pk)
            with self.assertRaises(PermissionDenied):
                services.publish_transparency(self.admin_c.user, draft.pk)
            reviewer = self._user('phase-e-reviewer', self.c, self.publico, 'ADMIN')
            reviewer_access = AcessoMunicipal.objects.create(
                membership=reviewer, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=reviewer_access, capacidade='transparency.publish')
            published = services.publish_transparency(reviewer.user, draft.pk)
            self.assertEqual(published.status, models.PublicacaoTransparenciaMunicipal.Status.PUBLICADO)

    def test_dashboard_does_not_show_uncontracted_phase_e_links(self):
        limited = PlanoSaaS.objects.create(slug='fase-e-dashboard-limited', nome='Somente processos', erp=self.publico, modulos=[])
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['gestao_publica'])
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['processo_digital'])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=limited)
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Processo Digital')
        self.assertNotContains(response, 'href="/gestao-publica/ouvidoria/"')
        self.assertNotContains(response, 'href="/gestao-publica/esic/"')

    def test_citizen_portal_lists_only_contracted_public_services_for_tenant(self):
        response = self.client.get(reverse('rh_municipal_public:public_citizen_portal', args=[self.c.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.c.display_name)
        self.assertContains(response, 'Transparência pública')
        self.assertContains(response, 'Ouvidoria')
        self.assertContains(response, 'E-SIC')

        limited = PlanoSaaS.objects.create(
            slug='fase-j-portal-limited', nome='Portal público limitado', erp=self.publico, modulos=[],
        )
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['gestao_publica'])
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['esic'])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=limited)
        response = self.client.get(reverse('rh_municipal_public:public_citizen_portal', args=[self.c.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'E-SIC')
        self.assertNotContains(response, 'Ouvidoria')
        self.assertNotContains(response, 'Transparência pública')

    def test_citizen_portal_resolves_only_the_requested_active_organization(self):
        response = self.client.get(reverse('rh_municipal_public:public_citizen_portal', args=[self.a.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.a.display_name)
        self.assertNotContains(response, self.c.display_name)
        self.assertContains(response, 'Nenhum serviço público digital está habilitado')

    def test_tracking_form_is_limited_to_contracted_channels_and_never_cached(self):
        response = self.client.get(reverse('rh_municipal_public:public_tracking_form', args=[self.c.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ouvidoria')
        self.assertContains(response, 'E-SIC')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

        limited = PlanoSaaS.objects.create(
            slug='fase-j-tracking-limited', nome='Apenas E-SIC', erp=self.publico, modulos=[],
        )
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['gestao_publica'])
        PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules['esic'])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=limited)
        response = self.client.get(reverse('rh_municipal_public:public_tracking_form', args=[self.c.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'E-SIC')
        self.assertNotContains(response, 'Ouvidoria')

        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=self.plan)
        no_public_plan = PlanoSaaS.objects.create(
            slug='fase-j-no-public-tracking', nome='Sem canais', erp=self.publico, modulos=[],
        )
        PlanoProdutoModulo.objects.create(plano=no_public_plan, modulo=self.modules['gestao_publica'])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=no_public_plan)
        self.assertEqual(
            self.client.get(reverse('rh_municipal_public:public_tracking_form', args=[self.c.slug])).status_code,
            404,
        )
