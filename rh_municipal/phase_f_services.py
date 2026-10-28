"""Audited Phase F services; municipal rates and legal rules are never guessed."""
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from platform_core.context import current_organization
from . import phase_f_models as m
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, require_municipal_permission

CENT = Decimal('0.01')


def _require(actor, capability, module):
    org = current_organization()
    if org is None:
        raise PermissionDenied('Selecione uma Prefeitura ativa para continuar.')
    if not public_module_available(org, module):
        raise PermissionDenied('O módulo não está contratado e ativo para esta Prefeitura.')
    require_municipal_permission(actor, capability, module=module)
    return org


def _audit(actor, org, action, entity, entity_id=None, changes=None):
    return m.AuditoriaTributariaMunicipal.objects.create(
        organization=org, acao=action, entidade=entity,
        entidade_id=entity_id, alteracoes=changes or {}, registrado_por=actor,
    )


def _require_record_scope(actor, capability, module, record):
    if not has_municipal_permission(actor, capability, module=module, record=record):
        raise PermissionDenied('O registro está fora do escopo municipal autorizado.')


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def create_contributor(actor, *, data):
    org = _require(actor, 'contribuinte.manage', m.PHASE_F_MODULES['tributos'])
    row = m.ContribuinteMunicipal(organization=org, **data)
    _require_record_scope(actor, 'contribuinte.manage', m.PHASE_F_MODULES['tributos'], row)
    row.save()
    _audit(actor, org, 'CONTRIBUINTE_CRIADO', row._meta.label_lower, row.pk, {'codigo': row.codigo, 'tipo': row.tipo})
    return row


@transaction.atomic
def create_property(actor, *, data):
    org = _require(actor, 'imovel.manage', m.PHASE_F_MODULES['territorio'])
    row = m.ImovelMunicipal(organization=org, **data)
    _require_record_scope(actor, 'imovel.manage', m.PHASE_F_MODULES['territorio'], row)
    row.save()
    _audit(actor, org, 'IMOVEL_CRIADO', row._meta.label_lower, row.pk, {'inscricao': row.inscricao})
    return row


@transaction.atomic
def save_tax_rule(actor, *, data):
    org = _require(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'])
    # Serialize rule-version writes per municipality so concurrent admins
    # cannot create overlapping active windows for the same tax code.
    type(org).objects.select_for_update().get(pk=org.pk)
    row = m.RegraTributariaMunicipal(organization=org, registrada_por=actor, registrada_em=timezone.now(), **data)
    _require_record_scope(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'], row)
    row.full_clean()
    if row.ativa:
        end = row.vigencia_fim or date.max
        overlap = m.RegraTributariaMunicipal.objects.select_for_update().filter(
            organization=org, tributo=row.tributo, codigo=row.codigo, ativa=True,
            vigencia_inicio__lte=end,
        ).exclude(vigencia_fim__lt=row.vigencia_inicio).exists()
        if overlap:
            raise ValidationError('Já existe uma regra ativa com vigência sobreposta para este código e tributo.')
    row.save()
    _audit(actor, org, 'REGRA_TRIBUTARIA_CRIADA', row._meta.label_lower, row.pk,
           {'codigo': row.codigo, 'tributo': row.tributo, 'versao': row.versao, 'ativa': row.ativa})
    return row


@transaction.atomic
def create_tax_launch(actor, *, taxpayer_id, tax_type, base_amount, due_date,
                      rule_id, exercise, property_id=None, competence='', scope=None):
    org = _require(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'])
    rule = m.RegraTributariaMunicipal.objects.select_for_update().filter(
        pk=rule_id, organization=org, tributo=tax_type, ativa=True,
        vigencia_inicio__lte=timezone.localdate(),
    ).filter(models_q_rule_end()).first()
    if rule is None:
        raise ValidationError('Não há regra ativa, vigente e pertencente à Prefeitura para este tributo.')
    rate = rule.parametros.get('aliquota_percentual')
    if rate is None:
        raise ValidationError('A regra não possui alíquota parametrizada; nenhum lançamento foi criado.')
    taxpayer = m.ContribuinteMunicipal.objects.filter(pk=taxpayer_id, organization=org).first()
    if taxpayer is None:
        raise ValidationError('Contribuinte não encontrado nesta Prefeitura.')
    _require_record_scope(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'], taxpayer)
    property_row = None
    if property_id:
        property_row = m.ImovelMunicipal.objects.filter(pk=property_id, organization=org).first()
        if property_row is None:
            raise ValidationError('Imóvel não encontrado nesta Prefeitura.')
        _require_record_scope(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'], property_row)
    if tax_type == m.RegraTributariaMunicipal.Tributo.IPTU and property_row is None:
        raise ValidationError('IPTU exige um imóvel cadastrado nesta Prefeitura.')
    base = _money(base_amount)
    percent = Decimal(str(rate))
    retention_percent = Decimal(str(rule.parametros.get('retencao_percentual', '0')))
    if not Decimal('0') <= retention_percent <= Decimal('100'):
        raise ValidationError('Retenção parametrizada inválida.')
    gross = _money(base * percent / Decimal('100'))
    retention = _money(gross * retention_percent / Decimal('100'))
    total = gross - retention
    if scope is None:
        scope = {field: getattr(taxpayer, f'{field}_id', None) for field in ('secretaria', 'departamento', 'setor', 'unidade')}
    row = m.LancamentoTributarioMunicipal(
        organization=org, numero=f'{tax_type}-{exercise}-{uuid.uuid4().hex[:12].upper()}',
        tributo=tax_type, exercicio=exercise, competencia=competence,
        contribuinte=taxpayer, imovel=property_row, regra=rule,
        regra_snapshot={**rule.parametros, 'codigo': rule.codigo, 'versao': rule.versao},
        base_calculo=base, aliquota_percentual=percent, retencao=retention,
        valor_total=total, vencimento=due_date, criado_por=actor, **(scope or {}),
    )
    _require_record_scope(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'], row)
    row.save()
    _audit(actor, org, 'LANCAMENTO_TRIBUTARIO_CRIADO', row._meta.label_lower, row.pk,
           {'numero': row.numero, 'tributo': row.tributo, 'regra_versao': rule.versao})
    return row


def models_q_rule_end():
    from django.db.models import Q
    return Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=timezone.localdate())


@transaction.atomic
def create_installments(actor, *, launch_id, count, first_due, interval_days=30):
    org = _require(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'])
    launch = m.LancamentoTributarioMunicipal.objects.select_for_update().filter(pk=launch_id, organization=org).first()
    if launch is None or launch.status != m.LancamentoTributarioMunicipal.Status.ABERTO:
        raise ValidationError('Lançamento não encontrado ou não está aberto.')
    _require_record_scope(actor, 'tributo.manage', m.PHASE_F_MODULES['tributos'], launch)
    if launch.parcelas.exists():
        raise ValidationError('O lançamento já possui parcelas; elas não serão substituídas.')
    if not 1 <= int(count) <= 60 or not 1 <= int(interval_days) <= 366:
        raise ValidationError('Quantidade ou intervalo de parcelas fora dos limites permitidos.')
    cents = int((launch.valor_total * 100).to_integral_value(rounding=ROUND_HALF_UP))
    quotient, remainder = divmod(cents, int(count))
    rows = []
    for index in range(int(count)):
        cents_for_row = quotient + (1 if index < remainder else 0)
        rows.append(m.ParcelaTributariaMunicipal(
            organization=org, lancamento=launch, numero=index + 1,
            vencimento=first_due + timezone.timedelta(days=index * int(interval_days)),
            valor=Decimal(cents_for_row) / 100,
            secretaria_id=launch.secretaria_id, departamento_id=launch.departamento_id,
            setor_id=launch.setor_id, unidade_id=launch.unidade_id,
        ))
    for row in rows:
        row.save()
    _audit(actor, org, 'PARCELAS_TRIBUTARIAS_CRIADAS', launch._meta.label_lower, launch.pk,
           {'quantidade': int(count)})
    return list(launch.parcelas.order_by('numero'))


@transaction.atomic
def record_manual_payment(actor, *, installment_id, amount, request_id, channel='MANUAL', reference=''):
    org = _require(actor, 'arrecadacao.manage', m.PHASE_F_MODULES['tributos'])
    try:
        request_uuid = uuid.UUID(str(request_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError('Identificador de operação inválido.') from exc
    previous = m.PagamentoArrecadacaoMunicipal.objects.filter(organization=org, request_id=request_uuid).first()
    amount = _money(amount)
    if previous:
        _require_record_scope(actor, 'arrecadacao.manage', m.PHASE_F_MODULES['tributos'], previous)
        if previous.parcela_id != int(installment_id) or previous.valor != amount:
            raise ValidationError('O identificador da operação já foi usado com outros dados.')
        return previous
    installment = m.ParcelaTributariaMunicipal.objects.select_for_update().filter(pk=installment_id, organization=org).first()
    if installment is None:
        raise ValidationError('Parcela não encontrada nesta Prefeitura.')
    _require_record_scope(actor, 'arrecadacao.manage', m.PHASE_F_MODULES['tributos'], installment)
    paid = sum((p.valor for p in installment.pagamentos.filter(status=m.PagamentoArrecadacaoMunicipal.Status.REGISTRADO)), Decimal('0'))
    if amount <= 0 or amount > installment.valor - paid:
        raise ValidationError('O valor excede o saldo pendente da parcela.')
    try:
        with transaction.atomic():
            payment = m.PagamentoArrecadacaoMunicipal.objects.create(
                organization=org, parcela=installment, valor=amount,
                request_id=request_uuid, canal=channel, referencia_externa=reference,
                registrado_por=actor, secretaria_id=installment.secretaria_id,
                departamento_id=installment.departamento_id, setor_id=installment.setor_id,
                unidade_id=installment.unidade_id,
            )
    except IntegrityError:
        payment = m.PagamentoArrecadacaoMunicipal.objects.get(organization=org, request_id=request_uuid)
        if payment.parcela_id != installment.pk or payment.valor != amount:
            raise ValidationError('Conflito de idempotência: a operação já existe com outros dados.')
        return payment
    launch = installment.lancamento
    total_due = sum((p.valor for p in launch.parcelas.all()), Decimal('0'))
    total_paid = sum((p.valor for part in launch.parcelas.all() for p in part.pagamentos.filter(status=m.PagamentoArrecadacaoMunicipal.Status.REGISTRADO)), Decimal('0'))
    if total_paid >= total_due:
        launch.status = m.LancamentoTributarioMunicipal.Status.PAGO
    elif total_paid:
        launch.status = m.LancamentoTributarioMunicipal.Status.PARCIAL
    launch.save(update_fields=['status'])
    _audit(actor, org, 'PAGAMENTO_ARRECADACAO_REGISTRADO', payment._meta.label_lower, payment.pk,
           {'valor': str(amount), 'canal': channel, 'referencia_externa': bool(reference)})
    return payment


@transaction.atomic
def register_active_debt(actor, *, launch_id):
    org = _require(actor, 'divida.manage', m.PHASE_F_MODULES['tributos'])
    launch = m.LancamentoTributarioMunicipal.objects.select_for_update().filter(pk=launch_id, organization=org).first()
    if launch is None:
        raise ValidationError('Lançamento não encontrado nesta Prefeitura.')
    _require_record_scope(actor, 'divida.manage', m.PHASE_F_MODULES['tributos'], launch)
    if launch.vencimento >= timezone.localdate():
        raise ValidationError('O lançamento ainda não venceu.')
    paid = sum((p.valor for part in launch.parcelas.all() for p in part.pagamentos.filter(status=m.PagamentoArrecadacaoMunicipal.Status.REGISTRADO)), Decimal('0'))
    open_value = launch.valor_total - paid
    if open_value <= 0 or launch.divida_ativa.filter(status__in=['INSCRITA', 'PARCELADA']).exists():
        raise ValidationError('Não existe saldo vencido elegível ou a inscrição já existe.')
    row = m.InscricaoDividaAtivaMunicipal.objects.create(
        organization=org, numero=f'DA-{launch.exercicio}-{uuid.uuid4().hex[:12].upper()}',
        lancamento=launch, contribuinte=launch.contribuinte, valor_inscrito=open_value,
        inscrita_em=timezone.localdate(), registrado_por=actor,
        secretaria_id=launch.secretaria_id, departamento_id=launch.departamento_id,
        setor_id=launch.setor_id, unidade_id=launch.unidade_id,
    )
    _audit(actor, org, 'DIVIDA_ATIVA_INSCRITA', row._meta.label_lower, row.pk,
           {'numero': row.numero, 'lancamento': launch.numero, 'valor': str(open_value)})
    return row


@transaction.atomic
def cancel_active_debt(actor, *, debt_id, reason):
    org = _require(actor, 'divida.manage', m.PHASE_F_MODULES['tributos'])
    row = m.InscricaoDividaAtivaMunicipal.objects.select_for_update().filter(pk=debt_id, organization=org).first()
    if row is None or row.status not in {m.InscricaoDividaAtivaMunicipal.Status.INSCRITA, m.InscricaoDividaAtivaMunicipal.Status.PARCELADA}:
        raise ValidationError('Inscrição ativa não encontrada nesta Prefeitura.')
    _require_record_scope(actor, 'divida.manage', m.PHASE_F_MODULES['tributos'], row)
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('Informe o motivo do cancelamento para preservar a auditoria.')
    row.status = m.InscricaoDividaAtivaMunicipal.Status.CANCELADA
    row.motivo_cancelamento = reason[:4000]
    row.save(update_fields=['status', 'motivo_cancelamento'])
    _audit(actor, org, 'DIVIDA_ATIVA_CANCELADA', row._meta.label_lower, row.pk,
           {'numero': row.numero, 'motivo': reason[:500]})
    return row


@transaction.atomic
def create_nfse_draft(actor, *, data):
    org = _require(actor, 'nfse.manage', m.PHASE_F_MODULES['nfse'])
    row = m.NotaServicoMunicipal(
        organization=org,
        numero_interno=f'RASC-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}',
        status=m.NotaServicoMunicipal.Status.RASCUNHO,
        parametros_snapshot={'transmissao': 'PENDENTE_INTEGRACAO_OFICIAL'},
        criado_por=actor, **data,
    )
    _require_record_scope(actor, 'nfse.manage', m.PHASE_F_MODULES['nfse'], row)
    row.save()
    _audit(actor, org, 'RASCUNHO_NFSE_CRIADO', row._meta.label_lower, row.pk,
           {'numero_interno': row.numero_interno})
    return row


def transmit_nfse(*args, **kwargs):
    """No official provider/municipal rules are configured in Phase F."""
    raise ValidationError('Transmissão NFS-e indisponível: integração oficial e parâmetros municipais ainda não foram homologados.')
