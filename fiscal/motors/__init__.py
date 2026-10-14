from .nfse import MotorNFSeSimulado
from .nfe import MotorNFeSimulado
from .nfce import MotorNFCeSimulado

def resolver(tipo, ambiente='SIMULACAO'):
    if ambiente == 'HOMOLOGACAO':
        if tipo != 'NFCE':
            from django.core.exceptions import ValidationError
            raise ValidationError('Homologação desta fase é exclusiva de NFC-e.')
        from .nfce_homologacao import MotorNFCeHomologacao
        return MotorNFCeHomologacao()
    if ambiente != 'SIMULACAO':
        from django.core.exceptions import ValidationError
        raise ValidationError('Produção fiscal não habilitada.')
    return {'NFSE': MotorNFSeSimulado, 'NFE': MotorNFeSimulado, 'NFCE': MotorNFCeSimulado}[tipo]()
