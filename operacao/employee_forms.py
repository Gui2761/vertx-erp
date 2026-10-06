"""One employee sheet over the existing tenant models and access policies."""
from django import forms
from django.forms.models import construct_instance
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from platform_core.access import effective_role
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership
from contas.models import Usuario, Tecnico
from gestao.forms import Estilizado
from . import models as m, workforce

DAYS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
TIMES = [('entrada', 'Entrada'), ('inicio_intervalo', 'Início intervalo'),
         ('fim_intervalo', 'Fim intervalo'), ('saida', 'Saída')]
TECH_FIELDS = ['especialidades', 'funcao', 'conselho', 'numero_registro',
               'competencias', 'registro_profissional', 'whatsapp', 'custo_hora', 'ativo']
EMPLOYEE_ROLES = [(key, label) for key, label in OrganizationMembership._meta.get_field('role').choices
                  if key not in {'CLIENTE', 'PAINEL', 'PAINEL_TV'}]


class JornadaForm(Estilizado):
    """Visual week editor; JSON is only the model's existing storage format."""
    class Meta:
        model = m.JornadaTrabalho
        fields = ['nome', 'virada_dia', 'tolerancia_atraso_minutos',
                  'banco_horas_habilitado', 'compensar_deficit', 'ativo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for index, day in enumerate(DAYS):
            row = self.instance.semana.get(str(index), {})
            self.fields[f'dia_{index}_trabalha'] = forms.BooleanField(
                label='Trabalha', required=False,
                initial=bool(row) if self.instance.pk else index < 5,
                widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'data-working-day': index}))
            for key, label in TIMES:
                self.fields[f'dia_{index}_{key}'] = forms.TimeField(
                    label=f'{day} · {label}', required=False, input_formats=['%H:%M'],
                    initial=row.get(key), widget=forms.TimeInput(format='%H:%M',
                    attrs={'type': 'time', 'class': 'form-control', 'data-schedule-time': key}))

    @property
    def days(self):
        return [{'label': day, 'index': index, 'works': self[f'dia_{index}_trabalha'],
                 'times': [self[f'dia_{index}_{key}'] for key, _ in TIMES]}
                for index, day in enumerate(DAYS)]

    def clean(self):
        data = super().clean()
        week = {}
        for index, day in enumerate(DAYS):
            if not data.get(f'dia_{index}_trabalha'):
                continue
            row = {}
            for key, label in TIMES:
                value = data.get(f'dia_{index}_{key}')
                if value:
                    row[key] = value.strftime('%H:%M')
                elif key in ('entrada', 'saida'):
                    self.add_error(f'dia_{index}_{key}', f'Informe {label.lower()} de {day.lower()}.')
            if 'entrada' in row and 'saida' in row:
                try:
                    workforce.schedule_values(row, data.get('virada_dia', False))
                except ValidationError as exc:
                    self.add_error(None, f'{day}: {"; ".join(exc.messages)}')
                week[str(index)] = row
        self.instance.semana = week
        if not week:
            self.add_error(None, 'Configure pelo menos um dia de trabalho.')
        return data


class FuncionarioForm(Estilizado):
    conta_modo = forms.ChoiceField(label='Conta de acesso', choices=[('EXISTENTE', 'Vincular conta existente'),
                                                                  ('NOVA', 'Criar conta de acesso')], initial='EXISTENTE')
    username = forms.CharField(label='Nome de usuário', max_length=150, required=False,
                              validators=Usuario._meta.get_field('username').validators)
    password1 = forms.CharField(label='Senha inicial', required=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirmar senha inicial', required=False, widget=forms.PasswordInput)
    perfil = forms.ChoiceField(label='Perfil de acesso nesta organização', choices=[('', 'Selecione o perfil')] + EMPLOYEE_ROLES, required=False)
    acesso_assistencia = forms.BooleanField(label='Acesso à Assistência', required=False, initial=True)
    jornada_modo = forms.ChoiceField(label='Jornada de trabalho', choices=[('EXISTENTE', 'Selecionar jornada existente'),
                                                                      ('NOVA', '+ Criar nova jornada')], initial='EXISTENTE')
    tecnico_existente = forms.ModelChoiceField(label='Ficha técnica existente (opcional)',
                                               queryset=Tecnico.objects.none(), required=False,
                                               help_text='Para reutilizar uma ficha técnica ainda sem conta vinculada.')

    class Meta:
        model = m.Funcionario
        fields = ['nome', 'matricula', 'telefone', 'email', 'admissao', 'ativo',
                  'departamento', 'cargo', 'gestor', 'vinculo', 'desligamento',
                  'usuario', 'jornada', 'autoriza_geolocalizacao']

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        self.manage_access = effective_role(actor) == 'ADMIN'
        self.manage_technical = effective_role(actor) in {'ADMIN', 'GESTOR'}
        super().__init__(*args, **kwargs)
        self.membership = None
        self.technical = self.instance.tecnico if self.instance.tecnico_id else None
        members = Usuario.objects.filter(memberships__organization=current_organization(),
                                         memberships__status='ATIVO', is_active=True).distinct()
        self.fields['usuario'].queryset = members
        self.fields['usuario'].required = False
        self.fields['gestor'].queryset = members
        self.fields['tecnico_existente'].queryset = Tecnico.objects.filter(usuario__isnull=True)
        if self.instance.pk:
            self.membership = OrganizationMembership.objects.get(organization=current_organization(), user=self.instance.usuario)
            self.fields['usuario'].disabled = True
            self.fields['conta_modo'].disabled = True
            self.initial.update(conta_modo='EXISTENTE', perfil=self.membership.role)
            self.initial['acesso_assistencia'] = self.membership.erp_accesses.filter(erp__code='assistencia', enabled=True).exists()
            if not self.technical:
                self.technical = Tecnico.objects.filter(usuario=self.instance.usuario).first()
        if not self.manage_access:
            self.fields['conta_modo'].choices = [('EXISTENTE', 'Vincular conta existente')]
            for key in ['username', 'password1', 'password2', 'perfil', 'acesso_assistencia']:
                self.fields.pop(key)
        if not self.manage_technical:
            self.fields.pop('tecnico_existente')
        if self.manage_technical:
            for name in TECH_FIELDS:
                field = Tecnico._meta.get_field(name).formfield(required=False)
                if name == 'ativo':
                    field.initial = True
                field.widget.attrs['class'] = ('form-check-input' if isinstance(field.widget, forms.CheckboxInput)
                                                else 'form-control')
                if isinstance(field.widget, forms.Textarea):
                    field.widget.attrs['rows'] = 3
                self.fields['tecnico_' + name] = field
                if self.technical:
                    self.initial['tecnico_' + name] = getattr(self.technical, name)
        if 'perfil' in self.fields:
            self.fields['perfil'].help_text = 'Perfil controla o acesso. Cargo/Função descreve o trabalho.'

    @property
    def technical_fields(self):
        return [self['tecnico_' + name] for name in TECH_FIELDS if 'tecnico_' + name in self.fields]

    def clean(self):
        data = super().clean()
        creating = data.get('conta_modo') == 'NOVA' and not self.instance.pk
        if not self.manage_access and any(key in self.data for key in ('perfil', 'username', 'password1', 'password2', 'acesso_assistencia')):
            self.add_error(None, 'Alteração de acesso exige administrador da organização.')
        if self.instance.pk and self.data.get('usuario') not in (None, '', str(self.instance.usuario_id)):
            self.add_error(None, 'A conta vinculada não pode ser substituída; o histórico pertence a esta pessoa.')
        if creating:
            if not data.get('username'):
                self.add_error('username', 'Informe o nome de usuário.')
            elif Usuario.objects.filter(username__iexact=data['username']).exists():
                self.add_error('username', 'Nome de usuário indisponível. Selecione uma conta existente autorizada.')
            if not data.get('password1'):
                self.add_error('password1', 'Defina a senha inicial.')
            elif data.get('password1') != data.get('password2'):
                self.add_error('password2', 'As senhas não coincidem.')
            else:
                try:
                    validate_password(data['password1'], Usuario(username=data.get('username', ''),
                                                                 first_name=data.get('nome', ''), email=data.get('email', '')))
                except ValidationError as exc:
                    self.add_error('password1', exc)
            if not data.get('perfil'):
                self.add_error('perfil', 'Selecione o perfil de acesso.')
        else:
            user = data.get('usuario')
            if not user:
                self.add_error('usuario', 'Selecione a conta de acesso vinculada.')
            else:
                self.membership = OrganizationMembership.objects.get(user=user, organization=current_organization(), status='ATIVO')
                if m.Funcionario.objects.filter(usuario=user).exclude(pk=self.instance.pk).exists():
                    self.add_error('usuario', 'Esta pessoa já possui ficha de funcionário nesta organização. Edite a ficha existente.')
                if self.membership.role not in dict(EMPLOYEE_ROLES):
                    self.add_error('usuario', 'Esta conta não possui perfil de funcionário.')
                data['perfil'] = data.get('perfil') or self.membership.role
        if data.get('jornada_modo') == 'NOVA':
            data['jornada'] = None
        if data.get('admissao') and data.get('desligamento') and data['desligamento'] < data['admissao']:
            self.add_error('desligamento', 'Desligamento anterior à admissão.')
        if data.get('tecnico_existente') and data.get('perfil') != 'TECNICO':
            self.add_error('tecnico_existente', 'Uma ficha técnica somente pode ser vinculada ao perfil TÉCNICO.')
        if self.manage_technical and data.get('tecnico_custo_hora') is not None and data['tecnico_custo_hora'] < 0:
            self.add_error('tecnico_custo_hora', 'Custo/hora não pode ser negativo.')
        if self.manage_access and self.membership and self.membership.user_id == self.actor.pk and data.get('perfil') != 'ADMIN':
            self.add_error('perfil', 'Seu próprio vínculo administrativo não pode ser removido nesta ficha.')
        return data

    def _post_clean(self):
        if self.instance.pk or (self.cleaned_data.get('conta_modo') != 'NOVA' and self.cleaned_data.get('usuario')):
            return super()._post_clean()
        # The required account will be created atomically by the service.
        # Validate the employee again with its real membership before persistence.
        self.instance = construct_instance(self, self.instance, self._meta.fields, self._meta.exclude)
        excluded = self._get_validation_exclusions() | {'usuario'}
        try:
            self.instance.clean_fields(exclude=excluded)
            self.instance.validate_constraints(exclude=excluded)
        except ValidationError as exc:
            self._update_errors(exc)
