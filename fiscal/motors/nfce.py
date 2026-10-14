from django.core.exceptions import ValidationError
from .base import MotorSimulado

class MotorNFCeSimulado(MotorSimulado):
    tipo = 'NFCE'
    modelo = '65'
    def validar(self, documento):
        super().validar(documento)
        if not hasattr(documento, 'detalhesnfce') or not documento.venda_id or documento.detalhesnfce.modo_emissao != 'NORMAL':
            raise ValidationError('NFC-e exige venda confirmada; contingência fiscal não habilitada.')
