"""Local, tenant-owned preparation of the existing fiscal graph. No emission."""
from copy import deepcopy
from django import forms
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from platform_core.access import effective_role
from platform_core.context import current_organization
from platform_core.models import FilialEmpresa, Organization
from platform_core.modules import require_capability
from gestao.services import audit, write
from gestao.models import Peca
from operacao import models as m
from operacao.fiscal_models import preparacao_fiscal_publica
from .services import local


def authorize(user):
    require_capability(user, 'fiscal_configurar')
    if effective_role(user) != 'ADMIN':
        raise PermissionDenied('Configuração documental restrita ao ADMIN desta organização.')
    local()


class PreparacaoForm(forms.Form):
    revisao = forms.IntegerField(min_value=0, widget=forms.HiddenInput, initial=0)
    dados_confirmados = forms.BooleanField(required=False, label='Confirmo os dados cadastrais documentais')
    logradouro = forms.CharField(max_length=200, required=False, label='Logradouro')
    numero = forms.CharField(max_length=30, required=False, label='Número')
    complemento = forms.CharField(max_length=200, required=False, label='Complemento')
    bairro = forms.CharField(max_length=100, required=False, label='Bairro')
    cep = forms.RegexField(r'^\d{8}$', max_length=8, required=False, label='CEP (8 dígitos)')
    endereco_confirmado = forms.BooleanField(required=False, label='Confirmo o endereço')
    municipio = forms.CharField(max_length=60, required=False, label='Município')
    uf = forms.ChoiceField(choices=[('', 'Pendente de confirmação'), ('SE', 'SE — Sergipe')], required=False, label='UF suportada nesta homologação')
    municipio_ibge = forms.RegexField(r'^28\d{5}$', max_length=7, required=False, label='Código IBGE confirmado (Sergipe)')
    municipio_confirmado = forms.BooleanField(required=False, label='Confirmo município e código IBGE')
    cnae = forms.RegexField(r'^\d{7}$', max_length=7, required=False, label='CNAE confirmado (7 dígitos, sem inferir tributação)')
    divergencias_confirmadas = forms.BooleanField(required=False, label='Revisei e confirmo expressamente endereço, CNAE e demais divergências documentais')
    tipo_estabelecimento = forms.ChoiceField(choices=[('', 'Pendente de confirmação'), ('MATRIZ', 'Matriz'), ('FILIAL', 'Filial')], required=False, label='Tipo de estabelecimento')
    regime = forms.CharField(max_length=40, required=False, label='Regime tributário confirmado pelo responsável fiscal')
    crt = forms.ChoiceField(choices=[('', 'Pendente de confirmação'), ('1', '1 — Simples Nacional'), ('2', '2 — Simples Nacional, excesso de sublimite'), ('3', '3 — Regime normal'), ('4', '4 — MEI')], required=False, label='CRT (sem seleção automática)')
    enquadramento = forms.CharField(max_length=200, required=False, label='Enquadramento fiscal')
    regime_confirmado = forms.BooleanField(required=False, label='Confirmo regime, CRT e enquadramento')
    credenciamento_confirmado = forms.BooleanField(required=False, label='Confirmo credenciamento NFC-e em homologação pelo responsável fiscal')
    serie = forms.IntegerField(min_value=0, max_value=889, required=False, label='Série NFC-e confirmada')
    proximo_numero = forms.IntegerField(min_value=1, max_value=999999999, required=False, label='Próximo número confirmado')
    natureza_operacao = forms.CharField(max_length=60, required=False, label='Natureza da operação')
    qr_url = forms.URLField(max_length=250, required=False, label='URL oficial QR Code (proposta a validar)')
    consulta_url = forms.URLField(max_length=250, required=False, label='URL oficial de consulta (proposta a validar)')
    fonte_urls = forms.URLField(max_length=250, required=False, label='Fonte oficial dos parâmetros')
    schema_release = forms.CharField(max_length=80, required=False, label='Release XSD (proposta a validar)')
    produto = forms.ModelChoiceField(queryset=Peca.objects.none(), required=False, label='Produto existente da organização')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Peca.objects.all().order_by('descricao')
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs['class'] = 'form-control'

    def clean(self):
        data = super().clean()
        values = {k: v for k, v in data.items() if k != 'produto'}
        values['produto_id'] = data['produto'].pk if data.get('produto') else None
        preparacao_fiscal_publica(values)
        for checked, required in [('endereco_confirmado', ('logradouro', 'numero', 'bairro', 'cep')),
                                  ('municipio_confirmado', ('municipio', 'uf', 'municipio_ibge')),
                                  ('regime_confirmado', ('regime', 'crt', 'enquadramento')),
                                  ('divergencias_confirmadas', ('cnae', 'bairro'))]:
            if data.get(checked) and any(not data.get(key) for key in required):
                raise ValidationError('Preencha os campos obrigatórios antes de confirmar: ' + ', '.join(required))
        return data


SECTIONS = [
    ('Confirmação documental', ['dados_confirmados']),
    ('Endereço e município', ['logradouro', 'numero', 'complemento', 'bairro', 'cep', 'endereco_confirmado', 'municipio', 'uf', 'municipio_ibge', 'municipio_confirmado', 'cnae', 'divergencias_confirmadas']),
    ('Regime tributário', ['regime', 'crt', 'enquadramento', 'regime_confirmado']),
    ('Estabelecimento fiscal', ['tipo_estabelecimento']),
    ('NFC-e — Modelo 65', ['credenciamento_confirmado', 'serie', 'proximo_numero', 'natureza_operacao', 'qr_url', 'consulta_url', 'fonte_urls', 'schema_release']),
    ('Produto para homologação', ['produto']),
]


def initial(config):
    d = config.proposta_documental['dados']
    values = {k: d[k] for k in ('logradouro', 'numero', 'complemento', 'bairro', 'cep', 'municipio', 'uf')}
    values.update(config.preparacao_fiscal)
    values['produto'] = values.pop('produto_id', None)
    values.setdefault('revisao', 0)
    # CNAE is a proposal, never an implicitly confirmed activity.
    return values


def establishment_ready(d):
    return all(d.get(k) for k in ('dados_confirmados', 'endereco_confirmado', 'municipio_confirmado', 'divergencias_confirmadas', 'logradouro', 'numero', 'bairro', 'cep', 'municipio', 'uf', 'municipio_ibge', 'cnae', 'tipo_estabelecimento'))


@transaction.atomic
def save_preparation(user, config_id, payload, confirm=False):
    authorize(user)
    config = m.ConfiguracaoFiscal.objects.select_for_update().get(pk=config_id)
    if not config.proposta_documental:
        raise ValidationError('Cadastro documental ausente nesta organização.')
    form = PreparacaoForm(payload)
    if not form.is_valid():
        raise ValidationError([str(e) for errors in form.errors.values() for e in errors])
    allowed = set(form.fields)
    if set(payload) - allowed:
        raise ValidationError('Emitente, tenant, ambiente, credenciais e habilitação não são campos editáveis.')
    d = dict(form.cleaned_data)
    product = d.pop('produto')
    d['produto_id'] = product.pk if product else None
    org = Organization.objects.select_for_update().get(pk=current_organization().pk)
    if config.estabelecimento.cnpj != org.cnpj or config.proposta_documental['dados']['cnpj'] != org.cnpj:
        raise ValidationError('Emitente diverge do cadastro documental desta organização.')
    before = deepcopy(config.preparacao_fiscal)
    if d['revisao'] != before.get('revisao', 0):
        raise ValidationError('Configuração mudou em outra sessão. Recarregue antes de salvar.')
    if confirm and not establishment_ready(d):
        raise ValidationError('Preencha e confirme dados cadastrais, endereço, município/IBGE, divergências e tipo antes de confirmar o estabelecimento.')
    final = config.configuracao_confirmada
    if final:
        locked = ('dados_confirmados', 'endereco_confirmado', 'municipio_confirmado', 'divergencias_confirmadas', 'logradouro', 'numero', 'complemento', 'bairro', 'cep', 'municipio', 'uf', 'municipio_ibge', 'cnae', 'tipo_estabelecimento')
        if any(d.get(k) != before.get(k) for k in locked):
            raise ValidationError('Estabelecimento confirmado não pode ser alterado silenciosamente; solicite revisão explícita.')
        if confirm:
            raise ValidationError('Estabelecimento já confirmado; nenhuma nova filial criada.')
    d['revisao'] += 1
    config.preparacao_fiscal = d
    if confirm:
        doc = config.proposta_documental['dados']
        branch = FilialEmpresa.objects.create(codigo='FISCAL-HOM-' + str(config.pk), nome=doc['nome_fantasia'],
            cnpj=doc['cnpj'], inscricao_estadual=doc['ie'], inscricao_municipal=doc['im'], ativo=True,
            endereco=', '.join(d[k] for k in ('logradouro', 'numero', 'complemento', 'bairro', 'municipio', 'uf', 'cep') if d[k]))
        m.PerfilFiscalEstabelecimento.objects.create(estabelecimento=branch, municipio_ibge=d['municipio_ibge'], uf=d['uf'],
            endereco_estruturado={k: d[k] for k in ('logradouro', 'numero', 'complemento', 'bairro', 'cep')}, regime=d['regime'], atividade=d['cnae'])
        final = m.ConfiguracaoFiscal.objects.create(estabelecimento=branch, tipo='NFCE', ambiente='HOMOLOGACAO', motor='NFCE_SVRS_HOM', habilitada=False, preparacao_fiscal=deepcopy(d))
        config.configuracao_confirmada = final
        audit(user, 'FISCAL_ESTABELECIMENTO_CONFIRMADO_LOCAL', final, {'origem_documental': config.pk, 'tipo': d['tipo_estabelecimento'], 'emissao_habilitada': False})
    elif final:
        # New public parameter version; the previous disabled configuration stays.
        config.configuracao_confirmada = m.ConfiguracaoFiscal.objects.create(estabelecimento=final.estabelecimento,
            tipo='NFCE', ambiente='HOMOLOGACAO', motor='NFCE_SVRS_HOM', habilitada=False,
            versao=final.versao + 1, preparacao_fiscal=deepcopy(d))
    write(config)
    audit(user, 'FISCAL_PREPARACAO_LOCAL', config, {'anterior': before, 'posterior': d, 'confirmacao_explicita': confirm})
    return config


def readiness(config):
    d = config.preparacao_fiscal
    final = config.configuracao_confirmada
    product = Peca.objects.filter(pk=d.get('produto_id')).first()
    # A stored opaque reference is NOT proof that a real vault was provisioned.
    rows = [
        ('Dados cadastrais confirmados', bool(d.get('dados_confirmados'))),
        ('Endereço confirmado', bool(d.get('endereco_confirmado') and d.get('divergencias_confirmadas'))),
        ('Município/IBGE confirmado', bool(d.get('municipio_confirmado') and d.get('municipio_ibge'))),
        ('CRT confirmado', bool(d.get('regime_confirmado') and d.get('crt'))),
        ('Regime confirmado', bool(d.get('regime_confirmado') and d.get('regime') and d.get('enquadramento'))),
        ('Estabelecimento confirmado', bool(final)),
        ('Credenciamento NFC-e confirmado', bool(d.get('credenciamento_confirmado'))),
        ('Série definida', d.get('serie') is not None),
        ('Próximo número definido', bool(d.get('proximo_numero'))),
        ('Certificado provisionado', False),
        ('Produto definido', bool(product)),
        ('Tributação definida', False),
        ('XSD validado', False),
        ('QR Code/consulta confirmados', False),
        ('Assinatura real validada no cofre', False),
        ('Endpoint SVRS de homologação identificado', True),
        ('WSDL oficial pinado e confirmado', False),
        ('Transporte seguro mTLS específico', False),
        ('Autorização explícita para primeiro envio', False),
    ]
    # This preparation screen never certifies tax rules, XSD or URLs by presence.
    # Their official validation/provisioning belongs to the next approved phase.
    return rows, product


def pendencias_responsavel(config, product):
    """Public checklist; presence of a product field never confirms its tax rule."""
    d = config.preparacao_fiscal
    result = [
        ('CRT', d.get('crt'), bool(d.get('regime_confirmado') and d.get('crt'))),
        ('Regime / enquadramento definitivo', ' / '.join(filter(None, (d.get('regime'), d.get('enquadramento')))), bool(d.get('regime_confirmado'))),
        ('Código IBGE', d.get('municipio_ibge'), bool(d.get('municipio_confirmado'))),
        ('Endereço definitivo e divergência documental', d.get('bairro'), bool(d.get('endereco_confirmado') and d.get('divergencias_confirmadas'))),
        ('CNAE definitivo', d.get('cnae'), bool(d.get('divergencias_confirmadas') and d.get('cnae'))),
        ('Credenciamento NFC-e', '', bool(d.get('credenciamento_confirmado'))),
        ('Estabelecimento fiscal', d.get('tipo_estabelecimento'), bool(config.configuracao_confirmada_id)),
        ('Série', d.get('serie'), False), ('Próxima numeração', d.get('proximo_numero'), False),
        ('Produto para teste', product.descricao if product else '', False),
    ]
    for label, field in [('NCM', 'ncm'), ('CEST / aplicabilidade', 'cest'), ('CFOP', 'cfop'),
                         ('Origem', 'origem_fiscal'), ('CST / CSOSN', 'csosn')]:
        result.append((label, getattr(product, field, '') if product else '', False))
    result.extend([('PIS / COFINS', '', False), ('Demais regras tributárias / RTC', '', False)])
    return result
