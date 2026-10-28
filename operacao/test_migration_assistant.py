"""Synthetic tenant imports only; no production, accounts or cash mutations."""
import csv
import io
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection,close_old_connections
from django.test import TestCase,TransactionTestCase,SimpleTestCase,override_settings
from django.urls import reverse
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership,PermissaoMembership,ModuloOrganizacao,PlatformAudit
from gestao.tests import Dados
from gestao import models as g,services as gs
from clientes.models import Cliente
from equipamentos.models import Equipamento
from integracoes import readers,services as s
from integracoes.catalog import CATALOG,suggest
from integracoes.views import excel_safe
from . import models as m

def csv_file(headers,rows,name='dados.csv'):
    out=io.StringIO();writer=csv.writer(out,delimiter=';');writer.writerow(headers);writer.writerows(rows)
    return SimpleUploadedFile(name,out.getvalue().encode('utf-8-sig'),content_type='text/csv')

class ImportData(Dados):
    def setup_import(self):
        self.prepare_data();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        override=override_settings(PRIVATE_STORAGE=None,PRIVATE_MEDIA_ROOT=self.tmp.name,UPLOAD_STORAGE='local');override.enable();self.addCleanup(override.disable)
        with tenant_context(self.a):self.depot=m.Deposito.objects.create(nome='Importação')
    def uploaded(self,kind='produtos',headers=None,rows=None,actor=None):
        obj,new=s.upload(actor or self.admin,kind,csv_file(headers or ['COD_PROD','Descrição'],rows or [['IMPORT-01','Produto importado']]))
        return obj
    def ready(self,kind='produtos',headers=None,rows=None,actor=None):
        actor=actor or self.admin;obj=self.uploaded(kind,headers,rows,actor);s.map_columns(actor,obj.public_id,obj.mapeamento);return obj
    def finish(self,obj,partial=False,actor=None):
        actor=actor or self.admin;s.start(actor,obj.public_id,partial)
        while obj.status!='CONCLUIDO':obj=s.execute_chunk(actor,obj.public_id)
        return obj

class MigrationAssistantTests(ImportData,TestCase):
    def setUp(self):self.setup_import()
    def test_csv_preview_does_not_create_or_modify_domain_records(self):
        with tenant_context(self.a):
            before=list(g.Peca.objects.values());obj=self.ready();self.assertEqual(list(g.Peca.objects.values()),before)
            self.assertEqual(s.summary(obj)['pronta'],1);self.assertTrue(obj.arquivo.name.startswith(f'organizations/{self.a.public_id}/integracoes/'))
            with self.assertRaises(ValueError):obj.arquivo.url
    def test_valid_xlsx_with_text_codes_and_prices(self):
        with tenant_context(self.a):
            file=Path(settings.BASE_DIR)/'tests/fixtures/migracao/produtos.xlsx';obj,_=s.upload(self.admin,'produtos',SimpleUploadedFile('produtos.xlsx',file.read_bytes()))
            s.map_columns(self.admin,obj.public_id,obj.mapeamento);self.finish(obj);part=g.Peca.objects.get(sku='00001')
            self.assertEqual((part.gtin,part.preco_venda),('0001234567890',Decimal('15.50')))
    def test_aliases_unknown_column_explicit_ignore(self):
        with tenant_context(self.a):
            obj=self.ready(headers=['COD_PROD','Descrição','Coluna antiga'],rows=[['NEW-X','Produto','Não importar']])
            self.assertEqual(obj.mapeamento,{'0':'sku','1':'descricao','2':''});self.finish(obj)
            self.assertEqual(g.Peca.objects.get(sku='NEW-X').descricao,'Produto')
    def test_missing_column_prevents_mapping_and_import(self):
        with tenant_context(self.a):
            obj=self.uploaded(headers=['Descrição'],rows=[['Nome']])
            with self.assertRaisesMessage(ValidationError,'Código'):s.map_columns(self.admin,obj.public_id,obj.mapeamento)
            with self.assertRaises(ValidationError):s.start(self.admin,obj.public_id)
            self.assertEqual(g.Peca.objects.count(),1)
    def test_duplicate_mapping_target_and_spoof_field_rejected(self):
        with tenant_context(self.a):
            obj=self.uploaded()
            for mapping in [{'0':'sku','1':'sku'},{'0':'organization_id','1':'descricao'},{'99':'sku','1':'descricao'}]:
                with self.assertRaises(ValidationError):s.map_columns(self.admin,obj.public_id,mapping)
    def test_required_data_and_decimal_precision_block_bad_rows(self):
        with tenant_context(self.a):
            obj=self.ready(headers=['Código','Descrição','Preço'],rows=[['','Nome','1.00'],['MISS-D','', '2'],['BAD-C','Nome','1.001']])
            self.assertEqual(s.summary(obj)['corrigir'],3)
            with self.assertRaises(ValidationError):s.start(self.admin,obj.public_id)
    def test_row_correction_uses_original_fields_and_does_not_import_early(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[['','Nome preservado']]);row=obj.linhas.get();self.assertEqual(row.dados['descricao'],'Nome preservado')
            s.edit_row(self.admin,obj.public_id,2,{'sku':'CORRIGIDO'},'CRIAR');self.assertFalse(g.Peca.objects.filter(sku='CORRIGIDO').exists())
            self.finish(obj);self.assertEqual(g.Peca.objects.get(sku='CORRIGIDO').descricao,'Nome preservado')
    def test_decimal_brazilian_money_and_quantity_exact(self):
        with tenant_context(self.a):
            obj=self.ready(headers=['Código','Nome','Preço','Estoque mínimo'],rows=[['BR-1','Exato','1.234,56','1,125']]);self.finish(obj)
            part=g.Peca.objects.get(sku='BR-1');self.assertEqual((part.preco_venda,part.estoque_minimo),(Decimal('1234.56'),Decimal('1.125')))
    def test_duplicates_in_same_file_require_decision_and_ignore_releases_other(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[['REPETIDO','A'],['REPETIDO','B']]);self.assertEqual(s.summary(obj)['duplicada'],2)
            s.edit_row(self.admin,obj.public_id,3,{},'IGNORAR');self.assertEqual(s.summary(obj)['pronta'],1)
            self.finish(obj);self.assertEqual((g.Peca.objects.filter(sku='REPETIDO').count(),s.summary(obj)['ignorada']),(1,1))
    def test_existing_product_update_is_explicit_preserves_empty_and_balance(self):
        with tenant_context(self.a):
            old=self.da['part'];old.marca='Manter marca';old.save();obj=self.ready(headers=['Código','Nome','Marca'],rows=[[old.sku,'Descrição atualizada','']])
            self.assertEqual(s.summary(obj)['duplicada'],1);old.refresh_from_db();self.assertNotEqual(old.descricao,'Descrição atualizada')
            s.edit_row(self.admin,obj.public_id,2,{},'ATUALIZAR');self.finish(obj);old.refresh_from_db()
            self.assertEqual((old.descricao,old.marca,old.quantidade_atual),('Descrição atualizada','Manter marca',0))
    def test_product_external_code_and_ean_detect_duplicates(self):
        with tenant_context(self.a):
            part=self.da['part'];part.gtin='0001234567890';part.save();g.CodigoProduto.objects.create(peca=part,codigo='EXTERNO-01')
            for header,value in [('EAN','0001234567890'),('Código externo','EXTERNO-01')]:
                obj=self.ready(headers=['Código','Nome',header],rows=[['DIFFERENT-'+header,'Nome',value]])
                self.assertEqual(obj.linhas.get().estado,'DUPLICADA')
    def test_ambiguous_identifiers_do_not_overwrite_any_record(self):
        with tenant_context(self.a):
            second=g.Peca.objects.create(sku='OUTRO',descricao='Outro',gtin='0001234567890')
            obj=self.ready(headers=['Código','Nome','EAN'],rows=[[self.da['part'].sku,'Novo','0001234567890']])
            self.assertEqual(obj.linhas.get().estado,'CORRIGIR');self.assertIn('cadastros diferentes',obj.linhas.get().problemas[0])
    def test_partial_import_requires_explicit_confirmation(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[['OK-01','Bom'],['','Inválido']])
            with self.assertRaises(ValidationError):s.start(self.admin,obj.public_id)
            self.finish(obj,True);self.assertEqual((s.summary(obj)['criada'],s.summary(obj)['ignorada']),(1,1))
    def test_same_file_reupload_returns_same_batch_and_no_duplicates(self):
        with tenant_context(self.a):
            obj=self.ready();self.finish(obj);other,new=s.upload(self.admin,'produtos',csv_file(['COD_PROD','Descrição'],[['IMPORT-01','Produto importado']],'outro_nome.csv'))
            self.assertFalse(new);self.assertEqual(other.pk,obj.pk);s.execute_chunk(self.admin,obj.public_id)
            self.assertEqual(g.Peca.objects.filter(sku='IMPORT-01').count(),1)
    def test_resume_chunks_after_close_is_idempotent(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[[f'ITEM-{i}',f'Produto {i}'] for i in range(3)]);s.start(self.admin,obj.public_id);s.execute_chunk(self.admin,obj.public_id,1)
            self.assertEqual(s.summary(obj)['criada'],1)
            s.execute_chunk(self.admin,obj.public_id);s.execute_chunk(self.admin,obj.public_id)
            obj.refresh_from_db();self.assertEqual((obj.status,s.summary(obj)['criada']),('CONCLUIDO',3))
    def test_error_after_write_rolls_back_row_and_keeps_other_rows(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[['ROLLBACK-01','Falhar'],['OK-02','Continuar']]);s.start(self.admin,obj.public_id)
            real=s.persist
            def failing(actor,kind,data,old):
                result=real(actor,kind,data,old)
                if data['sku']=='ROLLBACK-01':raise RuntimeError('synthetic-secret-never-report')
                return result
            with patch('integracoes.services.persist',side_effect=failing):s.execute_chunk(self.admin,obj.public_id)
            self.assertFalse(g.Peca.objects.filter(sku='ROLLBACK-01').exists());self.assertTrue(g.Peca.objects.filter(sku='OK-02').exists())
            row=obj.linhas.get(numero=2);self.assertEqual(row.estado,'REJEITADA');self.assertNotIn('synthetic-secret',str(row.problemas))
    def test_target_changed_after_preview_requires_new_conference(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[[self.da['part'].sku,'Novo']]);s.edit_row(self.admin,obj.public_id,2,{},'ATUALIZAR')
            part=self.da['part'];part.preco_venda=99;part.save()
            with self.assertRaisesMessage(ValidationError,'mudou'):s.start(self.admin,obj.public_id)
            part.refresh_from_db();self.assertEqual(part.preco_venda,99)
    def test_target_changed_after_confirmation_rejects_row(self):
        with tenant_context(self.a):
            obj=self.ready(rows=[[self.da['part'].sku,'Novo']]);s.edit_row(self.admin,obj.public_id,2,{},'ATUALIZAR');s.start(self.admin,obj.public_id)
            part=self.da['part'];part.marca='Alteração posterior';part.save();s.execute_chunk(self.admin,obj.public_id)
            self.assertEqual(obj.linhas.get().estado,'REJEITADA');part.refresh_from_db();self.assertNotEqual(part.descricao,'Novo')
    def test_new_collision_after_confirmation_is_rejected(self):
        with tenant_context(self.a):
            obj=self.ready();s.start(self.admin,obj.public_id);g.Peca.objects.create(sku='IMPORT-01',descricao='Criado por outro fluxo');s.execute_chunk(self.admin,obj.public_id)
            self.assertEqual(obj.linhas.get().estado,'REJEITADA');self.assertEqual(g.Peca.objects.filter(sku='IMPORT-01').count(),1)
    def test_clients_document_normalization_and_email_conflicts(self):
        with tenant_context(self.a):
            obj=self.ready('clientes',['Nome','CPF','E-mail'],[['Cliente importado','529.982.247-25','teste@example.invalid']]);self.finish(obj)
            client=Cliente.objects.get(cpf_cnpj='52998224725');self.assertEqual(client.tipo_pessoa,'PF')
            other=self.ready('clientes',['Nome','CNPJ','E-mail'],[['Outro','11222333000181','teste@example.invalid']]);self.assertEqual(other.linhas.get().estado,'DUPLICADA')
    def test_suppliers_cnpj_conflict_without_silent_update(self):
        with tenant_context(self.a):
            obj=self.ready('fornecedores',['Nome','CNPJ'],[['Fornecedor importado','11.222.333/0001-81']]);self.finish(obj)
            other=self.ready('fornecedores',['Nome','CNPJ'],[['Outro nome','11222333000181']]);self.assertEqual(other.linhas.get().estado,'DUPLICADA');self.assertEqual(g.Fornecedor.objects.get(documento='11222333000181').nome,'Fornecedor importado')
    def stock_batch(self,identifier='ENTRADA-01'):
        return self.ready('estoque',['ID_ENTRADA','SKU','Depósito','Quantidade','Custo','Lote','Validade'],[[identifier,self.da['part'].sku,self.depot.nome,'2,125','3,47','LOTE-MIG','01/01/2030']])
    def test_stock_entries_audit_exact_lot_depot_cost_and_preserve_existing(self):
        with tenant_context(self.a):
            part=self.da['part'];gs.movimentar(self.admin,part.pk,'ENTRADA',1,destino_id=self.depot.pk,lote_data={'numero':'ANTERIOR','custo_unitario':Decimal('1')})
            obj=self.stock_batch();self.finish(obj);part.refresh_from_db();lot=m.LoteEstoque.objects.get(numero='LOTE-MIG')
            self.assertEqual((part.quantidade_atual,lot.quantidade,lot.custo_unitario),(Decimal('3.125'),Decimal('2.125'),Decimal('3.47')))
            self.assertEqual(m.LoteEstoque.objects.get(numero='ANTERIOR').quantidade,1);self.assertTrue(PlatformAudit.objects.filter(action='LOTE_MOVIMENTADO').exists())
    def test_same_stock_entry_other_file_does_not_add_again(self):
        with tenant_context(self.a):
            obj=self.stock_batch();self.finish(obj)
            other=self.ready('estoque',['Identificador da entrada','SKU','Depósito','Quantidade','Custo','Lote'],[['ENTRADA-01',self.da['part'].sku,self.depot.nome,3,9,'DIFERENTE']])
            self.assertEqual(other.linhas.get().estado,'DUPLICADA')
            with self.assertRaises(ValidationError):s.edit_row(self.admin,other.public_id,2,{},'ATUALIZAR')
            self.da['part'].refresh_from_db();self.assertEqual(self.da['part'].quantidade_atual,Decimal('2.125'))
    def test_stock_missing_validity_for_controlled_product_blocked(self):
        with tenant_context(self.a):
            part=self.da['part'];part.controla_validade=True;part.save()
            obj=self.ready('estoque',['ID_ENTRADA','SKU','Depósito','Quantidade','Custo','Lote'],[['E1',part.sku,self.depot.nome,1,1,'L']])
            self.assertEqual(obj.linhas.get().estado,'CORRIGIR');self.assertIn('validade',obj.linhas.get().problemas[0])
    def test_equipment_existing_client_category_and_no_os_created(self):
        with tenant_context(self.a):
            client=Cliente.objects.create(nome_razao_social='Cliente importação',cpf_cnpj='52998224725')
            obj=self.ready('equipamentos',['Código','Nome','CPF / CNPJ do cliente','Categoria'],[['PAT-01','Equipamento importado',client.cpf_cnpj,self.da['equipment'].categoria.nome]])
            self.finish(obj);equipment=Equipamento.objects.get(codigo_interno='PAT-01');self.assertEqual(equipment.cliente_id,client.pk)
            self.assertEqual(self.da['order'].__class__.objects.count(),1)
    def test_employee_uses_existing_account_and_preserves_memberships_journey(self):
        with tenant_context(self.a):
            user=self.users['TECNICO'];before=list(user.memberships.values());password=user.password
            obj=self.ready('funcionarios',['Usuário','Matrícula','Nome'],[[user.username,'MIG-01','Pessoa importada']]);self.finish(obj)
            employee=m.Funcionario.objects.get(matricula='MIG-01');self.assertEqual(employee.usuario_id,user.pk)
            self.assertEqual(employee.tecnico_id,self.da['tech'].pk);self.assertEqual(list(user.memberships.values()),before);user.refresh_from_db();self.assertEqual(user.password,password)
            journey=m.JornadaTrabalho.objects.create(nome='Manter',semana={'0':{'entrada':'08:00','saida':'17:00'}});employee.jornada=journey;employee.save()
            other=self.ready('funcionarios',['Usuário','Matrícula','Nome'],[[user.username,'MIG-01','Atualizado']]);s.edit_row(self.admin,other.public_id,2,{},'ATUALIZAR');self.finish(other);employee.refresh_from_db();self.assertEqual(employee.jornada_id,journey.pk)
    def test_employee_missing_or_foreign_account_not_created(self):
        with tenant_context(self.a):
            for login in ['inexistente',self.tech_b.username]:
                obj=self.ready('funcionarios',['Usuário','Matrícula','Nome'],[[login,login,'Pessoa']]);self.assertEqual(obj.linhas.get().estado,'CORRIGIR')
            self.assertEqual(m.Funcionario.objects.count(),0)
    def test_other_organization_cannot_read_batch_or_use_its_matches(self):
        with tenant_context(self.a):obj=self.ready();self.finish(obj)
        with tenant_context(self.b):
            with self.assertRaises(m.LoteImportacao.DoesNotExist):s.batch(self.admin_b,obj.public_id)
            other=self.ready(actor=self.admin_b);self.assertEqual(s.summary(other)['pronta'],1);self.finish(other,actor=self.admin_b)
            self.assertEqual(g.Peca.objects.filter(sku='IMPORT-01').count(),1)
        self.client.force_login(self.admin_b);self.assertEqual(self.client.get(reverse('operacao:migration_result',args=[obj.public_id])).status_code,404)
    def test_permissions_backend_admin_gestor_only_even_with_grant(self):
        for role in ['TECNICO','ESTOQUE','FINANCEIRO','VENDEDOR','PDV']:
            user=self.users.get(role) or self.user('mig-'+role,self.a,role)
            with tenant_context(self.a):
                member=OrganizationMembership.objects.get(user=user,organization=self.a);PermissaoMembership.objects.create(membership=member,capacidade='migracao',permitido=True)
            with tenant_context(self.a):
                with self.assertRaises(PermissionDenied):s.authorize(user)
            self.client.force_login(user);self.assertEqual(self.client.get(reverse('operacao:migration_home')).status_code,403)
        for user in (self.admin,self.users['GESTOR']):
            self.client.force_login(user);self.assertEqual(self.client.get(reverse('operacao:migration_home')).status_code,200)
    def test_disabled_domain_module_blocks_corresponding_import(self):
        with tenant_context(self.a):
            ModuloOrganizacao.objects.create(codigo='estoque',habilitado=False)
            with self.assertRaises(PermissionDenied):self.uploaded()
    def test_unknown_fields_organization_spoof_and_csrf_not_bypassed(self):
        url=reverse('operacao:migration_upload',args=['produtos'])
        self.assertEqual(self.client.post(url,{'organization_id':self.b.pk,'arquivo':csv_file(['Código','Nome'],[['MAL','Nome']])}).status_code,200)
        with tenant_context(self.a):self.assertEqual(m.LoteImportacao.objects.count(),0)
        with tenant_context(self.a):
            obj=self.ready()
            with self.assertRaises(ValidationError):s.edit_row(self.admin,obj.public_id,2,{'organization_id':self.b.pk},'CRIAR')
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin);self.assertEqual(client.post(url,{'arquivo':csv_file(['Código','Nome'],[['CSRF','Nome']])}).status_code,403)
    def test_html_end_to_end_confirmation_chunks_report_and_friendly_labels(self):
        response=self.client.post(reverse('operacao:migration_upload',args=['produtos']),{'arquivo':csv_file(['COD_PROD','Descrição'],[['UI-01','Interface']])});self.assertEqual(response.status_code,302)
        with tenant_context(self.a):obj=m.LoteImportacao.objects.get()
        key=obj.public_id
        self.assertEqual(self.client.post(reverse('operacao:migration_mapping',args=[key]),{'col_0':'sku','col_1':'descricao'}).status_code,302)
        response=self.client.get(reverse('operacao:migration_preview',args=[key]));self.assertContains(response,'Nome do produto');self.assertNotContains(response,'<dt>sku</dt>')
        self.client.post(reverse('operacao:migration_start',args=[key]),{'confirmar':'sim'});response=self.client.post(reverse('operacao:migration_chunk',args=[key]));self.assertEqual(response.json()['criada'],1)
        response=self.client.get(reverse('operacao:migration_result',args=[key]));self.assertContains(response,'Importação concluída');self.assertIn('no-store',response['Cache-Control'])
        response=self.client.get(reverse('operacao:migration_report',args=[key]));self.assertEqual(response.status_code,200);self.assertIn('Enviado por',response.content.decode('utf-8-sig'))
    def test_only_confirming_actor_can_execute_and_after_logout_cannot(self):
        with tenant_context(self.a):obj=self.ready();s.start(self.admin,obj.public_id)
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied):s.execute_chunk(self.users['GESTOR'],obj.public_id)
        self.client.logout();response=self.client.post(reverse('operacao:migration_chunk',args=[obj.public_id]));self.assertEqual(response.status_code,302)
        with tenant_context(self.a):self.assertFalse(g.Peca.objects.filter(sku='IMPORT-01').exists())
    def test_all_excel_templates_download_authenticated_and_headers_correct(self):
        from openpyxl import load_workbook
        for kind,spec in CATALOG.items():
            response=self.client.get(reverse('operacao:migration_template',args=[kind]));self.assertEqual(response.status_code,200)
            data=b''.join(response.streaming_content);wb=load_workbook(io.BytesIO(data),read_only=True)
            self.assertEqual(wb.sheetnames,['Dados','Como preencher']);self.assertEqual(len(next(wb['Dados'].values)),len(spec['fields']));wb.close()
    def test_upload_storage_failure_does_not_create_batch(self):
        with tenant_context(self.a),patch('ordens.storage.PrivateStorage._save',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):self.uploaded()
            self.assertEqual(m.LoteImportacao.objects.count(),0)
    def test_approved_history_cannot_be_edited_and_audit_present(self):
        with tenant_context(self.a):
            obj=self.ready();self.finish(obj)
            with self.assertRaises(ValidationError):s.edit_row(self.admin,obj.public_id,2,{'descricao':'Tentar alterar'},'CRIAR')
            self.assertTrue(PlatformAudit.objects.filter(action='IMPORTACAO_CONCLUIDA').exists())

class ImportReaderTests(SimpleTestCase):
    def test_invalid_extension_corrupt_excel_binary_csv_and_empty(self):
        for name,data in [('file.exe',b'abc'),('file.xlsx',b'not-zip'),('file.csv',b'a\x00b'),('file.csv',b'')]:
            with self.assertRaises(ValidationError):readers.read(name,data)
    def test_large_file_rows_columns_and_cells_rejected(self):
        for data in [b'x'*(readers.MAX_BYTES+1),b'codigo;nome\n'+b'A;B\n'*(readers.MAX_ROWS+1),(';'.join('c'+str(i) for i in range(41))+'\n'+';'.join('a' for i in range(41))).encode(),b'codigo;nome\nA;'+b'x'*1001]:
            with self.assertRaises(ValidationError):readers.read('dados.csv',data)
    def test_unknown_headers_are_mappable_but_duplicate_or_blank_not_allowed(self):
        self.assertEqual(readers.read('a.csv',b'Coluna antiga;Nome\nA;B')[0],['Coluna antiga','Nome'])
        for data in [b'codigo;codigo\nA;B',b';nome\nA;B',b'codigo\nA;B']:
            with self.assertRaises(ValidationError):readers.read('a.csv',data)
    def test_csv_utf8_windows_encoding_and_delimiters(self):
        for separator in (';',',','\t'):
            for encoding in ('utf-8-sig','cp1252'):
                headers,rows=readers.read('dados.csv',f'Código{separator}Descrição\n0001{separator}Peça'.encode(encoding))
                self.assertEqual((headers,rows),(['Código','Descrição'],[(2,['0001','Peça'])]))
    def test_formula_zip_bomb_external_links_and_entities_blocked(self):
        source=(Path(settings.BASE_DIR)/'tests/fixtures/migracao/produtos.xlsx').read_bytes()
        for variant in ('formula','external','entity','bomb'):
            output=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(source)) as z,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as out:
                for name in z.namelist():
                    data=z.read(name)
                    if name=='xl/worksheets/sheet1.xml' and variant=='formula':
                        self.assertIn(b'</x:sheetData>',data)
                        data=data.replace(b'</x:sheetData>',b'<x:row r="4"><x:c r="A4"><x:f>WEBSERVICE("https://example.invalid")</x:f><x:v>0</x:v></x:c></x:row></x:sheetData>')
                    if name=='xl/workbook.xml' and variant=='entity':data=b'<!DOCTYPE workbook [<!ENTITY x "a">]>'+data
                    out.writestr(name,data)
                if variant=='external':out.writestr('xl/externalLinks/externalLink1.xml',b'<test/>')
                if variant=='bomb':out.writestr('large.xml',b'X'*(21*1024*1024))
            with self.assertRaises(ValidationError):readers.read('dados.xlsx',output.getvalue())
    def test_csv_report_formula_injection_neutralized(self):
        for value in ['=HYPERLINK("x")','+CMD','-CMD','@SUM(1)','  =EVIL']:
            self.assertTrue(excel_safe(value).startswith("'"))
        self.assertEqual(excel_safe('Texto seguro'),'Texto seguro')

@skipUnless(connection.vendor=='postgresql','PostgreSQL locks required')
class ImportConcurrencyTests(ImportData,TransactionTestCase):
    def setUp(self):self.setup_import()
    def worker(self,action):
        close_old_connections()
        try:
            with tenant_context(self.a):return action()
        finally:close_old_connections()
    def test_same_file_concurrent_upload_one_batch(self):
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(lambda _:self.worker(lambda:self.uploaded().pk),range(2)))
        self.assertEqual(ids[0],ids[1])
        with tenant_context(self.a):self.assertEqual(m.LoteImportacao.objects.count(),1)
    def test_same_batch_concurrent_chunks_one_creation(self):
        with tenant_context(self.a):obj=self.ready();s.start(self.admin,obj.public_id)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:self.worker(lambda:s.execute_chunk(self.admin,obj.public_id).pk),range(2)))
        with tenant_context(self.a):self.assertEqual((g.Peca.objects.filter(sku='IMPORT-01').count(),obj.linhas.get().estado),(1,'CRIADA'))

class ImportMigrationPreservationTests(ImportData,TransactionTestCase):
    def test_additive_migration_preserves_previous_tables_rows(self):
        from django.db.migrations.executor import MigrationExecutor
        from platform_core.models import ERPCatalog
        self.assertEqual(connection.settings_dict['HOST'],'127.0.0.1');self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        # TransactionTestCase flushes migration-seeded catalog rows. Restore
        # the public product required by rh_municipal.0004 before replaying the
        # forward migration chain; production installs receive it from
        # platform_core.0014.
        ERPCatalog.objects.get_or_create(
            code='gestao-publica',
            defaults={
                'name': 'VERTYX Gestão Pública',
                'description': 'Estrutura e gestão municipal.',
                'active': True,
                'operational': True,
                'public_path': '/gestao-publica/',
                'entry_path': '/gestao-publica/',
            },
        )
        MigrationExecutor(connection).migrate([('operacao','0021_nfce_response_code')])
        try:
            self.setup_import()
            tables={}
            with connection.cursor() as cur:
                for table in connection.introspection.table_names():
                    if table!='django_migrations':tables[table]=[col.name for col in connection.introspection.get_table_description(cur,table)]
            def snapshot():
                values={}
                with connection.cursor() as cur:
                    for table,cols in tables.items():
                        cur.execute('SELECT '+','.join(connection.ops.quote_name(c) for c in cols)+' FROM '+connection.ops.quote_name(table));values[table]=sorted(repr(row) for row in cur.fetchall())
                return values
            before=snapshot();MigrationExecutor(connection).migrate([('operacao','0022_migration_assistant')]);self.assertEqual(snapshot(),before)
            with tenant_context(self.a):self.assertEqual(m.LoteImportacao.objects.count(),0)
        finally:executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
