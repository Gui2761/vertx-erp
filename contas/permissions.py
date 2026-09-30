"""
Controle de acesso por perfil, aplicado sempre no backend (nunca só
escondendo botão na tela).

Uso em views baseadas em função:
    @perfis_requeridos("ADMIN", "GESTOR")
    def minha_view(request): ...

Uso em views baseadas em classe:
    class MinhaView(PerfilRequeridoMixin, View):
        perfis_permitidos = ("ADMIN", "GESTOR")
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from platform_core.access import require_erp


def perfis_requeridos(*perfis):
    def decorador(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            usuario = request.user
            require_erp(usuario, roles=perfis)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorador


class PerfilRequeridoMixin:
    """Mixin para CBVs. Defina `perfis_permitidos` na subclasse."""

    perfis_permitidos: tuple = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{'/contas/login/'}?next={request.path}")
        require_erp(request.user, roles=self.perfis_permitidos)
        return super().dispatch(request, *args, **kwargs)
