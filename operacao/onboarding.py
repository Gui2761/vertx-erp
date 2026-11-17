import uuid
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from platform_core.access import require_erp
from platform_core.context import current_organization
from platform_core.models import Organization, ConfiguracaoEmpresa
from .models import ContaBancaria, Configuracao, Deposito


@login_required
@require_http_methods(['GET', 'POST'])
def cadastro_inicial(request):
    """
    Central Unificada de Cadastro Inicial e Configuração da Empresa.
    Reúne em um só local:
    1. Identificação Jurídica & Endereço (CNPJ, Razão Social, IE, IM);
    2. Certificado Digital A1 & Parâmetros Fiscais;
    3. Contas Bancárias & Chaves Pix;
    4. Carga Massiva de Dados em Planilhas Oficiais (Tecnolmed).
    """
    require_erp(request.user, roles=['ADMIN', 'GESTOR'])
    org = request.organization
    
    empresa_cfg, _ = ConfiguracaoEmpresa.objects.get_or_create(organization=org)
    fiscal_cfg, _ = Configuracao.objects.get_or_create(organization=org)
    contas = ContaBancaria.objects.filter(organization=org)
    depositos = Deposito.objects.filter(organization=org, ativo=True)

    if request.method == 'POST':
        acao = request.POST.get('acao')
        
        if acao == 'dados_empresa':
            org.razao_social = request.POST.get('razao_social', org.razao_social).strip()
            org.nome_fantasia = request.POST.get('nome_fantasia', org.nome_fantasia).strip()
            cnpj_raw = request.POST.get('cnpj', org.cnpj).strip()
            if cnpj_raw:
                from platform_core.validators import normalize_cnpj
                org.cnpj = normalize_cnpj(cnpj_raw)
            org.email = request.POST.get('email', org.email).strip()
            org.telefone = request.POST.get('telefone', org.telefone).strip()
            org.endereco = request.POST.get('endereco', org.endereco).strip()
            org.cidade = request.POST.get('cidade', org.cidade).strip()
            org.uf = request.POST.get('uf', org.uf).strip().upper()[:2]
            
            empresa_cfg.inscricao_estadual = request.POST.get('inscricao_estadual', empresa_cfg.inscricao_estadual).strip()
            empresa_cfg.inscricao_municipal = request.POST.get('inscricao_municipal', empresa_cfg.inscricao_municipal).strip()
            empresa_cfg.regime_tributario = request.POST.get('regime_tributario', empresa_cfg.regime_tributario).strip()
            empresa_cfg.crt = request.POST.get('crt', empresa_cfg.crt).strip()

            try:
                with transaction.atomic():
                    org.full_clean()
                    org.save()
                    empresa_cfg.full_clean()
                    empresa_cfg.save()
                messages.success(request, '✅ Dados cadastrais da empresa salvos com sucesso!')
            except ValidationError as err:
                messages.error(request, f'Erro ao validar dados da empresa: {err}')
            return redirect('operacao:cadastro_inicial')

        elif acao == 'nova_conta_bancaria':
            nome = request.POST.get('conta_nome', '').strip()
            banco = request.POST.get('conta_banco', '').strip()
            agencia = request.POST.get('conta_agencia', '').strip()
            numero = request.POST.get('conta_numero', '').strip()
            titular = request.POST.get('conta_titular', org.razao_social).strip()
            tipo = request.POST.get('conta_tipo', 'BANCO')
            saldo_str = request.POST.get('conta_saldo_inicial', '0').replace(',', '.')
            try:
                saldo_inicial = Decimal(saldo_str)
            except Exception:
                saldo_inicial = Decimal('0.00')

            deposito_id = request.POST.get('conta_deposito')
            deposito = depositos.filter(pk=deposito_id).first() if deposito_id else depositos.first()

            if nome:
                try:
                    ContaBancaria.objects.create(
                        organization=org,
                        nome=nome,
                        banco=banco,
                        agencia=agencia,
                        numero=numero,
                        titular=titular,
                        tipo=tipo,
                        deposito_padrao=deposito,
                        saldo_inicial=saldo_inicial,
                        ativo=True
                    )
                    messages.success(request, f'✅ Conta bancária "{nome}" cadastrada com sucesso!')
                except Exception as err:
                    messages.error(request, f'Erro ao cadastrar conta bancária: {err}')
            else:
                messages.error(request, 'Informe um nome identificador para a conta bancária.')
            return redirect('operacao:cadastro_inicial')

        elif acao == 'parametros_fiscais':
            fiscal_cfg.ambiente_fiscal = request.POST.get('ambiente_fiscal', fiscal_cfg.ambiente_fiscal)
            fiscal_cfg.provedor_fiscal = request.POST.get('provedor_fiscal', fiscal_cfg.provedor_fiscal).strip()
            fiscal_cfg.municipio_fiscal = request.POST.get('municipio_fiscal', fiscal_cfg.municipio_fiscal).strip()
            try:
                fiscal_cfg.save()
                messages.success(request, '✅ Parâmetros fiscais e de ambiente atualizados!')
            except Exception as err:
                messages.error(request, f'Erro ao salvar parâmetros fiscais: {err}')
            return redirect('operacao:cadastro_inicial')

    # Calcula completude do setup
    tem_cnpj = bool(org.cnpj)
    tem_endereco = bool(org.endereco and org.cidade and org.uf)
    tem_banco = contas.exists()
    tem_fiscal = bool(empresa_cfg.inscricao_estadual or empresa_cfg.crt)
    pontos = sum([tem_cnpj, tem_endereco, tem_banco, tem_fiscal])
    percentual_pronto = int((pontos / 4) * 100)

    context = {
        'org': org,
        'empresa_cfg': empresa_cfg,
        'fiscal_cfg': fiscal_cfg,
        'contas': contas,
        'depositos': depositos,
        'percentual_pronto': percentual_pronto,
        'tem_cnpj': tem_cnpj,
        'tem_endereco': tem_endereco,
        'tem_banco': tem_banco,
        'tem_fiscal': tem_fiscal,
    }
    return render(request, 'operacao/cadastro_inicial.html', context)
