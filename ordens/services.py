import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .models import OrdemServico, Auditoria, Localizacao, Foto, Conferencia, Assinatura, Status
from platform_core.access import require_erp, has_erp_access, effective_role
from platform_core.context import current_organization


def gestor(user):
    return has_erp_access(user) and effective_role(user) in ['ADMIN', 'GESTOR']


def autorizar(user, ordem=None, administrativo=False):
    require_erp(user)
    if ordem and ordem.organization_id != current_organization().pk:
        raise PermissionDenied('OS de outra organização.')
    if gestor(user):
        return
    if not administrativo and user.is_authenticated and user.is_active and user.is_tecnico and ordem and ordem.tecnico_id and ordem.tecnico.usuario_id == user.pk:
        return
    raise PermissionDenied('Você não tem autorização para esta OS.')


def visiveis(user):
    qs = OrdemServico.objects.select_related('cliente', 'unidade', 'equipamento', 'tecnico')
    if not has_erp_access(user):
        return qs.none()
    if gestor(user):
        return qs
    if user.is_authenticated and user.is_active and user.is_tecnico:
        return qs.filter(tecnico__usuario=user)
    return qs.none()


def auditar(ordem, user, acao, alteracoes=None, justificativa=''):
    row = Auditoria.objects.create(ordem=ordem, usuario=user, acao=acao, alteracoes=alteracoes or {}, justificativa=justificativa)
    from operacao.notifications import event
    event(user, acao, ordem)
    return row


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def datahora(value):
    return timezone.localtime(value).isoformat() if value else ''


def endereco(obj):
    return ', '.join(str(v).strip() for v in [obj.endereco, obj.numero, getattr(obj, 'bairro', ''), obj.cidade, obj.uf] if str(v).strip()) or 'Endereço não informado'


def geo_data(geo):
    if not geo:
        return {'resultado': 'Não registrada', 'latitude': '', 'longitude': '', 'precisao': '', 'data': '', 'usuario': '', 'mapa': ''}
    return {'resultado': geo.get_resultado_display(), 'latitude': str(geo.latitude) if geo.latitude is not None else '', 'longitude': str(geo.longitude) if geo.longitude is not None else '', 'precisao': str(geo.precisao) if geo.precisao is not None else '', 'data': datahora(geo.registrado_em), 'usuario': str(geo.usuario), 'mapa': geo.mapa_url}


def snapshot(ordem, final=None):
    ordem.validate_tenant()
    cliente, unidade, equipamento, tecnico = ordem.cliente, ordem.unidade, ordem.equipamento, ordem.tecnico
    inicio = ordem.localizacoes.filter(ciclo=ordem.ciclo, evento='INICIO').first()
    dados = {
        'organization': {'id': str(ordem.organization.public_id), 'nome': ordem.organization.display_name, 'razao_social': ordem.organization.razao_social, 'cnpj': ordem.organization.cnpj_formatado, 'email': ordem.organization.email, 'telefone': ordem.organization.telefone, 'details': ordem.organization.document_details, 'logo_key': ordem.organization.logo_key},
        'numero': ordem.numero, 'codigo': str(ordem.codigo), 'ciclo': ordem.ciclo,
        'cliente_id': cliente.pk, 'cliente': str(cliente), 'documento': cliente.cpf_cnpj,
        'cliente_endereco': endereco(cliente),
        'cliente_telefone': cliente.telefone, 'cliente_email': cliente.email,
        'unidade_id': unidade.pk if unidade else None, 'unidade': str(unidade) if unidade else 'Sem unidade',
        'local': endereco(unidade) if unidade else endereco(cliente),
        'equipamento_id': equipamento.pk, 'equipamento': equipamento.nome,
        'patrimonio': equipamento.codigo_interno, 'serie': equipamento.numero_serie,
        'fabricante': equipamento.fabricante, 'modelo': equipamento.modelo,
        'tecnico_id': tecnico.pk if tecnico else None, 'tecnico': tecnico.nome if tecnico else 'Não atribuído', 'registro_profissional': tecnico.registro_profissional if tecnico else '',
        'tipo': ordem.get_tipo_atendimento_display(), 'defeito': ordem.defeito,
        'diagnostico': ordem.diagnostico, 'servico_executado': ordem.servico_executado,
        'pecas': ordem.pecas, 'observacoes': ordem.observacoes, 'abertura': datahora(ordem.abertura),
        'inicio': datahora(ordem.inicio), 'conclusao': datahora(final.registrado_em if final else ordem.conclusao),
        'localizacao_inicio': geo_data(inicio), 'localizacao_final': geo_data(final),
        'fotos': [{'id': f.pk, 'descricao': f.descricao, 'sha256': f.sha256, 'data': datahora(f.criado_em), 'usuario': str(f.usuario)} for f in ordem.fotos.order_by('pk')],
    }
    from gestao.services import pecas_snapshot
    stock = pecas_snapshot(ordem)
    if stock:
        dados['pecas_estoque'] = stock
        dados['pecas'] = '\n'.join(filter(None, [ordem.pecas] + [f"{item['tipo']}: {item['sku']} · {item['descricao']} · {item['quantidade']}" for item in stock]))
    if ordem.valor_cobranca:
        dados['valor_cobranca'] = str(ordem.valor_cobranca)
    if ordem.contrato_id:
        dados['contrato'] = ordem.contrato.numero
    if ordem.prioridade and ordem.prioridade != 'NORMAL':
        dados['prioridade'] = ordem.get_prioridade_display()
    if ordem.checklist:
        import copy
        dados['checklist'] = copy.deepcopy(ordem.checklist)
    if ordem.horas or ordem.deslocamento_km:
        dados['horas'] = str(ordem.horas)
        dados['deslocamento_km'] = str(ordem.deslocamento_km)
    return dados


def salvar_transicao(ordem):
    ordem._transicao_autorizada = True
    try:
        ordem.save()
    finally:
        ordem._transicao_autorizada = False


@transaction.atomic
def criar(user, form):
    autorizar(user, administrativo=True)
    from operacao.planning_services import lock_planning, validate_conflicts
    lock_planning()
    ordem = form.save(commit=False)
    validate_conflicts(user,ordem)
    ordem.save()
    form.save_m2m()
    auditar(ordem, user, 'CRIACAO', snapshot(ordem))
    return ordem


@transaction.atomic
def editar(user, pk, data):
    from .forms import OrdemForm
    from operacao.planning_services import lock_planning, validate_conflicts
    lock_planning()
    ordem = OrdemServico.objects.select_for_update().get(pk=pk)
    schedule_before=(ordem.tecnico_id,ordem.agendada_para,ordem.agendada_ate)
    autorizar(user, ordem)
    if ordem.status in ['FINALIZADA', 'APROVADA', 'FATURADA', 'CANCELADA']:
        raise ValidationError('Reabra a OS antes de editar.')
    form = OrdemForm(data, instance=ordem, operacional=not gestor(user))
    before = snapshot(ordem)
    if not form.is_valid():
        return ordem, form
    if form.cleaned_data['revisao'] != ordem.revisao:
        raise ValidationError('A OS mudou em outra sessão. Recarregue antes de editar.')
    if schedule_before != (ordem.tecnico_id,ordem.agendada_para,ordem.agendada_ate):
        validate_conflicts(user,ordem)
    ordem.revisao += 1
    form.save()
    after = snapshot(ordem)
    changes = {k: {'anterior': before.get(k), 'posterior': after.get(k)} for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    if schedule_before != (ordem.tecnico_id,ordem.agendada_para,ordem.agendada_ate):
        changes['agenda']={'anterior':[str(value) for value in schedule_before],'posterior':[str(value) for value in (ordem.tecnico_id,ordem.agendada_para,ordem.agendada_ate)]}
    auditar(ordem, user, 'ALTERACAO_APOS_REABERTURA' if ordem.ciclo > 1 else 'ALTERACAO', changes)
    return ordem, None


def registrar_geo(ordem, user, evento, data):
    geo = Localizacao.objects.create(ordem=ordem, usuario=user, ciclo=ordem.ciclo, evento=evento, **data)
    auditar(ordem, user, 'GEOLOCALIZACAO_' + evento, geo_data(geo))
    return geo


@transaction.atomic
def iniciar(user, pk, data):
    ordem = OrdemServico.objects.select_for_update().get(pk=pk)
    autorizar(user, ordem)
    if ordem.status not in [Status.ABERTA, Status.AGENDADA]:
        raise ValidationError('Somente uma OS aberta pode iniciar atendimento.')
    if not ordem.tecnico_id:
        raise ValidationError('Atribua um técnico antes de iniciar o atendimento.')
    ordem.inicio = timezone.now()
    ordem.status = Status.EXECUCAO
    ordem.revisao += 1
    registrar_geo(ordem, user, 'INICIO', data)
    salvar_transicao(ordem)
    auditar(ordem, user, 'INICIO', {'inicio': datahora(ordem.inicio), 'status': {'anterior': Status.ABERTA, 'posterior': Status.EXECUCAO}})
    return ordem


@transaction.atomic
def adicionar_foto(user, pk, data):
    ordem = OrdemServico.objects.select_for_update().get(pk=pk)
    autorizar(user, ordem)
    if ordem.status != Status.EXECUCAO:
        raise ValidationError('Fotos só podem ser adicionadas durante o atendimento.')
    arquivo = data['arquivo']
    raw = arquivo.read()
    arquivo.seek(0)
    foto = Foto.objects.create(ordem=ordem, usuario=user, arquivo=arquivo, descricao=data['descricao'], sha256=hashlib.sha256(raw).hexdigest())
    ordem.revisao += 1
    ordem.save()
    auditar(ordem, user, 'FOTO_ADICIONADA', {'foto': foto.pk, 'sha256': foto.sha256})
    return foto


@transaction.atomic
def preparar(user, pk, data):
    ordem = OrdemServico.objects.select_for_update().get(pk=pk)
    autorizar(user, ordem)
    if ordem.status != Status.EXECUCAO or not ordem.diagnostico.strip() or not ordem.servico_executado.strip():
        raise ValidationError('Registre diagnóstico e serviço executado durante o atendimento antes da conferência.')
    if any(row.get('obrigatorio') and not row.get('concluido') for row in ordem.checklist):
        raise ValidationError('Conclua os itens obrigatórios do checklist antes de assinar.')
    final = registrar_geo(ordem, user, 'FINAL', data)
    dados = snapshot(ordem, final)
    return Conferencia.objects.create(ordem=ordem, usuario=user, revisao=ordem.revisao, ciclo=ordem.ciclo, dados=dados, digest=digest(dados), localizacao_final=final, issuer=dados['organization'])


@transaction.atomic
def finalizar(user, pk, conferencia_id, data):
    import base64
    ordem = OrdemServico.objects.select_for_update().get(pk=pk)
    autorizar(user, ordem)
    conferencia = Conferencia.objects.get(pk=conferencia_id, ordem=ordem, usuario=user)
    if ordem.status != Status.EXECUCAO or conferencia.ciclo != ordem.ciclo or conferencia.revisao != ordem.revisao:
        raise ValidationError('OS alterada ou finalizada. Faça uma nova conferência.')
    if timezone.now() - conferencia.criado_em > timezone.timedelta(minutes=30):
        raise ValidationError('Conferência expirada. Solicite novamente a localização e confira os dados.')
    if digest(snapshot(ordem, conferencia.localizacao_final)) != conferencia.digest:
        raise ValidationError('Os dados conferidos mudaram. Faça uma nova conferência.')
    assinatura = Assinatura.objects.create(ordem=ordem, conferencia=conferencia, ciclo=ordem.ciclo, nome=data['nome'], cargo=data['cargo'], imagem=data['imagem'], imagem_sha256=hashlib.sha256(base64.b64decode(data['imagem'])).hexdigest(), usuario=user)
    ordem.conclusao = conferencia.localizacao_final.registrado_em
    ordem.status = Status.FINALIZADA
    ordem.revisao += 1
    salvar_transicao(ordem)
    auditar(ordem, user, 'ASSINATURA', {'assinatura': assinatura.pk, 'conferencia_sha256': conferencia.digest, 'imagem_sha256': assinatura.imagem_sha256})
    auditar(ordem, user, 'FINALIZACAO', {'status': {'anterior': Status.EXECUCAO, 'posterior': Status.FINALIZADA}, 'conclusao': datahora(ordem.conclusao)})
    from gestao.services import gerar_da_os
    gerar_da_os(user, ordem)
    from operacao.models import PreventivaProgramada
    occurrence = PreventivaProgramada.objects.filter(ordem=ordem).first()
    if occurrence:
        plan = occurrence.plano
        completed = timezone.localdate(ordem.conclusao)
        if not plan.ultima_execucao or completed > plan.ultima_execucao:
            plan.ultima_execucao = completed
            plan.save()
    if ordem.tipo_atendimento == 'PREVENTIVA':
        equipment = ordem.equipamento
        date = timezone.localdate(ordem.conclusao)
        if not equipment.data_ultima_preventiva or date > equipment.data_ultima_preventiva:
            equipment.data_ultima_preventiva = date
            equipment.save()
    return assinatura


@transaction.atomic
def reabrir(user, pk, motivo):
    ordem = OrdemServico.objects.select_for_update().get(pk=pk)
    autorizar(user, ordem, administrativo=True)
    if ordem.status not in ['FINALIZADA', 'APROVADA', 'FATURADA']:
        raise ValidationError('Somente OS finalizada pode ser reaberta.')
    before = {'status': ordem.status, 'inicio': datahora(ordem.inicio), 'conclusao': datahora(ordem.conclusao), 'ciclo': ordem.ciclo}
    ordem.status = Status.ABERTA
    ordem.inicio = ordem.conclusao = None
    ordem.ciclo += 1
    for row in ordem.checklist:
        row['concluido'] = False
    ordem.revisao += 1
    salvar_transicao(ordem)
    after = {'status': ordem.status, 'inicio': '', 'conclusao': '', 'ciclo': ordem.ciclo}
    auditar(ordem, user, 'REABERTURA', {k: {'anterior': before[k], 'posterior': after[k]} for k in before}, motivo)
    return ordem
