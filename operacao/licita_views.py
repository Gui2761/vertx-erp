"""Views operacionais do VERTYX Licita (Radar PNCP, Checklist de Edital e Funil Comercial)."""
from __future__ import annotations

from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from operacao import licita_services as ls
from operacao import pricing_services as ps
from operacao.licita_models import (
    AnaliseEditalRequisito,
    OportunidadeLicitacao,
    RadarFiltroPNCP,
)
from operacao.pricing_models import CalculadoraHoraTecnica, SimulacaoLanceEdital
from platform_core.modules import has_capability, require_capability


def _require_leitura(request):
    require_capability(request.user, 'licita_consultar')


def _require_escrita(request):
    require_capability(request.user, 'licita_escrever')


def _base_context(request, aba_ativa: str) -> dict:
    return {
        'aba_licita': aba_ativa,
        'pode_escrever': has_capability(request.user, 'licita_escrever'),
        'hoje': timezone.localdate(),
    }


@login_required
def licita_oportunidades(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'sincronizar_radar':
                radar_id = request.POST.get('radar_id')
                radar = get_object_or_404(RadarFiltroPNCP, pk=radar_id, organization=request.organization)
                novas, atualizadas = ls.sincronizar_radar_pncp(request.user, radar)
                messages.success(
                    request,
                    f'Radar "{radar.nome}" sincronizado com PNCP: {novas} nova(s) oportunidade(s) importada(s), {atualizadas} atualizada(s).',
                )
            elif acao == 'sincronizar_todos_radares':
                radares_ativos = list(RadarFiltroPNCP.objects.filter(organization=request.organization, ativo=True))
                if not radares_ativos:
                    radares_ativos = ls.inicializar_radares_padrao(request.user)
                total_novas = 0
                total_atualizadas = 0
                for rad in radares_ativos:
                    n, a = ls.sincronizar_radar_pncp(request.user, rad)
                    total_novas += n
                    total_atualizadas += a
                messages.success(
                    request,
                    f'Varredura de {len(radares_ativos)} radar(es) no PNCP concluída: {total_novas} nova(s) oportunidade(s) importada(s), {total_atualizadas} atualizada(s).',
                )
            elif acao == 'salvar_oportunidade':
                num_pncp = (request.POST.get('numero_controle_pncp') or f"MANUAL-{timezone.now():%Y%m%d%H%M%S}").strip()
                val_raw = request.POST.get('valor_total_estimado', '').replace('.', '').replace(',', '.')
                val_dec = Decimal(val_raw) if val_raw else Decimal('0.00')

                op = OportunidadeLicitacao(
                    organization=request.organization,
                    numero_controle_pncp=num_pncp,
                    orgao_nome=(request.POST.get('orgao_nome') or '').strip(),
                    orgao_cnpj=(request.POST.get('orgao_cnpj') or '').strip(),
                    uf=(request.POST.get('uf') or 'SE').strip().upper()[:2],
                    municipio=(request.POST.get('municipio') or '').strip(),
                    modalidade_nome=(request.POST.get('modalidade_nome') or 'Pregão Eletrônico').strip(),
                    numero_edital=(request.POST.get('numero_edital') or '').strip(),
                    objeto=(request.POST.get('objeto') or '').strip(),
                    valor_total_estimado=val_dec,
                    data_publicacao_pncp=timezone.localdate(),
                    link_fonte_pncp=(request.POST.get('link_fonte_pncp') or '').strip(),
                    etapa=OportunidadeLicitacao.EtapaFunil.ENCONTRADA,
                    responsavel=request.user,
                )
                op.full_clean()
                op.save()
                ls.gerar_checklist_padrao_edital(request.user, op)
                ls.registrar_log_licita(
                    request.user,
                    op,
                    'LICITACAO_CADASTRADA_MANUAL',
                    f'Oportunidade cadastrada: {op.orgao_nome} ({op.uf}) - R$ {op.valor_total_estimado:,.2f}',
                )
                messages.success(request, f'Oportunidade {op.numero_edital or op.numero_controle_pncp} cadastrada.')
                return redirect('operacao:licita_detalhe', pk=op.pk)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao processar: {exc}')
        return redirect('operacao:licita_oportunidades')

    ctx = _base_context(request, 'oportunidades')
    ctx['kpis'] = ls.resumo_kpis_licita()
    ctx['radares'] = RadarFiltroPNCP.objects.filter(organization=request.organization, ativo=True)

    qs = OportunidadeLicitacao.objects.filter(organization=request.organization)
    busca = (request.GET.get('q') or '').strip()
    if busca:
        qs = qs.filter(objeto__icontains=busca) | qs.filter(orgao_nome__icontains=busca) | qs.filter(numero_controle_pncp__icontains=busca)
    uf_filtro = request.GET.get('uf')
    if uf_filtro:
        qs = qs.filter(uf=uf_filtro.strip().upper())
    etapa_filtro = request.GET.get('etapa')
    if etapa_filtro:
        qs = qs.filter(etapa=etapa_filtro)

    ctx['oportunidades'] = qs
    ctx['busca'] = busca
    ctx['uf_filtro'] = uf_filtro
    ctx['etapa_filtro'] = etapa_filtro
    ctx['etapas_choices'] = OportunidadeLicitacao.EtapaFunil.choices
    return render(request, 'comercial/licita_oportunidades.html', ctx)


@login_required
def licita_radares(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'inicializar_radares':
                ls.inicializar_radares_padrao(request.user)
                messages.success(request, 'Radares padrão de Alagoas, Sergipe e Nordeste configurados com sucesso.')
            elif acao == 'salvar_radar':
                radar_id = request.POST.get('radar_id')
                radar = RadarFiltroPNCP.objects.filter(organization=request.organization, pk=radar_id).first() if radar_id else None
                if not radar:
                    radar = RadarFiltroPNCP(organization=request.organization)

                val_min_raw = request.POST.get('valor_minimo', '').replace('.', '').replace(',', '.')
                val_max_raw = request.POST.get('valor_maximo', '').replace('.', '').replace(',', '.')

                radar.nome = (request.POST.get('nome') or '').strip()
                radar.palavras_chave = (request.POST.get('palavras_chave') or '').strip()
                radar.ufs = (request.POST.get('ufs') or 'SE, AL, BA').strip()
                radar.modalidades_pncp = (request.POST.get('modalidades_pncp') or '6, 8, 4').strip()
                radar.valor_minimo = Decimal(val_min_raw) if val_min_raw else Decimal('0.00')
                radar.valor_maximo = Decimal(val_max_raw) if val_max_raw else None
                radar.ativo = bool(request.POST.get('ativo'))
                radar.full_clean()
                radar.save()

                messages.success(request, f'Radar "{radar.nome}" configurado com sucesso.')
                if request.POST.get('sincronizar_agora'):
                    novas, at = ls.sincronizar_radar_pncp(request.user, radar)
                    messages.info(request, f'Varredura imediata: {novas} novas licitações encontradas.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao salvar radar: {exc}')
        return redirect('operacao:licita_radares')

    ctx = _base_context(request, 'radares')
    radares = list(RadarFiltroPNCP.objects.filter(organization=request.organization))
    if not radares and ctx['pode_escrever']:
        radares = ls.inicializar_radares_padrao(request.user)
    ctx['radares'] = radares
    return render(request, 'comercial/licita_radares.html', ctx)


@login_required
def licita_funil(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        op_id = request.POST.get('oportunidade_id')
        nova_etapa = request.POST.get('nova_etapa')
        op = get_object_or_404(OportunidadeLicitacao, pk=op_id, organization=request.organization)
        ls.atualizar_etapa_funil(request.user, op, nova_etapa)
        messages.success(request, f'Licitação movida para {op.get_etapa_display()}.')
        return redirect('operacao:licita_funil')

    ctx = _base_context(request, 'funil')
    ctx['kpis'] = ls.resumo_kpis_licita()
    ops = OportunidadeLicitacao.objects.filter(organization=request.organization)

    # Agrupa por cada uma das 6 etapas oficiais do Funil Comercial
    funil_colunas = [
        ('ENCONTRADA', '1. Encontradas', ops.filter(etapa='ENCONTRADA')),
        ('EM_ANALISE', '2. Em Análise', ops.filter(etapa='EM_ANALISE')),
        ('DOCUMENTACAO', '3. Documentação', ops.filter(etapa='DOCUMENTACAO')),
        ('PROPOSTA', '4. Propostas', ops.filter(etapa='PROPOSTA')),
        ('EM_DISPUTA', '5. Em Disputa', ops.filter(etapa='EM_DISPUTA')),
        ('VENCIDA', '6. Vencidas', ops.filter(etapa='VENCIDA')),
    ]
    ctx['funil_colunas'] = funil_colunas
    return render(request, 'comercial/licita_funil.html', ctx)


@login_required
def licita_detalhe(request, pk: int):
    _require_leitura(request)
    op = get_object_or_404(OportunidadeLicitacao, pk=pk, organization=request.organization)

    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao')
        try:
            if acao == 'atualizar_etapa':
                nova_etapa = request.POST.get('etapa')
                ls.atualizar_etapa_funil(request.user, op, nova_etapa)
                messages.success(request, f'Etapa atualizada para {op.get_etapa_display()}.')
            elif acao == 'salvar_requisito':
                req_id = request.POST.get('requisito_id')
                data = {
                    'oportunidade_id': op.pk,
                    'categoria': request.POST.get('categoria'),
                    'titulo': request.POST.get('titulo'),
                    'descricao_detalhada': request.POST.get('descricao_detalhada'),
                    'pagina_edital': request.POST.get('pagina_edital'),
                    'trecho_citado': request.POST.get('trecho_citado'),
                    'status': request.POST.get('status'),
                    'parecer_conferencia': request.POST.get('parecer_conferencia'),
                }
                ls.salvar_analise_requisito(request.user, data, instance_id=int(req_id) if req_id else None)
                messages.success(request, 'Conferência do requisito registrada com sucesso.')
            elif acao == 'gerar_simulacao_pricing':
                # Cria ou atualiza simulador de lances integrado ao Market & Pricing
                data_sim = {
                    'titulo_edital': op.numero_edital or op.numero_controle_pncp,
                    'orgao_comprador': op.orgao_nome,
                    'objeto_resumo': op.objeto[:255],
                    'custos_pecas_equipamentos': request.POST.get('custos_pecas_equipamentos', '0.00'),
                    'horas_tecnicas_estimadas': request.POST.get('horas_tecnicas_estimadas', '0.00'),
                    'custo_hora_aplicado': request.POST.get('custo_hora_aplicado', '0.00'),
                    'custos_deslocamento_logistica': request.POST.get('custos_deslocamento_logistica', '0.00'),
                    'outras_despesas_diretas': request.POST.get('outras_despesas_diretas', '0.00'),
                    'percentual_taxa_risco': request.POST.get('percentual_taxa_risco', '5.00'),
                    'percentual_tributos': request.POST.get('percentual_tributos', '8.00'),
                    'percentual_margem_minima': request.POST.get('percentual_margem_minima', '15.00'),
                    'lance_simulado_disputa': request.POST.get('lance_simulado_disputa'),
                }
                sim = ps.salvar_simulacao_lance(
                    request.user,
                    data_sim,
                    instance_id=op.simulacao_pricing.pk if op.simulacao_pricing else None,
                )
                ls.vincular_simulacao_a_licitacao(request.user, op, sim)
                if sim.lance_abaixo_do_piso:
                    messages.warning(
                        request,
                        f'ALERTA DE RISCO: Lance de R$ {sim.lance_simulado_disputa:,.2f} está ABAIXO do piso sem lucro (R$ {sim.piso_sem_lucro:,.2f})!',
                    )
                else:
                    messages.success(request, f'Simulação integrada salva: Piso R$ {sim.piso_sem_lucro:,.2f} · Lance Sugerido R$ {sim.lance_com_margem:,.2f}.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        except Exception as exc:
            messages.error(request, f'Erro ao processar: {exc}')
        return redirect('operacao:licita_detalhe', pk=op.pk)

    ctx = _base_context(request, 'detalhe')
    ctx['op'] = op
    ctx['requisitos'] = op.requisitos.all()
    ctx['categorias_requisitos'] = AnaliseEditalRequisito.Categoria.choices
    ctx['status_requisitos'] = AnaliseEditalRequisito.StatusConformidade.choices
    ctx['etapas_choices'] = OportunidadeLicitacao.EtapaFunil.choices
    ctx['historico_eventos'] = op.historico_eventos.all()[:20]
    ctx['calculadoras_hora'] = CalculadoraHoraTecnica.objects.filter(organization=request.organization)
    return render(request, 'comercial/licita_detalhe.html', ctx)
