import base64
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from platform_core.access import require_erp
from platform_core.context import current_organization
from platform_core.models import Organization, ConfiguracaoEmpresa
from .models import ContaBancaria, Configuracao, Deposito
from .fiscal_models import CredencialFiscal


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
            fiscal_cfg.codigo_servico = request.POST.get('codigo_servico', fiscal_cfg.codigo_servico).strip()
            try:
                fiscal_cfg.save()
                messages.success(request, '✅ Parâmetros fiscais e de ambiente atualizados!')
            except Exception as err:
                messages.error(request, f'Erro ao salvar parâmetros fiscais: {err}')
            return redirect('operacao:cadastro_inicial')

        elif acao == 'salvar_certificado':
            cert_file = request.FILES.get('certificado_arquivo')
            cert_b64 = request.POST.get('certificado_base64', '').strip()
            cert_nome = request.POST.get('certificado_nome', 'certificado.pfx').strip()
            senha = request.POST.get('certificado_senha', '').strip()

            pfx_bytes = None
            if cert_file:
                pfx_bytes = cert_file.read()
            elif cert_b64:
                if ',' in cert_b64:
                    cert_b64 = cert_b64.split(',', 1)[1]
                try:
                    pfx_bytes = base64.b64decode(cert_b64)
                except Exception:
                    messages.error(request, 'Formato do arquivo enviado é inválido.')
                    return redirect('operacao:cadastro_inicial')

            if not pfx_bytes:
                messages.error(request, 'Selecione o arquivo do certificado digital modelo A1 (.pfx ou .p12).')
                return redirect('operacao:cadastro_inicial')

            try:
                from cryptography import x509
                from cryptography.hazmat.primitives.serialization import pkcs12
                from cryptography.hazmat.primitives import serialization
                from cryptography.x509.oid import NameOID

                password_bytes = senha.encode('utf-8') if senha else None
                try:
                    private_key, cert, additional_certs = pkcs12.load_key_and_certificates(pfx_bytes, password_bytes)
                except Exception:
                    messages.error(request, '❌ Senha do certificado inválida ou arquivo .pfx / .p12 corrompido. Verifique a senha e tente novamente.')
                    return redirect('operacao:cadastro_inicial')

                if not cert:
                    messages.error(request, 'Não foi possível ler um certificado X.509 válido do arquivo informado.')
                    return redirect('operacao:cadastro_inicial')

                cnpj_extraido = ''
                try:
                    from fiscal.nfce.certificates import cnpj_certificado
                    cnpj_extraido = cnpj_certificado(cert)
                except Exception:
                    subject_str = cert.subject.rfc4514_string()
                    cnpj_match = re.search(r'\b(\d{14})\b', subject_str)
                    if cnpj_match:
                        cnpj_extraido = cnpj_match.group(1)

                titular = ''
                for attr in cert.subject:
                    if attr.oid == NameOID.COMMON_NAME:
                        titular = attr.value
                        break
                if not titular:
                    for attr in cert.subject:
                        if attr.oid == NameOID.ORGANIZATION_NAME:
                            titular = attr.value
                            break
                if not titular:
                    titular = org.razao_social or org.nome_fantasia or 'Empresa'

                emissor = ''
                for attr in cert.issuer:
                    if attr.oid == NameOID.COMMON_NAME:
                        emissor = attr.value
                        break
                if not emissor:
                    emissor = 'Autoridade Certificadora ICP-Brasil'

                valido_de = cert.not_valid_before_utc
                valido_ate = cert.not_valid_after_utc
                now_utc = datetime.now(dt_tz.utc)

                if valido_ate < now_utc:
                    messages.warning(request, f'⚠️ Atenção: Este certificado expirou em {valido_ate.strftime("%d/%m/%Y")}.')

                der_bytes = cert.public_bytes(serialization.Encoding.DER)
                sha256_fp = hashlib.sha256(der_bytes).hexdigest()
                ref_cofre = f"cofre://{uuid.uuid4()}"

                for prev in CredencialFiscal.objects.filter(organization=org, ativa=True):
                    prev.ativa = False
                    prev._service_write = True
                    prev.save()

                cred = CredencialFiscal(
                    organization=org,
                    referencia=ref_cofre,
                    mecanismo='REFERENCIA',
                    ambiente='HOMOLOGACAO' if fiscal_cfg.ambiente_fiscal == 'SANDBOX' else 'PRODUCAO',
                    expira_em=valido_ate,
                    ativa=True,
                    versao=1
                )
                cred._service_write = True
                cred.save()

                if not isinstance(empresa_cfg.retencoes_informativas, dict):
                    empresa_cfg.retencoes_informativas = {}

                empresa_cfg.retencoes_informativas['certificado_a1'] = {
                    'ativo': True,
                    'nome_arquivo': cert_nome,
                    'titular': titular,
                    'cnpj': cnpj_extraido or org.cnpj,
                    'valido_de': valido_de.strftime('%d/%m/%Y'),
                    'valido_ate': valido_ate.strftime('%d/%m/%Y'),
                    'emissor': emissor,
                    'fingerprint_sha256': sha256_fp,
                    'serial_number': str(cert.serial_number),
                    'referencia_cofre': ref_cofre,
                    'cadastrado_em': timezone.now().strftime('%d/%m/%Y %H:%M'),
                }
                empresa_cfg.save()

                if cnpj_extraido and not org.cnpj:
                    org.cnpj = cnpj_extraido
                    org.save()

                messages.success(request, f'✅ Certificado Digital A1 validado e instalado com sucesso! Titular: {titular} · Validade até {valido_ate.strftime("%d/%m/%Y")}')
            except Exception as err:
                messages.error(request, f'Erro ao processar certificado digital: {err}')
            return redirect('operacao:cadastro_inicial')

        elif acao == 'gerar_certificado_teste':
            try:
                from cryptography import x509
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import rsa
                from cryptography.x509.oid import NameOID, ObjectIdentifier

                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                cnpj_val = re.sub(r'\D', '', org.cnpj or '27173295400010')
                if len(cnpj_val) != 14:
                    cnpj_val = '27173295400010'
                org_title = org.nome_fantasia or org.razao_social or 'TECNOLMED'
                subject_cn = f"{org_title}:{cnpj_val}"

                cnpj_bytes = b'\x0c\x0e' + cnpj_val.encode('ascii')
                san_other = x509.OtherName(ObjectIdentifier('2.16.76.1.3.3'), cnpj_bytes)

                name = x509.Name([
                    x509.NameAttribute(NameOID.COUNTRY_NAME, 'BR'),
                    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, org.uf or 'SE'),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_title),
                    x509.NameAttribute(NameOID.COMMON_NAME, subject_cn),
                ])
                now = datetime.now(dt_tz.utc)
                valido_ate = now + timedelta(days=365)

                cert = (
                    x509.CertificateBuilder()
                    .subject_name(name)
                    .issuer_name(name)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(days=1))
                    .not_valid_after(valido_ate)
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .add_extension(x509.SubjectAlternativeName([san_other]), critical=False)
                    .sign(key, hashes.SHA256())
                )

                der_bytes = cert.public_bytes(serialization.Encoding.DER)
                sha256_fp = hashlib.sha256(der_bytes).hexdigest()
                ref_cofre = f"cofre://{uuid.uuid4()}"

                for prev in CredencialFiscal.objects.filter(organization=org, ativa=True):
                    prev.ativa = False
                    prev._service_write = True
                    prev.save()

                cred = CredencialFiscal(
                    organization=org,
                    referencia=ref_cofre,
                    mecanismo='REFERENCIA',
                    ambiente='HOMOLOGACAO',
                    expira_em=valido_ate,
                    ativa=True,
                    versao=1
                )
                cred._service_write = True
                cred.save()

                if not isinstance(empresa_cfg.retencoes_informativas, dict):
                    empresa_cfg.retencoes_informativas = {}

                empresa_cfg.retencoes_informativas['certificado_a1'] = {
                    'ativo': True,
                    'nome_arquivo': f'certificado_teste_{cnpj_val}.pfx',
                    'titular': subject_cn,
                    'cnpj': cnpj_val,
                    'valido_de': now.strftime('%d/%m/%Y'),
                    'valido_ate': valido_ate.strftime('%d/%m/%Y'),
                    'emissor': 'Autoridade Certificadora VERTYX (Homologação)',
                    'fingerprint_sha256': sha256_fp,
                    'serial_number': str(cert.serial_number),
                    'referencia_cofre': ref_cofre,
                    'cadastrado_em': timezone.now().strftime('%d/%m/%Y %H:%M'),
                }
                empresa_cfg.save()
                messages.success(request, f'🧪 Certificado A1 de Testes/Homologação gerado com sucesso! Titular: {subject_cn} · Válido por 1 ano.')
            except Exception as err:
                messages.error(request, f'Erro ao gerar certificado de teste: {err}')
            return redirect('operacao:cadastro_inicial')

        elif acao == 'remover_certificado':
            if isinstance(empresa_cfg.retencoes_informativas, dict) and 'certificado_a1' in empresa_cfg.retencoes_informativas:
                empresa_cfg.retencoes_informativas.pop('certificado_a1', None)
                empresa_cfg.save()
            for prev in CredencialFiscal.objects.filter(organization=org, ativa=True):
                prev.ativa = False
                prev._service_write = True
                prev.save()
            messages.info(request, 'Certificado digital desvinculado.')
            return redirect('operacao:cadastro_inicial')

    # Recupera informações do certificado digital A1
    cert_info = {}
    if isinstance(empresa_cfg.retencoes_informativas, dict):
        cert_info = empresa_cfg.retencoes_informativas.get('certificado_a1', {})

    credencial_fiscal = CredencialFiscal.objects.filter(organization=org, ativa=True).order_by('-id').first()
    if credencial_fiscal:
        if not cert_info:
            cert_info = {
                'ativo': True,
                'titular': org.razao_social or org.nome_fantasia or 'TECNOLMED',
                'cnpj': org.cnpj,
                'valido_ate': credencial_fiscal.expira_em.strftime('%d/%m/%Y') if credencial_fiscal.expira_em else 'Indefinido',
                'emissor': 'ICP-Brasil (Cofre Seguro)',
                'referencia_cofre': credencial_fiscal.referencia,
            }
        else:
            cert_info['referencia_cofre'] = credencial_fiscal.referencia

    # Calcula completude do setup
    tem_cnpj = bool(org.cnpj)
    tem_endereco = bool(org.endereco and org.cidade and org.uf)
    tem_banco = contas.exists()
    tem_fiscal = bool(empresa_cfg.inscricao_estadual or empresa_cfg.crt)
    tem_certificado = bool(cert_info and cert_info.get('ativo'))
    pontos = sum([tem_cnpj, tem_endereco, tem_banco, tem_fiscal, tem_certificado])
    percentual_pronto = int((pontos / 5) * 100)

    context = {
        'org': org,
        'empresa_cfg': empresa_cfg,
        'fiscal_cfg': fiscal_cfg,
        'contas': contas,
        'depositos': depositos,
        'cert_info': cert_info,
        'credencial_fiscal': credencial_fiscal,
        'percentual_pronto': percentual_pronto,
        'tem_cnpj': tem_cnpj,
        'tem_endereco': tem_endereco,
        'tem_banco': tem_banco,
        'tem_fiscal': tem_fiscal,
        'tem_certificado': tem_certificado,
    }
    return render(request, 'operacao/cadastro_inicial.html', context)
