"""Operational scope for the existing technician experience and memberships."""
from django.db.models import Q
from platform_core.access import effective_role


def calls_for(user):
    from .models import Chamado
    from ordens.services import visiveis
    return Chamado.objects.filter(
        Q(tecnico__usuario=user, tecnico__ativo=True, ordem__isnull=True) |
        Q(ordem__in=visiveis(user))
    ).distinct()


def scoped_records(user, queryset, field):
    if effective_role(user) != 'TECNICO':
        return queryset
    from ordens.services import visiveis
    return queryset.filter(
        Q(pk__in=visiveis(user).values(field + '_id')) |
        Q(pk__in=calls_for(user).values(field + '_id'))
    ).distinct()


def route_allowed(match):
    """Deny administrative routes even if a capability override is granted."""
    if match is None:
        return True  # Unknown URLs retain the normal 404 response.
    namespace, name = match.namespace, match.url_name
    if namespace == 'ordens':
        return True  # Each operation additionally authorizes its OS and actor.
    if namespace == 'platform_core':
        return name in {'home', 'select_organization'}
    if namespace == 'contas':
        return name in {'login', 'logout'}
    if namespace == 'core':
        return name == 'painel'  # Redirected before administrative queries.
    if namespace == 'clientes':
        return name in {'cliente_list', 'cliente_detail'}
    if namespace == 'equipamentos':
        return name in {'equipamento_list', 'equipamento_detail', 'equipamento_qr'}
    if namespace == 'gestao':
        if name == 'relatorio':
            return match.kwargs.get('key') in {
                'os_periodo', 'os_status', 'os_tecnico', 'os_cliente',
                'preventivas_realizadas', 'pecas_utilizadas',
            }  # Existing exports are scoped by the authorized OS queryset.
        return name in {'movimentar', 'planejamento'}
    if namespace == 'operacao':
        return name in {
            'tecnico', 'mobile_qr', 'contract_activity', 'calendario', 'planning_detail',
            'chamado_lista', 'chamado_detalhe', 'conhecimento_lista', 'conhecimento_detalhe',
            'conhecimento_novo', 'conhecimento_editar',
            'plano_lista', 'plano_detalhe', 'documento_lista', 'documento_detalhe',
            'documento_novo', 'documento_arquivo', 'notificacoes', 'notificacao_lida',
            'os_acao', 'os_necessidade', 'necessidades', 'ponto_home', 'ponto_mirror', 'ponto_overtime',
            'manifest', 'worker',
        }
    return name in {'health', 'legacy_media'}
