"""Serviços transacionais e inteligência do VERTYX Market & Pricing."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Max, Min, Q
from django.utils import timezone

from gestao.models import Peca
from operacao.pricing_models import (
    CalculadoraHoraTecnica,
    CalculadoraPrecoProduto,
    CentroCustoRateio,
    HistoricoCalculoPreco,
    PesquisaPrecoConcorrente,
    SimulacaoLanceEdital,
)
from platform_core.context import current_organization

ZERO = Decimal('0.00')


def parse_dec(val, default='0.00') -> Decimal:
    if val is None or val == '':
        return Decimal(default)
    if isinstance(val, (int, float, Decimal)):
        return Decimal(str(val))
    s = str(val).strip()
    if ',' in s:
        # Formato brasileiro com vírgula decimal: "1.250,50" -> "1250.50"
        s = s.replace('.', '').replace(',', '.')
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)


def inicializar_centros_custo_padrao(user) -> list[CentroCustoRateio]:
    """Garante a existência dos três centros de custo do ERP (Loja, Assistência e Compartilhados)."""
    org = current_organization()
    if not org:
        return []
    existentes = {cc.codigo: cc for cc in CentroCustoRateio.objects.filter(organization=org)}
    padroes = [
        (
            CentroCustoRateio.CodigoCentro.LOJA,
            'Loja (Produtos, Insumos & Balcão)',
            Decimal('40.00'),
            Decimal('8500.00'),
            'Aluguel de loja, energia, equipe comercial, estoque, fretes e RT farmacêutica/médica.',
        ),
        (
            CentroCustoRateio.CodigoCentro.ASSISTENCIA,
            'Assistência Técnica (Eng. Clínica & Manutenção)',
            Decimal('40.00'),
            Decimal('13500.00'),
            'Equipe técnica, encargos, galpão de oficina, RT biomédica, veículos, ferramentas e calibração periódica.',
        ),
        (
            CentroCustoRateio.CodigoCentro.COMPARTILHADO,
            'Compartilhado (Administrativo, Fiscal & Gestão)',
            Decimal('20.00'),
            Decimal('5000.00'),
            'Contabilidade, assessoria jurídica, sistemas de TI, diretoria e pró-labore.',
        ),
    ]
    criados = []
    for cod, nome, pct, custo, obs in padroes:
        if cod not in existentes:
            cc = CentroCustoRateio(
                organization=org,
                codigo=cod,
                nome=nome,
                percentual_rateio=pct,
                custo_fixo_mensal=custo,
                observacoes=obs,
            )
            cc.save()
            criados.append(cc)
            registrar_log_pricing(user, 'CENTRO_CUSTO_CRIADO', f'Centro de custo {nome} inicializado.', {'codigo': cod})
    return list(CentroCustoRateio.objects.filter(organization=org).order_by('codigo'))


def registrar_log_pricing(user, tipo: str, descricao: str, detalhes: dict | None = None) -> HistoricoCalculoPreco:
    org = current_organization()
    hist = HistoricoCalculoPreco(
        organization=org,
        usuario=user,
        tipo_registro=tipo,
        descricao=descricao[:255],
        detalhes_json=detalhes or {},
    )
    hist._service_write = True
    hist.save()
    return hist


def salvar_calculo_produto(user, data: dict, instance_id: int | None = None) -> CalculadoraPrecoProduto:
    org = current_organization()
    calc = CalculadoraPrecoProduto.objects.filter(organization=org, pk=instance_id).first() if instance_id else None
    if not calc:
        calc = CalculadoraPrecoProduto(organization=org)

    calc.nome_produto = (data.get('nome_produto') or '').strip()
    calc.sku_referencia = (data.get('sku_referencia') or '').strip()
    calc.marca = (data.get('marca') or '').strip()
    calc.modelo = (data.get('modelo') or '').strip()

    peca_id = data.get('peca_id')
    if peca_id:
        calc.peca = Peca.objects.filter(organization=org, pk=peca_id).first()

    calc.custo_aquisicao = parse_dec(data.get('custo_aquisicao'))
    calc.custo_frete_seguro = parse_dec(data.get('custo_frete_seguro'))
    calc.percentual_despesas_fixas = parse_dec(data.get('percentual_despesas_fixas'), '15.00')
    calc.percentual_tributos = parse_dec(data.get('percentual_tributos'), '8.00')
    calc.percentual_outras_variaveis = parse_dec(data.get('percentual_outras_variaveis'), '0.00')
    calc.percentual_margem_desejada = parse_dec(data.get('percentual_margem_desejada'), '15.00')
    calc.observacoes = (data.get('observacoes') or '').strip()

    calc.full_clean()
    calc.save()

    registrar_log_pricing(
        user,
        'PRODUTO_PRECIFICADO',
        f'Precificação calculada para {calc.nome_produto} (Alvo: R$ {calc.preco_alvo:,.2f}, Break-even: R$ {calc.preco_equilibrio:,.2f})',
        {
            'produto_id': calc.pk,
            'custo_base': str(calc.custo_base),
            'preco_alvo': str(calc.preco_alvo),
            'preco_equilibrio': str(calc.preco_equilibrio),
        },
    )
    return calc


def salvar_calculo_hora_tecnica(user, data: dict, instance_id: int | None = None) -> CalculadoraHoraTecnica:
    org = current_organization()
    hora = CalculadoraHoraTecnica.objects.filter(organization=org, pk=instance_id).first() if instance_id else None
    if not hora:
        hora = CalculadoraHoraTecnica(organization=org)

    hora.especialidade = (data.get('especialidade') or '').strip()
    hora.num_tecnicos = int(data.get('num_tecnicos') or 1)
    hora.dias_uteis_mes = int(data.get('dias_uteis_mes') or 22)
    hora.horas_dia = parse_dec(data.get('horas_dia'), '8.00')
    hora.percentual_ocupacao_faturavel = parse_dec(data.get('percentual_ocupacao_faturavel'), '65.00')
    hora.custo_mensal_centro = parse_dec(data.get('custo_mensal_centro'))
    hora.percentual_tributos = parse_dec(data.get('percentual_tributos'), '12.00')
    hora.percentual_margem = parse_dec(data.get('percentual_margem'), '25.00')

    hora.full_clean()
    hora.save()

    registrar_log_pricing(
        user,
        'HORA_TECNICA_CALCULADA',
        f'Hora técnica da especialidade {hora.especialidade}: Custo R$ {hora.custo_por_hora:,.2f}/h · Sugerido R$ {hora.hora_sugerida:,.2f}/h',
        {
            'hora_id': hora.pk,
            'horas_faturaveis': str(hora.horas_faturaveis_mes),
            'custo_hora': str(hora.custo_por_hora),
            'hora_sugerida': str(hora.hora_sugerida),
        },
    )
    return hora


def salvar_pesquisa_concorrente(user, data: dict) -> PesquisaPrecoConcorrente:
    org = current_organization()
    produto_id = data.get('produto_calculo_id')
    prod = CalculadoraPrecoProduto.objects.filter(organization=org, pk=produto_id).first() if produto_id else None

    pesq = PesquisaPrecoConcorrente(
        organization=org,
        produto_calculo=prod,
        descricao_item=(data.get('descricao_item') or (prod.nome_produto if prod else '')).strip(),
        concorrente_fornecedor=(data.get('concorrente_fornecedor') or '').strip(),
        municipio=(data.get('municipio') or 'Aracaju').strip(),
        uf=(data.get('uf') or 'SE').strip().upper()[:2],
        canal=data.get('canal') or PesquisaPrecoConcorrente.CanalPreco.VAREJO,
        preco_identificado=parse_dec(data.get('preco_identificado')),
        data_coleta=data.get('data_coleta') or timezone.localdate(),
        link_fonte=(data.get('link_fonte') or '').strip(),
        observacoes=(data.get('observacoes') or '').strip(),
    )
    pesq.full_clean()
    pesq.save()

    registrar_log_pricing(
        user,
        'PESQUISA_CONCORRENCIA_REGISTRADA',
        f'Preço coletado para {pesq.descricao_item} em {pesq.concorrente_fornecedor}: R$ {pesq.preco_identificado:,.2f}',
        {'pesquisa_id': pesq.pk},
    )
    return pesq


def salvar_simulacao_lance(user, data: dict, instance_id: int | None = None) -> SimulacaoLanceEdital:
    org = current_organization()
    sim = SimulacaoLanceEdital.objects.filter(organization=org, pk=instance_id).first() if instance_id else None
    if not sim:
        sim = SimulacaoLanceEdital(organization=org)

    sim.titulo_edital = (data.get('titulo_edital') or '').strip()
    sim.orgao_comprador = (data.get('orgao_comprador') or '').strip()
    sim.objeto_resumo = (data.get('objeto_resumo') or '').strip()
    sim.custos_pecas_equipamentos = parse_dec(data.get('custos_pecas_equipamentos'))
    sim.horas_tecnicas_estimadas = parse_dec(data.get('horas_tecnicas_estimadas'))

    hora_id = data.get('calculadora_hora_id')
    if hora_id:
        sim.calculadora_hora = CalculadoraHoraTecnica.objects.filter(organization=org, pk=hora_id).first()
        if sim.calculadora_hora and not data.get('custo_hora_aplicado'):
            sim.custo_hora_aplicado = sim.calculadora_hora.custo_por_hora

    if data.get('custo_hora_aplicado'):
        sim.custo_hora_aplicado = parse_dec(data.get('custo_hora_aplicado'))

    sim.custos_deslocamento_logistica = parse_dec(data.get('custos_deslocamento_logistica'))
    sim.outras_despesas_diretas = parse_dec(data.get('outras_despesas_diretas'))
    sim.percentual_taxa_risco = parse_dec(data.get('percentual_taxa_risco'), '5.00')
    sim.percentual_tributos = parse_dec(data.get('percentual_tributos'), '8.00')
    sim.percentual_margem_minima = parse_dec(data.get('percentual_margem_minima'), '15.00')

    if data.get('lance_simulado_disputa'):
        sim.lance_simulado_disputa = parse_dec(data.get('lance_simulado_disputa'))

    sim.full_clean()
    sim.save()

    registrar_log_pricing(
        user,
        'SIMULACAO_LANCE_SALVA',
        f'Simulação {sim.titulo_edital} atualizada: Piso Sustentável R$ {sim.piso_sem_lucro:,.2f} · Lance Sugerido R$ {sim.lance_com_margem:,.2f}',
        {
            'simulacao_id': sim.pk,
            'custo_total': str(sim.custo_total_composto),
            'piso': str(sim.piso_sem_lucro),
            'lance_com_margem': str(sim.lance_com_margem),
            'lance_atual': str(sim.lance_simulado_disputa or '0.00'),
            'abaixo_piso': sim.lance_abaixo_do_piso,
        },
    )
    return sim


def resumo_kpis_pricing() -> dict:
    org = current_organization()
    if not org:
        return {}

    prods = CalculadoraPrecoProduto.objects.filter(organization=org)
    total_prods = prods.count()
    horas = CalculadoraHoraTecnica.objects.filter(organization=org)
    total_especialidades = horas.count()
    total_horas_faturaveis = sum((h.horas_faturaveis_mes for h in horas), ZERO)

    simulacoes = SimulacaoLanceEdital.objects.filter(organization=org)
    total_simulacoes = simulacoes.count()
    simulacoes_abaixo_piso = sum(1 for s in simulacoes if s.lance_abaixo_do_piso)

    pesquisas = PesquisaPrecoConcorrente.objects.filter(organization=org)
    total_pesquisas = pesquisas.count()

    return {
        'total_produtos_calculados': total_prods,
        'total_especialidades_tecnicas': total_especialidades,
        'total_horas_faturaveis_mes': total_horas_faturaveis,
        'total_simulacoes_lance': total_simulacoes,
        'simulacoes_em_alerta_piso': simulacoes_abaixo_piso,
        'total_pesquisas_concorrentes': total_pesquisas,
    }
