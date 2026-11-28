"""Views operacionais do VERTYX Market & Pricing."""
from __future__ import annotations

from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from operacao import pricing_services as ps
from operacao.pricing_models import (
    CalculadoraHoraTecnica,
    CalculadoraPrecoProduto,
    CentroCustoRateio,
    PesquisaPrecoConcorrente,
    SimulacaoLanceEdital,
)
from platform_core.modules import has_capability, require_capability


def _require_leitura(request):
    require_capability(request.user, 'pricing_consultar')


def _require_escrita(request):
    require_capability(request.user, 'pricing_escrever')


def _base_context(request, aba_ativa: str) -> dict:
    return {
        'aba_pricing': aba_ativa,
        'pode_escrever': has_capability(request.user, 'pricing_escrever'),
        'hoje': timezone.localdate(),
    }


@login_required
def pricing_dashboard(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'inicializar_centros':
                ps.inicializar_centros_custo_padrao(request.user)
                messages.success(request, 'Centros de custo Loja, Assistência e Compartilhado inicializados no ERP com sucesso.')
            elif acao == 'salvar_centro':
                cc_id = request.POST.get('centro_id')
                cc = get_object_or_404(CentroCustoRateio, pk=cc_id)
                pct = request.POST.get('percentual_rateio', '').replace(',', '.')
                custo = request.POST.get('custo_fixo_mensal', '').replace('.', '').replace(',', '.')
                if pct:
                    cc.percentual_rateio = Decimal(pct)
                if custo:
                    cc.custo_fixo_mensal = Decimal(custo)
                cc.observacoes = request.POST.get('observacoes', '')
                cc.full_clean()
                cc.save()
                ps.registrar_log_pricing(
                    request.user,
                    'CENTRO_CUSTO_ATUALIZADO',
                    f'Centro de custo {cc.nome} atualizado: {cc.percentual_rateio}% (R$ {cc.custo_fixo_mensal:,.2f})',
                )
                messages.success(request, f'Centro de custo {cc.nome} atualizado.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao processar: {exc}')
        return redirect('operacao:pricing_dashboard')

    ctx = _base_context(request, 'dashboard')
    ctx['kpis'] = ps.resumo_kpis_pricing()
    centros = list(CentroCustoRateio.objects.filter(organization=request.organization).order_by('codigo'))
    if not centros and ctx['pode_escrever']:
        centros = ps.inicializar_centros_custo_padrao(request.user)
    ctx['centros_custo'] = centros
    ctx['produtos_recentes'] = CalculadoraPrecoProduto.objects.filter(organization=request.organization)[:6]
    ctx['simulacoes_recentes'] = SimulacaoLanceEdital.objects.filter(organization=request.organization)[:5]
    ctx['pesquisas_recentes'] = PesquisaPrecoConcorrente.objects.filter(organization=request.organization)[:6]
    return render(request, 'comercial/pricing_dashboard.html', ctx)


@login_required
def pricing_produtos(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'salvar_produto':
                prod_id = request.POST.get('produto_id')
                calc = ps.salvar_calculo_produto(request.user, request.POST, instance_id=int(prod_id) if prod_id else None)
                messages.success(request, f'Precificação de {calc.nome_produto} salva com sucesso.')
            elif acao == 'salvar_pesquisa':
                pesq = ps.salvar_pesquisa_concorrente(request.user, request.POST)
                messages.success(request, f'Pesquisa de preço de {pesq.descricao_item} ({pesq.concorrente_fornecedor}) registrada.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao salvar: {exc}')
        return redirect('operacao:pricing_produtos')

    ctx = _base_context(request, 'produtos')
    busca = (request.GET.get('q') or '').strip()
    qs = CalculadoraPrecoProduto.objects.filter(organization=request.organization)
    if busca:
        qs = qs.filter(nome_produto__icontains=busca) | qs.filter(sku_referencia__icontains=busca)
    ctx['produtos'] = qs
    ctx['busca'] = busca
    ctx['pesquisas'] = PesquisaPrecoConcorrente.objects.filter(organization=request.organization)[:15]
    return render(request, 'comercial/pricing_produtos.html', ctx)


@login_required
def pricing_hora_tecnica(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'inicializar_especialidades':
                ps.inicializar_especialidades_padrao(request.user)
                messages.success(request, 'Especialidades técnicas da Engenharia Clínica inicializadas com sucesso.')
            elif acao == 'salvar_hora':
                hora_id = request.POST.get('hora_id')
                hora = ps.salvar_calculo_hora_tecnica(request.user, request.POST, instance_id=int(hora_id) if hora_id else None)
                messages.success(request, f'Hora técnica da especialidade {hora.especialidade} atualizada com sucesso.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao salvar: {exc}')
        return redirect('operacao:pricing_hora_tecnica')

    ctx = _base_context(request, 'hora_tecnica')
    especialidades = list(CalculadoraHoraTecnica.objects.filter(organization=request.organization))
    if not especialidades and ctx['pode_escrever']:
        especialidades = ps.inicializar_especialidades_padrao(request.user)
    ctx['especialidades'] = especialidades
    return render(request, 'comercial/pricing_hora_tecnica.html', ctx)


@login_required
def pricing_simulacoes(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'salvar_simulacao':
                sim_id = request.POST.get('simulacao_id')
                sim = ps.salvar_simulacao_lance(request.user, request.POST, instance_id=int(sim_id) if sim_id else None)
                if sim.lance_abaixo_do_piso:
                    messages.warning(
                        request,
                        f'ALERTA CRÍTICO: O lance de R$ {sim.lance_simulado_disputa:,.2f} está ABAIXO do piso sem lucro (R$ {sim.piso_sem_lucro:,.2f}). Operação gerará prejuízo!',
                    )
                else:
                    messages.success(request, f'Simulação de lance para {sim.titulo_edital} salva com sucesso.')
                return redirect('operacao:pricing_simulacao_detalhe', pk=sim.pk)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao salvar: {exc}')
        return redirect('operacao:pricing_simulacoes')

    ctx = _base_context(request, 'simulacoes')
    ctx['simulacoes'] = SimulacaoLanceEdital.objects.filter(organization=request.organization)
    ctx['calculadoras_hora'] = CalculadoraHoraTecnica.objects.filter(organization=request.organization)
    return render(request, 'comercial/pricing_simulacoes.html', ctx)


@login_required
def pricing_simulacao_detalhe(request, pk: int):
    _require_leitura(request)
    sim = get_object_or_404(SimulacaoLanceEdital, pk=pk, organization=request.organization)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'atualizar_lance':
                lance_raw = request.POST.get('lance_simulado_disputa', '').replace('.', '').replace(',', '.')
                sim.lance_simulado_disputa = Decimal(lance_raw) if lance_raw else None
                sim.save()
                ps.registrar_log_pricing(
                    request.user,
                    'LANCE_DISPUTA_SIMULADO',
                    f'Novo lance simulado em {sim.titulo_edital}: R$ {(sim.lance_simulado_disputa or Decimal("0.00")):,.2f}',
                )
                if sim.lance_abaixo_do_piso:
                    messages.warning(request, f'ATENÇÃO: Lance abaixo do piso sustentável de R$ {sim.piso_sem_lucro:,.2f}!')
                else:
                    messages.success(request, 'Lance simulado registrado com sucesso.')
                return redirect('operacao:pricing_simulacao_detalhe', pk=sim.pk)
        except Exception as exc:
            messages.error(request, f'Erro ao atualizar lance: {exc}')

    ctx = _base_context(request, 'simulacoes')
    ctx['sim'] = sim
    ctx['lucro_lance_atual'] = sim.calcular_lucro_lance()
    ctx['calculadoras_hora'] = CalculadoraHoraTecnica.objects.filter(organization=request.organization)
    return render(request, 'comercial/pricing_simulacao_detalhe.html', ctx)
