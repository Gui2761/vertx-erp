from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from platform_core.context import current_organization
from . import phase_d_models as m
from . import phase_d_services as svc
from .phase_b_models import ContratoPublicoMunicipal, ProcessoContratacaoMunicipal
from .models import UnidadeMunicipal
from .phase_d_forms import (
    AbastecimentoForm, BemPatrimonialForm, CondutorMunicipalForm,
    CountPropertyForm, CountStockForm, DepositoMunicipalForm,
    DocumentoFrotaForm, EntradaAlmoxarifadoForm, ItemAlmoxarifadoForm,
    ManutencaoVeiculoForm, MovimentacaoBemForm, ReturnTripForm,
    SolicitacaoMaterialForm, TransferenciaAlmoxarifadoForm,
    VeiculoMunicipalForm, ViagemMunicipalForm,
)
from .public_services import (
    audit_public, has_municipal_permission, require_municipal_permission,
    scoped_queryset,
)


def _org():
    return current_organization()


def _run(request, callback, *, success='Operação registrada com sucesso.'):
    try:
        result = callback()
    except (PermissionDenied, ValidationError, IntegrityError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            detail = '; '.join(exc.messages)
        elif isinstance(exc, PermissionDenied):
            detail = str(exc)
        elif isinstance(exc, IntegrityError):
            detail = 'A operação conflitou com um registro existente; nenhum dado foi alterado.'
        else:
            detail = 'Revise os dados informados.'
        messages.error(request, detail)
        return False
    if result is False:
        return False
    messages.success(request, success)
    return True


def _base_context(request, module, view_capability, manage_capability):
    org = _org()
    require_municipal_permission(request.user, view_capability, module=module)
    return {
        'organization': org,
        'can_manage': has_municipal_permission(request.user, manage_capability, module=module),
        'can_manage_inventory': has_municipal_permission(request.user, f'{module.split("_")[0]}.inventory', module=module),
        'can_move': has_municipal_permission(request.user, f'{module.split("_")[0]}.transfer', module=module),
        'can_report': has_municipal_permission(request.user, f'{module.split("_")[0]}.report', module=module),
    }


def _save_model_form(request, form, model, extra=None, audit_action=None):
    if not form.is_valid():
        return False
    row = form.save(commit=False)
    row.organization = _org()
    for key, value in (extra or {}).items():
        setattr(row, key, value)
    row.save()
    if audit_action:
        audit_public(request.user, audit_action, row, {'id': row.pk})
    return True


@login_required
@require_http_methods(['GET', 'POST'])
def patrimonio_home(request):
    context = _base_context(request, 'patrimonio', 'patrimonio.view', 'patrimonio.manage')
    org = context['organization']
    assets = scoped_queryset(request.user, m.BemPatrimonial.objects.filter(organization=org)).select_related('secretaria', 'unidade', 'responsavel')
    inventories = scoped_queryset(request.user, m.InventarioPatrimonial.objects.filter(organization=org)).order_by('-exercicio', '-pk')
    context.update({
        'assets': assets[:100], 'inventories': inventories[:25],
        'movements': scoped_queryset(request.user, m.MovimentacaoPatrimonial.objects.filter(organization=org)).select_related('bem').order_by('-ocorrido_em')[:25],
        'asset_form': BemPatrimonialForm(organization=org, actor=request.user),
        'move_form': MovimentacaoBemForm(organization=org),
        'inventory_units': scoped_queryset(request.user, UnidadeMunicipal.objects.filter(organization=org, ativo=True)),
        'can_transfer': has_municipal_permission(request.user, 'patrimonio.transfer', module='patrimonio'),
        'can_inventory': has_municipal_permission(request.user, 'patrimonio.inventory', module='patrimonio'),
    })
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_asset':
            require_municipal_permission(request.user, 'patrimonio.manage', module='patrimonio')
            form = BemPatrimonialForm(request.POST, organization=org, actor=request.user)
            if form.is_valid() and _run(request, lambda: svc.create_asset(request.user, data=form.cleaned_data), success='Bem cadastrado e tombado.'):
                return redirect('rh_municipal_public:patrimonio_home')
            context['asset_form'] = form
        elif action == 'move_asset':
            form = MovimentacaoBemForm(request.POST, organization=org)
            asset = get_object_or_404(assets, pk=request.POST.get('asset_id'))
            if form.is_valid():
                data = dict(form.cleaned_data)
                data = {key: value for key, value in data.items() if value not in (None, '')}
                if _run(request, lambda: svc.move_asset(request.user, asset.pk, data=data), success='Movimentação patrimonial registrada.'):
                    return redirect('rh_municipal_public:patrimonio_home')
            context['move_form'] = form
        elif action == 'start_inventory':
            require_municipal_permission(request.user, 'patrimonio.inventory', module='patrimonio')
            unit_id = request.POST.get('unidade')
            unit = scoped_queryset(request.user, UnidadeMunicipal.objects.filter(organization=org)).filter(pk=unit_id).first() if unit_id else None
            if unit_id and unit is None:
                raise PermissionDenied('Unidade fora da organização ou do seu escopo.')
            if _run(request, lambda: svc.start_property_inventory(request.user, exercise=int(request.POST.get('exercicio')), unit=unit)):
                return redirect('rh_municipal_public:patrimonio_home')
        elif action == 'count_asset':
            form = CountPropertyForm(request.POST)
            if form.is_valid() and _run(request, lambda: svc.count_property_item(request.user, request.POST.get('item_id'), data=form.cleaned_data), success='Conferência registrada.'):
                return redirect('rh_municipal_public:patrimonio_home')
        elif action == 'close_inventory':
            if _run(request, lambda: svc.close_property_inventory(request.user, request.POST.get('inventory_id')), success='Inventário encerrado.'):
                return redirect('rh_municipal_public:patrimonio_home')
        else:
            raise PermissionDenied('Ação patrimonial não autorizada.')
    return render(request, 'rh_municipal/phase_d_patrimonio.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def almoxarifado_home(request):
    context = _base_context(request, 'almoxarifado', 'almoxarifado.view', 'almoxarifado.manage')
    org = context['organization']
    deposits = scoped_queryset(request.user, m.DepositoAlmoxarifadoMunicipal.objects.filter(organization=org)).select_related('unidade')
    items = scoped_queryset(request.user, m.ItemAlmoxarifadoMunicipal.objects.filter(organization=org))
    processes = scoped_queryset(request.user, ProcessoContratacaoMunicipal.objects.filter(organization=org))
    contracts = scoped_queryset(request.user, ContratoPublicoMunicipal.objects.filter(organization=org))
    context.update({
        'deposits': deposits, 'items': items[:100],
        'balances': scoped_queryset(request.user, m.SaldoAlmoxarifadoMunicipal.objects.filter(organization=org)).select_related('deposito', 'item')[:100],
        'movements': scoped_queryset(request.user, m.MovimentoAlmoxarifadoMunicipal.objects.filter(organization=org)).select_related('deposito', 'item').order_by('-criado_em')[:30],
        'requests': scoped_queryset(request.user, m.SolicitacaoMaterialMunicipal.objects.filter(organization=org)).select_related('unidade', 'solicitante').order_by('-criada_em')[:50],
        'inventories': scoped_queryset(request.user, m.InventarioAlmoxarifadoMunicipal.objects.filter(organization=org)).select_related('deposito').order_by('-exercicio')[:20],
        'deposit_form': DepositoMunicipalForm(organization=org, actor=request.user),
        'item_form': ItemAlmoxarifadoForm(organization=org, actor=request.user),
        'entry_form': EntradaAlmoxarifadoForm(organization=org, process_queryset=processes, contract_queryset=contracts),
        'transfer_form': TransferenciaAlmoxarifadoForm(organization=org),
        'request_form': SolicitacaoMaterialForm(organization=org,
            unit_queryset=scoped_queryset(request.user, UnidadeMunicipal.objects.filter(organization=org, ativo=True)),
            item_queryset=items.filter(ativo=True)),
        'can_request': has_municipal_permission(request.user, 'almoxarifado.request', module='almoxarifado'),
        'can_approve': has_municipal_permission(request.user, 'almoxarifado.approve', module='almoxarifado'),
        'can_issue': has_municipal_permission(request.user, 'almoxarifado.issue', module='almoxarifado'),
        'can_transfer': has_municipal_permission(request.user, 'almoxarifado.transfer', module='almoxarifado'),
        'can_inventory': has_municipal_permission(request.user, 'almoxarifado.inventory', module='almoxarifado'),
    })
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_deposit':
            require_municipal_permission(request.user, 'almoxarifado.manage', module='almoxarifado')
            form = DepositoMunicipalForm(request.POST, organization=org, actor=request.user)
            if form.is_valid() and _run(request, lambda: svc.create_deposit(request.user, data=form.cleaned_data)):
                return redirect('rh_municipal_public:almoxarifado_home')
            context['deposit_form'] = form
        elif action == 'create_item':
            require_municipal_permission(request.user, 'almoxarifado.manage', module='almoxarifado')
            form = ItemAlmoxarifadoForm(request.POST, organization=org, actor=request.user)
            if form.is_valid() and _run(request, lambda: svc.create_stock_item(request.user, data=form.cleaned_data)):
                return redirect('rh_municipal_public:almoxarifado_home')
            context['item_form'] = form
        elif action == 'receive':
            require_municipal_permission(request.user, 'almoxarifado.manage', module='almoxarifado')
            form = EntradaAlmoxarifadoForm(request.POST, organization=org,
                deposit_queryset=deposits.filter(ativo=True), item_queryset=items.filter(ativo=True),
                supplier_queryset=__import__('gestao.models', fromlist=['Fornecedor']).Fornecedor.objects.filter(organization=org, ativo=True),
                process_queryset=processes, contract_queryset=contracts)
            if form.is_valid():
                d = form.cleaned_data
                if _run(request, lambda: svc.receive_stock(request.user,
                    deposit_id=d['deposito'].pk, item_id=d['item'].pk, quantity=d['quantidade'],
                    reason=d['justificativa'], supplier=d['fornecedor'], invoice=d['nota_fiscal'],
                    lot_code=d['lote'], expiry=d['validade'], process=d['processo'], contract=d['contrato']),
                    success='Entrada de estoque registrada com trilha auditável.'):
                    return redirect('rh_municipal_public:almoxarifado_home')
            context['entry_form'] = form
        elif action == 'transfer':
            require_municipal_permission(request.user, 'almoxarifado.transfer', module='almoxarifado')
            form = TransferenciaAlmoxarifadoForm(request.POST, organization=org, deposit_queryset=deposits.filter(ativo=True), item_queryset=items.filter(ativo=True))
            if form.is_valid():
                d = form.cleaned_data
                if _run(request, lambda: svc.transfer_stock(request.user, source_id=d['origem'].pk, target_id=d['destino'].pk,
                    item_id=d['item'].pk, quantity=d['quantidade'], reason=d['justificativa']), success='Transferência registrada nas duas pontas.'):
                    return redirect('rh_municipal_public:almoxarifado_home')
            context['transfer_form'] = form
        elif action == 'request_material':
            require_municipal_permission(request.user, 'almoxarifado.request', module='almoxarifado')
            form = SolicitacaoMaterialForm(request.POST, organization=org,
                unit_queryset=scoped_queryset(request.user, UnidadeMunicipal.objects.filter(organization=org, ativo=True)), item_queryset=items.filter(ativo=True))
            if form.is_valid():
                d = form.cleaned_data
                if _run(request, lambda: svc.create_material_request(request.user, unit=d['unidade'], items=[(d['item'], d['quantidade'])], priority=d['prioridade'], reason=d['justificativa']), success='Requisição enviada para aprovação.'):
                    return redirect('rh_municipal_public:almoxarifado_home')
            context['request_form'] = form
        elif action == 'decide_request':
            if _run(request, lambda: svc.decide_material_request(request.user, request.POST.get('request_id'), approve=request.POST.get('approve') == '1', reason=request.POST.get('motivo', '')), success='Decisão da requisição registrada.'):
                return redirect('rh_municipal_public:almoxarifado_home')
        elif action == 'issue_request':
            if _run(request, lambda: svc.issue_material_request(request.user, request.POST.get('request_id'), deposit_id=request.POST.get('deposito'), quantities={}, deliver=request.POST.get('deliver') == '1'), success='Separação/entrega registrada.'):
                return redirect('rh_municipal_public:almoxarifado_home')
        elif action == 'start_inventory':
            require_municipal_permission(request.user, 'almoxarifado.inventory', module='almoxarifado')
            if _run(request, lambda: svc.start_store_inventory(request.user, deposit_id=request.POST.get('deposito'), exercise=int(request.POST.get('exercicio'))), success='Inventário de estoque iniciado.'):
                return redirect('rh_municipal_public:almoxarifado_home')
        elif action == 'count_stock':
            form = CountStockForm(request.POST)
            if form.is_valid() and _run(request, lambda: svc.count_store_item(request.user, request.POST.get('item_id'), quantity=form.cleaned_data['quantidade'], reason=form.cleaned_data['observacao']), success='Contagem registrada.'):
                return redirect('rh_municipal_public:almoxarifado_home')
        elif action == 'close_inventory':
            if _run(request, lambda: svc.close_store_inventory(request.user, request.POST.get('inventory_id')), success='Inventário encerrado e ajustes auditados aplicados.'):
                return redirect('rh_municipal_public:almoxarifado_home')
        else:
            raise PermissionDenied('Ação de almoxarifado não autorizada.')
    return render(request, 'rh_municipal/phase_d_almoxarifado.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def frotas_home(request):
    context = _base_context(request, 'frotas', 'frotas.view', 'frotas.manage')
    org = context['organization']
    vehicles = scoped_queryset(request.user, m.VeiculoMunicipal.objects.filter(organization=org)).select_related('secretaria', 'unidade', 'responsavel')
    drivers = scoped_queryset(request.user, m.CondutorMunicipal.objects.filter(organization=org)).select_related('servidor')
    context.update({
        'vehicles': vehicles[:100], 'drivers': drivers[:100],
        'trips': scoped_queryset(request.user, m.ViagemMunicipal.objects.filter(organization=org)).select_related('veiculo', 'condutor__servidor').order_by('-saida_em')[:50],
        'fuelings': scoped_queryset(request.user, m.AbastecimentoMunicipal.objects.filter(organization=org)).select_related('veiculo').order_by('-data')[:30],
        'maintenance': scoped_queryset(request.user, m.ManutencaoVeiculoMunicipal.objects.filter(organization=org)).select_related('veiculo').order_by('-iniciada_em')[:30],
        'documents': scoped_queryset(request.user, m.DocumentoFrotaMunicipal.objects.filter(organization=org)).select_related('veiculo').order_by('vence_em')[:30],
        'today': timezone.localdate(),
        'vehicle_form': VeiculoMunicipalForm(organization=org, actor=request.user),
        'driver_form': CondutorMunicipalForm(organization=org, actor=request.user),
        'trip_form': ViagemMunicipalForm(vehicle_queryset=vehicles.filter(situacao=m.VeiculoMunicipal.Situacao.DISPONIVEL), driver_queryset=drivers.filter(autorizado=True, situacao='ATIVO', validade__gte=timezone.localdate())),
        'fuel_form': AbastecimentoForm(vehicle_queryset=vehicles),
        'maintenance_form': ManutencaoVeiculoForm(vehicle_queryset=vehicles),
        'document_form': DocumentoFrotaForm(vehicle_queryset=vehicles),
        'can_dispatch': has_municipal_permission(request.user, 'frotas.dispatch', module='frotas'),
        'can_fuel': has_municipal_permission(request.user, 'frotas.fuel', module='frotas'),
        'can_maintenance': has_municipal_permission(request.user, 'frotas.maintenance', module='frotas'),
        'can_documents': has_municipal_permission(request.user, 'frotas.documents', module='frotas'),
    })
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_vehicle':
            require_municipal_permission(request.user, 'frotas.manage', module='frotas')
            form = VeiculoMunicipalForm(request.POST, organization=org, actor=request.user)
            if form.is_valid() and _run(request, lambda: svc.create_vehicle(request.user, data=form.cleaned_data)):
                return redirect('rh_municipal_public:frotas_home')
            context['vehicle_form'] = form
        elif action == 'create_driver':
            require_municipal_permission(request.user, 'frotas.manage', module='frotas')
            form = CondutorMunicipalForm(request.POST, organization=org, actor=request.user)
            if _run(request, lambda: _save_model_form(request, form, m.CondutorMunicipal, audit_action='CONDUTOR_AUTORIZACAO_CADASTRADA')):
                if form.is_valid(): return redirect('rh_municipal_public:frotas_home')
            context['driver_form'] = form
        elif action == 'start_trip':
            form = ViagemMunicipalForm(request.POST, vehicle_queryset=vehicles, driver_queryset=drivers)
            if form.is_valid():
                d = form.cleaned_data
                if _run(request, lambda: svc.start_trip(request.user, vehicle_id=d['veiculo'].pk, driver_id=d['condutor'].pk, data=d), success='Saída do veículo registrada.'):
                    return redirect('rh_municipal_public:frotas_home')
            context['trip_form'] = form
        elif action == 'return_trip':
            form = ReturnTripForm(request.POST)
            if form.is_valid() and _run(request, lambda: svc.return_trip(request.user, request.POST.get('trip_id'), final_km=form.cleaned_data['quilometragem_final'], note=form.cleaned_data['observacao']), success='Retorno registrado; odômetro atualizado.'):
                return redirect('rh_municipal_public:frotas_home')
        elif action == 'fuel':
            form = AbastecimentoForm(request.POST, vehicle_queryset=vehicles)
            if form.is_valid():
                d = form.cleaned_data; vehicle = d.pop('veiculo')
                if _run(request, lambda: svc.record_fueling(request.user, vehicle_id=vehicle.pk, data=d), success='Abastecimento registrado e custos calculados.'):
                    return redirect('rh_municipal_public:frotas_home')
            context['fuel_form'] = form
        elif action == 'maintenance':
            require_municipal_permission(request.user, 'frotas.maintenance', module='frotas')
            form = ManutencaoVeiculoForm(request.POST, vehicle_queryset=vehicles)
            if form.is_valid():
                row = form.save(commit=False); row.organization = org; row.responsavel = request.user
                if _run(request, lambda: row.save(), success='Manutenção registrada.'):
                    vehicle = row.veiculo; old = vehicle.situacao
                    vehicle.situacao = m.VeiculoMunicipal.Situacao.MANUTENCAO; vehicle.save()
                    event = m.EventoFrotaMunicipal(organization=org, veiculo=vehicle, acao='MANUTENCAO_ABERTA',
                        antes={'situacao': old}, depois={'situacao': vehicle.situacao, 'manutencao': row.pk}, usuario=request.user)
                    event._service_write = True; event.save()
                    audit_public(request.user, 'MANUTENCAO_VEICULO_ABERTA', row, {'veiculo': vehicle.pk, 'situacao_anterior': old})
                    return redirect('rh_municipal_public:frotas_home')
            context['maintenance_form'] = form
        elif action == 'document':
            require_municipal_permission(request.user, 'frotas.documents', module='frotas')
            form = DocumentoFrotaForm(request.POST, vehicle_queryset=vehicles)
            if form.is_valid():
                row = form.save(commit=False); row.organization = org
                if _run(request, lambda: row.save(), success='Documento da frota cadastrado.'):
                    audit_public(request.user, 'DOCUMENTO_FROTA_CADASTRADO', row, {'tipo': row.tipo, 'vence_em': row.vence_em.isoformat() if row.vence_em else None})
                    return redirect('rh_municipal_public:frotas_home')
            context['document_form'] = form
        elif action == 'maintenance_status':
            if _run(request, lambda: svc.set_maintenance_status(request.user, request.POST.get('maintenance_id'), status=request.POST.get('status')),
                    success='Situação da manutenção atualizada.'):
                return redirect('rh_municipal_public:frotas_home')
        else:
            raise PermissionDenied('Ação de frota não autorizada.')
    return render(request, 'rh_municipal/phase_d_frotas.html', context)
