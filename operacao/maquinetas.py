"""Gestão de maquinetas de cartões e parametrização de taxas de débito e crédito."""
from decimal import Decimal
import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from platform_core.context import current_organization
from platform_core.models import ConfiguracaoEmpresa
from gestao.permissions import allowed


def maquinetas_padrao():
    return [
        {
            'id': 'maq_1',
            'nome': 'Maquineta 1 - Balcão Principal',
            'adquirente': 'Stone',
            'taxa_debito': 1.20,
            'taxa_credito_vista': 2.50,
            'taxa_credito_parcelado_2x6': 3.40,
            'taxa_credito_parcelado_7x12': 4.80,
            'dias_repasse': 1,
            'padrao': True,
            'ativo': True,
        },
        {
            'id': 'maq_2',
            'nome': 'Maquineta 2 - Balcão Reserva',
            'adquirente': 'PagBank / Moderninha',
            'taxa_debito': 1.49,
            'taxa_credito_vista': 3.19,
            'taxa_credito_parcelado_2x6': 3.99,
            'taxa_credito_parcelado_7x12': 5.50,
            'dias_repasse': 1,
            'padrao': False,
            'ativo': True,
        }
    ]


def obter_maquinetas(empresa):
    if not empresa:
        return maquinetas_padrao()
    ret = empresa.retencoes_informativas or {}
    maqs = ret.get('maquinetas')
    if not maqs:
        maqs = maquinetas_padrao()
        ret['maquinetas'] = maqs
        empresa.retencoes_informativas = ret
        empresa.save()
    return maqs


@login_required
@never_cache
def maquinetas_view(request):
    if not allowed(request.user, 'financeiro') and not request.user.is_staff:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Acesso restrito ao módulo financeiro.')

    org = current_organization()
    empresa = ConfiguracaoEmpresa.objects.filter(organization=org).first() if org else None
    if org and not empresa:
        empresa, _ = ConfiguracaoEmpresa.objects.get_or_create(organization=org)

    maquinetas = obter_maquinetas(empresa)

    if request.method == 'POST':
        action = request.POST.get('acao')

        if action == 'salvar':
            maq_id = request.POST.get('maq_id', '').strip()
            nome = request.POST.get('nome', '').strip() or 'Nova Maquineta'
            adquirente = request.POST.get('adquirente', '').strip() or 'Outra'
            try:
                taxa_deb = float(request.POST.get('taxa_debito', '1.2').replace(',', '.'))
            except ValueError:
                taxa_deb = 1.2
            try:
                taxa_cred_vista = float(request.POST.get('taxa_credito_vista', '2.5').replace(',', '.'))
            except ValueError:
                taxa_cred_vista = 2.5
            try:
                taxa_parc_2x6 = float(request.POST.get('taxa_credito_parcelado_2x6', '3.5').replace(',', '.'))
            except ValueError:
                taxa_parc_2x6 = 3.5
            try:
                taxa_parc_7x12 = float(request.POST.get('taxa_credito_parcelado_7x12', '5.0').replace(',', '.'))
            except ValueError:
                taxa_parc_7x12 = 5.0
            try:
                dias = int(request.POST.get('dias_repasse', '1'))
            except ValueError:
                dias = 1
            padrao = request.POST.get('padrao') == '1'
            ativo = request.POST.get('ativo', '1') == '1'

            if not maq_id:
                maq_id = f"maq_{uuid.uuid4().hex[:6]}"

            found = False
            for m in maquinetas:
                if m.get('id') == maq_id:
                    m['nome'] = nome
                    m['adquirente'] = adquirente
                    m['taxa_debito'] = taxa_deb
                    m['taxa_credito_vista'] = taxa_cred_vista
                    m['taxa_credito_parcelado_2x6'] = taxa_parc_2x6
                    m['taxa_credito_parcelado_7x12'] = taxa_parc_7x12
                    m['dias_repasse'] = dias
                    m['ativo'] = ativo
                    if padrao:
                        m['padrao'] = True
                    found = True
                    break

            if not found:
                nova = {
                    'id': maq_id,
                    'nome': nome,
                    'adquirente': adquirente,
                    'taxa_debito': taxa_deb,
                    'taxa_credito_vista': taxa_cred_vista,
                    'taxa_credito_parcelado_2x6': taxa_parc_2x6,
                    'taxa_credito_parcelado_7x12': taxa_parc_7x12,
                    'dias_repasse': dias,
                    'padrao': padrao or (len(maquinetas) == 0),
                    'ativo': ativo,
                }
                maquinetas.append(nova)

            if padrao:
                for m in maquinetas:
                    if m.get('id') != maq_id:
                        m['padrao'] = False

            ret = empresa.retencoes_informativas or {}
            ret['maquinetas'] = maquinetas
            empresa.retencoes_informativas = ret
            empresa.save()
            messages.success(request, f'Maquineta "{nome}" salva com sucesso!')
            return redirect('operacao:financeiro_maquinetas')

        elif action == 'excluir':
            maq_id = request.POST.get('maq_id', '').strip()
            maquinetas = [m for m in maquinetas if m.get('id') != maq_id]
            if maquinetas and not any(m.get('padrao') for m in maquinetas):
                maquinetas[0]['padrao'] = True
            ret = empresa.retencoes_informativas or {}
            ret['maquinetas'] = maquinetas
            empresa.retencoes_informativas = ret
            empresa.save()
            messages.success(request, 'Maquineta removida.')
            return redirect('operacao:financeiro_maquinetas')

        elif action == 'padrao':
            maq_id = request.POST.get('maq_id', '').strip()
            for m in maquinetas:
                m['padrao'] = (m.get('id') == maq_id)
            ret = empresa.retencoes_informativas or {}
            ret['maquinetas'] = maquinetas
            empresa.retencoes_informativas = ret
            empresa.save()
            messages.success(request, 'Maquineta padrão atualizada.')
            return redirect('operacao:financeiro_maquinetas')

    # Simulação de taxas para visualização imediata
    valor_simulado = 1000.0
    simulacoes = []
    for m in maquinetas:
        deb_taxa = m.get('taxa_debito', 0)
        deb_desconto = valor_simulado * (deb_taxa / 100.0)
        deb_liquido = valor_simulado - deb_desconto

        cred_taxa = m.get('taxa_credito_vista', 0)
        cred_desconto = valor_simulado * (cred_taxa / 100.0)
        cred_liquido = valor_simulado - cred_desconto

        simulacoes.append({
            'id': m.get('id'),
            'nome': m.get('nome'),
            'adquirente': m.get('adquirente'),
            'deb_taxa': deb_taxa,
            'deb_desconto': deb_desconto,
            'deb_liquido': deb_liquido,
            'cred_taxa': cred_taxa,
            'cred_desconto': cred_desconto,
            'cred_liquido': cred_liquido,
        })

    return render(request, 'operacao/maquinetas.html', {
        'maquinetas': maquinetas,
        'simulacoes': simulacoes,
        'valor_simulado': valor_simulado,
    })
