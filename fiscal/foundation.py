"""Tenant fiscal orchestration. This phase has NO external transport or vault access."""
import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from platform_core.context import current_organization
from platform_core.modules import require_capability
from gestao.services import write, audit
from operacao import models as m
from .motors import resolver

def permissao(user, capability):
    return require_capability(user, capability)

def simulacao():
    if not getattr(settings, 'FISCAL_SIMULATION_ENABLED', False):
        raise ValidationError('Simulação fiscal desabilitada. Nenhum ambiente oficial está habilitado.')
    if getattr(settings, 'UPLOAD_STORAGE', 'local') != 'local' or getattr(settings, 'PRIVATE_STORAGE', None):
        raise ValidationError('Esta fase exige armazenamento local isolado; storage externo bloqueado.')

def configuracao_valida(config, serie, credencial=None, regra=None):
    simulacao()
    config.full_clean(); serie.full_clean()
    if not config.habilitada or config.ambiente != 'SIMULACAO' or config.motor != 'SIMULADOR' or not config.estabelecimento.ativo:
        raise ValidationError('Somente configuração habilitada de simulação pode operar nesta fase.')
    profile = m.PerfilFiscalEstabelecimento.objects.filter(estabelecimento=config.estabelecimento).first()
    if not profile:
        raise ValidationError('Cadastre o perfil fiscal do estabelecimento.')
    if (serie.estabelecimento_id, serie.tipo, serie.ambiente) != (config.estabelecimento_id, config.tipo, config.ambiente):
        raise ValidationError('Série não pertence ao contexto fiscal selecionado.')
    if credencial:
        credencial.full_clean()
        if not credencial.ativa or credencial.ambiente != config.ambiente or credencial.mecanismo != 'SIMULACAO' or credencial.expira_em and credencial.expira_em <= timezone.now():
            raise ValidationError('Referência fiscal inválida para esta simulação.')
        if not m.VinculoCredencialFiscal.objects.filter(configuracao=config, credencial=credencial).exists():
            raise ValidationError('Referência não vinculada à configuração desta organização.')
    if regra:
        regra.full_clean()
        today = timezone.localdate()
        if regra.configuracao_id != config.pk or regra.inicio > today or regra.fim and regra.fim < today:
            raise ValidationError('Regra tributária não pertence à configuração/vigência selecionada.')
    return profile

def evento(user, doc, name, old='', req=None):
    write(m.EventoFiscal(documento=doc, solicitacao=req, usuario=user, evento=name, anterior=old, posterior=doc.status))
    audit(user, 'FISCAL_SIM_'+name, doc, {'anterior': old, 'posterior': doc.status, 'ambiente': doc.ambiente})

@transaction.atomic
def cadastrar(user, model, **values):
    permissao(user, 'fiscal_gerenciar_credenciais' if model in (m.CredencialFiscal, m.VinculoCredencialFiscal) else 'fiscal_configurar')
    simulacao()
    if 'organization' in values or 'organization_id' in values:
        raise ValidationError('Organização é determinada pela membership, não pelo formulário.')
    if values.get('ambiente', 'SIMULACAO') != 'SIMULACAO':
        raise ValidationError('Ambientes oficiais não estão habilitados.')
    if model not in (m.PerfilFiscalEstabelecimento, m.ConfiguracaoFiscal, m.CredencialFiscal, m.VinculoCredencialFiscal, m.SerieFiscal, m.RegraTributariaFiscal):
        raise ValidationError('Cadastro fiscal não permitido.')
    row = model(**values); row.save()
    audit(user, 'FISCAL_SIM_CADASTRO', row, {'modelo': model.__name__, 'id': row.pk})
    return row

@transaction.atomic
def revogar_credencial(user, credential_id):
    permissao(user, 'fiscal_gerenciar_credenciais')
    simulacao()
    row = m.CredencialFiscal.objects.select_for_update().get(pk=credential_id)
    if row.ativa:
        row.ativa = False; write(row)
        audit(user, 'FISCAL_SIM_REFERENCIA_REVOGADA', row, {'ativa': False, 'versao': row.versao})
    return row

@transaction.atomic
def preparar_documento(user, config_id, serie_id, *, cliente_id=None, venda_id=None, ordem_id=None,
                       descricao='', valor=None, credencial_id=None, regra_id=None):
    permissao(user, 'fiscal_emitir')
    config = m.ConfiguracaoFiscal.objects.get(pk=config_id)
    serie = m.SerieFiscal.objects.get(pk=serie_id)
    cred = m.CredencialFiscal.objects.get(pk=credencial_id) if credencial_id else None
    regra = m.RegraTributariaFiscal.objects.get(pk=regra_id) if regra_id else None
    profile = configuracao_valida(config, serie, cred, regra)
    from clientes.models import Cliente
    from ordens.models import OrdemServico
    customer = Cliente.objects.get(pk=cliente_id) if cliente_id else None
    sale = m.Venda.objects.select_for_update().get(pk=venda_id) if venda_id else None
    order = OrdemServico.objects.get(pk=ordem_id) if ordem_id else None
    if config.tipo in ('NFE', 'NFCE') and (not sale or sale.status != 'FINALIZADA'):
        raise ValidationError('Mercadorias exigem venda confirmada, sem alterar seu estado comercial.')
    if config.tipo == 'NFSE' and sale:
        raise ValidationError('Serviços não usam uma venda PDV como origem genérica.')
    if config.tipo != 'NFSE' and order:
        raise ValidationError('OS de serviço usa o motor NFS-e.')
    if sale:
        existing = m.DocumentoFiscal.objects.filter(venda=sale, tipo=config.tipo, ambiente=config.ambiente, configuracao_fiscal__isnull=False).first()
        if existing:
            if existing.configuracao_fiscal_id != config.pk or existing.serie_fiscal_id != serie.pk:
                raise ValidationError('Venda já possui documento deste tipo em outra configuração.')
            return existing
        if customer and customer.pk != sale.cliente_id:
            raise ValidationError('Cliente deve coincidir com a venda.')
        customer = sale.cliente
        valor = sale.total
    if config.tipo == 'NFSE' and not customer:
        raise ValidationError('Simulação de serviço exige tomador cadastrado nesta organização.')
    if order and order.cliente_id != (customer.pk if customer else None):
        raise ValidationError('Tomador não coincide com a OS.')
    try:
        amount = Decimal(str(valor))
    except ArithmeticError:
        raise ValidationError('Informe valor monetário válido.')
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValidationError('Valor positivo com até duas casas decimais é obrigatório.')
    snapshot = {'sem_valor_fiscal': True, 'tipo': config.tipo, 'ambiente': config.ambiente,
                'emitente': {'organization': str(current_organization().public_id), 'estabelecimento': str(config.estabelecimento.public_id), 'cnpj': config.estabelecimento.cnpj, 'razao_social': current_organization().razao_social},
                'tomador': {'id': customer.pk, 'nome': customer.nome_razao_social} if customer else {'consumidor_nao_identificado': True},
                'valor': str(amount), 'configuracao_versao': config.versao, 'regra_versao': regra.versao if regra else None,
                'regra': regra.parametros if regra else {}, 'venda': sale.snapshot if sale else None}
    doc = m.DocumentoFiscal.objects.create(estabelecimento=config.estabelecimento, configuracao_fiscal=config, serie_fiscal=serie,
        credencial_fiscal=cred, regra_fiscal=regra, tipo=config.tipo, ambiente=config.ambiente, serie=serie.serie,
        modelo={'NFSE': 'NFSE', 'NFE': '55', 'NFCE': '65'}[config.tipo], cliente=customer, venda=sale, ordem=order,
        descricao=descricao or 'Simulação fiscal — sem valor fiscal', valor=amount, snapshot_fiscal=snapshot, criado_por=user)
    if config.tipo == 'NFSE':
        write(m.DetalhesNFSe(documento=doc, competencia=timezone.localdate(), municipio_incidencia=profile.municipio_ibge, codigo_servico=(regra.parametros.get('codigo_servico', '') if regra else '')))
    elif config.tipo == 'NFE':
        write(m.DetalhesNFe(documento=doc, itens_snapshot=sale.snapshot.get('itens', [])))
    else:
        write(m.DetalhesNFCe(documento=doc, pagamentos_snapshot=sale.snapshot.get('pagamentos', [])))
    evento(user, doc, 'PREPARADO')
    return doc

@transaction.atomic
def solicitar(user, doc_id, request_id, *, operacao='EMITIR', motivo='', cenario='AUTORIZAR'):
    permissao(user, 'fiscal_cancelar' if operacao == 'CANCELAR' else 'fiscal_emitir')
    doc = m.DocumentoFiscal.objects.select_for_update().get(pk=doc_id)
    if not doc.configuracao_fiscal_id:
        raise ValidationError('Documento legado preservado; não migrado implicitamente para o novo fluxo.')
    configuracao_valida(doc.configuracao_fiscal, doc.serie_fiscal, doc.credencial_fiscal, doc.regra_fiscal)
    if operacao not in ('EMITIR', 'CANCELAR') or cenario not in ('AUTORIZAR', 'REJEITAR', 'TIMEOUT_ANTES', 'TIMEOUT_APOS'):
        raise ValidationError('Operação/cenário de simulação inválido.')
    rid = uuid.UUID(str(request_id))
    body = {'documento': doc.pk, 'snapshot': doc.snapshot_fiscal, 'operacao': operacao, 'motivo': motivo.strip(), 'cenario': cenario}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    existing = m.SolicitacaoFiscal.objects.filter(request_id=rid).first()
    if existing:
        if existing.payload_hash != digest:
            raise ValidationError('Identificador já usado com dados diferentes.')
        return existing
    existing = m.SolicitacaoFiscal.objects.filter(documento=doc, operacao=operacao).first()
    if existing:
        if existing.payload_hash != digest:
            raise ValidationError('Documento já tem solicitação; consulte/reconcilie sem criar outra.')
        return existing
    if operacao == 'EMITIR' and doc.status != 'RASCUNHO' or operacao == 'CANCELAR' and (doc.status != 'AUTORIZADA' or not motivo.strip()):
        raise ValidationError('Estado/motivo não permite a operação fiscal.')
    if operacao == 'EMITIR':
        serie = m.SerieFiscal.objects.select_for_update().get(pk=doc.serie_fiscal_id)
        number = serie.proximo_numero; serie.proximo_numero += 1; write(serie)
        write(m.ReservaNumeracaoFiscal(serie=serie, documento=doc, numero=number))
        doc.numero = str(number); write(doc)
    req = write(m.SolicitacaoFiscal(documento=doc, request_id=rid, operacao=operacao, solicitante=user, payload_hash=digest, motivo=motivo.strip(), cenario_simulacao=cenario))
    evento(user, doc, 'SOLICITADO', req=req)
    return req

def processar(user, request_pk):
    # A persisted lease avoids double transmission without holding DB locks over transport.
    with transaction.atomic():
        req = m.SolicitacaoFiscal.objects.select_for_update().select_related('documento').get(pk=request_pk)
        permissao(user, 'fiscal_cancelar' if req.operacao == 'CANCELAR' else 'fiscal_emitir')
        doc = req.documento
        configuracao_valida(doc.configuracao_fiscal, doc.serie_fiscal, doc.credencial_fiscal, doc.regra_fiscal)
        if req.estado == 'CONCLUIDA':
            return req
        if req.lease_ate and req.lease_ate > timezone.now():
            return req
        lease = uuid.uuid4(); req.lease_token = lease; req.lease_ate = timezone.now()+timedelta(minutes=2)
        req.estado = 'ENVIANDO'; write(req)
        write(m.TentativaFiscal(solicitacao=req, resultado='INICIADA'))
    motor = resolver(doc.tipo)
    try:
        motor.validar(doc)
        result = motor.consultar(req.pk) or motor.emitir(req)
        expected = {'status', 'tipo', 'modelo', 'ambiente', 'organization', 'documento', 'request_id', 'numero', 'protocolo', 'chave', 'sem_valor_fiscal'}
        if set(result) != expected or result['status'] not in ('AUTORIZADA', 'REJEITADA', 'CANCELADA') or result['organization'] != str(doc.organization.public_id) or result['documento'] != doc.pk or result['ambiente'] != 'SIMULACAO' or result['tipo'] != doc.tipo or result['modelo'] != doc.modelo or result['request_id'] != str(req.request_id) or not result['sem_valor_fiscal'] or result['numero'] != doc.numero or not result['protocolo'].startswith('SIMULACAO-') or not result['chave'].startswith('SIM-'):
            raise ValidationError('Resposta simulada incompatível com a solicitação.')
        if (req.operacao == 'CANCELAR') != (result['status'] == 'CANCELADA'):
            raise ValidationError('Resposta incompatível com a operação.')
        if req.operacao == 'CANCELAR' and result['chave'] != doc.chave:
            raise ValidationError('Cancelamento não pode substituir a identificação do documento.')
    except Exception as exc:
        # Never serialize/log exception content from a future provider.
        outcome = 'RESULTADO_DESCONHECIDO' if isinstance(exc, TimeoutError) else 'FALHA_VALIDACAO'
        with transaction.atomic():
            current = m.SolicitacaoFiscal.objects.select_for_update().get(pk=req.pk)
            if current.lease_token == lease:
                current.estado = outcome; current.lease_ate = None; write(current)
                write(m.TentativaFiscal(solicitacao=current, resultado=outcome))
                evento(user, doc, outcome, req=current)
        return current
    with transaction.atomic():
        current = m.SolicitacaoFiscal.objects.select_for_update().get(pk=req.pk)
        if current.lease_token != lease:
            return current
        permissao(user, 'fiscal_cancelar' if current.operacao == 'CANCELAR' else 'fiscal_emitir')
        configuracao_valida(doc.configuracao_fiscal, doc.serie_fiscal, doc.credencial_fiscal, doc.regra_fiscal)
        doc = m.DocumentoFiscal.objects.select_for_update().get(pk=doc.pk)
        old = doc.status
        doc.status = result['status']; doc.protocolo = result['protocolo']; doc.chave = result['chave']
        if doc.status == 'AUTORIZADA':
            doc.autorizado_em = timezone.now()
        write(doc)
        if doc.status in ('AUTORIZADA', 'CANCELADA'):
            xml = Element('SimulacaoFiscal', {'semValorFiscal': 'true', 'tipo': doc.tipo, 'ambiente': 'SIMULACAO'})
            for key in ('status', 'numero', 'protocolo', 'chave', 'organization'):
                SubElement(xml, key).text = str(result[key])
            content = tostring(xml, encoding='utf-8', xml_declaration=True)
            m.Documento.objects.create(titulo=f'SIMULAÇÃO {doc.tipo} {doc.numero} {doc.status}', tipo='FISCAL_XML',
                arquivo=ContentFile(content, name='simulacao.xml'), fiscal=doc, cliente=doc.cliente,
                sha256=hashlib.sha256(content).hexdigest(), enviado_por=user, disponivel_portal=False)
        current.estado = 'CONCLUIDA'; current.lease_ate = None; write(current)
        write(m.TentativaFiscal(solicitacao=current, resultado=doc.status))
        evento(user, doc, doc.status, old, current)
        return current
