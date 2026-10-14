"""Relatórios ampliados reutilizando filtros, permissões e exportadores do ERP."""
from decimal import Decimal
from django.db.models import Sum, Q, F
from django.utils import timezone
from gestao import models as g
from gestao.permissions import allowed
from ordens.services import visiveis
from . import models as m

REPORTS = {
    'os_executadas': ('OS executadas', 'operacional'),
    'os_pendentes': ('OS pendentes', 'operacional'),
    'preventivas_previstas': ('Preventivas previstas — planos e contratos', 'operacional'),
    'preventivas_executadas': ('Preventivas executadas — planos e contratos', 'operacional'),
    'custos_os': ('Custo registrado de peças por OS', 'contratos'),
    'custos_equipamento': ('Custo registrado de peças por equipamento', 'contratos'),
    'custos_cliente': ('Custo registrado de peças por cliente', 'contratos'),
    'custos_contrato': ('Custo registrado de peças por contrato', 'contratos'),
    'estoque_critico': ('Estoque crítico e sugestão atual', 'estoque'),
    'compras_pendentes': ('Compras e quantidades pendentes', 'estoque'),
    'produtividade': ('Produtividade dos técnicos', 'operacional'),
    'corretivas': ('Atendimentos corretivos', 'operacional'),
    'planos_preventivos': ('Ocorrências dos planos preventivos', 'operacional'),
    'estoque_atual': ('Estoque e depósitos', 'estoque'),
    'estoque_validade': ('Lotes e validade', 'estoque'),
    'estoque_giro': ('Giro / produtos sem movimentação', 'estoque'),
    'contas_vencidas': ('Contas vencidas', 'financeiro'),
    'recebimentos': ('Pagamentos e recebimentos realizados', 'financeiro'),
    'movimentacao_bancaria': ('Movimentações por conta', 'financeiro'),
    'fluxo_caixa': ('Fluxo de caixa previsto / realizado', 'financeiro'),
    'centros_custo': ('Lançamentos por centro de custo', 'financeiro'),
    'orcamentos_conversao': ('Orçamentos e conversão', 'orcamentos'),
    'vendas_margem': ('Vendas e margem', 'orcamentos'),
    'compras_recebidas': ('Compras e recebimentos', 'estoque'),
}

def financial_dashboard(start, end, filters=None):
    from gestao.financial_origin import origin_type_query
    filters = filters or {}
    qs = g.Lancamento.objects.exclude(status='CANCELADO')
    if filters.get('filial'):
        from gestao.financial_origin import origin_query
        qs=qs.filter(origin_query(venda_origem__filial=filters['filial'])|origin_query(devolucao_origem__venda__filial=filters['filial'])).distinct()
    if filters.get('centro_custo'):
        qs=qs.filter(centro_custo=filters['centro_custo'])
    if filters.get('origem'):
        qs = qs.filter(origin_type_query(filters['origem'])).distinct()
    pending = qs.filter(status__in=['PENDENTE','VENCIDO']).prefetch_related('pagamentos','eventos')
    def balance(rows):
        return sum((entry.saldo for entry in rows), g.ZERO)
    payments = m.Pagamento.objects.filter(data__range=(start,end), lancamento__in=qs).select_related('lancamento')
    if filters.get('conta'):
        payments = payments.filter(conta=filters['conta'])
    if filters.get('controle'):
        payments = payments.filter(conta__isnull=filters['controle'] == 'NAO_BANCARIZADO')
    # Contas liquidadas anteriormente ao novo módulo continuam contabilizadas uma vez.
    legacy = qs.filter(status='LIQUIDADO', pagamentos__isnull=True, data_liquidacao__range=(start,end)).exclude(eventos__tipo='ABATIMENTO')
    if filters.get('conta') or filters.get('controle') == 'BANCARIZADO':
        legacy = legacy.none()
    def realized(kind):
        return sum((row.valor for row in payments if row.lancamento.tipo == kind), g.ZERO) + sum((row.valor for row in legacy if row.tipo == kind), g.ZERO)
    today = timezone.localdate()
    result = {'a_receber': balance(pending.filter(tipo='RECEBER')), 'a_pagar':balance(pending.filter(tipo='PAGAR')), 'recebido':realized('RECEBER'), 'pago':realized('PAGAR'), 'vencido_receber':balance(pending.filter(tipo='RECEBER',vencimento__lt=today)), 'vencido_pagar':balance(pending.filter(tipo='PAGAR',vencimento__lt=today))}
    from .models import ContaBancaria, MovimentoCaixa
    today_payments = m.Pagamento.objects.filter(data=today).select_related('lancamento')
    if filters.get('conta'):
        today_payments = today_payments.filter(conta=filters['conta'])
    if filters.get('controle'):
        today_payments = today_payments.filter(conta__isnull=filters['controle'] == 'NAO_BANCARIZADO')
    manual_today = MovimentoCaixa.objects.filter(data=today).exclude(origem='LANCAMENTO')
    if filters.get('conta'):
        manual_today = manual_today.filter(conta=filters['conta'])
    manual_amounts = manual_today.aggregate(entradas=Sum('valor', filter=Q(tipo='ENTRADA')), saidas=Sum('valor', filter=Q(tipo='SAIDA')))
    result['entradas_hoje'] = sum((row.valor for row in today_payments if row.lancamento.tipo == 'RECEBER'), g.ZERO) + (manual_amounts['entradas'] or g.ZERO)
    result['saidas_hoje'] = sum((row.valor for row in today_payments if row.lancamento.tipo == 'PAGAR'), g.ZERO) + (manual_amounts['saidas'] or g.ZERO)
    result['vencendo_hoje_receber'] = balance(pending.filter(tipo='RECEBER', vencimento=today))
    result['vencendo_hoje_pagar'] = balance(pending.filter(tipo='PAGAR', vencimento=today))
    accounts = ContaBancaria.objects.filter(ativo=True)
    if filters.get('conta'):
        accounts = accounts.filter(pk=filters['conta'].pk)
    result['saldo_disponivel_contas'] = sum((account.saldo for account in accounts), g.ZERO)
    result['resultado'] = result['recebido'] - result['pago']
    for kind, key in [('RECEBER','recebido_nao_bancarizado'), ('PAGAR','pago_nao_bancarizado')]:
        result[key] = sum((row.valor for row in payments if row.lancamento.tipo == kind and not row.conta_id),g.ZERO) + sum((row.valor for row in legacy if row.tipo == kind),g.ZERO)
    months = {}
    def add(date, prefix, kind, amount):
        key = date.strftime('%Y-%m')
        row = months.setdefault(key, {'mes':key, 'previsto_RECEBER':g.ZERO, 'previsto_PAGAR':g.ZERO, 'realizado_RECEBER':g.ZERO, 'realizado_PAGAR':g.ZERO})
        row[prefix + '_' + kind] += amount
    for entry in qs.filter(vencimento__range=(start,end)).prefetch_related('pagamentos','eventos'):
        add(entry.vencimento,'previsto',entry.tipo,entry.saldo)
    for row in payments:
        add(row.data,'realizado',row.lancamento.tipo,row.valor)
    for entry in legacy:
        add(entry.data_liquidacao,'realizado',entry.tipo,entry.valor)
    result['fluxo'] = [dict(months[key], realizado_resultado=months[key]['realizado_RECEBER'] - months[key]['realizado_PAGAR']) for key in sorted(months)]
    forecasts = {}
    for horizon in (7, 30, 90):
        limit = today + timezone.timedelta(days=horizon)
        upcoming = qs.filter(status__in=['PENDENTE','VENCIDO'], vencimento__gte=today, vencimento__lte=limit).prefetch_related('pagamentos','eventos')
        incoming = sum((entry.saldo for entry in upcoming if entry.tipo == 'RECEBER'), g.ZERO)
        outgoing = sum((entry.saldo for entry in upcoming if entry.tipo == 'PAGAR'), g.ZERO)
        forecasts[horizon] = {'entradas': incoming, 'saidas': outgoing, 'saldo_projetado': result['saldo_disponivel_contas'] + incoming - outgoing}
    result['projecoes'] = forecasts
    return result

def date_filter(qs, data, field):
    if data.get('inicio'):
        qs = qs.filter(**{field+'__gte':data['inicio']})
    if data.get('fim'):
        qs = qs.filter(**{field+'__lte':data['fim']})
    return qs

def report_data(user, key, data):
    from gestao.reporting import filter_query
    if key in ['os_executadas', 'os_pendentes', 'custos_os', 'custos_equipamento', 'custos_cliente', 'custos_contrato']:
        orders = filter_query(visiveis(user), data, {'cliente': 'cliente', 'unidade': 'unidade', 'tecnico': 'tecnico', 'equipamento': 'equipamento', 'status': 'status'}, 'conclusao__date' if key == 'os_executadas' else 'abertura__date')
        if key == 'os_executadas':
            orders = orders.filter(status__in=['FINALIZADA', 'APROVADA', 'FATURADA'])
        if key == 'os_pendentes':
            orders = orders.exclude(status__in=m.ENCERRADAS)
        if key.startswith('custos_'):
            groups = {}
            attr = {'custos_os': None, 'custos_equipamento': 'equipamento', 'custos_cliente': 'cliente', 'custos_contrato': 'contrato'}[key]
            for order in orders:
                identity = order.pk if not attr else getattr(order, attr + '_id')
                label = order.numero if not attr else str(getattr(order, attr) or 'Sem contrato')
                group = groups.setdefault(identity, [label, 0, g.ZERO])
                group[1] += 1; group[2] += order.custo_pecas
            return ['Referência', 'OS na base', 'Custo líquido registrado de peças (R$)'], list(groups.values())
        return ['OS', 'Cliente', 'Unidade', 'Equipamento', 'Técnico', 'Tipo', 'Status', 'Abertura', 'Conclusão'], [[order.numero, str(order.cliente), str(order.unidade or ''), str(order.equipamento), str(order.tecnico or ''), order.get_tipo_atendimento_display(), order.get_status_display(), order.abertura.date(), order.conclusao.date() if order.conclusao else ''] for order in orders]
    if key in ['preventivas_previstas', 'preventivas_executadas']:
        plans = filter_query(m.PreventivaProgramada.objects.filter(cancelada=False, plano__ativo=True).select_related('plano', 'equipamento', 'ordem'), data, {'cliente': 'plano__cliente', 'unidade': 'equipamento__unidade', 'tecnico': 'plano__tecnico', 'equipamento': 'equipamento', 'contrato': 'plano__contrato'}, 'data')
        visits = filter_query(g.AgendaPreventiva.objects.filter(cancelada=False).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO']).select_related('contrato', 'equipamento', 'ordem'), data, {'cliente': 'contrato__cliente', 'unidade': 'equipamento__unidade', 'tecnico': 'tecnico', 'equipamento': 'equipamento', 'contrato': 'contrato'}, 'data_prevista')
        if not allowed(user, 'contratos'):
            plans = plans.filter(Q(plano__tecnico__usuario=user) | Q(plano__equipe__usuario=user)).distinct()
            visits = visits.filter(tecnico__usuario=user)
        rows = []
        for queryset, source, field in [(plans, 'Plano preventivo', 'data'), (visits, 'Contrato', 'data_prevista')]:
            for item in queryset:
                if key == 'preventivas_executadas' and item.situacao != 'CONCLUIDA':
                    continue
                if data.get('status') and item.situacao != data['status']:
                    continue
                if data.get('tipo_atendimento') and (item.ordem.tipo_atendimento if item.ordem_id else item.plano.tipo_manutencao or 'PREVENTIVA' if source == 'Plano preventivo' else 'PREVENTIVA') != data['tipo_atendimento']:
                    continue
                rows.append([source, str(item.equipamento), getattr(item, field), item.situacao, item.ordem.numero if item.ordem_id else ''])
        return ['Origem', 'Equipamento', 'Previsão', 'Situação', 'OS'], rows
    if key == 'estoque_critico':
        from .stock import metrics
        rows = []
        for part in g.Peca.objects.filter(ativo=True):
            item = metrics(part)
            if item['disponivel'] <= item['minimo'] or item['sugerido']:
                rows.append([part.sku, part.descricao, item['fisico'], item['reservado'], item['disponivel'], item['minimo'], item['em_compra'], item['sugerido']])
        return ['SKU', 'Produto', 'Físico', 'Reservado', 'Disponível', 'Mínimo', 'Pendente de compra', 'Sugestão'], rows
    if key == 'compras_pendentes':
        purchases = date_filter(m.Compra.objects.filter(status__in=['APROVADA', 'PEDIDO']).select_related('fornecedor', 'deposito'), data, 'criado_em__date')
        if data.get('status'):
            purchases = purchases.filter(status=data['status'])
        return ['Compra', 'Fornecedor', 'Status', 'Previsão', 'Produto', 'Pedido', 'Recebido', 'Pendente'], [[str(purchase), str(purchase.fornecedor or ''), purchase.get_status_display(), purchase.previsao_recebimento or '', str(item.peca), item.quantidade, item.quantidade_recebida, item.quantidade_pendente] for purchase in purchases for item in purchase.itens.select_related('peca', 'compra') if item.quantidade_pendente]
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
    if key=='movimentacao_bancaria':
        qs=date_filter(m.MovimentoCaixa.objects.select_related('conta','conta_contraparte','categoria','centro_custo','usuario','lancamento'),data,'data')
        return ['Data','Conta','Contraparte','Tipo','Descrição','Origem','Categoria','Centro de custo','Documento','Usuário','Valor'], [[row.data,str(row.conta),str(row.conta_contraparte or ''),row.get_tipo_display(),row.descricao,row.get_origem_display(),str(row.categoria or (row.lancamento.categoria if row.lancamento_id else '')),str(row.centro_custo or (row.lancamento.centro_custo if row.lancamento_id else '')),row.documento_ref or (row.lancamento_id or ''),str(row.usuario),row.valor] for row in qs]
    if key=='recebimentos':
        qs=filter_query(m.Pagamento.objects.select_related('lancamento','conta'),data,{'cliente':'lancamento__cliente'},'data')
        return ['Conta','Tipo','Data','Valor','Banco / controle','Usuário'], [[row.lancamento.descricao,row.lancamento.get_tipo_display(),row.data,row.valor,row.controle_caixa,str(row.usuario)] for row in qs]
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
        qs=filter_query(m.Venda.objects.select_related('cliente').prefetch_related('itens','devolucoes__itens__movimento'),data,{'cliente':'cliente'},'criado_em__date')
        if data.get('status'):
            qs=qs.filter(status=data['status'])
        rows=[]
        for sale in qs:
            gross=Decimal(sale.snapshot['total']) if sale.snapshot else sale.total
            cost=sum((item.custo_total if item.custo_total is not None else item.quantidade*item.custo_unitario for item in sale.itens.all()),g.ZERO)
            returned=sum((row.valor for row in sale.devolucoes.all()),g.ZERO)
            restored=sum((item.movimento.valor_custo for row in sale.devolucoes.all() for item in row.itens.all()),g.ZERO)
            rows.append([str(sale),str(sale.cliente or 'Consumidor não identificado'),sale.status,gross-returned,gross-returned-cost+restored])
        return ['Venda','Cliente','Estado','Total líquido','Margem registrada / estimada no rascunho'],rows
    qs=date_filter(m.Compra.objects.select_related('fornecedor'),data,'criado_em__date')
    return ['Compra','Fornecedor','Estado','Total','Conta a pagar'], [[str(row),str(row.fornecedor or ''),row.status,row.total,row.conta_id or ''] for row in qs]
