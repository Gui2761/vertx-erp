"""Tenant-safe transactional services for municipal property, stores and fleet.

This phase is operational foundation only. It deliberately does not create
public-accounting entries or infer legal depreciation/consumption rules.
"""
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from platform_core.context import current_organization

from . import phase_d_models as m
from .public_services import audit_public, require_municipal_permission, scoped_queryset


MODULES = {
    'patrimonio': 'patrimonio',
    'almoxarifado': 'almoxarifado',
    'frotas': 'frotas',
}


def _org():
    org = current_organization()
    if not org:
        raise PermissionDenied('Selecione uma Prefeitura para continuar.')
    return org


def _audit(actor, model, *, action, before=None, after=None, reason=''):
    event_model, user_field, time_field = {
        m.BemPatrimonial: (m.EventoPatrimonioMunicipal, 'bem', 'ocorrido_em'),
        m.DepositoAlmoxarifadoMunicipal: (m.EventoAlmoxarifadoMunicipal, None, 'criado_em'),
        m.ItemAlmoxarifadoMunicipal: (m.EventoAlmoxarifadoMunicipal, None, 'criado_em'),
        m.VeiculoMunicipal: (m.EventoFrotaMunicipal, 'veiculo', 'ocorrido_em'),
    }.get(type(model))
    if not event_model:
        return
    values = {
        'organization': _org(), 'acao': action, 'antes': before or {},
        'depois': after or {}, 'usuario': actor, 'motivo': reason,
    }
    if user_field:
        values[user_field] = model
    else:
        values.update(entidade=model._meta.model_name, entidade_id=model.pk)
    event = event_model(**values)
    event._service_write = True
    event.save()
    audit_public(actor, action, model, {'antes': before or {}, 'depois': after or {}, 'motivo': reason})


def _require(actor, capability, module, record=None):
    require_municipal_permission(actor, capability, module=module, record=record)
    return _org()


@transaction.atomic
def create_asset(actor, *, data):
    org = _require(actor, 'patrimonio.manage', MODULES['patrimonio'])
    row = m.BemPatrimonial(organization=org, criado_por=actor, **data)
    row.save()
    _audit(actor, row, action='BEM_TOMBADO', after={'tombamento': row.tombamento, 'situacao': row.situacao})
    return row


@transaction.atomic
def create_deposit(actor, *, data):
    org = _require(actor, 'almoxarifado.manage', MODULES['almoxarifado'])
    row = m.DepositoAlmoxarifadoMunicipal(organization=org, criado_por=actor, **data)
    row.save()
    _audit(actor, row, action='DEPOSITO_ALMOXARIFADO_CRIADO', after={'codigo': row.codigo, 'nome': row.nome})
    return row


@transaction.atomic
def create_stock_item(actor, *, data):
    org = _require(actor, 'almoxarifado.manage', MODULES['almoxarifado'])
    row = m.ItemAlmoxarifadoMunicipal(organization=org, **data)
    row.save()
    _audit(actor, row, action='ITEM_ALMOXARIFADO_CRIADO', after={'codigo': row.codigo, 'nome': row.nome})
    return row


@transaction.atomic
def create_vehicle(actor, *, data):
    org = _require(actor, 'frotas.manage', MODULES['frotas'])
    row = m.VeiculoMunicipal(organization=org, **data)
    row.save()
    _audit(actor, row, action='VEICULO_CADASTRADO', after={'placa': row.placa, 'situacao': row.situacao})
    return row


@transaction.atomic
def move_asset(actor, asset_id, *, data):
    org = _require(actor, 'patrimonio.transfer', MODULES['patrimonio'])
    row = scoped_queryset(actor, m.BemPatrimonial.objects.select_for_update()).filter(organization=org).get(pk=asset_id)
    if row.situacao == m.BemPatrimonial.Situacao.BAIXADO:
        raise ValidationError('Bem baixado não pode receber nova movimentação.')
    before = {key: getattr(row, f'{key}_id', None) for key in ('secretaria', 'departamento', 'setor', 'unidade', 'responsavel')}
    before.update({'situacao': row.situacao, 'localizacao': row.localizacao})
    movement = m.MovimentacaoPatrimonial(
        organization=org, bem=row, tipo=data['tipo'], origem=before,
        responsavel_anterior=row.responsavel, responsavel_novo=data.get('responsavel_novo'),
        usuario=actor, motivo=data['motivo'], documento_key=data.get('documento_key', ''),
        observacao=data.get('observacao', ''),
    )
    movement._service_write = True
    # Apply only explicitly supplied destination fields; model clean validates
    # hierarchy and tenant membership before the immutable movement is stored.
    for key in ('secretaria', 'departamento', 'setor', 'unidade', 'localizacao'):
        if key in data:
            setattr(row, key, data[key])
    if 'responsavel_novo' in data:
        row.responsavel = data['responsavel_novo']
    if data['tipo'] == m.MovimentacaoPatrimonial.Tipo.CESSAO:
        row.situacao = m.BemPatrimonial.Situacao.CEDIDO
    elif data['tipo'] == m.MovimentacaoPatrimonial.Tipo.MANUTENCAO:
        row.situacao = m.BemPatrimonial.Situacao.MANUTENCAO
    elif data['tipo'] in {m.MovimentacaoPatrimonial.Tipo.DEVOLUCAO, m.MovimentacaoPatrimonial.Tipo.RECOLHIMENTO}:
        row.situacao = m.BemPatrimonial.Situacao.ATIVO
    elif data['tipo'] == m.MovimentacaoPatrimonial.Tipo.BAIXA:
        _require(actor, 'patrimonio.writeoff', MODULES['patrimonio'], row)
        row.situacao = m.BemPatrimonial.Situacao.BAIXADO
    row.full_clean()
    movement.destino = {key: getattr(row, f'{key}_id', None) for key in ('secretaria', 'departamento', 'setor', 'unidade', 'responsavel')}
    movement.destino.update({'situacao': row.situacao, 'localizacao': row.localizacao})
    movement.full_clean()
    movement.save()
    row.save()
    _audit(actor, row, action=f'BEM_{data["tipo"]}', before=before, after=movement.destino, reason=data['motivo'])
    return movement


@transaction.atomic
def start_property_inventory(actor, *, exercise, unit=None, responsible=None):
    org = _require(actor, 'patrimonio.inventory', MODULES['patrimonio'])
    if unit and unit.organization_id != org.pk:
        raise ValidationError('A unidade selecionada não pertence a esta Prefeitura.')
    inventory = m.InventarioPatrimonial(
        organization=org, exercicio=exercise, unidade=unit,
        responsavel=responsible, iniciado_por=actor,
    )
    inventory.save()
    assets = scoped_queryset(actor, m.BemPatrimonial.objects.filter(situacao__in=[
        m.BemPatrimonial.Situacao.ATIVO, m.BemPatrimonial.Situacao.CEDIDO,
        m.BemPatrimonial.Situacao.MANUTENCAO,
    ]))
    if unit:
        assets = assets.filter(unidade=unit)
    for asset in assets:
        m.ItemInventarioPatrimonial(organization=org, inventario=inventory, bem=asset,
                                    tombamento_informado=asset.tombamento).save()
    audit_public(actor, 'INVENTARIO_PATRIMONIAL_INICIADO', inventory, {'exercicio': exercise, 'unidade': unit.pk if unit else None})
    return inventory


@transaction.atomic
def count_property_item(actor, item_id, *, data):
    org = _require(actor, 'patrimonio.inventory', MODULES['patrimonio'])
    row = scoped_queryset(actor, m.ItemInventarioPatrimonial.objects.select_for_update()).filter(organization=org).get(pk=item_id)
    if row.inventario.status == m.InventarioPatrimonial.Status.ENCERRADO:
        raise ValidationError('O inventário já está encerrado.')
    row.encontrado = data['encontrado']
    row.resultado = m.ItemInventarioPatrimonial.Resultado.ENCONTRADO if row.encontrado else m.ItemInventarioPatrimonial.Resultado.NAO_ENCONTRADO
    row.tombamento_informado = data.get('tombamento_informado', row.tombamento_informado)
    row.localizacao_informada = data.get('localizacao_informada', '')
    row.conservacao_informada = data.get('conservacao_informada', '')
    row.fotografia_key = data.get('fotografia_key', '')
    row.observacao = data.get('observacao', '')
    row.conferido_por, row.conferido_em = actor, timezone.now()
    row.save()
    audit_public(actor, 'ITEM_INVENTARIO_PATRIMONIAL_CONFERIDO', row, {'resultado': row.resultado})
    return row


@transaction.atomic
def close_property_inventory(actor, inventory_id):
    org = _require(actor, 'patrimonio.inventory', MODULES['patrimonio'])
    row = scoped_queryset(actor, m.InventarioPatrimonial.objects.select_for_update()).filter(organization=org).get(pk=inventory_id)
    if row.status == m.InventarioPatrimonial.Status.ENCERRADO:
        raise ValidationError('O inventário já está encerrado.')
    pending = row.itens.filter(resultado=m.ItemInventarioPatrimonial.Resultado.PENDENTE).exists()
    if pending:
        raise ValidationError('Conclua a conferência dos bens antes de encerrar o inventário.')
    row.status, row.encerrado_em = m.InventarioPatrimonial.Status.ENCERRADO, timezone.now()
    row.save(update_fields=['status', 'encerrado_em', 'atualizado_em'])
    audit_public(actor, 'INVENTARIO_PATRIMONIAL_ENCERRADO', row, {'itens': row.itens.count()})
    return row


def _stock_balance(actor, deposit_id, item_id, *, lock=False):
    org = _org()
    deposits = scoped_queryset(actor, m.DepositoAlmoxarifadoMunicipal.objects.filter(organization=org, ativo=True))
    items = scoped_queryset(actor, m.ItemAlmoxarifadoMunicipal.objects.filter(organization=org, ativo=True))
    deposit = deposits.get(pk=deposit_id)
    item = items.get(pk=item_id)
    qs = m.SaldoAlmoxarifadoMunicipal.objects
    if lock:
        qs = qs.select_for_update()
    balance, _ = qs.get_or_create(organization=org, deposito=deposit, item=item, defaults={'quantidade': Decimal('0')})
    return deposit, item, (qs.get(pk=balance.pk) if lock else balance)


@transaction.atomic
def receive_stock(actor, *, deposit_id, item_id, quantity, reason, supplier=None, invoice='', lot_code='', expiry=None, process=None, contract=None):
    org = _require(actor, 'almoxarifado.manage', MODULES['almoxarifado'])
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError('A quantidade recebida deve ser maior que zero.')
    deposit, item, balance = _stock_balance(actor, deposit_id, item_id, lock=True)
    if supplier and getattr(supplier, 'organization_id', None) not in (None, org.pk):
        raise ValidationError('Fornecedor pertence a outra Prefeitura.')
    receipt = m.RecebimentoAlmoxarifadoMunicipal(
        organization=org, deposito=deposit, fornecedor=supplier, nota_fiscal=invoice,
        processo=process, contrato=contract, usuario=actor, observacao=reason,
    )
    receipt._service_write = True
    receipt.save()
    lote = None
    if lot_code:
        lote = m.LoteAlmoxarifadoMunicipal.objects.filter(
            organization=org, deposito=deposit, item=item, codigo=lot_code,
        ).first()
        if lote:
            lote.quantidade += quantity
            if expiry:
                lote.validade = expiry
            lote.save()
        else:
            lote = m.LoteAlmoxarifadoMunicipal(organization=org, deposito=deposit, item=item,
                codigo=lot_code, validade=expiry, quantidade=quantity)
            lote.save()
    balance.quantidade += quantity
    balance.save()
    movement = m.MovimentoAlmoxarifadoMunicipal(
        organization=org, item=item, deposito=deposit, lote=lote, recebimento=receipt,
        tipo=m.MovimentoAlmoxarifadoMunicipal.Tipo.ENTRADA, quantidade=quantity,
        saldo_apos=balance.quantidade, motivo=reason, usuario=actor,
    )
    movement._service_write = True
    movement.save()
    audit_public(actor, 'ALMOXARIFADO_ENTRADA', receipt, {'item': item.pk, 'quantidade': str(quantity), 'saldo': str(balance.quantidade)})
    return movement


@transaction.atomic
def transfer_stock(actor, *, source_id, target_id, item_id, quantity, reason, lot_id=None):
    org = _require(actor, 'almoxarifado.transfer', MODULES['almoxarifado'])
    quantity = Decimal(quantity)
    if source_id == target_id or quantity <= 0:
        raise ValidationError('Selecione depósitos diferentes e uma quantidade positiva.')
    source, item, source_balance = _stock_balance(actor, source_id, item_id, lock=True)
    target, _, target_balance = _stock_balance(actor, target_id, item_id, lock=True)
    if source_balance.quantidade < quantity:
        raise ValidationError('Saldo insuficiente; a operação não pode gerar estoque negativo.')
    transfer_id = uuid4()
    source_balance.quantidade -= quantity
    target_balance.quantidade += quantity
    source_balance.save(); target_balance.save()
    for deposit, balance, kind in (
        (source, source_balance, m.MovimentoAlmoxarifadoMunicipal.Tipo.TRANSFERENCIA_SAIDA),
        (target, target_balance, m.MovimentoAlmoxarifadoMunicipal.Tipo.TRANSFERENCIA_ENTRADA),
    ):
        movement = m.MovimentoAlmoxarifadoMunicipal(
            organization=org, item=item, deposito=deposit, transferencia_id=transfer_id,
            tipo=kind, quantidade=quantity, saldo_apos=balance.quantidade,
            motivo=reason, usuario=actor,
        )
        movement._service_write = True; movement.save()
    audit_public(actor, 'ALMOXARIFADO_TRANSFERENCIA', item, {'origem': source.pk, 'destino': target.pk, 'quantidade': str(quantity), 'transferencia': str(transfer_id)})
    return transfer_id


@transaction.atomic
def adjust_stock(actor, *, deposit_id, item_id, counted_quantity, reason):
    org = _require(actor, 'almoxarifado.inventory', MODULES['almoxarifado'])
    if not reason.strip():
        raise ValidationError('Informe a justificativa do ajuste de inventário.')
    _, item, balance = _stock_balance(actor, deposit_id, item_id, lock=True)
    counted = Decimal(counted_quantity)
    if counted < 0:
        raise ValidationError('A contagem não pode ser negativa.')
    delta = counted - balance.quantidade
    if delta < 0:
        # Adjustment represents a count approved by the dedicated inventory capability.
        _require(actor, 'almoxarifado.inventory', MODULES['almoxarifado'])
    balance.quantidade = counted; balance.save()
    if delta == 0:
        audit_public(actor, 'ALMOXARIFADO_INVENTARIO_SEM_DIVERGENCIA', balance, {'saldo': str(counted), 'motivo': reason})
        return None
    movement = m.MovimentoAlmoxarifadoMunicipal(
        organization=org, item=item, deposito=balance.deposito,
        tipo=m.MovimentoAlmoxarifadoMunicipal.Tipo.AJUSTE,
        quantidade=abs(delta) or Decimal('0.0001'), saldo_apos=counted,
        motivo=reason, usuario=actor,
    )
    movement._service_write = True; movement.save()
    audit_public(actor, 'ALMOXARIFADO_AJUSTE_INVENTARIO', movement, {'delta': str(delta), 'saldo': str(counted), 'motivo': reason})
    return movement


@transaction.atomic
def create_material_request(actor, *, unit, items, priority, reason):
    org = _require(actor, 'almoxarifado.request', MODULES['almoxarifado'])
    if unit.organization_id != org.pk:
        raise ValidationError('Unidade pertence a outra Prefeitura.')
    request = m.SolicitacaoMaterialMunicipal(organization=org, unidade=unit,
        solicitante=actor, prioridade=priority, justificativa=reason)
    request.save()
    for item, quantity in items:
        if item.organization_id != org.pk or not item.ativo:
            raise ValidationError('Um item está inativo ou pertence a outra Prefeitura.')
        m.ItemSolicitacaoMaterialMunicipal(organization=org, solicitacao=request,
            item=item, quantidade_solicitada=Decimal(quantity)).save()
    _request_history(actor, request, 'CRIADA', after={'status': request.status})
    return request


def _request_history(actor, request, action, *, before=None, after=None, reason=''):
    row = m.RequisicaoMaterialAuditada(organization=_org(), solicitacao=request,
        acao=action, antes=before or {}, depois=after or {}, usuario=actor, motivo=reason)
    row._service_write = True; row.save()
    audit_public(actor, f'REQUISICAO_MATERIAL_{action}', request, {'antes': before or {}, 'depois': after or {}, 'motivo': reason})
    return row


@transaction.atomic
def decide_material_request(actor, request_id, *, approve, reason):
    org = _require(actor, 'almoxarifado.approve', MODULES['almoxarifado'])
    row = scoped_queryset(actor, m.SolicitacaoMaterialMunicipal.objects.select_for_update()).filter(organization=org).get(pk=request_id)
    if row.status != m.SolicitacaoMaterialMunicipal.Status.PENDENTE:
        raise ValidationError('Somente requisições pendentes podem ser decididas.')
    if not reason.strip():
        raise ValidationError('Informe a justificativa da decisão.')
    old = row.status
    row.status = m.SolicitacaoMaterialMunicipal.Status.APROVADA if approve else m.SolicitacaoMaterialMunicipal.Status.REJEITADA
    row.aprovada_por = actor; row.save()
    _request_history(actor, row, 'APROVADA' if approve else 'REJEITADA', before={'status': old}, after={'status': row.status}, reason=reason)
    return row


@transaction.atomic
def issue_material_request(actor, request_id, *, deposit_id, quantities, deliver=False):
    org = _require(actor, 'almoxarifado.issue', MODULES['almoxarifado'])
    row = scoped_queryset(actor, m.SolicitacaoMaterialMunicipal.objects.select_for_update()).filter(organization=org).get(pk=request_id)
    if row.status not in {m.SolicitacaoMaterialMunicipal.Status.APROVADA, m.SolicitacaoMaterialMunicipal.Status.SEPARACAO}:
        raise ValidationError('A requisição precisa estar aprovada para separação/entrega.')
    items = list(row.itens.select_for_update().select_related('item'))
    planned = []
    for request_item in items:
        qty = Decimal(quantities.get(str(request_item.pk), request_item.quantidade_solicitada))
        if qty <= 0 or qty > request_item.quantidade_solicitada:
            raise ValidationError('Quantidade separada inválida.')
        deposit, item, balance = _stock_balance(actor, deposit_id, request_item.item_id, lock=True)
        if deliver and balance.quantidade < qty:
            raise ValidationError(f'Saldo insuficiente para {item.nome}; nenhuma baixa foi feita.')
        planned.append((request_item, deposit, item, balance, qty))
    old = row.status
    row.separada_por = actor
    if deliver:
        for request_item, deposit, item, balance, qty in planned:
            balance.quantidade -= qty; balance.save()
            request_item.quantidade_separada = qty
            request_item.quantidade_entregue = qty
            request_item.save()
            movement = m.MovimentoAlmoxarifadoMunicipal(organization=org, item=item, deposito=deposit,
                solicitacao=row, tipo=m.MovimentoAlmoxarifadoMunicipal.Tipo.ENTREGA_REQUISICAO,
                quantidade=qty, saldo_apos=balance.quantidade, motivo=f'Entrega da requisição {row.pk}', usuario=actor)
            movement._service_write = True; movement.save()
        row.status = m.SolicitacaoMaterialMunicipal.Status.ENTREGUE
        row.entregue_por = actor
    else:
        for request_item, _, _, _, qty in planned:
            request_item.quantidade_separada = qty; request_item.save()
        row.status = m.SolicitacaoMaterialMunicipal.Status.SEPARACAO
    row.save()
    _request_history(actor, row, 'ENTREGUE' if deliver else 'SEPARADA', before={'status': old}, after={'status': row.status})
    return row


@transaction.atomic
def start_store_inventory(actor, *, deposit_id, exercise):
    org = _require(actor, 'almoxarifado.inventory', MODULES['almoxarifado'])
    deposits = scoped_queryset(actor, m.DepositoAlmoxarifadoMunicipal.objects.filter(organization=org, ativo=True))
    deposit = deposits.get(pk=deposit_id)
    inventory = m.InventarioAlmoxarifadoMunicipal(organization=org, deposito=deposit,
        exercicio=exercise, responsavel=actor)
    inventory.save()
    balances = m.SaldoAlmoxarifadoMunicipal.objects.filter(organization=org, deposito=deposit, item__ativo=True)
    for balance in balances:
        m.ItemInventarioAlmoxarifadoMunicipal(organization=org, inventario=inventory,
            item=balance.item, quantidade_sistema=balance.quantidade).save()
    audit_public(actor, 'INVENTARIO_ALMOXARIFADO_INICIADO', inventory, {'exercicio': exercise, 'deposito': deposit.pk})
    return inventory


@transaction.atomic
def count_store_item(actor, item_id, *, quantity, reason=''):
    org = _require(actor, 'almoxarifado.inventory', MODULES['almoxarifado'])
    row = scoped_queryset(actor, m.ItemInventarioAlmoxarifadoMunicipal.objects.select_for_update()).filter(organization=org).get(pk=item_id)
    if row.inventario.status == m.InventarioAlmoxarifadoMunicipal.Status.ENCERRADO:
        raise ValidationError('O inventário está encerrado.')
    counted = Decimal(quantity)
    if counted < 0:
        raise ValidationError('A contagem não pode ser negativa.')
    row.quantidade_contada = counted
    row.divergencia = counted - row.quantidade_sistema
    row.observacao = reason; row.conferido_por = actor; row.conferido_em = timezone.now()
    row.save()
    audit_public(actor, 'ITEM_INVENTARIO_ALMOXARIFADO_CONFERIDO', row, {'contado': str(counted), 'divergencia': str(row.divergencia)})
    return row


@transaction.atomic
def close_store_inventory(actor, inventory_id):
    org = _require(actor, 'almoxarifado.inventory', MODULES['almoxarifado'])
    inv = scoped_queryset(actor, m.InventarioAlmoxarifadoMunicipal.objects.select_for_update()).filter(organization=org).get(pk=inventory_id)
    if inv.status == m.InventarioAlmoxarifadoMunicipal.Status.ENCERRADO:
        raise ValidationError('O inventário já está encerrado.')
    items = list(inv.itens.select_for_update().select_related('item'))
    if any(item.quantidade_contada is None for item in items):
        raise ValidationError('Conclua todas as contagens antes de encerrar.')
    # Apply all approved counts atomically; the balance check constraint remains
    # a final guard against negative balances.
    for item in items:
        adjust_stock(actor, deposit_id=inv.deposito_id, item_id=item.item_id,
                     counted_quantity=item.quantidade_contada,
                     reason=f'Inventário {inv.exercicio}: {item.observacao or "contagem conferida"}')
    inv.status, inv.encerrado_em = m.InventarioAlmoxarifadoMunicipal.Status.ENCERRADO, timezone.now()
    inv.save(update_fields=['status', 'encerrado_em'])
    audit_public(actor, 'INVENTARIO_ALMOXARIFADO_ENCERRADO', inv, {'itens': len(items)})
    return inv


@transaction.atomic
def start_trip(actor, *, vehicle_id, driver_id, data):
    org = _require(actor, 'frotas.dispatch', MODULES['frotas'])
    vehicles = scoped_queryset(actor, m.VeiculoMunicipal.objects.select_for_update().filter(organization=org))
    vehicle = vehicles.get(pk=vehicle_id)
    driver = scoped_queryset(actor, m.CondutorMunicipal.objects.select_related('servidor').filter(organization=org)).get(pk=driver_id)
    require_municipal_permission(actor, 'frotas.dispatch', module='frotas', record=driver)
    if vehicle.situacao != m.VeiculoMunicipal.Situacao.DISPONIVEL:
        raise ValidationError('O veículo não está disponível para nova viagem.')
    if not driver.autorizado or driver.situacao != 'ATIVO' or driver.validade < timezone.localdate():
        raise ValidationError('Condutor sem autorização válida ou com CNH vencida.')
    km = int(data['quilometragem_inicial'])
    if km < vehicle.quilometragem_atual:
        raise ValidationError('A quilometragem inicial não pode ser inferior ao odômetro atual.')
    trip = m.ViagemMunicipal(organization=org, veiculo=vehicle, condutor=driver,
        origem=data['origem'], destino=data['destino'], finalidade=data['finalidade'],
        quilometragem_inicial=km, passageiros=data.get('passageiros', 0),
        observacoes=data.get('observacoes', ''), iniciado_por=actor)
    trip.save()
    before = {'situacao': vehicle.situacao, 'quilometragem': vehicle.quilometragem_atual}
    vehicle.situacao = m.VeiculoMunicipal.Situacao.EM_USO; vehicle.quilometragem_atual = km
    vehicle.save(update_fields=['situacao', 'quilometragem_atual'])
    _audit(actor, vehicle, action='VIAGEM_INICIADA', before=before, after={'viagem': trip.pk, 'km_inicial': km})
    return trip


@transaction.atomic
def return_trip(actor, trip_id, *, final_km, note=''):
    org = _require(actor, 'frotas.dispatch', MODULES['frotas'])
    trip = scoped_queryset(actor, m.ViagemMunicipal.objects.select_for_update().select_related('veiculo')).filter(organization=org).get(pk=trip_id)
    vehicle = m.VeiculoMunicipal.objects.select_for_update().get(pk=trip.veiculo_id, organization=org)
    if trip.status != m.ViagemMunicipal.Status.EM_USO:
        raise ValidationError('A viagem não está em andamento.')
    final_km = int(final_km)
    if final_km < trip.quilometragem_inicial or final_km < vehicle.quilometragem_atual:
        raise ValidationError('A quilometragem final deve ser igual ou superior ao odômetro atual.')
    trip.quilometragem_final, trip.retorno_em = final_km, timezone.now()
    trip.status, trip.encerrado_por = m.ViagemMunicipal.Status.CONCLUIDA, actor
    trip.observacoes = f'{trip.observacoes}\n{note}'.strip()
    trip.save()
    vehicle.quilometragem_atual = final_km
    if vehicle.situacao == m.VeiculoMunicipal.Situacao.EM_USO:
        vehicle.situacao = m.VeiculoMunicipal.Situacao.DISPONIVEL
    vehicle.save(update_fields=['quilometragem_atual', 'situacao'])
    _audit(actor, vehicle, action='VIAGEM_CONCLUIDA', before={'km': trip.quilometragem_inicial}, after={'km': final_km, 'percorridos': trip.km_percorridos}, reason=note)
    return trip


@transaction.atomic
def record_fueling(actor, *, vehicle_id, data):
    org = _require(actor, 'frotas.fuel', MODULES['frotas'])
    vehicle = scoped_queryset(actor, m.VeiculoMunicipal.objects.select_for_update().filter(organization=org)).get(pk=vehicle_id)
    km = int(data['quilometragem'])
    if km < vehicle.quilometragem_atual:
        raise ValidationError('A quilometragem informada é inferior ao odômetro registrado.')
    liters = Decimal(data['quantidade_litros'])
    price = Decimal(data['valor_unitario'])
    if liters <= 0 or price < 0:
        raise ValidationError('Informe quantidade positiva e valor unitário válido.')
    prior_full = m.AbastecimentoMunicipal.objects.filter(organization=org, veiculo=vehicle, tanque_completo=True).order_by('-quilometragem').first()
    avg = None
    if data.get('tanque_completo') and prior_full and km > prior_full.quilometragem:
        intervening_liters = m.AbastecimentoMunicipal.objects.filter(
            organization=org, veiculo=vehicle,
            quilometragem__gt=prior_full.quilometragem, quilometragem__lte=km,
        ).aggregate(total=__import__('django.db.models', fromlist=['Sum']).Sum('quantidade_litros'))['total'] or Decimal('0')
        intervening_liters += liters
        avg = ((Decimal(km - prior_full.quilometragem) / intervening_liters).quantize(Decimal('0.0001'))
               if intervening_liters else None)
    anomaly = False
    threshold = vehicle.limite_variacao_consumo_alerta
    if avg and threshold is not None:
        prior_avg = []
        full_rows = list(m.AbastecimentoMunicipal.objects.filter(organization=org, veiculo=vehicle, tanque_completo=True).order_by('-quilometragem')[:5])
        for current, previous in zip(full_rows, full_rows[1:]):
            quantity = m.AbastecimentoMunicipal.objects.filter(organization=org, veiculo=vehicle, quilometragem__gt=previous.quilometragem, quilometragem__lte=current.quilometragem).aggregate(total=__import__('django.db.models', fromlist=['Sum']).Sum('quantidade_litros'))['total'] or Decimal('0')
            if quantity and current.quilometragem > previous.quilometragem:
                prior_avg.append(Decimal(current.quilometragem - previous.quilometragem) / quantity)
        if prior_avg:
            baseline = sum(prior_avg, Decimal('0')) / len(prior_avg)
            anomaly = abs(avg - baseline) / baseline * 100 > threshold if baseline else False
    row = m.AbastecimentoMunicipal(
        organization=org, veiculo=vehicle, combustivel=data['combustivel'],
        quantidade_litros=liters, tanque_completo=bool(data.get('tanque_completo')),
        valor_unitario=price, quilometragem=km, posto=data.get('posto', ''),
        documento=data.get('documento', ''), responsavel=actor,
        fornecedor=data.get('fornecedor'), media_km_l=avg, alerta_consumo_anomalo=anomaly,
    )
    row.save()
    vehicle.quilometragem_atual = km
    vehicle.save(update_fields=['quilometragem_atual'])
    _audit(actor, vehicle, action='ABASTECIMENTO_REGISTRADO', after={'abastecimento': row.pk, 'valor_total': str(row.valor_total), 'media_km_l': str(avg) if avg else None, 'alerta': anomaly})
    return row


@transaction.atomic
def set_maintenance_status(actor, maintenance_id, *, status, data=None):
    org = _require(actor, 'frotas.maintenance', MODULES['frotas'])
    row = scoped_queryset(actor, m.ManutencaoVeiculoMunicipal.objects.select_for_update()).filter(organization=org).get(pk=maintenance_id)
    allowed = {
        m.ManutencaoVeiculoMunicipal.Status.ABERTA: {m.ManutencaoVeiculoMunicipal.Status.EM_ANDAMENTO, m.ManutencaoVeiculoMunicipal.Status.CANCELADA},
        m.ManutencaoVeiculoMunicipal.Status.EM_ANDAMENTO: {m.ManutencaoVeiculoMunicipal.Status.CONCLUIDA, m.ManutencaoVeiculoMunicipal.Status.CANCELADA},
    }
    if status not in allowed.get(row.status, set()):
        raise ValidationError('Transição de manutenção incompatível com o estado atual.')
    before = row.status; row.status = status
    data = data or {}
    if status == m.ManutencaoVeiculoMunicipal.Status.CONCLUIDA:
        row.concluida_em = data.get('concluida_em') or timezone.localdate()
    row.save()
    vehicle = m.VeiculoMunicipal.objects.select_for_update().get(pk=row.veiculo_id, organization=org)
    if status == m.ManutencaoVeiculoMunicipal.Status.ABERTA:
        vehicle.situacao = m.VeiculoMunicipal.Situacao.MANUTENCAO
    elif status == m.ManutencaoVeiculoMunicipal.Status.CONCLUIDA and vehicle.situacao == m.VeiculoMunicipal.Situacao.MANUTENCAO:
        vehicle.situacao = m.VeiculoMunicipal.Situacao.DISPONIVEL
    vehicle.save(update_fields=['situacao'])
    _audit(actor, vehicle, action='MANUTENCAO_FROTA_ATUALIZADA', before={'status': before}, after={'status': status, 'veiculo_situacao': vehicle.situacao})
    audit_public(actor, 'MANUTENCAO_FROTA_ATUALIZADA', row, {'antes': before, 'depois': status})
    return row
