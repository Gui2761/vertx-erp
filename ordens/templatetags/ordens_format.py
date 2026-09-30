from datetime import datetime
from django import template

register = template.Library()


@register.filter
def data_os(value):
    if not value:
        return ''
    try:
        date = datetime.fromisoformat(value) if isinstance(value, str) else value
        return date.strftime('%d/%m/%Y %H:%M:%S')
    except (ValueError, TypeError, AttributeError):
        return value
