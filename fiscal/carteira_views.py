"""Views das 4 telas operacionais do MVP VERTYX Contábil (Carteira Fiscal)."""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from clientes.models import Cliente, TipoPessoa
from fiscal import carteira_services as cs
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
)
from platform_core.modules import has_capability, require_capability


def _require_leitura(request):
    require_capability(request.user, 'fiscal_consultar')


def _require_escrita(request):
    require_capability(request.user, 'fiscal_carteira_escrever')


def _base_context(request, aba_ativa: str) -> dict:
    return {
        'aba_carteira': aba_ativa,
        'pode_escrever_carteira': has_capability(request.user, 'fiscal_carteira_escrever'),
        'equipe_membros': cs._membros_equipe_atual(),
        'departamentos_choices': DepartamentoContabil.choices,
        'regimes_choices': RegimeTributarioCarteira.choices,
        'hoje': timezone.localdate(),
    }


@login_required
def carteira_dashboard(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao', '')
        try:
            if acao == 'importar_erp':
                criados, ignorados = cs.importar_clientes_pj_do_erp(request.user)
                messages.success(
                    request,
                    f'Sincronização concluída: {criados} empresa(s) PJ importada(s) do ERP ({ignorados} já existentes ou sem CNPJ válido).',
                )
            elif acao == 'pre_analise':
                analise = cs.realizar_pre_analise_cnpj(request.user, request.POST)
                messages.success(
                    request,
                    f'Pré-análise comercial registrada para {analise.razao_social_identificada} ({analise.cnpj_formatado}).',
                )
            elif acao == 'converter_pre_analise':
                analise = get_object_or_404(PreAnaliseComercialCNPJ, pk=request.POST.get('analise_id'))
                emp = cs.converter_pre_analise_em_cliente(request.user, analise)
                messages.success(request, f'{emp.razao_social} integrada à carteira contábil com sucesso.')
                return redirect('operacao:fiscal_carteira_cliente_detalhe', public_id=emp.public_id)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        return redirect('operacao:fiscal_carteira_dashboard')

    resp_raw = request.GET.get('responsavel', '').strip()
    responsavel_id = int(resp_raw) if resp_raw.isdigit() else None
    departamento = request.GET.get('departamento', '').strip()

    kpis = cs.metricas_dashboard_carteira(responsavel_id=responsavel_id, departamento=departamento)
    pre_analises = PreAnaliseComercialCNPJ.objects.select_related('convertido_empresa', 'consultado_por')[:6]

    ctx = _base_context(request, 'dashboard')
    ctx.update({
        'kpis': kpis,
        'filtro_responsavel': responsavel_id,
        'filtro_departamento': departamento,
        'pre_analises': pre_analises,
    })
    return render(request, 'fiscal/carteira_dashboard.html', ctx)


@login_required
def carteira_clientes(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao', 'nova_empresa')
        try:
            if acao == 'importar_erp':
                criados, ignorados = cs.importar_clientes_pj_do_erp(request.user)
                messages.success(request, f'{criados} empresa(s) importada(s) do ERP ({ignorados} ignoradas).')
            else:
                emp = cs.salvar_empresa_carteira(
                    request.user,
                    {
                        **request.POST.dict(),
                        'procuracao_ecac_ativa': request.POST.get('procuracao_ecac_ativa') == '1',
                    },
                )
                messages.success(request, f'Empresa {emp.razao_social} ({emp.cnpj_formatado}) cadastrada na carteira.')
                return redirect('operacao:fiscal_carteira_cliente_detalhe', public_id=emp.public_id)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        return redirect('operacao:fiscal_carteira_clientes')

    busca = request.GET.get('q', '').strip()
    regime = request.GET.get('regime', '').strip()
    situacao = request.GET.get('situacao', '').strip()
    resp_raw = request.GET.get('responsavel', '').strip()

    qs = EmpresaCarteiraContabil.objects.filter(ativo=True).select_related(
        'responsavel_interno', 'cliente'
    ).prefetch_related('certidoes', 'obrigacoes', 'pendencias')
    if busca:
        digitos = cs.only_digits(busca)
        filtro_q = Q(razao_social__icontains=busca) | Q(nome_fantasia__icontains=busca)
        if digitos:
            filtro_q |= Q(cnpj__icontains=digitos)
        qs = qs.filter(filtro_q)
    if regime:
        qs = qs.filter(regime_tributario=regime)
    if situacao:
        qs = qs.filter(situacao_fiscal=situacao)
    if resp_raw.isdigit():
        qs = qs.filter(responsavel_interno_id=int(resp_raw))

    empresas = list(qs)
    for emp in empresas:
        emp.saude_diag = cs.calcular_saude_empresa(emp)

    ctx = _base_context(request, 'clientes')
    ctx.update({
        'empresas': empresas,
        'clientes_erp': Cliente.objects.filter(ativo=True, tipo_pessoa=TipoPessoa.JURIDICA)[:150],
        'situacoes_fiscais': EmpresaCarteiraContabil.SituacaoFiscal.choices,
        'situacoes_cadastrais': EmpresaCarteiraContabil.SituacaoCadastral.choices,
        'certificados_choices': EmpresaCarteiraContabil.TipoCertificado.choices,
        'filtro_q': busca,
        'filtro_regime': regime,
        'filtro_situacao': situacao,
        'filtro_responsavel': int(resp_raw) if resp_raw.isdigit() else None,
    })
    return render(request, 'fiscal/carteira_clientes.html', ctx)


@login_required
def carteira_cliente_detalhe(request, public_id):
    _require_leitura(request)
    empresa = get_object_or_404(
        EmpresaCarteiraContabil.objects.select_related('responsavel_interno', 'cliente'),
        public_id=public_id,
    )
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao', '')
        try:
            if acao == 'atualizar_empresa':
                cs.salvar_empresa_carteira(
                    request.user,
                    {
                        **request.POST.dict(),
                        'procuracao_ecac_ativa': request.POST.get('procuracao_ecac_ativa') == '1',
                    },
                    instance=empresa,
                )
                messages.success(request, 'Ficha cadastral e fiscal atualizada com sucesso.')
            elif acao == 'registrar_ocorrencia':
                texto = (request.POST.get('descricao') or '').strip()
                if not texto:
                    raise ValidationError('Descreva a ocorrência para registrar no histórico.')
                anexo = cs._salvar_anexo_contabil(request.user, request.FILES.get('anexo'), f'Ocorrência {empresa.razao_social}', empresa.cliente)
                cs.registrar_evento(request.user, empresa, EventoHistoricoContabil.TipoEvento.OCORRENCIA, texto, anexo=anexo)
                messages.success(request, 'Ocorrência registrada no histórico imutável do CNPJ.')
            elif acao == 'enviar_comunicacao':
                dados = request.POST.dict()
                dados['empresa_id'] = empresa.pk
                cs.registrar_comunicacao_cliente(request.user, dados)
                messages.success(request, 'Comunicação registrada na trilha do cliente.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        return redirect('operacao:fiscal_carteira_cliente_detalhe', public_id=empresa.public_id)

    saude = cs.sincronizar_situacao_fiscal(empresa)
    certidoes = list(empresa.certidoes.select_related('arquivo').all())
    por_esfera = {c.esfera: c for c in certidoes}
    resumo_esferas = [
        {'codigo': code, 'nome': label, 'certidao': por_esfera.get(code)}
        for code, label in CertidaoFiscalCarteira.Esfera.choices
    ]

    ctx = _base_context(request, 'clientes')
    ctx.update({
        'empresa': empresa,
        'saude': saude,
        'resumo_esferas': resumo_esferas,
        'certidoes': certidoes,
        'obrigacoes': empresa.obrigacoes.select_related('responsavel', 'comprovante')[:20],
        'pendencias': empresa.pendencias.select_related('responsavel', 'anexo')[:20],
        'comunicacoes': empresa.comunicacoes.select_related('enviado_por', 'pendencia')[:15],
        'historico': empresa.historico.select_related('autor', 'anexo', 'pendencia')[:40],
        'situacoes_cadastrais': EmpresaCarteiraContabil.SituacaoCadastral.choices,
        'certificados_choices': EmpresaCarteiraContabil.TipoCertificado.choices,
        'canais_comunicacao': ComunicacaoClienteContabil.Canal.choices,
        'tipos_comunicacao': ComunicacaoClienteContabil.Tipo.choices,
    })
    return render(request, 'fiscal/carteira_cliente_detalhe.html', ctx)


@login_required
def carteira_pendencias(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        try:
            pend = cs.criar_pendencia_operacional(request.user, request.POST.dict(), request.FILES.get('anexo'))
            messages.success(request, f'Pendência {pend.codigo} aberta e registrada no fluxo operacional.')
            return redirect('operacao:fiscal_carteira_pendencia_detalhe', pk=pend.pk)
        except (ValidationError, EmpresaCarteiraContabil.DoesNotExist) as exc:
            msg = '; '.join(exc.messages) if hasattr(exc, 'messages') else 'Selecione uma empresa válida da carteira.'
            messages.error(request, msg)
        return redirect('operacao:fiscal_carteira_pendencias')

    status_f = request.GET.get('status', '').strip()
    prio_f = request.GET.get('prioridade', '').strip()
    depto_f = request.GET.get('departamento', '').strip()
    resp_raw = request.GET.get('responsavel', '').strip()

    qs = PendenciaFiscalCarteira.objects.select_related('empresa', 'responsavel', 'criado_por', 'anexo')
    if status_f:
        qs = qs.filter(status=status_f)
    if prio_f:
        qs = qs.filter(prioridade=prio_f)
    if depto_f:
        qs = qs.filter(departamento=depto_f)
    if resp_raw.isdigit():
        qs = qs.filter(responsavel_id=int(resp_raw))

    todas_ativas = PendenciaFiscalCarteira.objects.exclude(status=PendenciaFiscalCarteira.Status.RESOLVIDO)
    contagem_etapas = [
        {
            'codigo': code,
            'nome': label,
            'total': todas_ativas.filter(etapa_fluxo=code).count()
            if code != PendenciaFiscalCarteira.EtapaFluxo.AUDITAR
            else PendenciaFiscalCarteira.objects.filter(etapa_fluxo=code).count(),
        }
        for code, label in PendenciaFiscalCarteira.EtapaFluxo.choices
    ]

    ctx = _base_context(request, 'pendencias')
    ctx.update({
        'pendencias': list(qs[:120]),
        'empresas': EmpresaCarteiraContabil.objects.filter(ativo=True).only('id', 'razao_social', 'cnpj'),
        'status_choices': PendenciaFiscalCarteira.Status.choices,
        'prioridade_choices': PendenciaFiscalCarteira.Prioridade.choices,
        'etapas_fluxo': contagem_etapas,
        'filtro_status': status_f,
        'filtro_prioridade': prio_f,
        'filtro_departamento': depto_f,
        'filtro_responsavel': int(resp_raw) if resp_raw.isdigit() else None,
        'prazo_padrao': (timezone.localdate() + timedelta(days=5)).isoformat(),
    })
    return render(request, 'fiscal/carteira_pendencias.html', ctx)


@login_required
def carteira_pendencia_detalhe(request, pk: int):
    _require_leitura(request)
    pendencia = get_object_or_404(
        PendenciaFiscalCarteira.objects.select_related(
            'empresa', 'responsavel', 'criado_por', 'anexo', 'certidao_origem', 'obrigacao_origem'
        ),
        pk=pk,
    )
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao', 'atualizar')
        try:
            if acao == 'comunicar_cliente':
                dados = request.POST.dict()
                dados['empresa_id'] = pendencia.empresa_id
                dados['pendencia_id'] = pendencia.pk
                cs.registrar_comunicacao_cliente(request.user, dados)
                messages.success(request, 'Aviso/solicitação registrado e etapa avançada para Comunicação com Cliente.')
            elif acao == 'confirmar_recebimento':
                com = get_object_or_404(ComunicacaoClienteContabil, pk=request.POST.get('comunicacao_id'), pendencia=pendencia)
                cs.confirmar_recebimento_comunicacao(request.user, com)
                messages.success(request, 'Confirmação de recebimento registrada na auditoria.')
            else:
                cs.avancar_pendencia_operacional(request.user, pendencia, request.POST.dict(), request.FILES.get('anexo'))
                messages.success(request, f'Pendência {pendencia.codigo} atualizada com sucesso.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        return redirect('operacao:fiscal_carteira_pendencia_detalhe', pk=pendencia.pk)

    ctx = _base_context(request, 'pendencias')
    ctx.update({
        'pendencia': pendencia,
        'empresa': pendencia.empresa,
        'status_choices': PendenciaFiscalCarteira.Status.choices,
        'prioridade_choices': PendenciaFiscalCarteira.Prioridade.choices,
        'etapa_choices': PendenciaFiscalCarteira.EtapaFluxo.choices,
        'canais_comunicacao': ComunicacaoClienteContabil.Canal.choices,
        'tipos_comunicacao': ComunicacaoClienteContabil.Tipo.choices,
        'comunicacoes': pendencia.comunicacoes.select_related('enviado_por').all(),
        'historico': pendencia.historico.select_related('autor', 'anexo').all(),
    })
    return render(request, 'fiscal/carteira_pendencia_detalhe.html', ctx)


@login_required
def carteira_obrigacoes(request):
    _require_leitura(request)
    if request.method == 'POST':
        _require_escrita(request)
        acao = request.POST.get('acao', '')
        try:
            if acao == 'nova_certidao':
                cert = cs.registrar_certidao_carteira(request.user, request.POST.dict(), request.FILES.get('arquivo'))
                messages.success(request, f'Certidão {cert.get_esfera_display()} registrada para {cert.empresa.razao_social}.')
            elif acao == 'nova_obrigacao':
                obrig = cs.registrar_obrigacao_carteira(request.user, request.POST.dict(), request.FILES.get('comprovante'))
                messages.success(request, f'{obrig.get_tipo_display()} ({obrig.competencia}) cadastrada para {obrig.empresa.razao_social}.')
            elif acao == 'concluir_obrigacao':
                obrig = get_object_or_404(ObrigacaoFiscalCarteira, pk=request.POST.get('obrigacao_id'))
                cs.concluir_obrigacao_carteira(request.user, obrig, request.POST.get('protocolo_recibo', ''))
                messages.success(request, f'{obrig.get_tipo_display()} marcada como {obrig.get_status_display()}.')
            elif acao == 'gerar_pendencia_obrigacao':
                obrig = get_object_or_404(ObrigacaoFiscalCarteira.objects.select_related('empresa'), pk=request.POST.get('obrigacao_id'))
                pend = cs.criar_pendencia_operacional(
                    request.user,
                    {
                        'empresa_id': obrig.empresa_id,
                        'titulo': f'Pendência {obrig.get_tipo_display()} ({obrig.competencia})',
                        'descricao': f'Obrigação/guia com vencimento em {obrig.vencimento:%d/%m/%Y} e valor R$ {obrig.valor_guia}.',
                        'departamento': DepartamentoContabil.FISCAL,
                        'prioridade': PendenciaFiscalCarteira.Prioridade.CRITICA if obrig.esta_atrasada else PendenciaFiscalCarteira.Prioridade.ALTA,
                        'responsavel_id': obrig.responsavel_id or obrig.empresa.responsavel_interno_id,
                        'prazo': timezone.localdate() + timedelta(days=3),
                        'obrigacao_origem_id': obrig.pk,
                    },
                )
                messages.success(request, f'Pendência operacional {pend.codigo} gerada a partir da obrigação.')
                return redirect('operacao:fiscal_carteira_pendencia_detalhe', pk=pend.pk)
            elif acao == 'gerar_pendencia_certidao':
                cert = get_object_or_404(CertidaoFiscalCarteira.objects.select_related('empresa'), pk=request.POST.get('certidao_id'))
                pend = cs.criar_pendencia_operacional(
                    request.user,
                    {
                        'empresa_id': cert.empresa_id,
                        'titulo': f'Renovação/Regularização CND {cert.get_esfera_display()}',
                        'descricao': f'Certidão {cert.get_situacao_display()} com validade em {cert.validade:%d/%m/%Y}.',
                        'departamento': DepartamentoContabil.FISCAL,
                        'prioridade': PendenciaFiscalCarteira.Prioridade.ALTA,
                        'responsavel_id': cert.empresa.responsavel_interno_id,
                        'prazo': timezone.localdate() + timedelta(days=5),
                        'certidao_origem_id': cert.pk,
                    },
                )
                messages.success(request, f'Pendência operacional {pend.codigo} criada para regularizar certidão.')
                return redirect('operacao:fiscal_carteira_pendencia_detalhe', pk=pend.pk)
        except (ValidationError, EmpresaCarteiraContabil.DoesNotExist) as exc:
            msg = '; '.join(exc.messages) if hasattr(exc, 'messages') else 'Dados inválidos para registro.'
            messages.error(request, msg)
        return redirect('operacao:fiscal_carteira_obrigacoes')

    empresa_f = request.GET.get('empresa', '').strip()
    tipo_f = request.GET.get('tipo', '').strip()
    esfera_f = request.GET.get('esfera', '').strip()

    obrig_qs = ObrigacaoFiscalCarteira.objects.select_related('empresa', 'responsavel', 'comprovante')
    cert_qs = CertidaoFiscalCarteira.objects.select_related('empresa', 'arquivo')
    if empresa_f.isdigit():
        obrig_qs = obrig_qs.filter(empresa_id=int(empresa_f))
        cert_qs = cert_qs.filter(empresa_id=int(empresa_f))
    if tipo_f:
        obrig_qs = obrig_qs.filter(tipo=tipo_f)
    if esfera_f:
        cert_qs = cert_qs.filter(esfera=esfera_f)

    hoje = timezone.localdate()
    ctx = _base_context(request, 'obrigacoes')
    ctx.update({
        'obrigacoes': list(obrig_qs[:120]),
        'certidoes': list(cert_qs[:120]),
        'empresas': EmpresaCarteiraContabil.objects.filter(ativo=True).only('id', 'razao_social', 'cnpj'),
        'tipos_obrigacao': ObrigacaoFiscalCarteira.Tipo.choices,
        'naturezas_obrigacao': ObrigacaoFiscalCarteira.Natureza.choices,
        'status_obrigacao': ObrigacaoFiscalCarteira.Status.choices,
        'esferas_certidao': CertidaoFiscalCarteira.Esfera.choices,
        'situacoes_certidao': CertidaoFiscalCarteira.Situacao.choices,
        'competencia_padrao': f'{hoje.month:02d}/{hoje.year}',
        'vencimento_padrao': (hoje + timedelta(days=15)).isoformat(),
        'validade_padrao': (hoje + timedelta(days=180)).isoformat(),
        'filtro_empresa': int(empresa_f) if empresa_f.isdigit() else None,
        'filtro_tipo': tipo_f,
        'filtro_esfera': esfera_f,
    })
    return render(request, 'fiscal/carteira_obrigacoes.html', ctx)


@login_required
def confirmar_comunicacao(request, token):
    _require_escrita(request)
    com = get_object_or_404(ComunicacaoClienteContabil, token_confirmacao=token)
    cs.confirmar_recebimento_comunicacao(request.user, com)
    messages.success(request, 'Confirmação de recebimento registrada com sucesso.')
    if com.pendencia_id:
        return redirect('operacao:fiscal_carteira_pendencia_detalhe', pk=com.pendencia_id)
    return redirect('operacao:fiscal_carteira_cliente_detalhe', public_id=com.empresa.public_id)
