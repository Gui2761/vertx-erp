from django import template
from django.utils import timezone
from django.utils.dateparse import parse_datetime
register=template.Library()

@register.filter
def ponto_duracao(value):
    if value is None: return 'Sem referência'
    minutes=int(value)
    return f'{minutes//60:02d}:{minutes%60:02d}'

@register.filter
def ponto_instante(value):
    at=parse_datetime(value) if value else None
    if at is None: return '—'
    if timezone.is_aware(at): at=timezone.localtime(at)
    return at.strftime('%d/%m/%Y %H:%M:%S')
