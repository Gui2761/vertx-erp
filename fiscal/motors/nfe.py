from django.core.exceptions import ValidationError
from .base import MotorSimulado

class MotorNFeSimulado(MotorSimulado):
    tipo = 'NFE'
    modelo = '55'
    def validar(self, documento):
        super().validar(documento)
        if not hasattr(documento, 'detalhesnfe') or not documento.venda_id:
            raise ValidationError('NF-e exige venda confirmada e detalhes de mercadorias.')
