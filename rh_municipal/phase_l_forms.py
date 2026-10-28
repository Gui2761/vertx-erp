"""Safe, user-facing setup form for non-operational integration endpoints."""
from django import forms

from platform_core.context import current_organization
from .phase_e_services import public_module_available
from .phase_l_models import ConfiguracaoIntegracaoMunicipal, INTEGRATION_MODULES
from .public_services import has_municipal_permission


class IntegrationConfigurationForm(forms.Form):
    provedor = forms.ChoiceField(label='Sistema oficial')
    nome = forms.CharField(label='Identificação', max_length=120)
    endpoint = forms.URLField(label='Endpoint HTTPS', max_length=500, required=False)
    versao_api = forms.CharField(label='Versão da API', max_length=60, required=False)
    ambiente = forms.ChoiceField(label='Ambiente', choices=ConfiguracaoIntegracaoMunicipal.Ambiente.choices)
    referencia_credencial = forms.CharField(
        label='Referência no cofre seguro', max_length=80, required=False,
        help_text='Somente cofre://UUID ou vault://UUID. Não informe senha, token, certificado ou CSC.',
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')
        choices = []
        for provider, module in INTEGRATION_MODULES.items():
            if (public_module_available(current_organization(), module)
                    and has_municipal_permission(actor, 'integration.manage', module=module)):
                choices.append((provider, ConfiguracaoIntegracaoMunicipal.Provedor(provider).label))
        self.fields['provedor'].choices = choices

    def clean(self):
        cleaned = super().clean()
        provider = cleaned.get('provedor')
        if provider:
            module = INTEGRATION_MODULES.get(provider)
            if not module or not has_municipal_permission(self.actor, 'integration.manage', module=module):
                self.add_error('provedor', 'Você não tem acesso ao módulo contratado para configurar esse sistema.')
        ref = (cleaned.get('referencia_credencial') or '').strip()
        if ref:
            from django.core.exceptions import ValidationError
            from .phase_l_models import _validate_secret_reference
            try:
                _validate_secret_reference(ref)
            except ValidationError as exc:
                self.add_error('referencia_credencial', exc)
        return cleaned
