from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class FiscalResult:
    status: str
    numero: str = ''
    protocolo: str = ''
    xml: bytes = b''
    pdf: bytes = b''

class Provider(Protocol):
    def emitir(self, payload: dict, idempotency_key: str) -> FiscalResult: ...
    def consultar(self, protocolo: str) -> FiscalResult: ...
    def cancelar(self, protocolo: str, justificativa: str) -> FiscalResult: ...
