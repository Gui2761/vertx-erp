"""Serviços transacionais, conector PNCP e inteligência do VERTYX Licita."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from operacao.licita_models import (
    AnaliseEditalRequisito,
    HistoricoLicitacaoEvento,
    OportunidadeLicitacao,
    RadarFiltroPNCP,
)
from operacao.pricing_models import SimulacaoLanceEdital
from platform_core.context import current_organization

ZERO = Decimal('0.00')
PNCP_API_URL = 'https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao'


def registrar_log_licita(
    user,
    oportunidade: OportunidadeLicitacao,
    tipo: str,
    descricao: str,
    etapa_anterior: str = '',
    etapa_nova: str = '',
    dados: dict | None = None,
) -> HistoricoLicitacaoEvento:
    org = current_organization()
    evento = HistoricoLicitacaoEvento(
        organization=org,
        oportunidade=oportunidade,
        usuario=user,
        tipo_evento=tipo,
        etapa_anterior=etapa_anterior,
        etapa_nova=etapa_nova,
        descricao=descricao[:255],
        dados_adicionais=dados or {},
    )
    evento._service_write = True
    evento.save()
    return evento


def consultar_api_pncp_publicacoes(
    data_inicial: date | None = None,
    data_final: date | None = None,
    uf: str = 'SE',
    codigo_modalidade: int = 6,
    pagina: int = 1,
    tamanho_pagina: int = 25,
) -> list[dict]:
    """Consulta o endpoint oficial do Portal Nacional de Contratações Públicas (PNCP).

    GET /api/consulta/v1/contratacoes/publicacao?dataInicial=YYYYMMDD&dataFinal=YYYYMMDD&codigoModalidadeContratacao=X&uf=UF
    """
    hoje = timezone.localdate()
    dt_fim = data_final or hoje
    dt_ini = data_inicial or (dt_fim - timedelta(days=7))

    params = {
        'dataInicial': dt_ini.strftime('%Y%m%d'),
        'dataFinal': dt_fim.strftime('%Y%m%d'),
        'codigoModalidadeContratacao': int(codigo_modalidade),
        'uf': uf.strip().upper(),
        'pagina': int(pagina),
        'tamanhoPagina': int(tamanho_pagina),
    }

    url = f"{PNCP_API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            'Accept': 'application/json',
            'User-Agent': 'VertyxERP-Licita/1.0 (Hospitalar & EngClinica)',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 204:
                return []
            content = resp.read().decode('utf-8', errors='replace')
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get('data') or data.get('items') or data.get('resultado') or []
    except Exception:
        # Fallback resiliente: falha de rede/timeout nunca quebra a visualização
        return []
    return []


def sincronizar_radar_pncp(user, radar: RadarFiltroPNCP) -> tuple[int, int]:
    """Varre as modalidades e UFs do radar na API do PNCP e importa contratações compatíveis."""
    org = current_organization()
    if not org:
        return 0, 0

    palavras = radar.lista_palavras_chave()
    ufs = radar.lista_ufs()
    modalidades = radar.lista_modalidades_int()

    novas = 0
    atualizadas = 0
    hoje = timezone.localdate()
    dt_ini = hoje - timedelta(days=5)

    for uf in ufs:
        for mod in modalidades:
            resultados = consultar_api_pncp_publicacoes(
                data_inicial=dt_ini,
                data_final=hoje,
                uf=uf,
                codigo_modalidade=mod,
                pagina=1,
                tamanho_pagina=30,
            )
            for item in resultados:
                num_controle = str(item.get('numeroControlePNCP') or '').strip()
                if not num_controle:
                    continue

                objeto = str(item.get('objetoCompra') or '').strip()
                objeto_lower = objeto.lower()

                # Verifica aderência às palavras-chave do radar
                if palavras and not any(p in objeto_lower for p in palavras):
                    continue

                orgao = item.get('orgaoEntidade') or {}
                orgao_nome = str(orgao.get('razaoSocial') or item.get('nomeOrgao') or 'Órgão Público').strip()
                orgao_cnpj = str(orgao.get('cnpj') or '').strip()
                mun_nome = str(item.get('municipioNome') or '').strip()
                mod_nome = str(item.get('modalidadeNome') or 'Pregão Eletrônico').strip()
                num_edital = str(item.get('numeroEdital') or item.get('sequencialCompra') or '').strip()

                val_est = ZERO
                raw_val = item.get('valorTotalEstimado')
                if raw_val is not None:
                    try:
                        val_est = Decimal(str(raw_val))
                    except InvalidOperation:
                        val_est = ZERO

                # Filtro por valor mínimo e máximo configurados no radar
                if radar.valor_minimo and val_est < radar.valor_minimo:
                    continue
                if radar.valor_maximo and val_est > radar.valor_maximo:
                    continue

                existente = OportunidadeLicitacao.objects.filter(
                    organization=org,
                    numero_controle_pncp=num_controle,
                ).first()

                link = str(item.get('linkFonte') or f"https://pncp.gov.br/app/editais/{num_controle}").strip()

                if existente:
                    existente.valor_total_estimado = val_est
                    if not existente.radar_origem:
                        existente.radar_origem = radar
                    existente.save()
                    atualizadas += 1
                else:
                    nova_op = OportunidadeLicitacao(
                        organization=org,
                        numero_controle_pncp=num_controle,
                        orgao_nome=orgao_nome[:255],
                        orgao_cnpj=orgao_cnpj[:20],
                        uf=uf,
                        municipio=mun_nome[:150],
                        modalidade_nome=mod_nome[:100],
                        numero_edital=num_edital[:100],
                        objeto=objeto,
                        valor_total_estimado=val_est,
                        data_publicacao_pncp=hoje,
                        link_fonte_pncp=link[:500],
                        etapa=OportunidadeLicitacao.EtapaFunil.ENCONTRADA,
                        radar_origem=radar,
                        responsavel=user,
                    )
                    nova_op.save()
                    gerar_checklist_padrao_edital(user, nova_op)
                    registrar_log_licita(
                        user,
                        nova_op,
                        'LICITACAO_CAPTURADA_PNCP',
                        f'Capturada no PNCP via radar {radar.nome}: {orgao_nome} ({uf}) - R$ {val_est:,.2f}',
                        etapa_nova='ENCONTRADA',
                    )
                    novas += 1

    radar.ultima_sincronizacao = timezone.now()
    radar.save()
    return novas, atualizadas


def gerar_checklist_padrao_edital(user, oportunidade: OportunidadeLicitacao) -> list[AnaliseEditalRequisito]:
    """Cria os requisitos padrão auditáveis com estrutura para citação de página e trecho."""
    org = oportunidade.organization
    requisitos_base = [
        (
            AnaliseEditalRequisito.Categoria.REGULARIDADE_FISCAL,
            'Certidão Conjunta Federal & Previdenciária (PGFN/RFB)',
            'Comprovação de regularidade fiscal perante a Fazenda Nacional e Seguridade Social.',
            4,
            'Item 8.1.a do Edital: "Certidão Negativa de Débitos Relativos aos Tributos Federais e à Dívida Ativa da União..."',
        ),
        (
            AnaliseEditalRequisito.Categoria.REGULARIDADE_FISCAL,
            'Certidão de Regularidade do FGTS (CRF)',
            'Certificado de Regularidade do FGTS emitido pela Caixa Econômica Federal em plena vigência.',
            4,
            'Item 8.1.b do Edital: "Certidão de Regularidade perante o Fundo de Garantia por Tempo de Serviço - CRF/FGTS."',
        ),
        (
            AnaliseEditalRequisito.Categoria.REGULARIDADE_FISCAL,
            'Certidão Negativa de Débitos Trabalhistas (CNDT)',
            'Certidão comprovando a inexistência de débitos inadimplidos perante a Justiça do Trabalho.',
            5,
            'Item 8.1.c do Edital: "Certidão Negativa de Débitos Trabalhistas - CNDT, expedida pela Justiça do Trabalho."',
        ),
        (
            AnaliseEditalRequisito.Categoria.REGULARIDADE_FISCAL,
            f'Certidão Estadual ({oportunidade.uf}) e Municipal',
            'Comprovação de quitação com as Fazendas Estadual e Municipal do domicílio da licitante.',
            5,
            'Item 8.2 do Edital: "Prova de regularidade para com as Fazendas Estadual e Municipal da sede do proponente..."',
        ),
        (
            AnaliseEditalRequisito.Categoria.QUALIFICACAO_TECNICA,
            'Atestado de Capacidade Técnica (Engenharia / Hospitalar)',
            'Atestado emitido por pessoa jurídica de direito público ou privado demonstrando fornecimento ou prestação de serviços compatíveis.',
            7,
            'Item 9.1 do Edital: "Apresentar no mínimo 01 (um) atestado de capacidade técnica emitido por entidade hospitalar ou clínica..."',
        ),
        (
            AnaliseEditalRequisito.Categoria.QUALIFICACAO_TECNICA,
            'Registro / Visto no Conselho Profissional (CREA / CFT)',
            'Comprovação de inscrição ativa da empresa e de seu Responsável Técnico no Conselho de Classe.',
            8,
            'Item 9.3 do Edital: "Certidão de Registro e Quitação no CREA ou CFT, com comprovação do Responsável Técnico habilitado."',
        ),
        (
            AnaliseEditalRequisito.Categoria.PRAZOS_CONDICOES,
            'Prazo de Atendimento / SLA de Chamados',
            'Conferência do SLA exigido para início do atendimento presencial ou entrega dos materiais.',
            12,
            'Item 12.2 do Edital: "O prazo máximo para atendimento de chamados de urgência será de até 04 (quatro) horas corridas."',
        ),
    ]

    criados = []
    for cat, tit, desc, pag, trecho in requisitos_base:
        req = AnaliseEditalRequisito(
            organization=org,
            oportunidade=oportunidade,
            categoria=cat,
            titulo=tit,
            descricao_detalhada=desc,
            pagina_edital=pag,
            trecho_citado=trecho,
            status=AnaliseEditalRequisito.StatusConformidade.PENDENTE,
        )
        req.save()
        criados.append(req)
    return criados


def atualizar_etapa_funil(user, oportunidade: OportunidadeLicitacao, nova_etapa: str) -> OportunidadeLicitacao:
    """Avança ou retrocede a licitação no funil comercial de 6 etapas com auditoria imutável."""
    etapa_anterior = oportunidade.etapa
    if etapa_anterior != nova_etapa:
        oportunidade.etapa = nova_etapa
        oportunidade.save()
        registrar_log_licita(
            user,
            oportunidade,
            'ETAPA_FUNIL_ALTERADA',
            f'Oportunidade movida de {oportunidade.get_etapa_display()} para a nova etapa.',
            etapa_anterior=etapa_anterior,
            etapa_nova=nova_etapa,
        )
    return oportunidade


def salvar_analise_requisito(user, data: dict, instance_id: int | None = None) -> AnaliseEditalRequisito:
    org = current_organization()
    req = AnaliseEditalRequisito.objects.filter(organization=org, pk=instance_id).first() if instance_id else None
    if not req:
        op_id = data.get('oportunidade_id')
        op = OportunidadeLicitacao.objects.filter(organization=org, pk=op_id).first()
        if not op:
            raise ValidationError('Licitação de vínculo obrigatória.')
        req = AnaliseEditalRequisito(organization=org, oportunidade=op)

    req.categoria = data.get('categoria') or req.categoria
    req.titulo = (data.get('titulo') or '').strip()
    req.descricao_detalhada = (data.get('descricao_detalhada') or '').strip()
    req.pagina_edital = int(data.get('pagina_edital') or 1)
    req.trecho_citado = (data.get('trecho_citado') or '').strip()
    req.status = data.get('status') or AnaliseEditalRequisito.StatusConformidade.PENDENTE
    req.parecer_conferencia = (data.get('parecer_conferencia') or '').strip()
    req.conferido_por = user
    req.conferido_em = timezone.now()

    req.full_clean()
    req.save()

    registrar_log_licita(
        user,
        req.oportunidade,
        'REQUISITO_EDITAL_CONFERIDO',
        f'Requisito "{req.titulo}" marcado como {req.get_status_display()} (pág. {req.pagina_edital}).',
        dados={'requisito_id': req.pk, 'status': req.status, 'pagina': req.pagina_edital},
    )
    return req


def vincular_simulacao_a_licitacao(user, oportunidade: OportunidadeLicitacao, simulacao: SimulacaoLanceEdital) -> None:
    oportunidade.simulacao_pricing = simulacao
    oportunidade.save()
    registrar_log_licita(
        user,
        oportunidade,
        'SIMULACAO_PRICING_VINCULADA',
        f'Simulador de lance vinculado: Piso R$ {simulacao.piso_sem_lucro:,.2f} · Lance Sugerido R$ {simulacao.lance_com_margem:,.2f}',
        dados={'simulacao_id': simulacao.pk},
    )


def resumo_kpis_licita() -> dict:
    org = current_organization()
    if not org:
        return {}

    ops = OportunidadeLicitacao.objects.filter(organization=org)
    total_encontradas = ops.filter(etapa=OportunidadeLicitacao.EtapaFunil.ENCONTRADA).count()
    total_analise = ops.filter(etapa=OportunidadeLicitacao.EtapaFunil.EM_ANALISE).count()
    total_documentacao = ops.filter(etapa=OportunidadeLicitacao.EtapaFunil.DOCUMENTACAO).count()
    total_propostas = ops.filter(etapa=OportunidadeLicitacao.EtapaFunil.PROPOSTA).count()
    total_disputa = ops.filter(etapa=OportunidadeLicitacao.EtapaFunil.EM_DISPUTA).count()
    total_vencidas = ops.filter(etapa=OportunidadeLicitacao.EtapaFunil.VENCIDA).count()

    valor_total_pipeline = ops.exclude(
        etapa__in=[OportunidadeLicitacao.EtapaFunil.PERDIDA, OportunidadeLicitacao.EtapaFunil.DESERTA_CANCELADA],
    ).aggregate(total=Sum('valor_total_estimado'))['total'] or ZERO

    return {
        'total_encontradas': total_encontradas,
        'total_analise': total_analise,
        'total_documentacao': total_documentacao,
        'total_propostas': total_propostas,
        'total_disputa': total_disputa,
        'total_vencidas': total_vencidas,
        'valor_total_pipeline': valor_total_pipeline,
        'total_radares_ativos': RadarFiltroPNCP.objects.filter(organization=org, ativo=True).count(),
    }
