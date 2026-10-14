from django.core.exceptions import ValidationError
from .base import MotorSimulado

class MotorNFSeSimulado(MotorSimulado):
    tipo = 'NFSE'
    modelo = 'NFSE'
    def validar(self, documento):
        super().validar(documento)
        if not hasattr(documento, 'detalhesnfse'):
            raise ValidationError('NFS-e exige seus detalhes de serviço.')
