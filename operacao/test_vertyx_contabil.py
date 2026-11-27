"""Testes de integração, fluxo operacional e fronteiras multi-tenant do VERTYX Contábil."""
from __future__ import annotations

import io
from datetime import timedelta
from openpyxl import Workbook

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from clientes.models import Cliente, TipoPessoa
from equipamentos.models import Equipamento
from fiscal import carteira_services as cs
from integracoes import services as mig_services
from operacao.contabil_models import (
    ComunicacaoClienteContabil,
    EmpresaCarteiraContabil,
    EventoHistoricoContabil,
    PendenciaFiscalCarteira,
    validar_cnpj_digitos,
)
from platform_core.context import tenant_context
from .test_block3_commerce import CommerceData


# CNPJs sintéticos matematicamente válidos (DV módulo 11 oficial) para testes
CNPJ_SINTETICO_1 = '11222333000181'
CNPJ_SINTETICO_2 = '11444777000161'
CNPJ_SINTETICO_3 = '19131243000197'


class VertyxContabilMVPTests(CommerceData, TestCase):
    def setUp(self):
        self.setup_commerce()
        self.org_a = self.a
        self.org_b = self.b
        self.admin_a = self.admin
        self.contador_a = self.users['CONTABILIDADE']
        self.tecnico_a = self.users['TECNICO']

    def _login_org(self, user, org):
        self.client.force_login(user)
        session = self.client.session
        session['organization_id'] = org.pk
        session.save()

    def test_validacao_cnpj_oficial_e_unicidade_por_organizacao(self):
        self.assertEqual(validar_cnpj_digitos('11.222.333/0001-81'), CNPJ_SINTETICO_1)
        with self.assertRaises(ValidationError):
            validar_cnpj_digitos('11.222.333/0001-99')

        with tenant_context(self.org_a):
            emp_a = cs.salvar_empresa_carteira(
                self.admin_a,
                {'razao_social': 'Clínica Sintética A', 'cnpj': CNPJ_SINTETICO_1},
            )
            self.assertEqual(emp_a.cnpj, CNPJ_SINTETICO_1)
            with self.assertRaises(ValidationError):
                cs.salvar_empresa_carteira(
                    self.admin_a,
                    {'razao_social': 'Duplicada A', 'cnpj': CNPJ_SINTETICO_1},
                )

        with tenant_context(self.org_b):
            emp_b = cs.salvar_empresa_carteira(
                self.admin_b,
                {'razao_social': 'Clínica Sintética em Outra Carteira', 'cnpj': CNPJ_SINTETICO_1},
            )
            self.assertNotEqual(emp_a.pk, emp_b.pk)
            self.assertEqual(EmpresaCarteiraContabil.objects.count(), 1)

    def test_quatro_telas_mvp_fluxo_rastreavel_e_imutabilidade_auditoria(self):
        self._login_org(self.contador_a, self.org_a)

        resp_cli = self.client.post(
            '/fiscal/carteira/clientes/',
            {
                'acao': 'nova_empresa',
                'razao_social': 'Hospital Modelo Sintético Ltda',
                'cnpj': '11.222.333/0001-81',
                'regime_tributario': 'LUCRO_PRESUMIDO',
                'departamento_padrao': 'FISCAL',
                'whatsapp_contato': '79999998888',
                'email_contato': 'fiscal@hospitalmodelo.test',
                'procuracao_ecac_ativa': '1',
            },
        )
        self.assertEqual(resp_cli.status_code, 302)

        with tenant_context(self.org_a):
            emp = EmpresaCarteiraContabil.objects.get(cnpj=CNPJ_SINTETICO_1)

        ontem = (timezone.localdate() - timedelta(days=2)).isoformat()
        self.assertEqual(
            self.client.post(
                '/fiscal/carteira/obrigacoes/',
                {
                    'acao': 'nova_certidao',
                    'empresa_id': emp.pk,
                    'esfera': 'FEDERAL',
                    'situacao': 'IRREGULAR',
                    'validade': ontem,
                    'gerar_pendencia': '1',
                },
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(
                '/fiscal/carteira/obrigacoes/',
                {
                    'acao': 'nova_obrigacao',
                    'empresa_id': emp.pk,
                    'tipo': 'DAS',
                    'competencia': '10/2026',
                    'vencimento': ontem,
                    'valor_guia': '1450.50',
                },
            ).status_code,
            302,
        )

        with tenant_context(self.org_a):
            pend = PendenciaFiscalCarteira.objects.get(empresa=emp)
            self.assertEqual(pend.codigo, 'PEND-0001')

        self.assertEqual(
            self.client.post(
                f'/fiscal/carteira/pendencias/{pend.pk}/',
                {
                    'acao': 'comunicar_cliente',
                    'canal': 'WHATSAPP',
                    'tipo': 'SOLICITACAO_DOC',
                    'destinatario': '79999998888',
                    'assunto': 'Regularização CND Federal',
                    'documento_solicitado': 'Comprovante DARF Previdenciário',
                    'mensagem': 'Favor encaminhar comprovante para baixa na RFB.',
                },
            ).status_code,
            302,
        )

        with tenant_context(self.org_a):
            com = ComunicacaoClienteContabil.objects.get(pendencia=pend)
            self.assertIn('wa.me/5579999998888', com.whatsapp_link)

        self.assertEqual(
            self.client.get(f'/fiscal/carteira/comunicacoes/{com.token_confirmacao}/confirmar/').status_code,
            302,
        )

        self.assertEqual(
            self.client.post(
                f'/fiscal/carteira/pendencias/{pend.pk}/',
                {
                    'acao': 'atualizar',
                    'etapa_fluxo': 'AUDITAR',
                    'status': 'RESOLVIDO',
                    'evidencia_resolucao': 'CND reemitida sob código ABCD-1234',
                    'comentario': 'Situação regularizada junto ao e-CAC.',
                },
            ).status_code,
            302,
        )

        dash = self.client.get('/fiscal/carteira/')
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, 'Hospital Modelo Sintético Ltda')

        for url in [
            '/fiscal/carteira/clientes/',
            f'/fiscal/carteira/clientes/{emp.public_id}/',
            '/fiscal/carteira/pendencias/',
            f'/fiscal/carteira/pendencias/{pend.pk}/',
            '/fiscal/carteira/obrigacoes/',
        ]:
            self.assertEqual(self.client.get(url).status_code, 200)

        with tenant_context(self.org_a):
            pend.refresh_from_db()
            com.refresh_from_db()
            self.assertEqual(pend.status, 'RESOLVIDO')
            self.assertTrue(com.confirmado_recebimento)
            ev = EventoHistoricoContabil.objects.filter(empresa=emp).first()
            self.assertIsNotNone(ev)
            with self.assertRaises(ValidationError):
                ev.delete()
            with self.assertRaises(ValidationError):
                EventoHistoricoContabil.objects.filter(empresa=emp).delete()

    def test_isolamento_multi_tenant_e_bloqueio_de_papeis_nao_autorizados(self):
        with tenant_context(self.org_a):
            emp_a = cs.salvar_empresa_carteira(
                self.admin_a,
                {'razao_social': 'Empresa Secreta Org A', 'cnpj': CNPJ_SINTETICO_2},
            )
            pend_a = cs.criar_pendencia_operacional(
                self.admin_a,
                {'empresa_id': emp_a.pk, 'titulo': 'Pendência Confidencial A'},
            )

        self._login_org(self.tecnico_a, self.org_a)
        self.assertEqual(self.client.get('/fiscal/carteira/').status_code, 403)

        self._login_org(self.admin_b, self.org_b)
        dash_b = self.client.get('/fiscal/carteira/')
        self.assertEqual(dash_b.status_code, 200)
        self.assertNotContains(dash_b, 'Empresa Secreta Org A')
        self.assertEqual(self.client.get(f'/fiscal/carteira/clientes/{emp_a.public_id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/fiscal/carteira/pendencias/{pend_a.pk}/').status_code, 404)

    def test_pre_analise_comercial_sincronizacao_erp_e_atualizacao_em_lote_migracao(self):
        with tenant_context(self.org_a):
            cli = Cliente.objects.create(
                organization=self.org_a,
                tipo_pessoa=TipoPessoa.JURIDICA,
                nome_razao_social='Distribuidora Médica ERP Ltda',
                cpf_cnpj='19.131.243/0001-97',
                cidade='Estância',
                uf='SE',
            )
            criados, _ = cs.importar_clientes_pj_do_erp(self.admin_a)
            self.assertEqual(criados, 1)
            self.assertTrue(EmpresaCarteiraContabil.objects.filter(cnpj=CNPJ_SINTETICO_3).exists())

            analise = cs.realizar_pre_analise_cnpj(
                self.admin_a,
                {
                    'cnpj': CNPJ_SINTETICO_1,
                    'razao_social': 'Novo Cliente Contábil S/A',
                    'regime_estimado': 'SIMPLES_NACIONAL',
                    'pendencias_conhecidas': 'PGDAS em aberto',
                    'consultar_publico': '0',
                },
            )
            convertida = cs.converter_pre_analise_em_cliente(self.admin_a, analise)
            self.assertEqual(convertida.cnpj, CNPJ_SINTETICO_1)
            self.assertEqual(convertida.pendencias.count(), 1)

            # Conferência de atualização em lote sem duplicar cadastros existentes
            wb = Workbook()
            ws = wb.active
            ws.append(['Nome / Razão social', 'CPF/CNPJ', 'Cidade'])
            ws.append(['Distribuidora Médica ERP Atualizada Ltda', '19.131.243/0001-97', 'Aracaju'])
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            lote, _ = mig_services.upload(
                self.admin_a,
                'clientes',
                SimpleUploadedFile('clientes.xlsx', buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            )
            mig_services.map_columns(self.admin_a, lote.public_id, {'0': 'nome_razao_social', '1': 'cpf_cnpj', '2': 'cidade'})
            self.assertEqual(mig_services.summary(lote)['duplicada'], 1)
            marcados = mig_services.mark_matching_rows_update(self.admin_a, lote.public_id)
            self.assertEqual(marcados, 1)
            self.assertEqual(mig_services.summary(lote)['pronta'], 1)
            self.assertEqual(mig_services.summary(lote)['duplicada'], 0)
