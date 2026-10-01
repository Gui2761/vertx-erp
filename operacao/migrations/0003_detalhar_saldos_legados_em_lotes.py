"""Detalha saldos existentes, sem reescrever produtos ou movimentos anteriores."""
import uuid
from decimal import Decimal
from django.db import migrations
from django.utils import timezone

def detalhar(apps, schema_editor):
    Peca = apps.get_model('gestao','Peca')
    Deposito = apps.get_model('operacao','Deposito')
    Saldo = apps.get_model('operacao','SaldoDeposito')
    Lote = apps.get_model('operacao','LoteEstoque')
    alias = schema_editor.connection.alias
    for part in Peca._base_manager.using(alias).filter(quantidade_atual__gt=0).iterator():
        balances = list(Saldo._base_manager.using(alias).filter(peca_id=part.pk))
        allocated = sum((row.quantidade for row in balances),Decimal('0'))
        if allocated > part.quantidade_atual:
            raise RuntimeError('Saldo de depósitos superior ao produto; regularize antes de migrar.')
        if allocated < part.quantidade_atual:
            depot, _ = Deposito._base_manager.using(alias).get_or_create(organization_id=part.organization_id,nome='Principal',defaults={'ativo':True,'endereco':''})
            balance, created = Saldo._base_manager.using(alias).get_or_create(organization_id=part.organization_id,peca_id=part.pk,deposito_id=depot.pk,defaults={'quantidade':part.quantidade_atual-allocated})
            if not created:
                # Não modificar um saldo já existente nesta migration aditiva.
                if balance.quantidade != part.quantidade_atual-allocated:
                    raise RuntimeError('Saldo legado parcialmente alocado exige revisão antes de migrar.')
            balances = list(Saldo._base_manager.using(alias).filter(peca_id=part.pk))
        for balance in balances:
            if balance.quantidade:
                group = uuid.uuid5(uuid.NAMESPACE_URL,f'vertyx-legacy:{part.organization_id}:{part.pk}:{balance.deposito_id}')
                Lote._base_manager.using(alias).get_or_create(organization_id=part.organization_id,grupo=group,deposito_id=balance.deposito_id,defaults={'peca_id':part.pk,'numero':part.lote or f'LEGADO-{part.pk}','validade':part.validade,'quantidade':balance.quantidade,'fornecedor_id':part.fornecedor_id,'custo_unitario':part.custo_aquisicao,'entrada_em':timezone.now(),'localizacao':part.localizacao,'documento_entrada':'Saldo anterior ao controle por lote','legado':True})

class Migration(migrations.Migration):
    dependencies = [('operacao','0002_compra_pedido_relatorio_id_compra_selecao_relatorio_and_more')]
    operations = [migrations.RunPython(detalhar,reverse_code=migrations.RunPython.noop)]
