"""Visão executiva somente com dados existentes e permissões do ERP."""
from decimal import Decimal
from urllib.parse import urlencode
from django import forms
from django.db.models import Sum
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from gestao import models as g
from gestao.permissions import allowed
from . import models as m
from .reporting import financial_dashboard
from .stock import metrics

class PeriodForm(forms.Form):
    periodo=forms.ChoiceField(required=False,choices=[('HOJE','Hoje'),('SEMANA','Esta semana'),('MES','Este mês'),('PERSONALIZADO','Personalizado')])
    inicio=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date','class':'form-control'},format='%Y-%m-%d'))
    fim=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date','class':'form-control'},format='%Y-%m-%d'))
    grafico=forms.ChoiceField(required=False,choices=[('7','7 dias'),('30','30 dias'),('3M','3 meses'),('6M','6 meses'),('12M','12 meses')])
    def clean(self):
        data=super().clean()
        if data.get('periodo')=='PERSONALIZADO' and (not data.get('inicio') or not data.get('fim')):
            raise forms.ValidationError('Informe início e fim do período personalizado.')
        if data.get('inicio') and data.get('fim') and (data['fim'] < data['inicio'] or (data['fim']-data['inicio']).days>366):
            raise forms.ValidationError('Período deve ter até 366 dias e fim posterior ao início.')
        return data

def dates(form):
    today=timezone.localdate()
    mode=form.cleaned_data.get('periodo') or 'MES'
    if mode=='HOJE':
        return today,today
    if mode=='SEMANA':
        return today-timezone.timedelta(days=today.weekday()),today
    if mode=='PERSONALIZADO':
        return form.cleaned_data['inicio'],form.cleaned_data['fim']
    return today.replace(day=1),today

def link_ledger(kind, **filters):
    return '/financeiro/lancamentos/?'+urlencode({'tipo':kind,**filters})

def charts(start,end,interval):
    # Mesmo conceito de realizado do financeiro: pagamentos + liquidações legadas
    # sem pagamentos; nenhuma duplicação de contas parcialmente recebidas.
    periods=[]
    monthly=interval.endswith('M')
    date=start.replace(day=1) if monthly else start
    while date<=end:
        until=min(end,date+relativedelta(months=1)-timezone.timedelta(days=1)) if monthly else date
        periods.append({'inicio':max(date,start),'fim':until,'label':date.strftime('%m/%Y' if monthly else '%d/%m'),'entrada':g.ZERO,'saida':g.ZERO,'faturamento':g.ZERO})
        date=date+relativedelta(months=1) if monthly else date+timezone.timedelta(days=1)
    payments=m.Pagamento.objects.filter(data__range=(start,end)).select_related('lancamento')
    legacy=g.Lancamento.objects.filter(status='LIQUIDADO',pagamentos__isnull=True,data_liquidacao__range=(start,end))
    revenues=g.Lancamento.objects.filter(tipo='RECEBER',data_emissao__range=(start,end)).exclude(status='CANCELADO')
    for row in periods:
        row['entrada']=sum((p.valor for p in payments if row['inicio']<=p.data<=row['fim'] and p.lancamento.tipo=='RECEBER'),g.ZERO)+sum((p.valor for p in legacy if row['inicio']<=p.data_liquidacao<=row['fim'] and p.tipo=='RECEBER'),g.ZERO)
        row['saida']=sum((p.valor for p in payments if row['inicio']<=p.data<=row['fim'] and p.lancamento.tipo=='PAGAR'),g.ZERO)+sum((p.valor for p in legacy if row['inicio']<=p.data_liquidacao<=row['fim'] and p.tipo=='PAGAR'),g.ZERO)
        row['faturamento']=sum((p.valor for p in revenues if row['inicio']<=p.data_emissao<=row['fim']),g.ZERO)
    maximum=max([max(row['entrada'],row['saida'],row['faturamento']) for row in periods],default=1) or 1
    cash_max=max([max(row['entrada'],row['saida']) for row in periods],default=1) or 1
    revenue_max=max([row['faturamento'] for row in periods],default=1) or 1
    for index,row in enumerate(periods):
        row['x']=round(30+index*580/max(len(periods)-1,1))
        row['y_entrada']=round(175-150*row['entrada']/cash_max)
        row['y_saida']=round(175-150*row['saida']/cash_max)
        row['revenue_height']=round(150*row['faturamento']/revenue_max)
        row['revenue_y']=175-row['revenue_height']
        for key in ['entrada','saida','faturamento']:
            row[key+'_width']=round(100*row[key]/maximum)
    return periods

def context(request, form, orders):
    start,end=dates(form)
    today=timezone.localdate()
    now=timezone.localtime()
    ctx={'executive':True,'period_form':form,'period_start':start,'period_end':end,'greeting':'Bom dia' if now.hour<12 else 'Boa tarde' if now.hour<18 else 'Boa noite'}
    ctx['agenda_hoje']=orders.filter(agendada_para__date=today).select_related('cliente','unidade','equipamento').order_by('agendada_para')[:12]
    completed=orders.filter(status__in=['FINALIZADA','APROVADA','FATURADA'],conclusao__date__range=(start,end))
    ctx['assistance_completed']={'preventivas':completed.filter(tipo_atendimento='PREVENTIVA').count(),'corretivas':completed.filter(tipo_atendimento='CORRETIVA').count(),'total':completed.count()}
    ctx['executive_operations']=[('OS abertas',orders.filter(status__in=['ABERTA','AGENDADA']).count(),'/ordens/?grupo=abertas'),('OS em andamento',orders.filter(status__in=['EXECUCAO','AG_PECA','AG_CLIENTE']).count(),'/ordens/?grupo=andamento'),('OS atrasadas',orders.filter(prazo__lt=timezone.now()).exclude(status__in=m.ENCERRADAS).count(),'/ordens/?atrasadas=1'),('Preventivas pendentes',m.PreventivaProgramada.objects.filter(cancelada=False,plano__ativo=True).exclude(ordem__status__in=m.ENCERRADAS).count(),'/preventivas/'),('Orçamentos aguardando aprovação',g.Orcamento.objects.filter(status='ENVIADO',validade__gte=today).count(),'/orcamentos/?status=ENVIADO')]
    stock=[metrics(part) for part in g.Peca.objects.filter(ativo=True).select_related('fornecedor','categoria')]
    ctx['stock_summary']={'baixo':sum(row['disponivel']>0 and row['disponivel']<=row['minimo'] for row in stock),'zerados':sum(row['disponivel']==0 for row in stock),'vencendo':m.LoteEstoque.objects.filter(quantidade__gt=0,validade__range=(today,today+timezone.timedelta(days=90))).count(),'vencidos':m.LoteEstoque.objects.filter(quantidade__gt=0,validade__lt=today).values('peca_id').distinct().count(),'repor':sum(row['disponivel']<=row['minimo'] for row in stock)}
    ctx['executive_operations'].append(('Estoque baixo',ctx['stock_summary']['repor'],'/estoque/ocorrencias/?tipo=REPOSICAO'))
    latest=m.RelatorioEstoque.objects.filter(automatico=True).first() or m.RelatorioEstoque.objects.first()
    ctx['weekly_report']=latest
    if latest:
        items=list(latest.itens.all())
        ctx['purchase_count']=sum(Decimal(row.dados['sugerido'])>0 for row in items)
        ctx['purchase_value']=sum((Decimal(row.dados['valor_estimado']) for row in items),g.ZERO)
    contracts=g.Contrato.objects.exclude(status__in=['SUSPENSO','ENCERRADO']).filter(data_inicial__lte=today,data_final__gte=today)
    ctx['contract_count']=contracts.count()
    frequencies={'MENSAL':1,'TRIMESTRAL':3,'SEMESTRAL':6,'ANUAL':12}
    ctx['contract_monthly']=sum((row.valor/frequencies[row.periodicidade_cobranca] for row in contracts if row.periodicidade_cobranca in frequencies),g.ZERO)
    ctx['contract_expiring']=contracts.filter(data_final__lte=today+timezone.timedelta(days=30)).count()
    ctx['contract_adjustments_unset']=True  # Regra textual não é data de reajuste.
    quotes=g.Orcamento.objects.filter(data__range=(start,end))
    open_quotes=quotes.filter(status__in=['RASCUNHO','ENVIADO'])
    approved=quotes.filter(status__in=['APROVADO','CONVERTIDO'])
    confirmed=list(m.Venda.objects.filter(status='CONFIRMADA',criado_em__date__range=(start,end)).prefetch_related('itens'))
    sales_value=sum((sale.total for sale in confirmed),g.ZERO)
    ctx['commercial']={'abertos':open_quotes.count(),'aprovados':approved.count(),'vendas':len(confirmed),'valor':sales_value,'ticket':sales_value/len(confirmed) if confirmed else g.ZERO,'conversao':round(100*approved.count()/quotes.count(),1) if quotes.exists() else 0,'base':quotes.count()}
    if allowed(request.user,'financeiro'):
        ledger=g.Lancamento.objects.filter(status__in=['PENDENTE','VENCIDO'])
        due=lambda kind:sum((row.saldo for row in ledger.filter(tipo=kind,vencimento=today)),g.ZERO)
        month=financial_dashboard(today.replace(day=1),today)
        period=financial_dashboard(start,end)
        ctx['financial_cards']=[{'title':'A receber hoje','value':due('RECEBER'),'url':link_ledger('RECEBER',vencimento_inicio=today,vencimento_fim=today,status='PENDENTE')},{'title':'A pagar hoje','value':due('PAGAR'),'url':link_ledger('PAGAR',vencimento_inicio=today,vencimento_fim=today,status='PENDENTE')},{'title':'Recebimentos do mês','value':month['recebido'],'url':link_ledger('RECEBER',pagamento_inicio=today.replace(day=1),pagamento_fim=today)},{'title':'Pagamentos do mês','value':month['pago'],'url':link_ledger('PAGAR',pagamento_inicio=today.replace(day=1),pagamento_fim=today)},{'title':'Saldo realizado no período','value':period['resultado'],'url':'/financeiro/?'+urlencode({'inicio':start,'fim':end})},{'title':'Inadimplência','value':period['vencido_receber'],'url':link_ledger('RECEBER',status='VENCIDO')}]
        banks=[]
        for account in m.ContaBancaria.objects.filter(ativo=True):
            moves=account.movimentos.filter(data__range=(start,end))
            banks.append({'account':account,'balance':account.saldo,'incoming':moves.filter(tipo='ENTRADA').aggregate(value=Sum('valor'))['value'] or g.ZERO,'outgoing':moves.filter(tipo='SAIDA').aggregate(value=Sum('valor'))['value'] or g.ZERO})
        ctx['bank_rows']=banks
        ctx['bank_total']=sum((row['balance'] for row in banks),g.ZERO)
        interval=form.cleaned_data.get('grafico') or '30'
        chart_start=today.replace(day=1)-relativedelta(months=int(interval[:-1])-1) if interval.endswith('M') else today-timezone.timedelta(days=int(interval)-1)
        ctx['cash_chart']=charts(chart_start,today,interval)
        ctx['cash_in_points']=' '.join(f'{row["x"]},{row["y_entrada"]}' for row in ctx['cash_chart'])
        ctx['cash_out_points']=' '.join(f'{row["x"]},{row["y_saida"]}' for row in ctx['cash_chart'])
        month_start=today.replace(day=1)-relativedelta(months=11)
        ctx['revenue_chart']=charts(month_start,today,'12M')
        entries=g.Lancamento.objects.filter(tipo='RECEBER',data_emissao__range=(start,end)).exclude(status='CANCELADO').select_related('contrato','orcamento').prefetch_related('orcamento__itens')
        totals={'Serviços':g.ZERO,'Produtos':g.ZERO,'Contratos':g.ZERO,'Locações':g.ZERO,'Sem classificação':g.ZERO}
        sale_accounts=set(m.Venda.objects.exclude(conta=None).values_list('conta_id',flat=True))
        for entry in entries:
            category='Locações' if entry.contrato_id and 'loca' in entry.contrato.tipo.lower() else 'Contratos' if entry.contrato_id else 'Produtos' if entry.pk in sale_accounts else 'Serviços' if entry.ordem_id or entry.orcamento_id and not entry.orcamento.itens.filter(tipo='PECA').exists() else 'Sem classificação'
            totals[category]+=entry.valor
        ctx['revenue_categories']=totals.items()
    return ctx
