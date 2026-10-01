from django import template
from gestao.permissions import allowed

register = template.Library()


@register.simple_tag(takes_context=True)
def modulo_permitido(context, permission):
    request = context.get('request')
    return bool(request and allowed(request.user, permission))
