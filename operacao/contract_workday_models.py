"""Jornada contratual: eventos próprios, sem reutilizar marcações de ponto."""
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from gestao.models import Validado, RegistroImutavel


class ConfiguracaoJornadaContrato(Validado):
    contrato = models.OneToOneField('gestao.Contrato', on_delete=models.PROTECT, related_name='jornada_config')
    habilitada = models.BooleanField(default=False)
    exigir_inicio = models.BooleanField('Exigir início para liberar OS', default=False)
    deslocamento_faturavel = models.BooleanField(default=False)
    inicio_contagem = models.CharField(max_length=8, choices=[('BASE', 'Saída da base'), ('DESTINO', 'Chegada ao destino')], default='DESTINO')
    retorno_faturavel = models.BooleanField(default=False)
    descontar_intervalos = models.BooleanField(default=True)
    limite_diario_minutos = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    horario_inicial = models.TimeField(null=True, blank=True)
    horario_final = models.TimeField(null=True, blank=True)
    categoria_padrao = models.CharField(max_length=80, default='Assistência técnica')
    tarifas = models.JSONField(default=dict, help_text='Objeto categoria: valor/hora, por exemplo {"Assistência técnica": "100.00"}. Não aparece na OS.')
    fracao_minutos = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    arredondamento = models.CharField(max_length=10, choices=[('EXATO', 'Exato'), ('CIMA', 'Próxima fração'), ('PROXIMO', 'Fração mais próxima')], default='EXATO')

    def clean(self):
        super().clean()
        if self.exigir_inicio and not self.habilitada:
            raise ValidationError('Habilite a jornada antes de exigir início.')
        if bool(self.horario_inicial) != bool(self.horario_final) or self.horario_inicial and self.horario_final <= self.horario_inicial:
            raise ValidationError('Informe os dois horários, com término posterior; faixa diária sem atravessar meia-noite.')
        if not isinstance(self.tarifas, dict) or not self.tarifas or self.categoria_padrao not in self.tarifas:
            raise ValidationError({'tarifas': 'Cadastre a categoria padrão e seu valor/hora.'})
        try:
            for name, value in self.tarifas.items():
                amount = Decimal(str(value))
                if not isinstance(name, str) or not name.strip() or len(name)>80 or not amount.is_finite() or amount<0 or amount>Decimal('999999999999.99') or amount.as_tuple().exponent < -2:
                    raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError({'tarifas': 'Use categorias e valores não negativos com até dois decimais.'})


class JornadaContrato(RegistroImutavel):
    contrato = models.ForeignKey('gestao.Contrato', on_delete=models.PROTECT, related_name='jornadas_externas')
    tecnico = models.ForeignKey('contas.Tecnico', on_delete=models.PROTECT)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    data = models.DateField(editable=False)
    inicio = models.DateTimeField(editable=False)
    origem = models.CharField(max_length=255, blank=True)
    municipio = models.CharField(max_length=150, blank=True)
    destino = models.CharField(max_length=255)
    agenda = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT)
    categoria = models.CharField(max_length=80)
    regras = models.JSONField(editable=False)
    gps = models.JSONField(default=dict, editable=False)

    class Meta:
        ordering = ['-inicio', '-pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'contrato', 'tecnico', 'data'], name='jornada_contrato_tecnico_dia')]

    def clean(self):
        super().clean()
        if self.agenda.contrato_id!=self.contrato_id or not (self.agenda.tecnico_id==self.tecnico_id or self.agenda.auxiliares.filter(pk=self.tecnico_id).exists()) or self.tecnico.usuario_id!=self.usuario_id:
            raise ValidationError('Agenda, técnico, usuário e contrato devem coincidir.')

    @property
    def fim(self):
        event = self.eventos.filter(tipo='FIM').first()
        return event.horario if event else None


class EventoJornadaContrato(RegistroImutavel):
    jornada = models.ForeignKey(JornadaContrato, on_delete=models.PROTECT, related_name='eventos')
    tipo = models.CharField(max_length=10, choices=[('CHEGADA', 'Chegada ao destino'), ('PAUSA', 'Iniciar intervalo'), ('RETOMADA', 'Encerrar intervalo'), ('RETORNO', 'Iniciar retorno'), ('FIM', 'Encerrar atividade')])
    horario = models.DateTimeField(editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacao = models.CharField(max_length=1000, blank=True)
    gps = models.JSONField(default=dict, editable=False)

    class Meta:
        ordering = ['horario', 'pk']
        constraints = [models.UniqueConstraint(fields=['jornada', 'tipo'], condition=models.Q(tipo__in=['CHEGADA', 'RETORNO', 'FIM']), name='jornada_evento_terminal_unico')]


class OrdemJornadaContrato(RegistroImutavel):
    jornada = models.ForeignKey(JornadaContrato, on_delete=models.PROTECT, related_name='ordens_vinculadas')
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, related_name='jornadas_contratuais')
    ciclo = models.PositiveIntegerField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['jornada', 'ordem', 'ciclo'], name='jornada_os_ciclo_unico')]

    def clean(self):
        super().clean()
        if self.ordem.contrato_id!=self.jornada.contrato_id or not (self.ordem.tecnico_id==self.jornada.tecnico_id or self.ordem.auxiliares.filter(pk=self.jornada.tecnico_id).exists()):
            raise ValidationError('OS fora do contrato/equipe da jornada.')


class CorrecaoJornadaContrato(RegistroImutavel):
    jornada = models.ForeignKey(JornadaContrato, on_delete=models.PROTECT, related_name='correcoes')
    inicio_solicitado = models.DateTimeField()
    fim_solicitado = models.DateTimeField()
    justificativa = models.TextField()
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    solicitado_em = models.DateTimeField(auto_now_add=True)


class DecisaoJornadaContrato(RegistroImutavel):
    correcao = models.OneToOneField(CorrecaoJornadaContrato, on_delete=models.PROTECT, related_name='decisao')
    aprovada = models.BooleanField()
    justificativa = models.TextField()
    aprovador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decidido_em = models.DateTimeField(auto_now_add=True)
