"""Public operational states over the existing append-only fiscal records."""
from dataclasses import dataclass
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone
from urllib.parse import urlsplit


def estado(documento, solicitacao=None):
    final={'AUTORIZADA':'AUTORIZADO','REJEITADA':'REJEITADO','CANCELADA':'CANCELADO'}
    if documento.status in final:return final[documento.status]
    if solicitacao:
        last=solicitacao.tentativas.order_by('-pk').first()
        if solicitacao.estado=='RESULTADO_DESCONHECIDO':
            return 'TIMEOUT' if last and last.resultado=='TIMEOUT' else 'CONSULTA_PENDENTE'
        if solicitacao.estado=='BLOQUEADA':return 'ERRO'
        if solicitacao.estado=='ENVIANDO':return 'ENVIANDO'
        if solicitacao.artefatos_nfce.filter(tipo='ENVIADO').exists():return 'CONSULTA_PENDENTE'
    return 'PENDENTE'


@dataclass(frozen=True)
class RegraCancelamento:
    organization_id: int
    estabelecimento_id: int
    minutos: int
    fonte: str
    confirmada: bool = False

    def validar(self,doc):
        source=urlsplit(self.fonte)
        if self.confirmada is not True or type(self.minutos) is not int or self.minutos<=0 or source.scheme!='https' or source.hostname not in ('www.sefaz.se.gov.br','www.nfe.fazenda.gov.br','www.confaz.fazenda.gov.br') or source.username or source.password:
            raise ValidationError('Prazo/regras de cancelamento SE não confirmados; evento bloqueado.')
        if (doc.organization_id,doc.estabelecimento_id,doc.ambiente,doc.status)!=(self.organization_id,self.estabelecimento_id,'HOMOLOGACAO','AUTORIZADA'):
            raise ValidationError('Cancelamento fora do tenant/estabelecimento/ambiente ou sem autorização.')
        if not doc.autorizado_em or not doc.protocolo or not doc.autorizado_em<=timezone.now()<=doc.autorizado_em+timedelta(minutes=self.minutos):
            raise ValidationError('Cancelamento fora do prazo confirmado ou sem protocolo/data de autorização.')
