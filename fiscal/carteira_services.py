"""Serviços transacionais e inteligência operacional do VERTYX Contábil (Carteira Fiscal)."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from clientes.models import Cliente, TipoPessoa
from operacao import models as m
from operacao.contabil_models import (
    CertidaoFiscalCarteira,
    ComunicacaoClienteContabil,
    DepartamentoContabil,
    EmpresaCarteiraContabil,
    EventoHistoricoContabil,
    ObrigacaoFiscalCarteira,
    PendenciaFiscalCarteira,
    PreAnaliseComercialCNPJ,
    RegimeTributarioCarteira,
    formatar_cnpj,
    only_digits,
    validar_cnpj_digitos,
)
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership


def _membros_equipe_atual():
    org = current_organization()
    if not org:
        return []
    user_ids = OrganizationMembership.objects.filter(
        organization=org,
        status='ATIVO',
    ).exclude(role='CLIENTE').values_list('user_id', flat=True)
    from contas.models import Usuario
    return list(Usuario.objects.filter(id__in=user_ids, is_active=True).order_by('first_name', 'username'))


def _salvar_anexo_contabil(user, uploaded_file, titulo: str, cliente=None) -> m.Documento | None:
    if not uploaded_file:
        return None
    raw = uploaded_file.read()
    uploaded_file.seek(0)
    digest = hashlib.sha256(raw).hexdigest()
    nome_lower = (uploaded_file.name or '').lower()
    tipo_doc = 'IMAGEM' if nome_lower.endswith(('.png', '.jpg', '.jpeg', '.webp')) else 'PDF'
    doc = m.Documento(
        organization=current_organization(),
        titulo=(titulo or uploaded_file.name or 'Anexo Contábil')[:180],
        tipo=tipo_doc,
        categoria='CERTIFICADO' if 'certid' in (titulo or '').lower() else 'OUTRO',
        arquivo=uploaded_file,
        cliente=cliente,
        sha256=digest,
        enviado_por=user,
    )
    doc.save()
    return doc


def registrar_evento(
    autor,
    empresa: EmpresaCarteiraContabil,
    tipo_evento: str,
    descricao: str,
    pendencia: PendenciaFiscalCarteira | None = None,
    anexo: m.Documento | None = None,
) -> EventoHistoricoContabil:
    ev = EventoHistoricoContabil(
        organization=empresa.organization,
        empresa=empresa,
        pendencia=pendencia,
        tipo_evento=tipo_evento,
        descricao=descricao.strip(),
        anexo=anexo,
        autor=autor,
    )
    ev._service_write = True
    ev.save()
    return ev


def calcular_saude_empresa(empresa: EmpresaCarteiraContabil, hoje: date | None = None) -> dict:
    """Calcula dinamicamente o Índice de Saúde Fiscal (0–100) e diagnóstico real por CNPJ."""
    hoje = hoje or timezone.localdate()
    score = 100
    motivos: list[str] = []

    if empresa.situacao_cadastral != EmpresaCarteiraContabil.SituacaoCadastral.ATIVA:
        score -= 40
        motivos.append(f'Situação cadastral {empresa.get_situacao_cadastral_display()}')

    certidoes = list(empresa.certidoes.all())
    vencidas_irreg = [
        c for c in certidoes
        if c.validade < hoje or c.situacao in {CertidaoFiscalCarteira.Situacao.IRREGULAR, CertidaoFiscalCarteira.Situacao.VENCIDA}
    ]
    a_vencer = [
        c for c in certidoes
        if 0 <= (c.validade - hoje).days <= int(c.dias_alerta_antecedencia or 15)
        and c not in vencidas_irreg
    ]
    if vencidas_irreg:
        score -= min(35, 15 * len(vencidas_irreg))
        motivos.append(f'{len(vencidas_irreg)} certidão(ões) vencida(s)/irregular(es)')
    if a_vencer:
        score -= min(15, 5 * len(a_vencer))
        motivos.append(f'{len(a_vencer)} certidão(ões) próxima(s) do vencimento')

    obrigacoes = list(empresa.obrigacoes.all())
    atrasadas = [
        o for o in obrigacoes
        if o.status not in {ObrigacaoFiscalCarteira.Status.TRANSMITIDA, ObrigacaoFiscalCarteira.Status.PAGA, ObrigacaoFiscalCarteira.Status.DISPENSADA}
        and (o.vencimento < hoje or o.status == ObrigacaoFiscalCarteira.Status.ATRASADA)
    ]
    guias_abertas = [
        o for o in obrigacoes
        if o.natureza in {ObrigacaoFiscalCarteira.Natureza.GUIA, ObrigacaoFiscalCarteira.Natureza.PARCELAMENTO}
        and o.status not in {ObrigacaoFiscalCarteira.Status.PAGA, ObrigacaoFiscalCarteira.Status.DISPENSADA}
    ]
    if atrasadas:
        score -= min(35, 12 * len(atrasadas))
        motivos.append(f'{len(atrasadas)} obrigação(ões)/guia(s) em atraso')

    pendencias_ativas = [p for p in empresa.pendencias.all() if p.status != PendenciaFiscalCarteira.Status.RESOLVIDO]
    criticas = [p for p in pendencias_ativas if p.prioridade == PendenciaFiscalCarteira.Prioridade.CRITICA]
    if criticas:
        score -= min(25, 12 * len(criticas))
        motivos.append(f'{len(criticas)} pendência(s) crítica(s)')
    elif pendencias_ativas:
        score -= min(15, 5 * len(pendencias_ativas))

    if empresa.certificado_validade and empresa.certificado_validade < hoje:
        score -= 15
        motivos.append('Certificado digital vencido')
    elif empresa.certificado_validade and (empresa.certificado_validade - hoje).days <= 30:
        score -= 5
        motivos.append('Certificado digital vence em até 30 dias')

    if empresa.procuracao_ecac_ativa and empresa.procuracao_validade and empresa.procuracao_validade < hoje:
        score -= 10
        motivos.append('Procuração e-CAC vencida')

    score = max(0, min(100, score))
    if score >= 85 and not vencidas_irreg and not atrasadas and not criticas:
        faixa = 'SAUDAVEL'
        situacao_sugerida = EmpresaCarteiraContabil.SituacaoFiscal.REGULAR
    elif score >= 65:
        faixa = 'ATENCAO'
        situacao_sugerida = EmpresaCarteiraContabil.SituacaoFiscal.ALERTA
    elif score >= 40:
        faixa = 'RISCO'
        situacao_sugerida = EmpresaCarteiraContabil.SituacaoFiscal.IRREGULAR
    else:
        faixa = 'CRITICO'
        situacao_sugerida = EmpresaCarteiraContabil.SituacaoFiscal.CRITICA

    return {
        'score': score,
        'faixa': faixa,
        'situacao_calculada': situacao_sugerida,
        'motivos': motivos,
        'certidoes_irregulares': len(vencidas_irreg),
        'certidoes_a_vencer': len(a_vencer),
        'obrigacoes_atrasadas': len(atrasadas),
        'guias_abertas_qtd': len(guias_abertas),
        'guias_abertas_valor': sum((o.valor_guia or Decimal('0.00')) for o in guias_abertas),
        'pendencias_abertas': len(pendencias_ativas),
        'pendencias_criticas': len(criticas),
    }


def sincronizar_situacao_fiscal(empresa: EmpresaCarteiraContabil) -> dict:
    diag = calcular_saude_empresa(empresa)
    if empresa.situacao_fiscal != diag['situacao_calculada']:
        empresa.situacao_fiscal = diag['situacao_calculada']
        empresa.save(update_fields=['situacao_fiscal', 'atualizado_em'])
    return diag


def metricas_dashboard_carteira(responsavel_id: int | None = None, departamento: str = '') -> dict:
    hoje = timezone.localdate()
    limite_alerta = hoje + timedelta(days=30)

    empresas_qs = EmpresaCarteiraContabil.objects.filter(ativo=True).select_related(
        'responsavel_interno', 'cliente'
    ).prefetch_related('certidoes', 'obrigacoes', 'pendencias')
    if responsavel_id:
        empresas_qs = empresas_qs.filter(responsavel_interno_id=responsavel_id)
    if departamento:
        empresas_qs = empresas_qs.filter(departamento_padrao=departamento)

    empresas = list(empresas_qs)
    empresa_ids = [e.pk for e in empresas]

    avaliacoes = []
    soma_scores = 0
    regulares = 0
    irregulares = 0
    clientes_em_risco = 0
    alertas_criticos = 0

    for emp in empresas:
        diag = calcular_saude_empresa(emp, hoje=hoje)
        emp.saude_diag = diag
        soma_scores += diag['score']
        if diag['situacao_calculada'] == EmpresaCarteiraContabil.SituacaoFiscal.REGULAR:
            regulares += 1
        else:
            irregulares += 1
        if diag['faixa'] in {'RISCO', 'CRITICO'}:
            clientes_em_risco += 1
        if diag['faixa'] == 'CRITICO' or diag['pendencias_criticas'] > 0:
            alertas_criticos += max(1, diag['pendencias_criticas'])
        avaliacoes.append((emp, diag))

    indice_medio = round(soma_scores / len(empresas)) if empresas else 100

    cert_qs = CertidaoFiscalCarteira.objects.filter(empresa_id__in=empresa_ids) if responsavel_id or departamento else CertidaoFiscalCarteira.objects.filter(empresa__ativo=True)
    certidoes_vencendo = cert_qs.filter(validade__gte=hoje, validade__lte=limite_alerta).exclude(
        situacao=CertidaoFiscalCarteira.Situacao.IRREGULAR
    ).count()
    certidoes_irregulares = cert_qs.filter(
        Q(validade__lt=hoje) | Q(situacao__in=[CertidaoFiscalCarteira.Situacao.IRREGULAR, CertidaoFiscalCarteira.Situacao.VENCIDA])
    ).count()

    obrig_qs = ObrigacaoFiscalCarteira.objects.filter(empresa_id__in=empresa_ids) if responsavel_id or departamento else ObrigacaoFiscalCarteira.objects.filter(empresa__ativo=True)
    obrig_abertas = obrig_qs.exclude(
        status__in=[
            ObrigacaoFiscalCarteira.Status.TRANSMITIDA,
            ObrigacaoFiscalCarteira.Status.PAGA,
            ObrigacaoFiscalCarteira.Status.DISPENSADA,
        ]
    )
    obrigacoes_pendentes = obrig_abertas.count()
    obrigacoes_atrasadas = obrig_abertas.filter(
        Q(vencimento__lt=hoje) | Q(status=ObrigacaoFiscalCarteira.Status.ATRASADA)
    ).count()
    guias_qs = obrig_abertas.filter(
        natureza__in=[ObrigacaoFiscalCarteira.Natureza.GUIA, ObrigacaoFiscalCarteira.Natureza.PARCELAMENTO]
    )
    guias_em_aberto_qtd = guias_qs.count()
    guias_em_aberto_valor = guias_qs.aggregate(total=Sum('valor_guia'))['total'] or Decimal('0.00')

    pend_qs = PendenciaFiscalCarteira.objects.filter(empresa__ativo=True)
    if responsavel_id:
        pend_qs = pend_qs.filter(Q(responsavel_id=responsavel_id) | Q(empresa__responsavel_interno_id=responsavel_id))
    if departamento:
        pend_qs = pend_qs.filter(departamento=departamento)

    pend_ativas = pend_qs.exclude(status=PendenciaFiscalCarteira.Status.RESOLVIDO)
    por_depto_raw = dict(
        pend_ativas.values('departamento').annotate(total=Count('id')).values_list('departamento', 'total')
    )
    max_depto = max(por_depto_raw.values(), default=1) or 1
    pendencias_por_departamento = [
        {
            'codigo': code,
            'nome': label,
            'total': por_depto_raw.get(code, 0),
            'percentual': round((por_depto_raw.get(code, 0) / max_depto) * 100) if por_depto_raw.get(code, 0) else 0,
        }
        for code, label in DepartamentoContabil.choices
    ]

    resolvidas = list(
        pend_qs.filter(status=PendenciaFiscalCarteira.Status.RESOLVIDO, resolvido_em__isnull=False)
        .only('criado_em', 'resolvido_em')[:200]
    )
    if resolvidas:
        horas = [
            max(0.1, (p.resolvido_em - p.criado_em).total_seconds() / 3600.0)
            for p in resolvidas
            if p.resolvido_em and p.criado_em
        ]
        tempo_medio_horas = round(sum(horas) / len(horas), 1) if horas else None
    else:
        tempo_medio_horas = None

    ranking_criticas = [
        emp for emp, _ in sorted(
            avaliacoes,
            key=lambda item: (item[1]['score'], -item[1]['pendencias_criticas'], -item[1]['obrigacoes_atrasadas']),
        )[:8]
    ]

    return {
        'total_empresas': len(empresas),
        'empresas_regulares': regulares,
        'empresas_irregulares': irregulares,
        'certidoes_vencendo': certidoes_vencendo,
        'certidoes_irregulares': certidoes_irregulares,
        'obrigacoes_pendentes': obrigacoes_pendentes,
        'obrigacoes_atrasadas': obrigacoes_atrasadas,
        'guias_em_aberto_qtd': guias_em_aberto_qtd,
        'guias_em_aberto_valor': guias_em_aberto_valor,
        'alertas_criticos': alertas_criticos + certidoes_irregulares + obrigacoes_atrasadas,
        'clientes_em_risco': clientes_em_risco,
        'pendencias_abertas_total': pend_ativas.count(),
        'indice_saude_fiscal': indice_medio,
        'tempo_medio_resolucao_horas': tempo_medio_horas,
        'pendencias_por_departamento': pendencias_por_departamento,
        'ranking_criticas': ranking_criticas,
        'proximas_obrigacoes': list(obrig_abertas.select_related('empresa', 'responsavel').order_by('vencimento')[:6]),
        'pendencias_urgentes': list(pend_ativas.select_related('empresa', 'responsavel').order_by('prazo', '-criado_em')[:6]),
    }


@transaction.atomic
def salvar_empresa_carteira(user, dados: dict, instance: EmpresaCarteiraContabil | None = None) -> EmpresaCarteiraContabil:
    org = current_organization()
    cnpj = validar_cnpj_digitos(dados.get('cnpj', ''))
    qs_existente = EmpresaCarteiraContabil.objects.filter(cnpj=cnpj)
    if instance:
        qs_existente = qs_existente.exclude(pk=instance.pk)
    if qs_existente.exists():
        raise ValidationError('Este CNPJ já está cadastrado na carteira fiscal desta organização.')

    emp = instance or EmpresaCarteiraContabil(organization=org)
    emp.razao_social = (dados.get('razao_social') or '').strip()
    if not emp.razao_social:
        raise ValidationError('A Razão Social é obrigatória.')
    emp.nome_fantasia = (dados.get('nome_fantasia') or '').strip()
    emp.cnpj = cnpj
    emp.inscricao_estadual = (dados.get('inscricao_estadual') or '').strip()
    emp.inscricao_municipal = (dados.get('inscricao_municipal') or '').strip()
    emp.regime_tributario = dados.get('regime_tributario') or RegimeTributarioCarteira.SIMPLES_NACIONAL
    emp.situacao_cadastral = dados.get('situacao_cadastral') or EmpresaCarteiraContabil.SituacaoCadastral.ATIVA
    emp.situacao_fiscal = dados.get('situacao_fiscal') or EmpresaCarteiraContabil.SituacaoFiscal.REGULAR
    emp.departamento_padrao = dados.get('departamento_padrao') or DepartamentoContabil.FISCAL
    emp.email_contato = (dados.get('email_contato') or '').strip()
    emp.whatsapp_contato = (dados.get('whatsapp_contato') or '').strip()
    emp.cidade = (dados.get('cidade') or '').strip()
    emp.uf = (dados.get('uf') or '').strip().upper()[:2]
    emp.certificado_tipo = dados.get('certificado_tipo') or EmpresaCarteiraContabil.TipoCertificado.NENHUM
    emp.certificado_validade = dados.get('certificado_validade') or None
    emp.procuracao_ecac_ativa = bool(dados.get('procuracao_ecac_ativa'))
    emp.procuracao_validade = dados.get('procuracao_validade') or None
    emp.observacoes = (dados.get('observacoes') or '').strip()

    try:
        emp.honorario_mensal = Decimal(str(dados.get('honorario_mensal') or '0').replace(',', '.'))
    except InvalidOperation:
        emp.honorario_mensal = Decimal('0.00')

    resp_id = dados.get('responsavel_interno_id')
    emp.responsavel_interno_id = int(resp_id) if resp_id else None
    cli_id = dados.get('cliente_id')
    if cli_id:
        emp.cliente = Cliente.objects.filter(pk=int(cli_id)).first()

    novo = emp.pk is None
    emp.save()
    registrar_evento(
        user,
        emp,
        EventoHistoricoContabil.TipoEvento.CADASTRO,
        f'{"Empresa incluída na carteira contábil" if novo else "Ficha fiscal atualizada"} ({emp.get_regime_tributario_display()}).',
    )
    return emp


@transaction.atomic
def importar_clientes_pj_do_erp(user) -> tuple[int, int]:
    """Sincroniza em 1 clique os clientes PJ do ERP com CNPJ válido para a Carteira Contábil."""
    org = current_organization()
    existentes = set(EmpresaCarteiraContabil.objects.values_list('cnpj', flat=True))
    criados = 0
    ignorados = 0
    for cli in Cliente.objects.filter(ativo=True, tipo_pessoa=TipoPessoa.JURIDICA):
        try:
            cnpj = validar_cnpj_digitos(cli.cpf_cnpj)
        except ValidationError:
            ignorados += 1
            continue
        if cnpj in existentes:
            ignorados += 1
            continue
        emp = EmpresaCarteiraContabil(
            organization=org,
            cliente=cli,
            razao_social=cli.nome_razao_social,
            nome_fantasia=cli.nome_fantasia,
            cnpj=cnpj,
            inscricao_estadual=cli.inscricao_estadual,
            inscricao_municipal=cli.inscricao_municipal,
            email_contato=cli.email,
            whatsapp_contato=cli.whatsapp or cli.telefone,
            cidade=cli.cidade,
            uf=cli.uf,
            responsavel_interno=user,
        )
        emp.save()
        existentes.add(cnpj)
        registrar_evento(
            user,
            emp,
            EventoHistoricoContabil.TipoEvento.CADASTRO,
            'Importada automaticamente a partir do cadastro de Clientes PJ do ERP.',
        )
        criados += 1
    return criados, ignorados


def _proximo_codigo_pendencia() -> str:
    ultimo = PendenciaFiscalCarteira.objects.order_by('-id').first()
    seq = 1
    if ultimo and ultimo.codigo.startswith('PEND-'):
        try:
            seq = int(ultimo.codigo.split('-')[1]) + 1
        except (IndexError, ValueError):
            seq = PendenciaFiscalCarteira.objects.count() + 1
    while PendenciaFiscalCarteira.objects.filter(codigo=f'PEND-{seq:04d}').exists():
        seq += 1
    return f'PEND-{seq:04d}'


@transaction.atomic
def criar_pendencia_operacional(user, dados: dict, uploaded_file=None) -> PendenciaFiscalCarteira:
    empresa = EmpresaCarteiraContabil.objects.get(pk=int(dados['empresa_id']))
    anexo = _salvar_anexo_contabil(user, uploaded_file, dados.get('titulo') or 'Evidência Pendência', empresa.cliente)
    resp_id = dados.get('responsavel_id')
    etapa = (
        PendenciaFiscalCarteira.EtapaFluxo.DELEGAR
        if resp_id
        else PendenciaFiscalCarteira.EtapaFluxo.DETECTAR
    )
    pend = PendenciaFiscalCarteira(
        organization=empresa.organization,
        codigo=_proximo_codigo_pendencia(),
        empresa=empresa,
        titulo=(dados.get('titulo') or '').strip(),
        descricao=(dados.get('descricao') or '').strip(),
        departamento=dados.get('departamento') or empresa.departamento_padrao,
        prioridade=dados.get('prioridade') or PendenciaFiscalCarteira.Prioridade.MEDIA,
        status=PendenciaFiscalCarteira.Status.EM_ANDAMENTO if resp_id else PendenciaFiscalCarteira.Status.ABERTO,
        etapa_fluxo=etapa,
        responsavel_id=int(resp_id) if resp_id else None,
        criado_por=user,
        prazo=dados.get('prazo') or None,
        certidao_origem_id=dados.get('certidao_origem_id') or None,
        obrigacao_origem_id=dados.get('obrigacao_origem_id') or None,
        anexo=anexo,
    )
    pend.save()
    registrar_evento(
        user,
        empresa,
        EventoHistoricoContabil.TipoEvento.PENDENCIA_DETECTADA,
        f'Pendência {pend.codigo} aberta ({pend.get_prioridade_display()} · {pend.get_departamento_display()}): {pend.titulo}',
        pendencia=pend,
        anexo=anexo,
    )
    sincronizar_situacao_fiscal(empresa)
    return pend


@transaction.atomic
def avancar_pendencia_operacional(user, pendencia: PendenciaFiscalCarteira, dados: dict, uploaded_file=None) -> PendenciaFiscalCarteira:
    anexo = _salvar_anexo_contabil(user, uploaded_file, f'Anexo {pendencia.codigo}', pendencia.empresa.cliente)
    mudancas = []

    novo_resp = dados.get('responsavel_id')
    if novo_resp is not None and str(novo_resp) != str(pendencia.responsavel_id or ''):
        pendencia.responsavel_id = int(novo_resp) if novo_resp else None
        mudancas.append('responsável atualizado')

    nova_prio = dados.get('prioridade')
    if nova_prio and nova_prio != pendencia.prioridade:
        pendencia.prioridade = nova_prio
        mudancas.append(f'prioridade → {pendencia.get_prioridade_display()}')

    novo_prazo = dados.get('prazo')
    if novo_prazo:
        pendencia.prazo = novo_prazo

    nova_etapa = dados.get('etapa_fluxo')
    if nova_etapa and nova_etapa != pendencia.etapa_fluxo:
        pendencia.etapa_fluxo = nova_etapa
        mudancas.append(f'etapa → {pendencia.get_etapa_fluxo_display()}')

    novo_status = dados.get('status')
    if novo_status and novo_status != pendencia.status:
        pendencia.status = novo_status
        mudancas.append(f'status → {pendencia.get_status_display()}')

    evidencia = (dados.get('evidencia_resolucao') or '').strip()
    if evidencia:
        pendencia.evidencia_resolucao = evidencia

    if pendencia.status == PendenciaFiscalCarteira.Status.RESOLVIDO or pendencia.etapa_fluxo in {
        PendenciaFiscalCarteira.EtapaFluxo.RESOLVER,
        PendenciaFiscalCarteira.EtapaFluxo.AUDITAR,
    }:
        pendencia.status = PendenciaFiscalCarteira.Status.RESOLVIDO
        if not pendencia.resolvido_em:
            pendencia.resolvido_em = timezone.now()
        if pendencia.etapa_fluxo not in {PendenciaFiscalCarteira.EtapaFluxo.RESOLVER, PendenciaFiscalCarteira.EtapaFluxo.AUDITAR}:
            pendencia.etapa_fluxo = PendenciaFiscalCarteira.EtapaFluxo.RESOLVER

    if anexo:
        pendencia.anexo = anexo
        mudancas.append('evidência anexada')

    pendencia.save()

    comentario = (dados.get('comentario') or '').strip()
    texto_log = comentario or (f'Atualização operacional: {", ".join(mudancas)}.' if mudancas else 'Registro operacional atualizado.')
    if evidencia and evidencia not in texto_log:
        texto_log = f'{texto_log} | Evidência: {evidencia}'

    tipo_ev = (
        EventoHistoricoContabil.TipoEvento.AUDITORIA_CONCLUIDA
        if pendencia.etapa_fluxo == PendenciaFiscalCarteira.EtapaFluxo.AUDITAR
        else EventoHistoricoContabil.TipoEvento.PENDENCIA_RESOLVIDA
        if pendencia.status == PendenciaFiscalCarteira.Status.RESOLVIDO
        else EventoHistoricoContabil.TipoEvento.TAREFA_EXECUCAO
        if mudancas
        else EventoHistoricoContabil.TipoEvento.COMENTARIO
    )
    registrar_evento(user, pendencia.empresa, tipo_ev, texto_log, pendencia=pendencia, anexo=anexo)
    sincronizar_situacao_fiscal(pendencia.empresa)
    return pendencia


@transaction.atomic
def registrar_comunicacao_cliente(user, dados: dict) -> ComunicacaoClienteContabil:
    empresa = EmpresaCarteiraContabil.objects.get(pk=int(dados['empresa_id']))
    pendencia = None
    if dados.get('pendencia_id'):
        pendencia = PendenciaFiscalCarteira.objects.filter(pk=int(dados['pendencia_id']), empresa=empresa).first()

    canal = dados.get('canal') or ComunicacaoClienteContabil.Canal.WHATSAPP
    destinatario = (dados.get('destinatario') or '').strip()
    if not destinatario:
        destinatario = empresa.whatsapp_contato if canal == ComunicacaoClienteContabil.Canal.WHATSAPP else empresa.email_contato
    if not destinatario:
        raise ValidationError('Informe o destinatário (WhatsApp ou E-mail) para registrar o envio.')

    com = ComunicacaoClienteContabil(
        organization=empresa.organization,
        empresa=empresa,
        pendencia=pendencia,
        canal=canal,
        tipo=dados.get('tipo') or ComunicacaoClienteContabil.Tipo.SOLICITACAO_DOC,
        destinatario=destinatario,
        assunto=(dados.get('assunto') or '').strip() or 'Comunicado Contábil VERTYX',
        documento_solicitado=(dados.get('documento_solicitado') or '').strip(),
        mensagem=(dados.get('mensagem') or '').strip(),
        enviado_por=user,
    )
    com.save()

    if canal == ComunicacaoClienteContabil.Canal.EMAIL and '@' in destinatario:
        try:
            send_mail(
                subject=f'[VERTYX Contábil] {com.assunto}',
                message=f'{com.mensagem}\n\nDocumento solicitado: {com.documento_solicitado or "N/A"}',
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@vertyxerp.com.br'),
                recipient_list=[destinatario],
                fail_silently=True,
            )
        except Exception:
            pass

    if pendencia and pendencia.status != PendenciaFiscalCarteira.Status.RESOLVIDO:
        pendencia.etapa_fluxo = PendenciaFiscalCarteira.EtapaFluxo.COMUNICAR
        pendencia.status = PendenciaFiscalCarteira.Status.EM_ANDAMENTO
        pendencia.save(update_fields=['etapa_fluxo', 'status'])

    registrar_evento(
        user,
        empresa,
        EventoHistoricoContabil.TipoEvento.COMUNICACAO_CLIENTE,
        f'Comunicação enviada via {com.get_canal_display()} para {destinatario}: "{com.assunto}".',
        pendencia=pendencia,
    )
    return com


@transaction.atomic
def confirmar_recebimento_comunicacao(user, comunicacao: ComunicacaoClienteContabil) -> ComunicacaoClienteContabil:
    if not comunicacao.confirmado_recebimento:
        comunicacao.confirmado_recebimento = True
        comunicacao.confirmado_em = timezone.now()
        comunicacao.save(update_fields=['confirmado_recebimento', 'confirmado_em'])
        registrar_evento(
            user,
            comunicacao.empresa,
            EventoHistoricoContabil.TipoEvento.RECEBIMENTO_CONFIRMADO,
            f'Recebimento confirmado pelo cliente para "{comunicacao.assunto}" ({comunicacao.get_canal_display()}).',
            pendencia=comunicacao.pendencia,
        )
    return comunicacao


@transaction.atomic
def registrar_certidao_carteira(user, dados: dict, uploaded_file=None) -> CertidaoFiscalCarteira:
    empresa = EmpresaCarteiraContabil.objects.get(pk=int(dados['empresa_id']))
    anexo = _salvar_anexo_contabil(user, uploaded_file, f'Certidão {dados.get("esfera")}', empresa.cliente)
    cert = CertidaoFiscalCarteira(
        organization=empresa.organization,
        empresa=empresa,
        esfera=dados['esfera'],
        situacao=dados.get('situacao') or CertidaoFiscalCarteira.Situacao.REGULAR,
        codigo_controle=(dados.get('codigo_controle') or '').strip(),
        emitida_em=dados.get('emitida_em') or None,
        validade=dados['validade'],
        dias_alerta_antecedencia=int(dados.get('dias_alerta_antecedencia') or 15),
        fonte_consulta=(dados.get('fonte_consulta') or 'Controle Operacional').strip(),
        arquivo=anexo,
        observacoes=(dados.get('observacoes') or '').strip(),
    )
    cert.save()
    registrar_evento(
        user,
        empresa,
        EventoHistoricoContabil.TipoEvento.CERTIDAO,
        f'Certidão {cert.get_esfera_display()} registrada ({cert.get_situacao_display()} · validade {cert.validade:%d/%m/%Y}).',
        anexo=anexo,
    )
    if cert.situacao in {CertidaoFiscalCarteira.Situacao.IRREGULAR, CertidaoFiscalCarteira.Situacao.VENCIDA} and dados.get('gerar_pendencia') == '1':
        criar_pendencia_operacional(
            user,
            {
                'empresa_id': empresa.pk,
                'titulo': f'Regularizar Certidão {cert.get_esfera_display()}',
                'descricao': f'Certidão com status {cert.get_situacao_display()} e validade {cert.validade:%d/%m/%Y}.',
                'departamento': DepartamentoContabil.FISCAL,
                'prioridade': PendenciaFiscalCarteira.Prioridade.ALTA,
                'responsavel_id': empresa.responsavel_interno_id,
                'prazo': timezone.localdate() + timedelta(days=5),
                'certidao_origem_id': cert.pk,
            },
        )
    sincronizar_situacao_fiscal(empresa)
    return cert


@transaction.atomic
def registrar_obrigacao_carteira(user, dados: dict, uploaded_file=None) -> ObrigacaoFiscalCarteira:
    empresa = EmpresaCarteiraContabil.objects.get(pk=int(dados['empresa_id']))
    anexo = _salvar_anexo_contabil(user, uploaded_file, f'{dados.get("tipo")} {dados.get("competencia")}', empresa.cliente)
    try:
        valor_guia = Decimal(str(dados.get('valor_guia') or '0').replace(',', '.'))
    except InvalidOperation:
        valor_guia = Decimal('0.00')

    tipo = dados['tipo']
    natureza = dados.get('natureza')
    if not natureza:
        if tipo in {ObrigacaoFiscalCarteira.Tipo.DAS, ObrigacaoFiscalCarteira.Tipo.DARF}:
            natureza = ObrigacaoFiscalCarteira.Natureza.GUIA
        elif tipo == ObrigacaoFiscalCarteira.Tipo.PARCELAMENTO:
            natureza = ObrigacaoFiscalCarteira.Natureza.PARCELAMENTO
        else:
            natureza = ObrigacaoFiscalCarteira.Natureza.DECLARACAO

    resp_id = dados.get('responsavel_id') or empresa.responsavel_interno_id
    obrig = ObrigacaoFiscalCarteira(
        organization=empresa.organization,
        empresa=empresa,
        tipo=tipo,
        natureza=natureza,
        competencia=(dados.get('competencia') or '').strip(),
        vencimento=dados['vencimento'],
        valor_guia=valor_guia,
        status=dados.get('status') or ObrigacaoFiscalCarteira.Status.PENDENTE,
        responsavel_id=int(resp_id) if resp_id else None,
        protocolo_recibo=(dados.get('protocolo_recibo') or '').strip(),
        comprovante=anexo,
        observacoes=(dados.get('observacoes') or '').strip(),
    )
    if obrig.concluida:
        obrig.entregue_em = timezone.now()
    obrig.save()
    registrar_evento(
        user,
        empresa,
        EventoHistoricoContabil.TipoEvento.OBRIGACAO,
        f'Obrigação {obrig.get_tipo_display()} ({obrig.competencia}) agendada com vencimento em {obrig.vencimento:%d/%m/%Y}.',
        anexo=anexo,
    )
    sincronizar_situacao_fiscal(empresa)
    return obrig


@transaction.atomic
def concluir_obrigacao_carteira(user, obrigacao: ObrigacaoFiscalCarteira, protocolo: str = '') -> ObrigacaoFiscalCarteira:
    novo_status = (
        ObrigacaoFiscalCarteira.Status.PAGA
        if obrigacao.natureza in {ObrigacaoFiscalCarteira.Natureza.GUIA, ObrigacaoFiscalCarteira.Natureza.PARCELAMENTO}
        else ObrigacaoFiscalCarteira.Status.TRANSMITIDA
    )
    obrigacao.status = novo_status
    obrigacao.entregue_em = timezone.now()
    if protocolo:
        obrigacao.protocolo_recibo = protocolo.strip()[:100]
    obrigacao.save(update_fields=['status', 'entregue_em', 'protocolo_recibo'])
    registrar_evento(
        user,
        obrigacao.empresa,
        EventoHistoricoContabil.TipoEvento.OBRIGACAO,
        f'{obrigacao.get_tipo_display()} ({obrigacao.competencia}) marcada como {obrigacao.get_status_display()}'
        + (f' · Protocolo: {obrigacao.protocolo_recibo}' if obrigacao.protocolo_recibo else '.'),
    )
    sincronizar_situacao_fiscal(obrigacao.empresa)
    return obrigacao


@transaction.atomic
def realizar_pre_analise_cnpj(user, dados: dict) -> PreAnaliseComercialCNPJ:
    """Valida dígitos oficiais do CNPJ, consulta dados públicos quando disponíveis e gera diagnóstico comercial."""
    cnpj = validar_cnpj_digitos(dados.get('cnpj', ''))
    razao = (dados.get('razao_social') or '').strip()
    uf = (dados.get('uf') or '').strip().upper()[:2]
    cidade = (dados.get('cidade') or '').strip()
    regime = dados.get('regime_estimado') or RegimeTributarioCarteira.SIMPLES_NACIONAL
    pendencias_info = (dados.get('pendencias_conhecidas') or '').strip()

    if not razao and dados.get('consultar_publico') != '0':
        try:
            req = urllib.request.Request(
                f'https://brasilapi.com.br/api/cnpj/v1/{cnpj}',
                headers={'User-Agent': 'VertyxERP-Contabil/1.0'},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
                razao = payload.get('razao_social') or razao
                cidade = payload.get('municipio') or cidade
                uf = (payload.get('uf') or uf)[:2]
                if payload.get('opcao_pelo_mei'):
                    regime = RegimeTributarioCarteira.MEI
                elif payload.get('opcao_pelo_simples'):
                    regime = RegimeTributarioCarteira.SIMPLES_NACIONAL
        except Exception:
            pass

    if not razao:
        razao = f'Prospect Empresarial CNPJ {formatar_cnpj(cnpj)}'

    ja_na_carteira = EmpresaCarteiraContabil.objects.filter(cnpj=cnpj).first()
    pontos_diag = [
        f'CNPJ {formatar_cnpj(cnpj)} matematicamente íntegro (DV Receita Federal validado).',
        f'Regime tributário alvo: {dict(RegimeTributarioCarteira.choices).get(regime, regime)}.',
    ]
    if pendencias_info:
        pontos_diag.append(f'Pontos críticos relatados para regularização: {pendencias_info}.')
        oportunidade = PreAnaliseComercialCNPJ.Oportunidade.ALTA
    elif ja_na_carteira:
        pontos_diag.append('CNPJ já consta ativo na carteira fiscal da organização.')
        oportunidade = PreAnaliseComercialCNPJ.Oportunidade.BAIXA
    else:
        pontos_diag.append('Elegível para onboarding contábil, checklist de procuração e-CAC, certificado A1 e varredura inicial de CND Federal/Estadual/Municipal/FGTS.')
        oportunidade = PreAnaliseComercialCNPJ.Oportunidade.ALTA

    analise = PreAnaliseComercialCNPJ(
        organization=current_organization(),
        cnpj=cnpj,
        razao_social_identificada=razao,
        regime_estimado=regime,
        uf=uf,
        cidade=cidade,
        pendencias_conhecidas=pendencias_info,
        diagnostico_inicial=' '.join(pontos_diag),
        nivel_oportunidade=oportunidade,
        convertido_empresa=ja_na_carteira,
        consultado_por=user,
    )
    analise.save()
    return analise


@transaction.atomic
def converter_pre_analise_em_cliente(user, analise: PreAnaliseComercialCNPJ) -> EmpresaCarteiraContabil:
    existente = EmpresaCarteiraContabil.objects.filter(cnpj=analise.cnpj).first()
    if existente:
        analise.convertido_empresa = existente
        analise.save(update_fields=['convertido_empresa'])
        return existente

    emp = salvar_empresa_carteira(
        user,
        {
            'razao_social': analise.razao_social_identificada,
            'cnpj': analise.cnpj,
            'regime_tributario': analise.regime_estimado,
            'cidade': analise.cidade,
            'uf': analise.uf,
            'responsavel_interno_id': user.pk,
            'observacoes': f'Convertida a partir de Pré-Análise Comercial.\n{analise.diagnostico_inicial}',
        },
    )
    analise.convertido_empresa = emp
    analise.save(update_fields=['convertido_empresa'])

    if analise.pendencias_conhecidas:
        criar_pendencia_operacional(
            user,
            {
                'empresa_id': emp.pk,
                'titulo': 'Regularização inicial pós-captação comercial',
                'descricao': analise.pendencias_conhecidas,
                'departamento': DepartamentoContabil.FISCAL,
                'prioridade': PendenciaFiscalCarteira.Prioridade.ALTA,
                'responsavel_id': user.pk,
                'prazo': timezone.localdate() + timedelta(days=7),
            },
        )
    return emp
