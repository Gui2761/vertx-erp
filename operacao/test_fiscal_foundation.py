import hashlib
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from platform_core.context import tenant_context
from platform_core.models import FilialEmpresa, OrganizationMembership, PermissaoMembership
from platform_core.modules import has_capability
from gestao.services import write
from fiscal import foundation as s
from fiscal.motors import resolver
from . import models as m
from .test_block3_commerce import CommerceData

class FiscalData(CommerceData):
    def fiscal_setup(self):
        self.setup_commerce()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.storage_override = override_settings(FISCAL_SIMULATION_ENABLED=True, PRIVATE_STORAGE=None, UPLOAD_STORAGE='local', PRIVATE_MEDIA_ROOT=self.temp.name)
        self.storage_override.enable(); self.addCleanup(self.storage_override.disable)
        self.configs = {}; self.series = {}
        for org, admin in [(self.a, self.admin), (self.b, self.admin_b)]:
            with tenant_context(org):
                branch = FilialEmpresa.objects.create(codigo='SIM', nome='Estabelecimento de teste sem CNPJ')
                s.cadastrar(admin, m.PerfilFiscalEstabelecimento, estabelecimento=branch, municipio_ibge='3550308', uf='SP')
                for kind in ('NFSE', 'NFE', 'NFCE'):
                    cfg=s.cadastrar(admin, m.ConfiguracaoFiscal, estabelecimento=branch, tipo=kind, habilitada=True)
                    serie=s.cadastrar(admin, m.SerieFiscal, estabelecimento=branch, tipo=kind, serie='SIM')
                    self.configs[org.pk, kind]=cfg; self.series[org.pk, kind]=serie
    def doc(self, kind='NFSE', org=None, sale=None):
        org=org or self.a; admin=self.admin if org.pk==self.a.pk else self.admin_b
        customer=self.da['customer'] if org.pk==self.a.pk else self.db['customer']
        return s.preparar_documento(admin,self.configs[org.pk,kind].pk,self.series[org.pk,kind].pk,
            cliente_id=customer.pk if not sale else None,venda_id=sale.pk if sale else None,descricao='Ensaio sem valor fiscal',valor='10.01')
    def request(self, doc, cenario='AUTORIZAR', **kwargs):
        return s.solicitar(self.admin, doc.pk, uuid.uuid4(), cenario=cenario, **kwargs)

class FiscalFoundationTests(FiscalData,TestCase):
    def setUp(self):self.fiscal_setup()
    def test_simulation_authorization_and_private_xml_are_explicitly_non_fiscal(self):
        with tenant_context(self.a):
            doc=self.doc(); req=self.request(doc); result=s.processar(self.admin,req.pk)
            doc.refresh_from_db(); self.assertEqual((result.estado,doc.status),('CONCLUIDA','AUTORIZADA'))
            self.assertTrue(doc.protocolo.startswith('SIMULACAO-')); self.assertTrue(doc.chave.startswith('SIM-'))
            file=m.Documento.objects.get(fiscal=doc); data=file.arquivo.read(); file.arquivo.close()
            self.assertIn(b'semValorFiscal="true"',data); self.assertEqual(file.sha256,hashlib.sha256(data).hexdigest())
            self.assertFalse(file.disponivel_portal); self.assertEqual(doc.eventos_fiscais.last().evento,'AUTORIZADA')
        self.assertContains(self.client.get(f'/fiscal/simulacao/documentos/{doc.pk}/'),'SEM VALOR FISCAL')
    def test_rejection_does_not_create_authorized_xml(self):
        with tenant_context(self.a):
            doc=self.doc(); req=self.request(doc,'REJEITAR'); s.processar(self.admin,req.pk); doc.refresh_from_db()
            self.assertEqual(doc.status,'REJEITADA'); self.assertFalse(m.Documento.objects.filter(fiscal=doc).exists())
    def test_same_uuid_and_new_uuid_same_intent_do_not_duplicate(self):
        with tenant_context(self.a):
            doc=self.doc(); req=self.request(doc)
            self.assertEqual(s.solicitar(self.admin,doc.pk,req.request_id).pk,req.pk)
            self.assertEqual(s.solicitar(self.admin,doc.pk,uuid.uuid4()).pk,req.pk)
            s.processar(self.admin,req.pk); s.processar(self.admin,req.pk)
            self.assertEqual(m.SolicitacaoFiscal.objects.count(),1); self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)
            self.assertEqual(m.Documento.objects.filter(fiscal=doc).count(),1)
    def test_uuid_with_changed_payload_is_rejected(self):
        with tenant_context(self.a):
            doc=self.doc(); req=self.request(doc)
            with self.assertRaises(ValidationError):s.solicitar(self.admin,doc.pk,req.request_id,cenario='REJEITAR')
    def test_timeout_before_response_retries_same_number(self):
        with tenant_context(self.a):
            doc=self.doc(); req=self.request(doc,'TIMEOUT_ANTES'); s.processar(self.admin,req.pk); req.refresh_from_db(); doc.refresh_from_db()
            self.assertEqual(req.estado,'RESULTADO_DESCONHECIDO'); self.assertEqual(doc.status,'RASCUNHO')
            number=doc.numero; s.processar(self.admin,req.pk); doc.refresh_from_db()
            self.assertEqual(doc.status,'AUTORIZADA'); self.assertEqual(doc.numero,number)
            self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)
    def test_lost_response_reconciles_durable_simulated_receipt(self):
        with tenant_context(self.a):
            doc=self.doc(); req=self.request(doc,'TIMEOUT_APOS'); s.processar(self.admin,req.pk); req.refresh_from_db(); doc.refresh_from_db()
            self.assertEqual(req.estado,'RESULTADO_DESCONHECIDO'); self.assertTrue(req.resultado_simulado)
            self.assertEqual(doc.status,'RASCUNHO')
            with patch('fiscal.motors.base.MotorSimulado.emitir',side_effect=AssertionError('Must consult, not send again')):
                s.processar(self.admin,req.pk)
            doc.refresh_from_db(); self.assertEqual(doc.status,'AUTORIZADA')
            self.assertEqual(m.SolicitacaoFiscal.objects.count(),1)
    def test_simulated_cancel_preserves_original_xml_and_history(self):
        with tenant_context(self.a):
            doc=self.doc(); s.processar(self.admin,self.request(doc).pk)
            doc.refresh_from_db(); identity=(doc.chave,doc.numero,doc.autorizado_em)
            req=self.request(doc,operacao='CANCELAR',motivo='Ensaio de cancelamento'); s.processar(self.admin,req.pk); doc.refresh_from_db()
            self.assertEqual(doc.status,'CANCELADA'); self.assertEqual(m.Documento.objects.filter(fiscal=doc).count(),2)
            self.assertEqual((doc.chave,doc.numero,doc.autorizado_em),identity)
            self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)
            self.assertEqual(doc.eventos_fiscais.last().evento,'CANCELADA')
    def test_cancel_requires_authorized_document_and_reason(self):
        with tenant_context(self.a):
            doc=self.doc()
            with self.assertRaises(ValidationError):self.request(doc,operacao='CANCELAR',motivo='')
    def test_wrong_tenant_configuration_establishment_and_series_are_denied(self):
        with tenant_context(self.a):
            with self.assertRaises(ObjectDoesNotExist):s.preparar_documento(self.admin,self.configs[self.b.pk,'NFSE'].pk,self.series[self.a.pk,'NFSE'].pk,cliente_id=self.da['customer'].pk,valor=10)
            with self.assertRaises(ObjectDoesNotExist):s.preparar_documento(self.admin,self.configs[self.a.pk,'NFSE'].pk,self.series[self.b.pk,'NFSE'].pk,cliente_id=self.da['customer'].pk,valor=10)
            with self.assertRaises(ValidationError):s.cadastrar(self.admin,m.ConfiguracaoFiscal,estabelecimento=self.configs[self.b.pk,'NFSE'].estabelecimento,tipo='NFSE')
    def test_wrong_organization_credential_reference_cannot_be_linked(self):
        with tenant_context(self.b):cred=s.cadastrar(self.admin_b,m.CredencialFiscal,referencia='simulacao://'+str(uuid.uuid4()),mecanismo='SIMULACAO')
        with tenant_context(self.a):
            with self.assertRaises(ValidationError):s.cadastrar(self.admin,m.VinculoCredencialFiscal,configuracao=self.configs[self.a.pk,'NFSE'],credencial=cred)
    def test_reference_requires_explicit_same_tenant_link_and_validity(self):
        with tenant_context(self.a):
            cred=s.cadastrar(self.admin,m.CredencialFiscal,referencia='simulacao://'+str(uuid.uuid4()),mecanismo='SIMULACAO')
            kwargs=dict(cliente_id=self.da['customer'].pk,valor=10,credencial_id=cred.pk)
            with self.assertRaises(ValidationError):s.preparar_documento(self.admin,self.configs[self.a.pk,'NFSE'].pk,self.series[self.a.pk,'NFSE'].pk,**kwargs)
            s.cadastrar(self.admin,m.VinculoCredencialFiscal,configuracao=self.configs[self.a.pk,'NFSE'],credencial=cred)
            doc=s.preparar_documento(self.admin,self.configs[self.a.pk,'NFSE'].pk,self.series[self.a.pk,'NFSE'].pk,**kwargs)
            s.revogar_credencial(self.admin,cred.pk)
            with self.assertRaises(ValidationError):self.request(doc)
    def test_no_real_credential_material_can_be_registered(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError):s.cadastrar(self.admin,m.CredencialFiscal,referencia='-----BEGIN PRIVATE KEY-----',mecanismo='REFERENCIA')
            with self.assertRaises(ValidationError):s.cadastrar(self.admin,m.CredencialFiscal,referencia='simulacao://'+str(uuid.uuid4()),mecanismo='SIMULACAO',ambiente='PRODUCAO')
    def test_organization_id_tampering_is_rejected_by_backend(self):
        response=self.client.post('/fiscal/simulacao/cadastros/configuracao/',{'estabelecimento':self.configs[self.a.pk,'NFSE'].estabelecimento_id,'tipo':'NFSE','versao':2,'organization_id':self.b.pk})
        self.assertContains(response,'Campos não permitidos')
        with tenant_context(self.a):self.assertFalse(m.ConfiguracaoFiscal.objects.filter(versao=2).exists())
    def test_other_tenant_document_request_xml_are_not_accessible(self):
        with tenant_context(self.b):
            doc=self.doc(org=self.b); req=s.solicitar(self.admin_b,doc.pk,uuid.uuid4());s.processar(self.admin_b,req.pk)
            file=m.Documento.objects.get(fiscal=doc)
        for url in [f'/fiscal/simulacao/documentos/{doc.pk}/',f'/documentos/{file.pk}/arquivo/']:
            self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.post(f'/fiscal/simulacao/solicitacoes/{req.pk}/reconciliar/').status_code,404)
    def test_saas_and_customer_contexts_have_independent_documents_and_numbers(self):
        for org,admin in [(self.a,self.admin),(self.b,self.admin_b)]:
            with tenant_context(org):
                doc=self.doc(org=org);req=s.solicitar(admin,doc.pk,uuid.uuid4());s.processar(admin,req.pk);doc.refresh_from_db()
                self.assertEqual(doc.numero,'1');self.assertEqual(m.DocumentoFiscal.objects.count(),1)
                self.assertEqual(doc.snapshot_fiscal['emitente']['organization'],str(org.public_id))
        self.assertFalse(m.DocumentoFiscal.objects.exists()) # no tenant context
    def test_cash_permission_never_grants_fiscal_admin(self):
        with tenant_context(self.a):
            self.assertTrue(has_capability(self.operator,'operar_pdv'))
            for capability in ['fiscal_consultar','fiscal_emitir','fiscal_configurar','fiscal_gerenciar_credenciais']:
                self.assertFalse(has_capability(self.operator,capability))
        self.client.force_login(self.operator);self.assertEqual(self.client.get('/fiscal/simulacao/').status_code,403)
    def test_technician_and_seller_cannot_gain_fiscal_through_override(self):
        for role in ('TECNICO','VENDEDOR'):
            user=self.user('fiscal-denied-'+role,self.a,role)
            with tenant_context(self.a):
                member=OrganizationMembership.objects.get(user=user,organization=self.a)
                PermissaoMembership.objects.create(membership=member,capacidade='fiscal_configurar',permitido=True)
                self.assertFalse(has_capability(user,'fiscal_configurar'))
            self.client.force_login(user);self.assertEqual(self.client.get('/fiscal/simulacao/').status_code,403)
    def test_explicit_fiscal_permission_denial_blocks_service(self):
        with tenant_context(self.a):
            doc=self.doc();member=OrganizationMembership.objects.get(user=self.admin,organization=self.a)
            PermissaoMembership.objects.create(membership=member,capacidade='fiscal_emitir',permitido=False)
            with self.assertRaises(PermissionDenied):self.request(doc)
    def test_simulation_disabled_and_official_environments_are_blocked(self):
        with tenant_context(self.a):
            doc=self.doc()
            with override_settings(FISCAL_SIMULATION_ENABLED=False):
                with self.assertRaises(ValidationError):self.request(doc)
            for env in ('HOMOLOGACAO','PRODUCAO'):
                with self.assertRaises(ValidationError):s.cadastrar(self.admin,m.SerieFiscal,estabelecimento=doc.estabelecimento,tipo='NFSE',serie='SIM',ambiente=env)
    def test_external_storage_and_vault_are_not_used(self):
        with tenant_context(self.a), override_settings(PRIVATE_STORAGE={'BACKEND':'unused.external.storage'}):
            with self.assertRaises(ValidationError):self.doc()
    def test_series_environment_type_and_establishment_must_match(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError):s.preparar_documento(self.admin,self.configs[self.a.pk,'NFSE'].pk,self.series[self.a.pk,'NFCE'].pk,cliente_id=self.da['customer'].pk,valor=10)
            other=FilialEmpresa.objects.create(codigo='OTHER',nome='Outra filial sintética')
            serie=s.cadastrar(self.admin,m.SerieFiscal,estabelecimento=other,tipo='NFSE',serie='SIM')
            with self.assertRaises(ValidationError):s.preparar_documento(self.admin,self.configs[self.a.pk,'NFSE'].pk,serie.pk,cliente_id=self.da['customer'].pk,valor=10)
    def test_rules_are_versioned_and_snapshots_do_not_change(self):
        with tenant_context(self.a):
            cfg=self.configs[self.a.pk,'NFSE']
            r1=s.cadastrar(self.admin,m.RegraTributariaFiscal,configuracao=cfg,inicio=timezone.localdate(),parametros={'codigo_servico':'TESTE'})
            doc=s.preparar_documento(self.admin,cfg.pk,self.series[self.a.pk,'NFSE'].pk,cliente_id=self.da['customer'].pk,valor=10,regra_id=r1.pk)
            r1.parametros={'codigo_servico':'OUTRO'}
            with self.assertRaises(ValidationError):r1.save()
            s.cadastrar(self.admin,m.RegraTributariaFiscal,configuracao=cfg,versao=2,inicio=timezone.localdate(),parametros={'codigo_servico':'TESTE2'})
            doc.refresh_from_db();self.assertEqual(doc.snapshot_fiscal['regra']['codigo_servico'],'TESTE')
            with self.assertRaises(ValidationError):s.cadastrar(self.admin,m.RegraTributariaFiscal,configuracao=cfg,versao=3,inicio=timezone.localdate(),parametros={'token':'not-a-real-token'})
    def test_no_silent_document_or_number_edits(self):
        with tenant_context(self.a):
            doc=self.doc();doc.valor=Decimal('999')
            with self.assertRaises(ValidationError):doc.save()
            serie=self.series[self.a.pk,'NFSE'];serie.proximo_numero=42
            with self.assertRaises(ValidationError):serie.save()
            with self.assertRaises(ValidationError):write(doc)
            with self.assertRaises(ValidationError):m.SerieFiscal.objects.all().delete()
    def test_legacy_document_is_preserved_not_implicitly_enabled(self):
        with tenant_context(self.a):
            legacy=m.DocumentoFiscal.objects.create(tipo='NFSE',cliente=self.da['customer'],descricao='Legado',valor=10,criado_por=self.admin)
            original=(legacy.pk,legacy.numero,legacy.status,legacy.cliente_id,legacy.ambiente)
            with self.assertRaises(ValidationError):self.request(legacy)
            legacy.refresh_from_db();self.assertEqual(original,(legacy.pk,legacy.numero,legacy.status,legacy.cliente_id,legacy.ambiente))
    def test_each_motor_rejects_details_for_other_type(self):
        with tenant_context(self.a):
            doc=self.doc()
            for kind in ('NFE','NFCE'):
                with self.assertRaises(ValidationError):resolver(kind).validar(doc)
            with self.assertRaises(ValidationError):write(m.DetalhesNFe(documento=doc))
    def test_pdv_confirmed_sale_to_fiscal_does_not_replay_commercial_effects(self):
        with tenant_context(self.a):
            self.incoming(3);sale,_=self.sale();self.paid(sale);sale.refresh_from_db()
            original=(sale.status,sale.total,sale.conta_id,self.session.pk)
            qty=self.part.__class__.objects.get(pk=self.part.pk).quantidade_atual
            payments=sale.pagamentos_pdv.count();doc=self.doc('NFCE',sale=sale)
            self.assertEqual(self.doc('NFCE',sale=sale).pk,doc.pk)
            req=self.request(doc);s.processar(self.admin,req.pk);s.processar(self.admin,req.pk)
            sale.refresh_from_db();self.assertEqual(original,(sale.status,sale.total,sale.conta_id,self.session.pk))
            self.assertEqual(self.part.__class__.objects.get(pk=self.part.pk).quantidade_atual,qty)
            self.assertEqual(sale.pagamentos_pdv.count(),payments);self.session.refresh_from_db();self.assertIsNone(self.session.fechado_em)
            self.assertEqual(doc.detalhesnfce.modo_emissao,'NORMAL')
    def test_draft_sale_cannot_enter_fiscal_pipeline(self):
        with tenant_context(self.a):
            self.incoming(3);sale,_=self.sale()
            with self.assertRaises(ValidationError):self.doc('NFCE',sale=sale)
    def test_nfe_merchandise_motor_authorizes_only_its_own_detail(self):
        with tenant_context(self.a):
            self.incoming(3);sale,_=self.sale();self.paid(sale);sale.refresh_from_db()
            original=(sale.status,sale.total,sale.pagamentos_pdv.count(),self.part.__class__.objects.get(pk=self.part.pk).quantidade_atual)
            doc=self.doc('NFE',sale=sale);s.processar(self.admin,self.request(doc).pk);doc.refresh_from_db()
            self.assertEqual((doc.modelo,doc.status),('55','AUTORIZADA'))
            self.assertTrue(doc.detalhesnfe.itens_snapshot);self.assertFalse(m.DetalhesNFCe.objects.filter(documento=doc).exists())
            sale.refresh_from_db()
            self.assertEqual(original,(sale.status,sale.total,sale.pagamentos_pdv.count(),self.part.__class__.objects.get(pk=self.part.pk).quantidade_atual))
    def test_invalid_engine_identity_is_not_authorized(self):
        with tenant_context(self.a):
            doc=self.doc();req=self.request(doc)
            with patch('fiscal.motors.base.MotorSimulado.consultar',return_value={'status':'AUTORIZADA','organization':str(self.b.public_id)}):
                result=s.processar(self.admin,req.pk)
            self.assertEqual(result.estado,'FALHA_VALIDACAO');doc.refresh_from_db();self.assertEqual(doc.status,'RASCUNHO')
    def test_expired_lease_is_recoverable_without_new_request(self):
        with tenant_context(self.a):
            doc=self.doc();req=self.request(doc);req.estado='ENVIANDO';req.lease_token=uuid.uuid4();req.lease_ate=timezone.now()-timedelta(seconds=1);write(req)
            self.assertEqual(s.processar(self.admin,req.pk).estado,'CONCLUIDA')
    def test_fiscal_forms_and_csrf_flow_show_simulation_without_secret_inputs(self):
        self.assertContains(self.client.get('/fiscal/simulacao/'),'SEM VALOR FISCAL')
        for kind in ('perfil','configuracao','referencia','vinculo','serie','regra'):
            response=self.client.get(f'/fiscal/simulacao/cadastros/{kind}/')
            self.assertEqual(response.status_code,200)
            for forbidden in ('name="organization"','name="senha"','name="token"','name="certificado"','name="CSC"'):
                self.assertNotContains(response,forbidden)
        self.assertEqual(self.client.get('/fiscal/simulacao/novo/').status_code,200)
    def test_posting_secret_or_untrusted_environment_fields_is_rejected(self):
        for field in ('senha','certificado','csc','token','ambiente'):
            response=self.client.post('/fiscal/simulacao/cadastros/referencia/',{'versao':'1',field:'forbidden-value'})
            self.assertContains(response,'Campos não permitidos');self.assertNotContains(response,'forbidden-value')
    def test_cadastro_foreign_key_choices_are_recomputed_for_current_tenant(self):
        from fiscal.forms import CADASTROS
        branch_a=self.configs[self.a.pk,'NFSE'].estabelecimento
        branch_b=self.configs[self.b.pk,'NFSE'].estabelecimento
        with tenant_context(self.a):
            form=CADASTROS['configuracao'][1]()
            self.assertTrue(form.fields['estabelecimento'].queryset.filter(pk=branch_a.pk).exists())
            self.assertFalse(form.fields['estabelecimento'].queryset.filter(pk=branch_b.pk).exists())
        response=self.client.post('/fiscal/simulacao/cadastros/configuracao/',{'estabelecimento':branch_a.pk,'tipo':'NFSE','versao':2,'habilitada':'on'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):self.assertTrue(m.ConfiguracaoFiscal.objects.filter(versao=2).exists())
    def test_reference_ui_generates_only_opaque_simulation_handle(self):
        response=self.client.post('/fiscal/simulacao/cadastros/referencia/',{'versao':1})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            ref=m.CredencialFiscal.objects.get()
            self.assertEqual(ref.mecanismo,'SIMULACAO');self.assertTrue(ref.referencia.startswith('simulacao://'))
    def test_xml_download_is_no_store_and_requires_authorization(self):
        with tenant_context(self.a):
            doc=self.doc();s.processar(self.admin,self.request(doc).pk);file=m.Documento.objects.get(fiscal=doc)
        from django.urls import reverse
        url=reverse('operacao:documento_arquivo',args=[file.pk]);response=self.client.get(url)
        self.assertEqual(response.status_code,200);self.assertIn('no-store',response['Cache-Control'])
        self.assertIn(b'SimulacaoFiscal', b''.join(response.streaming_content))
        self.client.force_login(self.operator);self.assertIn(self.client.get(url).status_code,(403,404))

@skipUnless(connection.vendor=='postgresql','PostgreSQL row locking required')
class FiscalConcurrencyTests(FiscalData,TransactionTestCase):
    def setUp(self):self.fiscal_setup()
    def worker(self, pk, request_id):
        close_old_connections()
        try:
            with tenant_context(self.a):return s.solicitar(self.admin,pk,request_id).pk
        finally:close_old_connections()
    def test_concurrent_number_reservations_are_distinct(self):
        with tenant_context(self.a):docs=[self.doc(),self.doc()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda d:self.worker(d.pk,uuid.uuid4()),docs))
        with tenant_context(self.a):
            self.assertEqual(len(set(results)),2)
            self.assertEqual(set(m.ReservaNumeracaoFiscal.objects.values_list('numero',flat=True)),{1,2})
    def test_concurrent_same_document_creates_one_request_and_reservation(self):
        with tenant_context(self.a):doc=self.doc()
        rid=uuid.uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.worker(doc.pk,rid),range(2)))
        self.assertEqual(results[0],results[1])
        with tenant_context(self.a):self.assertEqual(m.ReservaNumeracaoFiscal.objects.count(),1)

    def test_concurrent_processing_applies_one_authorization_and_xml(self):
        with tenant_context(self.a):doc=self.doc();req=self.request(doc)
        def run(_):
            close_old_connections()
            try:
                with tenant_context(self.a):return s.processar(self.admin,req.pk).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(results[0],results[1])
        with tenant_context(self.a):
            self.assertEqual(m.Documento.objects.filter(fiscal=doc).count(),1)
            self.assertEqual(m.EventoFiscal.objects.filter(documento=doc,evento='AUTORIZADA').count(),1)

class FiscalMigrationPreservationTests(CommerceData,TransactionTestCase):
    def test_0019_preserves_every_old_column_and_legacy_fiscal_document(self):
        from django.db.migrations.executor import MigrationExecutor
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        self.assertEqual(connection.settings_dict['HOST'],'127.0.0.1')
        executor=MigrationExecutor(connection)
        self.setup_commerce()
        with tenant_context(self.a):
            olddoc=m.DocumentoFiscal.objects.create(organization_id=self.a.pk,
                cliente_id=self.da['customer'].pk,criado_por_id=self.admin.pk,tipo='NFSE',descricao='Documento anterior preservado',valor='10.01',serie='OLD',numero='8')
        executor.migrate([('operacao','0018_pdv_offline_sync')])
        try:
            historic=executor.loader.project_state([('operacao','0018_pdv_offline_sync')]).apps
            cols={}
            with connection.cursor() as cursor:
                for table in connection.introspection.table_names():
                    if table!='django_migrations':cols[table]=[d.name for d in connection.introspection.get_table_description(cursor,table)]
            def snapshot():
                data={}
                with connection.cursor() as cursor:
                    for table,columns in sorted(cols.items()):
                        cursor.execute('SELECT '+','.join(connection.ops.quote_name(c) for c in columns)+' FROM '+connection.ops.quote_name(table))
                        data[table]=sorted(repr(row) for row in cursor.fetchall())
                return data
            before=snapshot();MigrationExecutor(connection).migrate([('operacao','0019_fiscal_foundation')])
            self.assertEqual(snapshot(),before)
            with tenant_context(self.a):
                doc=m.DocumentoFiscal.objects.get(pk=olddoc.pk)
                self.assertEqual((doc.numero,doc.serie,doc.status,doc.ambiente),('8','OLD','RASCUNHO','SANDBOX'))
                self.assertIsNone(doc.configuracao_fiscal_id);self.assertEqual(doc.snapshot_fiscal,{})
        finally:
            executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
