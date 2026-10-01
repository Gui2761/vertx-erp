from django.contrib import admin
from platform_core.business_admin import BusinessAdmin
from . import models

for model in [models.Peca, models.Fornecedor, models.Movimentacao, models.Orcamento, models.ItemOrcamento, models.Contrato, models.AgendaPreventiva, models.CategoriaFinanceira, models.CentroCusto, models.FormaPagamento, models.Lancamento, models.EventoFinanceiro]:
    admin.site.register(model, BusinessAdmin)
