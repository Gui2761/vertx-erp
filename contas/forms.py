from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Usuario, Tecnico
from platform_core.forms import TenantModelForm
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label='E-mail ou usuário', max_length=254,
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}),
    )

    def clean(self):
        submitted = self.cleaned_data.get('username')
        if submitted and '@' in submitted:
            User = get_user_model()
            identity_field = User.USERNAME_FIELD
            matches = list(
                User._default_manager.filter(email__iexact=submitted)
                .values_list(identity_field, flat=True)[:2]
            )
            if len(matches) == 1:
                self.cleaned_data['username'] = matches[0]
            elif len(matches) > 1:
                # Never choose arbitrarily when duplicate email addresses exist.
                self.add_error('username', self.get_invalid_login_error())
                return self.cleaned_data
        return super().clean()


class UsuarioCreationForm(UserCreationForm):
    visualizar_painel_operacional = forms.BooleanField(label='Visualizar painel operacional (dados operacionais de toda a organização)', required=False)
    acesso_assistencia = forms.BooleanField(label='Acesso ao ERP Assistência', required=False, initial=True)
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("username", "first_name", "last_name", "email", "perfil", "telefone")


class UsuarioEdicaoForm(forms.Form):
    visualizar_painel_operacional = forms.BooleanField(label='Visualizar painel operacional (dados operacionais de toda a organização)', required=False)
    perfil = forms.ChoiceField(label='Papel nesta organização', choices=OrganizationMembership._meta.get_field('role').choices)
    status = forms.ChoiceField(label='Status do vínculo', choices=OrganizationMembership.Status.choices)
    acesso_assistencia = forms.BooleanField(label='Acesso ao ERP Assistência', required=False)

    def __init__(self, *args, membership, **kwargs):
        kwargs.setdefault('initial', {}).update(perfil=membership.role, status=membership.status, visualizar_painel_operacional=membership.erp_accesses.filter(erp__code='assistencia', visualizar_painel_operacional=True).exists(), acesso_assistencia=membership.erp_accesses.filter(erp__code='assistencia', enabled=True).exists())
        super().__init__(*args, **kwargs)


class TecnicoForm(TenantModelForm):
    class Meta:
        model = Tecnico
        fields = (
            "usuario",
            "nome",
            "telefone",
            "whatsapp",
            "email",
            "especialidades",
            "funcao", "conselho", "numero_registro", "competencias",
            "registro_profissional",
            "jornada",
            "custo_hora",
            "ativo",
        )
        widgets = {
            "especialidades": forms.TextInput(),
        }

    def __init__(self, *args, usuario_logado=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['usuario'].queryset = Usuario.objects.filter(memberships__organization=current_organization(), memberships__status='ATIVO', is_active=True).distinct()
        # custo_hora só é visível/editável para administrador e gestor
        if usuario_logado and not (usuario_logado.is_administrador or usuario_logado.is_gestor):
            self.fields.pop("custo_hora", None)
