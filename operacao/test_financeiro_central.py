import uuid
from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from gestao import models as g
from gestao.reporting import financial_dashboard
from platform_core.context import tenant_context
from . import models as m, services
from .test_block2 import Block2Fixtures


class FinanceiroCentralTests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()

    def entry(self, **kwargs):
        values = dict(tipo='RECEBER', descricao='Título de teste', valor=Decimal('100.00'), vencimento=self.today, criado_por=self.admin)
        values.update(kwargs)
        return g.Lancamento.objects.create(**values)

    def test_partial_payment_preserves_original_and_tracks_interest_fine_discount_idempotently(self):
        with tenant_context(self.a):
            category = g.CategoriaFinanceira.objects.create(nome='Serviços', natureza='RECEITA')
            center = g.CentroCusto.objects.create(nome='Assistência')
            account = m.ContaBancaria.objects.create(nome='Banco homologação', banco='Banco fictício teste', titular='Conta sintética', tipo='BANCO', saldo_inicial=Decimal('500.00'))
            title = self.entry(categoria=category, centro_custo=center)
            key = uuid.uuid4()
            payment = services.pagar(self.users['FINANCEIRO'], title.pk, Decimal('30.00'), self.today, 'Parcela', account.pk, key, desconto=Decimal('2'), juros=Decimal('3'), multa=Decimal('1'))
            self.assertEqual((payment.valor, payment.desconto, payment.juros, payment.multa), (Decimal('30.00'), Decimal('2.00'), Decimal('3.00'), Decimal('1.00')))
            self.assertEqual(title.valor, Decimal('100.00'))
            self.assertEqual(title.saldo, Decimal('72.00'))
            self.assertEqual(title.situacao, 'PARCIAL')
            self.assertEqual(m.MovimentoCaixa.objects.get(conta=account).lancamento_id, title.pk)
            self.assertEqual(m.MovimentoCaixa.objects.get(conta=account).centro_custo_id, center.pk)
            replay = services.pagar(self.users['FINANCEIRO'], title.pk, Decimal('30.00'), self.today, 'Parcela', account.pk, key, desconto=Decimal('2'), juros=Decimal('3'), multa=Decimal('1'))
            self.assertEqual(replay.pk, payment.pk)
            self.assertEqual(m.Pagamento.objects.filter(lancamento=title).count(), 1)
            services.pagar(self.users['FINANCEIRO'], title.pk, Decimal('72.00'), self.today, 'Quitação', account.pk, uuid.uuid4())
            title.refresh_from_db()
            self.assertEqual((title.status, title.saldo), ('LIQUIDADO', Decimal('0')))

    def test_account_and_category_are_organization_scoped(self):
        with tenant_context(self.a):
            category = g.CategoriaFinanceira.objects.create(nome='Somente A', natureza='RECEITA')
            bank = m.ContaBancaria.objects.create(nome='Banco A')
            services.caixa(self.users['FINANCEIRO'], bank.pk, 'ENTRADA', Decimal('10'), self.today, 'Entrada A', categoria=category)
            self.assertEqual(m.MovimentoCaixa.objects.count(), 1)
        with tenant_context(self.b):
            self.assertEqual(m.MovimentoCaixa.objects.count(), 0)
            self.assertEqual(m.ContaBancaria.objects.count(), 0)
            self.assertEqual(g.CategoriaFinanceira.objects.count(), 0)
            with self.assertRaises(m.ContaBancaria.DoesNotExist):
                services.caixa(self.admin_b, bank.pk, 'ENTRADA', Decimal('10'), self.today, 'Tentativa cross tenant')

    def test_statement_import_replay_create_movement_and_ignore_audit(self):
        with tenant_context(self.a):
            account = m.ContaBancaria.objects.create(nome='Banco extrato', saldo_inicial=Decimal('100'))
            payload = b'id,data,valor,descricao\nFIT-1,2026-10-10,-12.50,Fornecedor\n'
            first = services.importar_extrato(self.users['FINANCEIRO'], account.pk, SimpleUploadedFile('extrato.csv', payload, content_type='text/csv'))
            second = services.importar_extrato(self.users['FINANCEIRO'], account.pk, SimpleUploadedFile('extrato.csv', payload, content_type='text/csv'))
            self.assertEqual((first['criados'], first['duplicados']), (1, 0))
            self.assertEqual((second['criados'], second['duplicados']), (0, 1))
            row = m.ExtratoBancario.objects.get(identificador='FIT-1')
            move = services.conciliar_criar_movimento(self.users['FINANCEIRO'], row.pk)
            account.refresh_from_db()
            row.refresh_from_db()
            self.assertEqual((move.origem, row.movimento_id, account.saldo), ('CONCILIACAO', move.pk, Decimal('87.50')))
            with self.assertRaises(ValidationError):
                services.conciliar_criar_movimento(self.users['FINANCEIRO'], row.pk)
            untouched = m.ExtratoBancario.objects.create(conta=account, identificador='FIT-2', data=self.today, valor=Decimal('4.00'), descricao='Linha para ignorar')
            services.ignorar_extrato(self.users['FINANCEIRO'], untouched.pk, 'Não reconhecida')
            untouched.refresh_from_db()
            self.assertTrue(untouched.ignorado)
            self.assertEqual(untouched.ignorado_por_id, self.users['FINANCEIRO'].pk)

    def test_dashboard_uses_cash_basis_and_reports_projection_and_today(self):
        with tenant_context(self.a):
            due_today = self.entry(valor=Decimal('40.00'), vencimento=self.today)
            future = self.entry(descricao='Próximo mês', valor=Decimal('60.00'), vencimento=self.today + timedelta(days=20))
            services.pagar(self.users['FINANCEIRO'], due_today.pk, Decimal('10'), self.today, 'Parcial sem conta')
            result = financial_dashboard(self.today - timedelta(days=60), self.today - timedelta(days=30))
            self.assertEqual(result['a_receber'], Decimal('90.00'))
            self.assertEqual(result['recebido'], Decimal('0'))
            self.assertEqual(result['vencendo_hoje_receber'], Decimal('30.00'))
            self.assertEqual(result['projecoes'][30]['entradas'], Decimal('90.00'))
            self.assertEqual(result['entradas_hoje'], Decimal('10.00'))

    def test_category_nature_and_finance_urls_are_enforced(self):
        with tenant_context(self.a):
            expense = g.CategoriaFinanceira.objects.create(nome='Despesa exclusiva', natureza='DESPESA')
            with self.assertRaises(ValidationError):
                self.entry(categoria=expense)
            self.client.force_login(self.users['TECNICO'])
            self.assertEqual(self.client.get(reverse('gestao:financeiro')).status_code, 403)
            self.assertEqual(self.client.get(reverse('operacao:financeiro_movimentacoes')).status_code, 403)
            self.assertEqual(self.client.get(reverse('operacao:extrato_importar')).status_code, 403)
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(reverse('gestao:financeiro')).status_code, 200)
            self.assertEqual(self.client.get(reverse('operacao:financeiro_movimentacoes')).status_code, 200)

    def test_invalid_csv_does_not_write_partial_extrato_and_ofx_is_supported(self):
        from .finance_import import parse_statement
        with tenant_context(self.a):
            account = m.ContaBancaria.objects.create(nome='Conta arquivos')
            invalid = SimpleUploadedFile('erro.csv', b'id,data,valor,descricao\nOK,2026-10-10,10.00,Valid\nBAD,data,abc,Invalid\n')
            with self.assertRaises(ValidationError):
                services.importar_extrato(self.users['FINANCEIRO'], account.pk, invalid)
            self.assertEqual(m.ExtratoBancario.objects.count(), 0)
            ofx_content = f'<OFX><BANKTRANLIST><STMTTRN><FITID>ABC1<DTPOSTED>{self.today:%Y%m%d}<TRNAMT>15.25<NAME>Recebimento teste</STMTTRN></BANKTRANLIST></OFX>'.encode()
            ofx = SimpleUploadedFile('amostra.ofx', ofx_content)
            parsed = parse_statement(ofx)
            self.assertEqual((parsed[0]['identificador'], parsed[0]['data'], parsed[0]['valor']), ('ABC1', self.today, Decimal('15.25')))
