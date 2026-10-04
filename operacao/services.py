import copy
import hashlib
import uuid
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Sum
from django.utils import timezone
from contas.models import Tecnico
from ordens.models import OrdemServico, Status
from ordens import services as os_services
from gestao import models as g, services as gs
from gestao.permissions import require
from . import models as m

def positive(value):
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValidationError('Informe valor positivo com até dois decimais.')
    return amount


@transaction.atomic
def salvar_chamado(user, form, request_id=None, portal=False):
    from .planning_services import lock_planning, validate_call_conflicts
    from .permissions import portal_clients
    lock_planning()
    call = form.save(commit=False)
    if portal:
        if call.cliente_id not in portal_clients(user):
            raise PermissionDenied('Cliente não autorizado.')
        call.origem = 'PORTAL'
        call.prioridade_solicitada = call.prioridade
        call.prioridade = 'NORMAL'
    else:
        require(user, 'contratos')
        call.origem = call.origem or 'INTERNO'
    previous = m.Chamado.objects.filter(request_id=request_id).first() if request_id and not call.pk else None
    if previous:
        if (previous.cliente_id, previous.unidade_id, previous.equipamento_id, previous.titulo, previous.descricao, previous.criado_por_id) != (call.cliente_id, call.unidade_id, call.equipamento_id, call.titulo, call.descricao, user.pk):
            raise ValidationError('Identificador de chamado já utilizado com outros dados.')
        return previous
    if call.pk and call.ordem_id:
        raise ValidationError('Chamado convertido deve ser acompanhado pela OS.')
    validate_call_conflicts(user, call)
    call.criado_por = user if not call.pk else call.criado_por
    call.request_id = request_id if not call.pk else call.request_id
    if call.contrato_id and not call.sla_horas:
        call.sla_horas = call.contrato.sla_horas
        if call.sla_horas and not call.prazo:
            call.prazo = (call.criado_em or timezone.now()) + timezone.timedelta(hours=call.sla_horas)
    call.save()
    upload = form.cleaned_data.get('anexo')
    if upload:
        raw = upload.read(); upload.seek(0)
        document = m.Documento(titulo=f'Anexo {call.numero}', tipo='IMAGEM' if upload.name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) else 'PDF', categoria='TECNICO', arquivo=upload, cliente=call.cliente, unidade=call.unidade, equipamento=call.equipamento, chamado=call, enviado_por=user, disponivel_portal=portal, sha256=hashlib.sha256(raw).hexdigest())
        document.save()
        gs.audit(user, 'CHAMADO_ANEXO', document, {'chamado': call.pk, 'sha256': document.sha256})
    gs.audit(user, 'CHAMADO_SALVO', call, {'origem': call.origem, 'prazo': str(call.prazo or '')})
    from .notifications import deliver
    deliver(f'chamado-novo:{call.pk}', 'Novo chamado técnico', call.titulo, ['ADMIN', 'GESTOR'], f'/chamados/{call.pk}/')
    return call


@transaction.atomic
def chamado_status(user, pk, target, reason=''):
    require(user, 'contratos')
    from .planning_services import lock_planning, validate_call_conflicts
    lock_planning()
    call = m.Chamado.objects.select_for_update().get(pk=pk)
    if call.ordem_id:
        raise ValidationError('Altere o atendimento pela OS vinculada.')
    allowed = {'ABERTO': ['TRIAGEM', 'CANCELADO'], 'TRIAGEM': ['AG_AGENDAMENTO', 'AGENDADO', 'CANCELADO'], 'AG_AGENDAMENTO': ['TRIAGEM', 'AGENDADO', 'CANCELADO'], 'AGENDADO': ['TRIAGEM', 'AG_AGENDAMENTO', 'CANCELADO']}
    if target == call.status:
        return call
    if target not in allowed.get(call.status, []):
        raise ValidationError('Transição de chamado inválida.')
    if target == 'AGENDADO' and (not call.tecnico_id or not call.agendada_para):
        raise ValidationError('Agendamento exige técnico e horário.')
    if target == 'CANCELADO' and not reason.strip():
        raise ValidationError('Informe o motivo do cancelamento.')
    old = call.status
    call.status = target
    validate_call_conflicts(user, call)
    gs.write(call)
    gs.audit(user, 'CHAMADO_STATUS', call, {'anterior': old, 'posterior': target, 'motivo': reason})
    return call


def sincronizar_chamado(user, order):
    call = m.Chamado.objects.filter(ordem=order).first()
    if not call:
        return
    target = {'ABERTA': 'CONVERTIDO', 'AGENDADA': 'AGENDADO', 'DESLOCAMENTO': 'EM_ATENDIMENTO', 'EXECUCAO': 'EM_ATENDIMENTO', 'AG_PECA': 'AG_PECA', 'AG_CLIENTE': 'AG_CLIENTE', 'AG_APROVACAO': 'AG_APROVACAO', 'FINALIZADA': 'CONCLUIDO', 'APROVADA': 'CONCLUIDO', 'FATURADA': 'CONCLUIDO', 'CANCELADA': 'CANCELADO'}[order.status]
    if call.status != target:
        old = call.status
        call.status = target
        gs.write(call)
        gs.audit(user, 'CHAMADO_ATENDIMENTO', call, {'os': order.pk, 'anterior': old, 'posterior': target})


def validar_respostas_checklist(order, required=True):
    m.checklist_valido(order.checklist)
    for item in order.checklist:
        if not item.get('tipo'):
            continue
        answer = item.get('resposta')
        answered = answer is not None and answer != ''
        if item.get('tipo') == 'FOTO' and answered and not order.fotos.filter(pk=answer).exists():
            raise ValidationError('Foto do checklist não pertence a esta OS.')
        if item.get('concluido') != answered:
            raise ValidationError('Estado da resposta inconsistente.')
        if required and item.get('obrigatorio') and not answered:
            raise ValidationError('Responda todos os itens obrigatórios do checklist.')


@transaction.atomic
def necessidade_peca(user, pk, form):
    order = OrdemServico.objects.select_for_update().get(pk=pk)
    os_services.autorizar(user, order)
    from .contract_workday import link_order
    link_order(user, order)
    if order.status in m.ENCERRADAS:
        raise ValidationError('OS encerrada não aceita necessidade de peça.')
    need = form.save(commit=False)
    old = m.NecessidadePecaOS.objects.filter(ordem=order, peca=need.peca, deposito=need.deposito, resolvida_em__isnull=True).first()
    if old:
        if old.quantidade != need.quantidade or old.urgencia != need.urgencia or old.observacoes != need.observacoes:
            raise ValidationError('Necessidade já aberta com outros dados; regularize a ocorrência existente.')
        return old
    need.ordem, need.usuario = order, user
    gs.write(need)
    gs.audit(user, 'OS_PECA_NECESSARIA', need, {'os': order.pk, 'peca': need.peca_id, 'quantidade': str(need.quantidade), 'urgencia': need.urgencia})
    if order.status == 'EXECUCAO':
        transicao_os(user, pk, 'aguardar_peca', need.observacoes)
    from .notifications import deliver
    deliver(f'peca-necessaria:{need.pk}', 'Peça necessária para atendimento', f'{order.numero} · {need.peca} · {need.quantidade}', ['ADMIN', 'GESTOR', 'ESTOQUE'], '/estoque/necessidades/')
    return need


@transaction.atomic
def comprar_necessidade(user, pk):
    require(user, 'estoque_escrever')
    need = m.NecessidadePecaOS.objects.get(pk=pk)
    order = OrdemServico.objects.select_for_update().get(pk=need.ordem_id)
    need = m.NecessidadePecaOS.objects.select_for_update().get(pk=pk)
    if need.compra_id and need.compra.status != 'CANCELADA':
        return need.compra
    if need.resolvida_em or order.status in m.ENCERRADAS:
        raise ValidationError('Necessidade encerrada não gera compra.')
    from .stock import need_remaining, valid_lots, active_reservations, total
    g.Peca.objects.select_for_update().get(pk=need.peca_id)
    quantity = need_remaining(need)
    available = max(g.ZERO, total(valid_lots(need.peca, need.deposito)) - total(active_reservations(need.peca, need.deposito)))
    pending = sum((item.quantidade_pendente for item in m.ItemCompra.objects.filter(peca=need.peca, compra__deposito=need.deposito, compra__status__in=['APROVADA', 'PEDIDO']).select_related('compra')), g.ZERO)
    quantity = max(g.ZERO, quantity - available - pending)
    if not quantity:
        raise ValidationError('Necessidade atendida, reservada ou coberta por estoque válido / compra aprovada pendente. Reserve o saldo ou acompanhe o recebimento.')
    purchase = m.Compra.objects.create(deposito=need.deposito, fornecedor=need.peca.fornecedor, necessidade=f'Peça para {order.numero}: {need.observacoes}', vencimento=timezone.localdate(), criado_por=user)
    m.ItemCompra.objects.create(compra=purchase, peca=need.peca, quantidade=quantity, custo_unitario=need.peca.custo_aquisicao)
    need.compra = purchase
    gs.write(need)
    gs.audit(user, 'OS_PECA_COMPRA_SOLICITADA', need, {'compra': purchase.pk, 'quantidade': str(quantity)})
    return purchase


@transaction.atomic
def resolver_necessidade(user, pk, reason):
    require(user, 'estoque_escrever')
    need = m.NecessidadePecaOS.objects.get(pk=pk)
    OrdemServico.objects.select_for_update().get(pk=need.ordem_id)
    need = m.NecessidadePecaOS.objects.select_for_update().get(pk=pk)
    if not reason.strip():
        raise ValidationError('Informe o motivo da resolução; esta ação não movimenta estoque.')
    if not need.resolvida_em:
        need.resolvida_em = timezone.now()
        gs.write(need)
        gs.audit(user, 'OS_PECA_NECESSIDADE_RESOLVIDA', need, {'motivo': reason, 'os': need.ordem_id})
        for notice in m.Notificacao.objects.filter(chave=f'peca-necessaria:{need.pk}', resolvida_em__isnull=True):
            notice.resolvida_em = need.resolvida_em
            notice.save()
    return need

@transaction.atomic
def saldo_deposito(part):
    """Aloca o saldo legado sem gerar consumo/entrada fictícios."""
    principal, _ = m.Deposito.objects.get_or_create(nome='Principal')
    saldo = m.SaldoDeposito.objects.filter(deposito=principal, peca=part).first()
    if saldo is None:
        other = m.SaldoDeposito.objects.filter(peca=part).aggregate(total=Sum('quantidade'))['total'] or g.ZERO
        saldo = gs.write(m.SaldoDeposito(deposito=principal, peca=part, quantidade=part.quantidade_atual - other))
    return principal

def saldo_movimentar(part, delta, origem=None, destino=None, transferencia=False, quantidade=None):
    default = saldo_deposito(part)
    source = m.Deposito.objects.get(pk=origem, ativo=True) if origem else default
    target = m.Deposito.objects.get(pk=destino, ativo=True) if destino else default
    if transferencia:
        if not origem or not destino or source.pk == target.pk:
            raise ValidationError('Transferência exige dois depósitos ativos diferentes.')
        changes = [(source, -quantidade), (target, quantidade)]
    else:
        selected = source if delta < 0 else target
        changes = [(selected, delta)]
    for deposit, change in sorted(changes, key=lambda item: item[0].pk):
        balance = m.SaldoDeposito.objects.select_for_update().filter(deposito=deposit, peca=part).first()
        if not balance:
            balance = gs.write(m.SaldoDeposito(deposito=deposit, peca=part))
        if balance.quantidade + change < 0:
            raise ValidationError('Saldo insuficiente no depósito de origem.')
        balance.quantidade += change
        gs.write(balance)
    return (source if delta < 0 or transferencia else None, target if delta >= 0 or transferencia else None)

@transaction.atomic
def chamado_os(user, pk, tecnico_id):
    require(user, 'contratos')
    from .planning_services import lock_planning, validate_conflicts
    lock_planning()
    call = m.Chamado.objects.select_for_update().get(pk=pk)
    if call.ordem_id:
        return call.ordem
    if call.status not in ['ABERTO', 'TRIAGEM', 'AG_AGENDAMENTO', 'AGENDADO'] or not call.equipamento_id:
        raise ValidationError('Chamado aberto precisa de equipamento para gerar OS.')
    tech = Tecnico.objects.get(pk=tecnico_id, ativo=True)
    order = OrdemServico(cliente=call.cliente, unidade=call.unidade, equipamento=call.equipamento, tecnico=tech, contrato=call.contrato, prioridade=call.prioridade, tipo_atendimento=call.tipo or 'CORRETIVA', defeito=call.descricao, prazo=call.prazo, agendada_para=call.agendada_para, agendada_ate=call.agendada_ate, status='AGENDADA' if call.agendada_para else 'ABERTA')
    validate_conflicts(user, order, exclude_call_id=call.pk)
    order.save()
    os_services.auditar(order, user, 'CRIACAO', os_services.snapshot(order))
    call.ordem, call.status = order, 'CONVERTIDO'
    gs.write(call)
    gs.audit(user, 'CHAMADO_CONVERTIDO', call, {'ordem': order.pk})
    return order

def datas_plano(plan):
    days = {'DIARIO': 1, 'SEMANAL': 7, 'QUINZENAL': 15, 'PERSONALIZADA': plan.intervalo_dias}
    months = {'MENSAL': 1, 'BIMESTRAL': 2, 'TRIMESTRAL': 3, 'QUADRIMESTRAL': 4, 'SEMESTRAL': 6, 'ANUAL': 12}
    for index in range(1201):
        date = plan.inicio + (timezone.timedelta(days=index * days[plan.periodicidade]) if plan.periodicidade in days else relativedelta(months=index * months[plan.periodicidade]))
        if date > plan.fim:
            return
        if index == 1200:
            raise ValidationError('Divida planos com mais de 1200 ocorrências por equipamento.')
        yield date

@transaction.atomic
def salvar_plano(user, form):
    require(user, 'contratos')
    plan = form.save(commit=False)
    plan.save()
    wanted = {x.pk for x in form.cleaned_data['equipamentos']}
    for link in plan.planoequipamento_set.all():
        if link.equipamento_id not in wanted:
            if plan.ocorrencias.filter(equipamento_id=link.equipamento_id).exists():
                raise ValidationError('Equipamento com agenda gerada deve ser preservado; desative o plano.')
            link.delete()
    for equipment in form.cleaned_data['equipamentos']:
        m.PlanoEquipamento.objects.get_or_create(plano=plan, equipamento=equipment)
    wanted_team = {tech.pk for tech in form.cleaned_data.get('equipe', [])}
    for link in plan.planotecnico_set.all():
        if link.tecnico_id not in wanted_team:
            link.delete()
    for tech in form.cleaned_data.get('equipe', []):
        m.PlanoTecnico.objects.get_or_create(plano=plan, tecnico=tech)
    gerar_plano(user, plan.pk)
    gs.audit(user, 'PLANO_SALVO', plan)
    return plan

@transaction.atomic
def gerar_plano(user, pk):
    require(user, 'contratos')
    plan = m.PlanoPreventivo.objects.select_for_update().get(pk=pk)
    if not plan.ativo:
        return
    dates = list(datas_plano(plan))
    if len(dates) * plan.equipamentos.count() > 10000:
        raise ValidationError('Divida planos com mais de 10.000 ocorrências.')
    for equipment in plan.equipamentos.all():
        for date in dates:
            m.PreventivaProgramada.objects.get_or_create(plano=plan, equipamento=equipment, data=date)

@transaction.atomic
def preventiva_os(user, pk, tecnico_id):
    require(user, 'contratos')
    from .planning_services import lock_planning, validate_conflicts
    lock_planning()
    item = m.PreventivaProgramada.objects.select_for_update().get(pk=pk)
    if item.ordem_id:
        return item.ordem
    if item.situacao == 'CANCELADA':
        raise ValidationError('Plano/ocorrência desativados.')
    tech = Tecnico.objects.get(pk=tecnico_id, ativo=True)
    equipment, plan = item.equipamento, item.plano
    checklist = copy.deepcopy(plan.checklist.itens) if plan.checklist_id else []
    for row in checklist:
        row['concluido'] = False
        row.pop('resposta', None)
    order = OrdemServico(cliente=equipment.cliente, unidade=equipment.unidade, equipamento=equipment, tecnico=tech, contrato=plan.contrato, tipo_atendimento=plan.tipo_manutencao or 'PREVENTIVA', defeito=f'Plano {plan.nome} · {item.data:%d/%m/%Y}', agendada_para=timezone.make_aware(timezone.datetime.combine(item.data, timezone.datetime.min.time()).replace(hour=8)), checklist=checklist, modelo_checklist=plan.checklist, observacoes=plan.observacoes)
    validate_conflicts(user, order, auxiliary_ids=list(plan.equipe.exclude(pk=tech.pk).values_list('pk', flat=True)))
    order.save()
    os_services.salvar_equipe(user, order, plan.equipe.exclude(pk=tech.pk))
    os_services.auditar(order, user, 'CRIACAO', os_services.snapshot(order))
    item.ordem = order
    item.save()
    gs.audit(user, 'PREVENTIVA_OS_GERADA', item, {'ordem': order.pk})
    return order

@transaction.atomic
def checklist_salvar(user, pk, concluded, observations, answers=None):
    order = OrdemServico.objects.select_for_update().get(pk=pk)
    os_services.autorizar(user, order)
    from .contract_workday import link_order
    link_order(user, order)
    if order.status in m.ENCERRADAS:
        raise ValidationError('Atendimento encerrado é imutável.')
    old = copy.deepcopy(order.checklist)
    for index, row in enumerate(order.checklist):
        key = str(index)
        if row.get('tipo'):
            answer = (answers or {}).get(key)
            if row['tipo'] in ['BOOLEANO', 'CONFORMIDADE']:
                if answer in ['true', 'false']:
                    answer = answer == 'true'
            if row['tipo'] == 'FOTO' and answer not in [None, '']:
                try:
                    answer = int(answer)
                except (ValueError, TypeError):
                    raise ValidationError('Foto inválida.')
            row['resposta'] = answer
            row['concluido'] = answer is not None and answer != ''
        else:
            row['concluido'] = key in concluded
        row['observacao'] = observations.get(str(index), '')[:1000]
    validar_respostas_checklist(order, required=False)
    order.revisao += 1
    order.save()
    os_services.auditar(order, user, 'CHECKLIST', {'anterior': old, 'posterior': order.checklist})

@transaction.atomic
def transicao_os(user, pk, action, reason=''):
    order = OrdemServico.objects.select_for_update().get(pk=pk)
    os_services.autorizar(user, order)
    if action in ['deslocamento','aguardar_peca','aguardar_cliente','aguardar_aprovacao','retomar']:
        from .contract_workday import link_order
        link_order(user, order)
    old = order.status
    transitions = {'agendar': (['ABERTA'], 'AGENDADA'), 'deslocamento': (['ABERTA', 'AGENDADA'], 'DESLOCAMENTO'), 'aguardar_peca': (['EXECUCAO'], 'AG_PECA'), 'aguardar_aprovacao': (['EXECUCAO'], 'AG_APROVACAO'), 'aguardar_cliente': (['EXECUCAO'], 'AG_CLIENTE'), 'retomar': (['AG_PECA', 'AG_CLIENTE', 'AG_APROVACAO'], 'EXECUCAO'), 'aprovar': (['FINALIZADA'], 'APROVADA'), 'faturar': (['APROVADA'], 'FATURADA')}
    if action == 'cancelar':
        os_services.autorizar(user, order, administrativo=True)
        if old == 'CANCELADA' or not reason.strip():
            raise ValidationError('Cancelamento exige justificativa e OS não cancelada.')
        if m.DocumentoFiscal.objects.filter(ordem=order, status='AUTORIZADA').exists():
            raise ValidationError('Regularize a nota fiscal no provedor antes de cancelar.')
        from gestao.financial_origin import origin_query
        for entry in g.Lancamento.objects.select_for_update(of=('self',)).filter(origin_query(ordem=order)).order_by('pk'):
            if entry.status == 'LIQUIDADO' or entry.pagamentos.exists():
                raise ValidationError('OS tem recebimento; regularize o financeiro antes de cancelar.')
            if entry.status != 'CANCELADO':
                gs.cancelar_lancamento(user, entry.pk, reason)
        target = 'CANCELADA'
        from .stock import release
        for reservation in order.reservas_estoque.filter(status='ATIVA').order_by('peca_id', 'pk'):
            release(user, reservation.pk, reason)
    else:
        if action not in transitions or old not in transitions[action][0]:
            raise ValidationError('Transição não permitida neste estado.')
        target = transitions[action][1]
        if action in ['agendar', 'aprovar', 'faturar']:
            os_services.autorizar(user, order, administrativo=True)
        if action == 'agendar' and not order.agendada_para:
            raise ValidationError('Informe a data/hora agendada ao editar a OS.')
        if action == 'faturar' and not order.lancamentos.exists() and not g.Orcamento.objects.filter(ordem_convertida=order, lancamentos__isnull=False).exists():
            raise ValidationError('OS sem conta a receber não pode ser faturada.')
    order.status = target
    order.revisao += 1
    os_services.salvar_transicao(order)
    os_services.auditar(order, user, 'STATUS_' + target, {'status': {'anterior': old, 'posterior': target}}, reason)
    return order

@transaction.atomic
def compra_acao(user, pk, action, quotation_id=None):
    from platform_core.modules import require_capability
    require_capability(user, 'compras')
    purchase = m.Compra.objects.select_for_update().get(pk=pk)
    if action == 'receber' and purchase.status == 'RECEBIDA':
        return purchase
    old = purchase.status
    if action == 'aprovar':
        if old != 'RASCUNHO' or not purchase.itens.exists() or purchase.total <= 0:
            raise ValidationError('Solicitação precisa de itens/valor e estar em rascunho.')
        if quotation_id:
            quotation = purchase.cotacoes.get(pk=quotation_id)
            if quotation.validade < timezone.localdate() or quotation.valor != purchase.total:
                raise ValidationError('Revise validade e preços dos itens para coincidir com a cotação escolhida.')
            purchase.fornecedor = quotation.fornecedor
        if not purchase.fornecedor_id:
            raise ValidationError('Selecione o fornecedor/cotação antes da aprovação.')
        purchase.status = 'APROVADA'
    elif action == 'pedir' and old == 'APROVADA':
        purchase.status = 'PEDIDO'
    elif action == 'receber' and old == 'PEDIDO':
        lines = [{'item_id': item.pk, 'quantidade': item.quantidade_pendente, 'lote': item.lote, 'fabricacao': item.fabricacao, 'validade': item.validade, 'documento': item.documento_entrada} for item in purchase.itens.select_related('peca').order_by('peca_id', 'pk') if item.quantidade_pendente]
        receber_compra(user, pk, lines, uuid.uuid5(uuid.NAMESPACE_URL, f'vertyx:compra:{purchase.organization_id}:{pk}:recebimento-integral'))
        return m.Compra.objects.get(pk=pk)
    elif action == 'cancelar' and old in ['RASCUNHO', 'APROVADA', 'PEDIDO']:
        if purchase.recebimentos.exists():
            raise ValidationError('Compra parcialmente recebida exige regularização do estoque; cancelamento não apaga recebimentos.')
        purchase.status = 'CANCELADA'
    else:
        raise ValidationError('Transição de compra inválida.')
    gs.write(purchase)
    gs.audit(user, 'COMPRA_' + purchase.status, purchase, {'status': {'anterior': old, 'posterior': purchase.status}})
    return purchase


@transaction.atomic
def receber_compra(user, pk, lines, request_id, deposito_id=None, recebido_em=None, documento=''):
    """Entrada incremental pelo estoque oficial; toda falha desfaz recebimento e lotes."""
    from .stock import amount
    from platform_core.modules import require_capability
    require_capability(user, 'compras')
    purchase = m.Compra.objects.select_for_update().get(pk=pk)
    depot = m.Deposito.objects.get(pk=deposito_id or purchase.deposito_id, ativo=True)
    token = uuid.UUID(str(request_id))
    if not lines or len(lines) > 500:
        raise ValidationError('Selecione até 500 itens para receber.')
    normalized = []
    seen = set()
    for data in lines:
        item_id = int(data['item_id'])
        if item_id in seen:
            raise ValidationError('Item repetido no mesmo recebimento.')
        seen.add(item_id)
        quantity = amount(data['quantidade'])
        normalized.append({'item_id': item_id, 'quantidade': str(quantity), 'lote': str(data.get('lote', '')),
                           'fabricacao': data.get('fabricacao').isoformat() if data.get('fabricacao') else None,
                           'validade': data.get('validade').isoformat() if data.get('validade') else None,
                           'documento': str(data.get('documento', documento))})
    normalized.sort(key=lambda line: line['item_id'])
    parameters = {'compra': pk, 'deposito': depot.pk, 'itens': normalized, 'documento': documento, 'data_informada': recebido_em.isoformat() if recebido_em else None}
    previous = m.RecebimentoCompra.objects.filter(request_id=token).first()
    if previous:
        if previous.parametros != parameters:
            raise ValidationError('Identificador de recebimento já utilizado com outros dados.')
        return previous
    if purchase.status != 'PEDIDO':
        raise ValidationError('Somente pedidos podem receber mercadoria.')
    when = recebido_em or timezone.now()
    if when > timezone.now() or when < purchase.criado_em:
        raise ValidationError('Data do recebimento fora do período da compra.')
    items = list(purchase.itens.filter(pk__in=seen).select_related('peca', 'compra').order_by('peca_id', 'pk'))
    if len(items) != len(seen):
        raise ValidationError('Item não pertence a esta compra.')
    # Ordem estável dos locks entre compras diferentes que recebem vários produtos.
    list(g.Peca.objects.select_for_update().filter(pk__in={item.peca_id for item in items}).order_by('pk'))
    try:
        with transaction.atomic():
            receipt = gs.write(m.RecebimentoCompra(compra=purchase, deposito=depot, request_id=token, recebido_em=when, usuario=user, documento=documento, parametros=parameters))
    except (IntegrityError, ValidationError):
        previous = m.RecebimentoCompra.objects.filter(request_id=token).first()
        if previous and previous.parametros == parameters:
            return previous
        raise ValidationError('Identificador de recebimento disputado; nenhuma entrada foi realizada.') from None
    by_id = {line['item_id']: line for line in normalized}
    from datetime import date
    for item in items:
        line = by_id[item.pk]
        quantity = Decimal(line['quantidade'])
        if quantity > item.quantidade_pendente:
            raise ValidationError('Quantidade excede o saldo pendente do item.')
        manufacture = date.fromisoformat(line['fabricacao']) if line['fabricacao'] else None
        expiration = date.fromisoformat(line['validade']) if line['validade'] else None
        if expiration and expiration < timezone.localdate(when):
            raise ValidationError('Não é permitido receber produto já vencido.')
        from .purchase_scope import _execution
        with _execution(user,purchase,depot,item,quantity):
            movement = gs.movimentar(user, item.peca_id, 'ENTRADA', quantity, f'Recebimento {purchase} · {receipt.pk}', destino_id=depot.pk,
                lote_data={'numero': line['lote'], 'fabricacao': manufacture, 'validade': expiration, 'documento_entrada': line['documento'], 'item_compra': item, 'fornecedor': purchase.fornecedor, 'custo_unitario': item.custo_unitario})
        gs.write(m.ItemRecebimentoCompra(recebimento=receipt, item=item, movimentacao=movement, quantidade=quantity, custo_unitario=item.custo_unitario, lote=line['lote'], fabricacao=manufacture, validade=expiration))
    complete = all(item.quantidade_pendente == 0 for item in purchase.itens.select_related('compra'))
    if complete:
        if not purchase.conta_id:
            purchase.conta = gs.write(g.Lancamento(tipo='PAGAR', descricao=str(purchase), fornecedor=purchase.fornecedor, valor=purchase.total, vencimento=purchase.vencimento, criado_por=user))
        purchase.status = 'RECEBIDA'
        gs.write(purchase)
    gs.audit(user, 'COMPRA_RECEBIMENTO', receipt, {'compra': pk, 'itens': normalized, 'concluida': complete, 'conta': purchase.conta_id})
    from .notifications import deliver
    deliver(f'compra-recebida:{receipt.pk}', 'Compra recebida' if complete else 'Recebimento parcial de compra', str(purchase), ['ADMIN', 'GESTOR', 'ESTOQUE'], f'/compras/{pk}/')
    return receipt

@transaction.atomic
def venda_confirmar(user, pk):
    require(user, 'contratos')
    sale = m.Venda.objects.select_for_update().get(pk=pk)
    if sale.status == 'CONFIRMADA':
        return sale
    if sale.status != 'RASCUNHO' or not sale.itens.exists() or sale.total <= 0:
        raise ValidationError('Venda exige itens, total positivo e rascunho.')
    for item in sale.itens.select_related('peca').order_by('peca_id'):
        movement = gs.movimentar(user, item.peca_id, 'SAIDA', item.quantidade, str(sale), origem_id=sale.deposito_id, venda_id=sale.pk)
        item.custo_total = movement.valor_custo
        item.custo_unitario = (item.custo_total / item.quantidade).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        item.save()
    sale.conta = gs.write(g.Lancamento(tipo='RECEBER', descricao=str(sale), cliente=sale.cliente, valor=sale.total, vencimento=sale.vencimento, criado_por=user))
    sale.status = 'CONFIRMADA'
    gs.write(sale)
    gs.audit(user, 'VENDA_CONFIRMADA', sale, {'total': str(sale.total), 'lancamento': sale.conta_id})
    return sale

@transaction.atomic
def caixa(user, conta_id, tipo, valor, date, description, reference=None):
    from .commerce_scope import _authorized
    if not _authorized(user,'cash',account_id=conta_id):
        require(user, 'financeiro_escrever')
    account = m.ContaBancaria.objects.select_for_update().get(pk=conta_id, ativo=True)
    amount = positive(valor)
    if tipo not in ['ENTRADA', 'SAIDA'] or date > timezone.localdate() or not description.strip():
        raise ValidationError('Tipo/data/descrição inválidos.')
    ref = reference or uuid.uuid4()
    existing = account.movimentos.filter(referencia=ref).first()
    if existing:
        if (existing.tipo, existing.valor, existing.data, existing.descricao) != (tipo, amount, date, description):
            raise ValidationError('Identificador de caixa já utilizado com outros dados.')
        return existing
    if tipo == 'SAIDA' and not account.permite_saldo_negativo and amount > account.saldo:
        raise ValidationError('Saldo bancário insuficiente; limite negativo não habilitado.')
    movement = gs.write(m.MovimentoCaixa(conta=account, tipo=tipo, valor=amount, data=date, descricao=description, referencia=ref, usuario=user))
    gs.audit(user, 'CAIXA_MOVIMENTADO', movement, {'tipo': tipo, 'valor': str(amount)})
    return movement

@transaction.atomic
def transferir_banco(user, origem, destino, amount, date, reference):
    require(user, 'financeiro_escrever')
    if origem == destino:
        raise ValidationError('Contas de origem/destino devem ser diferentes.')
    list(m.ContaBancaria.objects.select_for_update().filter(pk__in=[origem, destino]).order_by('pk'))
    caixa(user, origem, 'SAIDA', amount, date, 'Transferência entre contas', reference)
    caixa(user, destino, 'ENTRADA', amount, date, 'Transferência entre contas', reference)

@transaction.atomic
def pagar(user, pk, amount, date, observation='', account_id=None, request_id=None):
    from .commerce_scope import _authorized
    if not _authorized(user,'payment',entry_id=pk):
        require(user, 'financeiro_escrever')
    entry = g.Lancamento.objects.select_for_update().get(pk=pk)
    token = request_id or uuid.uuid4()
    previous = m.Pagamento.objects.filter(request_id=token).first()
    if previous:
        if (previous.lancamento_id, previous.valor, previous.data, previous.conta_id) != (pk, Decimal(amount), date, account_id):
            raise ValidationError('Identificador de pagamento já usado com outros dados.')
        return previous
    amount = positive(amount)
    if entry.status not in ['PENDENTE', 'VENCIDO'] or amount > entry.saldo or date > timezone.localdate() or date < entry.data_emissao:
        raise ValidationError('Revise estado, saldo pendente e data do pagamento.')
    try:
        with transaction.atomic():
            if account_id:
                account = m.ContaBancaria.objects.get(pk=account_id, ativo=True)
                caixa(user, account.pk, 'ENTRADA' if entry.tipo == 'RECEBER' else 'SAIDA', amount, date, entry.descricao, token)
            else:
                account = None
            payment = gs.write(m.Pagamento(lancamento=entry, valor=amount, data=date, conta=account, usuario=user, observacoes=observation, request_id=token))
    except IntegrityError:
        previous = m.Pagamento.objects.filter(request_id=token).first()
        if previous and (previous.lancamento_id, previous.valor, previous.data, previous.conta_id) == (pk, amount, date, account_id):
            return previous
        raise ValidationError('Identificador de pagamento disputado por outra operação; nenhuma baixa foi realizada.') from None
    gs.write(g.EventoFinanceiro(lancamento=entry, tipo='LIQUIDACAO', valor=amount, data=date, usuario=user, observacao=observation))
    if entry.saldo == 0:
        entry.status, entry.data_liquidacao = 'LIQUIDADO', date
        gs.write(entry)
    gs.audit(user, 'LANCAMENTO_LIQUIDADO' if entry.status == 'LIQUIDADO' else 'PAGAMENTO_PARCIAL', entry, {'valor': str(amount), 'saldo': str(entry.saldo), 'data': date.isoformat(), 'pagamento':payment.pk, 'request_id':str(token), 'conta':account_id, 'controle_caixa':'BANCARIZADO' if account_id else 'NAO_BANCARIZADO', 'origem_raiz':entry.raiz_financeira.pk})
    return payment

@transaction.atomic
def parcelar(user, pk, quantity, first_date):
    require(user, 'financeiro_escrever')
    entry = g.Lancamento.objects.select_for_update().get(pk=pk)
    if entry.parcelas.exists():
        existing = list(entry.parcelas.select_related('lancamento').order_by('numero'))
        if len(existing) != quantity or existing[0].lancamento.vencimento != first_date:
            raise ValidationError('Lançamento já parcelado com quantidade/data diferentes.')
        return existing
    if entry.status != 'PENDENTE' or entry.pagamentos.exists() or not 2 <= quantity <= 60:
        raise ValidationError('Parcelamento exige conta pendente sem pagamentos e 2 a 60 parcelas.')
    cents = int(entry.valor * 100)
    base, remainder = divmod(cents, quantity)
    portion = Decimal(base) / 100
    if portion < Decimal('.01'):
        raise ValidationError('Valor insuficiente para a quantidade de parcelas.')
    result = []
    for index in range(quantity):
        amount = portion + (Decimal('.01') if index < remainder else g.ZERO)
        part = gs.write(g.Lancamento(tipo=entry.tipo, descricao=f'{entry.descricao} · {index + 1}/{quantity}', cliente=entry.cliente, fornecedor=entry.fornecedor, categoria=entry.categoria, centro_custo=entry.centro_custo, forma_pagamento=entry.forma_pagamento, valor=amount, data_emissao=entry.data_emissao, competencia=entry.competencia, origem_raiz=entry.raiz_financeira, vencimento=first_date + relativedelta(months=index), criado_por=user))
        result.append(m.Parcela.objects.create(origem=entry, lancamento=part, numero=index + 1))
    gs.cancelar_lancamento(user, entry.pk, 'Substituído por parcelas vinculadas, sem baixa de caixa.')
    gs.audit(user, 'LANCAMENTO_PARCELADO', entry, {'parcelas': quantity, 'valor': str(entry.valor)})
    return result

@transaction.atomic
def conciliar(user, pk, movement_id):
    require(user, 'financeiro_escrever')
    row = m.ExtratoBancario.objects.select_for_update().get(pk=pk)
    movement = m.MovimentoCaixa.objects.get(pk=movement_id, conta=row.conta)
    expected = movement.valor if movement.tipo == 'ENTRADA' else -movement.valor
    if row.movimento_id or expected != row.valor or movement.data != row.data:
        raise ValidationError('Extrato já conciliado ou valor/data divergentes.')
    row.movimento = movement
    row.save()
    gs.audit(user, 'EXTRATO_CONCILIADO', row, {'movimento': movement.pk})

@transaction.atomic
def documento_salvar(user, form):
    from .permissions import document_allowed
    document = form.save(commit=False)
    document.enviado_por = user
    document.clean()
    if not document_allowed(user, document, writing=True):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Documento fora da função/OS atribuída.')
    document.sha256 = hashlib.sha256(document.arquivo.read()).hexdigest()
    document.arquivo.seek(0)
    document.save()
    gs.audit(user, 'DOCUMENTO_ENVIADO', document, {'sha256': document.sha256})
    return document
