"""Explicit, tenant-scoped forms for the municipal foundation screens."""
from django import forms

from platform_core.context import current_organization

from . import phase_a_models as civic
from .public_services import scoped_queryset


FORM_SPECS = {
    'planejamento': {
        'exercicio': ('Exercício municipal', civic.ExercicioMunicipal, ('ano', 'descricao', 'status')),
        'instrumento': ('Instrumento PPA / LDO / LOA', civic.InstrumentoPlanejamentoMunicipal, ('exercicio', 'tipo', 'versao', 'nome', 'descricao', 'inicio_vigencia', 'fim_vigencia', 'status')),
        'programa': ('Programa', civic.ProgramaPlanejamentoMunicipal, ('exercicio', 'instrumento', 'secretaria', 'codigo', 'nome', 'objetivo', 'publico_alvo', 'status')),
        'indicador': ('Indicador', civic.IndicadorPlanejamentoMunicipal, ('programa', 'codigo', 'nome', 'unidade_medida', 'linha_base', 'meta', 'periodicidade')),
        'acao': ('Projeto, atividade ou operação especial', civic.AcaoPlanejamentoMunicipal, ('programa', 'indicador', 'codigo', 'tipo', 'nome', 'descricao', 'meta_fisica', 'unidade_medida', 'inicio_previsto', 'fim_previsto', 'ativa')),
    },
    'orcamento': {
        'orgao': ('Órgão orçamentário', civic.OrgaoOrcamentarioMunicipal, ('codigo', 'nome', 'secretaria', 'ativo')),
        'unidade_orcamentaria': ('Unidade orçamentária', civic.UnidadeOrcamentariaMunicipal, ('orgao', 'codigo', 'nome', 'secretaria', 'unidade_municipal', 'ativa')),
        'funcao': ('Função', civic.FuncaoOrcamentariaMunicipal, ('codigo', 'nome', 'ativa')),
        'subfuncao': ('Subfunção', civic.SubfuncaoOrcamentariaMunicipal, ('funcao', 'codigo', 'nome', 'ativa')),
        'natureza': ('Natureza da despesa', civic.NaturezaDespesaMunicipal, ('codigo', 'nome', 'descricao', 'ativa')),
        'elemento': ('Elemento da despesa', civic.ElementoDespesaMunicipal, ('natureza', 'codigo', 'nome', 'ativo')),
        'fonte': ('Fonte / destinação de recurso', civic.FonteDestinacaoRecursoMunicipal, ('codigo', 'nome', 'descricao', 'ativa')),
        'dotacao': ('Dotação / QDD', civic.DotacaoOrcamentariaMunicipal, ('exercicio', 'unidade_orcamentaria', 'funcao', 'subfuncao', 'programa', 'acao', 'natureza_despesa', 'elemento_despesa', 'fonte_recurso', 'codigo_qdd', 'descricao', 'valor_inicial', 'ativa')),
        'credito': ('Crédito adicional (registro preparatório)', civic.CreditoAdicionalMunicipal, ('exercicio', 'dotacao_destino', 'dotacao_origem', 'tipo', 'valor', 'fundamento', 'documento_referencia', 'status')),
    },
    'contabilidade': {
        'plano': ('Plano de contas parametrizável', civic.PlanoContasMunicipal, ('codigo', 'nome', 'versao', 'referencia_normativa', 'vigente_desde', 'vigente_ate', 'ativo', 'parametrizacao')),
        'conta': ('Conta contábil', civic.ContaContabilMunicipal, ('plano', 'conta_pai', 'codigo', 'nome', 'classificacao', 'natureza_saldo', 'nivel', 'aceita_lancamento', 'ativa')),
        'periodo': ('Período contábil', civic.PeriodoContabilMunicipal, ('exercicio', 'mes', 'status')),
        'lancamento': ('Lançamento preparatório', civic.LancamentoContabilMunicipal, ('exercicio', 'periodo', 'data_referencia', 'origem', 'referencia_externa', 'historico', 'status', 'request_id')),
        'partida': ('Partida contábil preparatória', civic.PartidaContabilMunicipal, ('lancamento', 'conta', 'lado', 'valor', 'historico')),
        'documento': ('Referência documental', civic.DocumentoContabilMunicipal, ('lancamento', 'titulo', 'tipo', 'identificador', 'sha256', 'storage_key')),
        'fechamento': ('Acompanhamento de fechamento', civic.FechamentoContabilMunicipal, ('periodo', 'status', 'observacoes')),
    },
    'tesouraria': {
        'banco': ('Banco', civic.BancoMunicipal, ('codigo', 'nome', 'ativo')),
        'conta_bancaria': ('Conta bancária municipal', civic.ContaBancariaMunicipal, ('banco', 'unidade_orcamentaria', 'descricao', 'agencia', 'numero_conta', 'digito', 'saldo_inicial_informativo', 'data_saldo_inicial', 'status', 'observacoes')),
        'movimentacao': ('Referência de movimentação (não contabiliza nem paga)', civic.MovimentacaoTesourariaMunicipal, ('conta_origem', 'conta_destino', 'tipo', 'data_referencia', 'valor', 'descricao', 'documento_referencia', 'status')),
        'conciliacao': ('Acompanhamento de conciliação', civic.ConciliacaoBancariaMunicipal, ('conta', 'periodo_inicio', 'periodo_fim', 'saldo_extrato_informativo', 'referencia_extrato', 'status', 'observacoes')),
    },
}

ACTOR_FIELDS = {
    civic.ExercicioMunicipal: {'criado_por'},
    civic.InstrumentoPlanejamentoMunicipal: {'criado_por'},
    civic.ProgramaPlanejamentoMunicipal: {'criado_por'},
    civic.DotacaoOrcamentariaMunicipal: {'criado_por'},
    civic.CreditoAdicionalMunicipal: {'criado_por'},
    civic.LancamentoContabilMunicipal: {'criado_por'},
    civic.DocumentoContabilMunicipal: {'criado_por'},
    civic.FechamentoContabilMunicipal: {'iniciado_por'},
    civic.MovimentacaoTesourariaMunicipal: {'criado_por'},
    civic.ConciliacaoBancariaMunicipal: {'iniciado_por'},
}


def build_foundation_form(model, fields, *, actor, data=None, instance=None, prefix=None):
    """Create a ModelForm whose foreign-key choices are restricted to tenant."""
    meta = type('Meta', (), {'model': model, 'fields': fields})

    def __init__(self, *args, **kwargs):
        super(form_class, self).__init__(*args, **kwargs)
        organization = current_organization()
        for name, field in self.fields.items():
            widget = field.widget
            css = 'gp-input'
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = 'gp-select'
            attrs = {'class': css}
            if isinstance(field, forms.DateField):
                attrs['type'] = 'date'
            if isinstance(field, forms.DecimalField):
                attrs['inputmode'] = 'decimal'
            widget.attrs.update(attrs)
            if isinstance(field, forms.ModelChoiceField):
                related_model = field.queryset.model
                if any(f.name == 'organization' for f in related_model._meta.fields):
                    field.queryset = scoped_queryset(actor, related_model.objects.filter(organization=organization))
        for name in ACTOR_FIELDS.get(model, set()):
            if hasattr(self.instance, name):
                setattr(self.instance, name, getattr(self, '_actor', None))

    form_class = type(f'{model.__name__}FoundationForm', (forms.ModelForm,), {'Meta': meta, '__init__': __init__})
    form = form_class(data=data, instance=instance, prefix=prefix)
    form._actor = None
    return form


def foundation_form(model, fields, *, actor, data=None, instance=None, prefix=None):
    form = build_foundation_form(model, fields, actor=actor, data=data, instance=instance, prefix=prefix)
    form._actor = actor
    for name in ACTOR_FIELDS.get(model, set()):
        if hasattr(form.instance, name):
            setattr(form.instance, name, actor)
    return form
