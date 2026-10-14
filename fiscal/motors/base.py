"""Durable LOCAL simulation responses, explicitly NOT a fiscal authority."""
from django.core.exceptions import ValidationError
from django.db import transaction
from gestao.services import write
from operacao.models import SolicitacaoFiscal

class MotorSimulado:
    tipo = ''
    modelo = ''
    def validar(self, documento):
        if documento.tipo != self.tipo or documento.ambiente != 'SIMULACAO' or documento.modelo != self.modelo:
            raise ValidationError('Motor, modelo ou ambiente incompatíveis.')

    def consultar(self, request_id):
        # Acts as the durable receipt of a remote authority, but LOCAL only.
        return SolicitacaoFiscal.objects.get(pk=request_id).resultado_simulado or None

    def emitir(self, solicitacao):
        with transaction.atomic():
            req = SolicitacaoFiscal.objects.select_for_update().select_related('documento').get(pk=solicitacao.pk)
            self.validar(req.documento)
            if req.resultado_simulado:
                return req.resultado_simulado
            if req.cenario_simulacao == 'TIMEOUT_ANTES' and req.tentativas.count() == 1:
                raise TimeoutError('Falha sintética antes da resposta.')
            status = 'CANCELADA' if req.operacao == 'CANCELAR' else 'REJEITADA' if req.cenario_simulacao == 'REJEITAR' else 'AUTORIZADA'
            result = {'status': status, 'tipo': self.tipo, 'modelo': self.modelo, 'ambiente': 'SIMULACAO',
                      'organization': str(req.organization.public_id), 'documento': req.documento_id,
                      'request_id': str(req.request_id), 'numero': req.documento.numero,
                      'protocolo': f'SIMULACAO-{req.request_id}',
                      'chave': req.documento.chave if req.operacao == 'CANCELAR' else f'SIM-{req.documento_id}-{req.request_id}',
                      'sem_valor_fiscal': True}
            req.resultado_simulado = result
            write(req)
        # Commit the simulated receipt FIRST, to reproduce a lost response safely.
        if req.cenario_simulacao == 'TIMEOUT_APOS':
            raise TimeoutError('Falha sintética após confirmação simulada.')
        return result
