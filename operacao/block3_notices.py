"""Operational notices share the existing read/resolved/reopened lifecycle."""
from django.utils import timezone
from platform_core.modules import has_capability, module_enabled
from . import models as m
from .notifications import sync_notices

def scan(user):
    if module_enabled('estoque') and has_capability(user,'inventario_aprovar'):
        wanted={}
        for inventory in m.Inventario.objects.exclude(status='APROVADO').prefetch_related('itens__contagens'):
            divergent=False
            for item in inventory.itens.all():
                counted=max(item.contagens.all(),key=lambda row:row.pk,default=None)
                if counted and counted.quantidade!=item.esperado: divergent=True
            if divergent:
                wanted[f'ops-inventario:{inventory.pk}']=('Inventário com divergência',inventory.motivo,f'/inventarios/{inventory.public_id}/',None)
        sync_notices(user,'ops-inventario:',wanted,['ADMIN','GESTOR','ESTOQUE'])
    if module_enabled('pdv') and has_capability(user,'executivo'):
        wanted={f'ops-pdv:{sale.pk}':('Venda aguardando pagamento',str(sale),f'/pdv/vendas/{sale.public_id}/',None) for sale in m.Venda.objects.filter(status='AG_PAGAMENTO',public_id__isnull=False)}
        sync_notices(user,'ops-pdv:',wanted,['ADMIN','GESTOR'])
        wanted={f'ops-caixa:{row.pk}':('Diferença de caixa registrada',f'Caixa {row.conta.nome} · conferência com justificativa',f'/pdv/caixas/{row.public_id}/',None) for row in m.SessaoCaixa.objects.filter(fechado_em__isnull=False).exclude(diferenca=0).select_related('conta')}
        sync_notices(user,'ops-caixa:',wanted,['ADMIN','GESTOR','FINANCEIRO'])
    if module_enabled('ponto') and has_capability(user,'ajuste_ponto'):
        from .workforce import effective_marks
        today=timezone.localdate();wanted={}
        for employee in m.Funcionario.objects.filter(ativo=True):
            marks=effective_marks(employee)
            if marks and marks[-1]['tipo']!='SAIDA' and timezone.localdate(marks[-1]['at'])<today:
                wanted[f'ops-ponto:{employee.pk}']=('Ponto com marcação pendente',f'{employee.nome} · revisar espelho/solicitação de ajuste','/ponto/ajustes/',None)
        sync_notices(user,'ops-ponto:',wanted,['ADMIN','GESTOR','RH'])
