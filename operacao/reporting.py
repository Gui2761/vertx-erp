"""Relatórios ampliados reutilizando filtros, permissões e exportadores do ERP."""
from decimal import Decimal
from django.db.models import Sum, Q, F
from django.utils import timezone
from gestao import models as g
from gestao.permissions import allowed
from ordens.services import visiveis
from . import models as m

REPORTS = {
    'produtividade': ('Produtividade dos técnicos', 'operacional'),
    'corretivas': ('Atendimentos corretivos', 'operacional'),
    'planos_preventivos': ('Ocorrências dos planos preventivos', 'operacional'),
    'estoque_atual': ('Estoque e depósitos', 'estoque'),
    'estoque_validade': ('Lotes e validade', 'estoque'),
    'estoque_giro': ('Giro / produtos sem movimentação', 'estoque'),
    'contas_vencidas': ('Contas vencidas', 'financeiro'),
    'recebimentos': ('Pagamentos e recebimentos realizados', 'financeiro'),
    'fluxo_caixa': ('Fluxo de caixa previsto / realizado', 'financeiro'),
    'centros_custo': ('Lançamentos por centro de custo', 'financeiro'),
    'orcamentos_conversao': ('Orçamentos e conversão', 'orcamentos'),
    'vendas_margem': ('Vendas e margem', 'orcamentos'),
    'compras_recebidas': ('Compras e recebimentos', 'estoque'),
}

def financial_dashboard(start, end):
    qs = g.Lancamento.objects.exclude(status='CANCELADO')
    pending = qs.filter(status__in=['PENDENTE','VENCIDO']).prefetch_related('pagamentos')
    def balance(rows):
        return sum((entry.saldo for entry in rows), g.ZERO)
    payments = m.Pagamento.objects.filter(data__range=(start,end)).select_related('lancamento')
    # Contas liquidadas anteriormente ao novo módulo continuam contabilizadas uma vez.
    legacy = qs.filter(status='LIQUIDADO', pagamentos__isnull=True, data_liquidacao__range=(start,end))
    def realized(kind):
        return sum((row.valor for row in payments if row.lancamento.tipo == kind), g.ZERO) + sum((row.valor for row in legacy if row.tipo == kind), g.ZERO)
    today = timezone.localdate()
    result = {'a_receber': balance(pending.filter(tipo='RECEBER')), 'a_pagar':balance(pending.filter(tipo='PAGAR')), 'recebido':realized('RECEBER'), 'pago':realized('PAGAR'), 'vencido_receber':balance(pending.filter(tipo='RECEBER',vencimento__lt=today)), 'vencido_pagar':balance(pending.filter(tipo='PAGAR',vencimento__lt=today))}
    result['resultado'] = result['recebido'] - result['pago']
    months = {}
    def add(date, prefix, kind, amount):
        key = date.strftime('%Y-%m')
        row = months.setdefault(key, {'mes':key, 'previsto_RECEBER':g.ZERO, 'previsto_PAGAR':g.ZERO, 'realizado_RECEBER':g.ZERO, 'realizado_PAGAR':g.ZERO})
        row[prefix + '_' + kind] += amount
    for entry in qs.filter(vencimento__range=(start,end)):
        add(entry.vencimento,'previsto',entry.tipo,entry.valor)
    for row in payments:
        add(row.data,'realizado',row.lancamento.tipo,row.valor)
    for entry in legacy:
        add(entry.data_liquidacao,'realizado',entry.tipo,entry.valor)
    result['fluxo'] = [months[key] for key in sorted(months)]
    return result

def date_filter(qs, data, field):
    if data.get('inicio'):
        qs = qs.filter(**{field+'__gte':data['inicio']})
    if data.get('fim'):
        qs = qs.filter(**{field+'__lte':data['fim']})
    return qs

def report_data(user, key, data):
    from gestao.reporting import filter_query
    if key in ['produtividade','corretivas']:
        qs = filter_query(visiveis(user),data,{'cliente':'cliente','unidade':'unidade','tecnico':'tecnico','equipamento':'equipamento','status':'status'},'conclusao__date' if key=='produtividade' else 'abertura__date')
        if key == 'corretivas':
            qs=qs.filter(tipo_atendimento='CORRETIVA')
            return ['OS','Cliente','Equipamento','Técnico','Situação','Horas'], [[row.numero,str(row.cliente),str(row.equipamento),str(row.tecnico),row.get_status_display(),row.horas] for row in qs]
        qs=qs.filter(status__in=['FINALIZADA','APROVADA','FATURADA'])
        from django.db.models import Count
        totals=qs.values('tecnico__nome').annotate(total=Count('pk'),horas=Sum('horas'))
        return ['Técnico','OS concluídas','Horas'], [[row['tecnico__nome'],row['total'],row['horas'] or 0] for row in totals]
    if key=='planos_preventivos':
        qs=filter_query(m.PreventivaProgramada.objects.select_related('plano__tecnico','equipamento'),data,{'cliente':'plano__cliente','unidade':'equipamento__unidade','tecnico':'plano__tecnico','equipamento':'equipamento'},'data')
        if not allowed(user,'contratos'):
            qs=qs.filter(plano__tecnico__usuario=user)
        rows=[[row.plano.nome,str(row.equipamento),row.data,row.situacao,row.ordem.numero if row.ordem_id else ''] for row in qs if not data.get('status') or row.situacao==data['status']]
        return ['Plano','Equipamento','Data','Situação','OS'], rows
    if key in ['estoque_atual','estoque_validade','estoque_giro']:
        qs=g.Peca.objects.filter(ativo=True)
        if key=='estoque_validade':
            lots=date_filter(m.LoteEstoque.objects.filter(peca__ativo=True,validade__isnull=False).select_related('peca','deposito'),data,'validade')
            return ['SKU','Peça','Lote','Validade','Saldo','Depósito','Situação'],[[lot.peca.sku,lot.peca.descricao,lot.numero,lot.validade,lot.quantidade,str(lot.deposito),lot.classificacao] for lot in lots]
        rows=[]
        for part in qs:
            if key=='estoque_giro':
                moves=date_filter(part.movimentacoes.all(),data,'criado_em__date')
                consumption=-(moves.filter(variacao__lt=0).aggregate(total=Sum('variacao'))['total'] or 0)
                last=part.movimentacoes.order_by('-criado_em').first()
                rows.append([part.sku,part.descricao,part.quantidade_atual,consumption,last.criado_em.date() if last else 'Sem movimentação'])
            elif key=='estoque_atual':
                balances=list(m.SaldoDeposito.objects.filter(peca=part).select_related('deposito'))
                rows.extend([[part.sku,part.descricao,str(b.deposito),b.quantidade,part.estoque_minimo] for b in balances] or [[part.sku,part.descricao,'Principal (saldo legado)',part.quantidade_atual,part.estoque_minimo]])
            else:
                rows.append([part.sku,part.descricao,part.lote,part.validade,part.quantidade_atual])
        return {'estoque_atual':['SKU','Peça','Depósito','Saldo','Mínimo'], 'estoque_validade':['SKU','Peça','Lote','Validade','Saldo'], 'estoque_giro':['SKU','Peça','Saldo','Consumo no período','Última movimentação']}[key],rows
    if key=='recebimentos':
        qs=filter_query(m.Pagamento.objects.select_related('lancamento','conta'),data,{'cliente':'lancamento__cliente'},'data')
        return ['Conta','Tipo','Data','Valor','Banco','Usuário'], [[row.lancamento.descricao,row.lancamento.get_tipo_display(),row.data,row.valor,str(row.conta or ''),str(row.usuario)] for row in qs]
    if key=='fluxo_caixa':
        start=data.get('inicio') or timezone.localdate().replace(day=1)
        end=data.get('fim') or timezone.localdate()
        result=financial_dashboard(start,end)
        return ['Mês','Receber previsto','Pagar previsto','Recebido','Pago'], [[row['mes'],row['previsto_RECEBER'],row['previsto_PAGAR'],row['realizado_RECEBER'],row['realizado_PAGAR']] for row in result['fluxo']]
    if key in ['contas_vencidas','centros_custo']:
        qs=filter_query(g.Lancamento.objects.exclude(status='CANCELADO').select_related('centro_custo','cliente'),data,{'cliente':'cliente'},'vencimento')
        if key=='contas_vencidas':
            qs=qs.filter(status__in=['PENDENTE','VENCIDO'],vencimento__lt=timezone.localdate())
        return ['Conta','Centro de custo','Tipo','Cliente','Vencimento','Valor','Saldo'], [[row.descricao,str(row.centro_custo or 'Sem centro'),row.get_tipo_display(),str(row.cliente or ''),row.vencimento,row.valor,row.saldo] for row in qs]
    if key=='orcamentos_conversao':
        qs=filter_query(g.Orcamento.objects.select_related('cliente'),data,{'cliente':'cliente','unidade':'unidade','equipamento':'equipamento'},'data')
        if data.get('status'):
            qs=qs.filter(status=data['status'])
        return ['Orçamento','Cliente','Estado','Total','OS convertida','Margem estimada'], [[row.numero,str(row.cliente),row.status,row.total,row.ordem_convertida.numero if row.ordem_convertida_id else '',row.total-sum((item.quantidade*item.peca.custo_aquisicao if item.peca_id else g.ZERO for item in row.itens.all()),g.ZERO)] for row in qs]
    if key=='vendas_margem':
        qs=filter_query(m.Venda.objects.select_related('cliente'),data,{'cliente':'cliente'},'criado_em__date')
        if data.get('status'):
            qs=qs.filter(status=data['status'])
        return ['Venda','Cliente','Estado','Total','Margem'], [[str(row),str(row.cliente),row.status,row.total,sum((item.margem for item in row.itens.all()),g.ZERO)] for row in qs]
    qs=date_filter(m.Compra.objects.select_related('fornecedor'),data,'criado_em__date')
    return ['Compra','Fornecedor','Estado','Total','Conta a pagar'], [[str(row),str(row.fornecedor or ''),row.status,row.total,row.conta_id or ''] for row in qs]
