"""Commercial units resolve into the existing stock base; no secondary balance."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Peca

def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('Número decimal inválido.')
    if not result.is_finite():
        raise ValidationError('Número decimal inválido.')
    return result

def convert(part, quantity, mode='venda', unit_price=None):
    if mode not in ('compra', 'venda', 'base'):
        raise ValidationError('Conversão desconhecida.')
    quantity = number(quantity)
    factor = Decimal('1') if mode == 'base' else getattr(part, 'fator_' + mode)
    base = quantity * factor
    if quantity <= 0 or base > Decimal('99999999999.999') or base != base.quantize(Decimal('.001')) or (not part.fracionavel and base != base.to_integral_value()):
        raise ValidationError('Quantidade incompatível com a unidade base/precisão do estoque.')
    result = {'quantidade_comercial': str(quantity), 'fator': str(factor), 'unidade': part.unidade_medida if mode == 'base' else getattr(part, 'unidade_' + mode) or part.unidade_medida, 'quantidade_base': base.quantize(Decimal('.001'))}
    if unit_price is not None:
        price = number(unit_price)
        base_price = price / factor
        if price < 0 or base_price > Decimal('999999999999.99') or base_price != base_price.quantize(Decimal('.01')):
            raise ValidationError('Preço/custo por unidade base precisa ser exato em centavos; revise unidade ou valor.')
        result['valor_base'] = base_price.quantize(Decimal('.01'))
    return result

def lookup(code):
    code = str(code).strip()
    matches = list(Peca.objects.filter(ativo=True).filter(Q(sku__iexact=code) | Q(gtin=code) | Q(codigo_barras=code) | Q(codigos_alternativos__codigo=code)).distinct()[:2])
    if len(matches) != 1:
        raise ValidationError('Produto não encontrado ou código ambíguo; revise o cadastro.')
    return matches[0]
