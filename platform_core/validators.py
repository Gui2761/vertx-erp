"""CNPJ numérico e alfanumérico: módulo 11, valores ASCII menos 48 (RFB)."""
import re
from django.core.exceptions import ValidationError


def normalize_cnpj(value):
    return re.sub(r'[.\-/\s]', '', str(value or '')).upper()


def validate_cnpj(value):
    value = normalize_cnpj(value)
    if not value:
        return  # TECNOLMED inicial não deve receber CNPJ fictício.
    if not re.fullmatch(r'[A-Z0-9]{12}[0-9]{2}', value) or len(set(value)) == 1:
        raise ValidationError('Informe um CNPJ válido, numérico ou alfanumérico.')
    base = value[:12]
    for weights in [(5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)]:
        remainder = sum((ord(char) - 48) * weight for char, weight in zip(base, weights)) % 11
        base += str(0 if remainder < 2 else 11 - remainder)
    if value != base:
        raise ValidationError('Dígitos verificadores do CNPJ inválidos.')


def formatted_cnpj(value):
    value = normalize_cnpj(value)
    return f'{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}' if len(value) == 14 else value
