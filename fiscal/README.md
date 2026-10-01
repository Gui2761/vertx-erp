# Integração fiscal — preparação e limites

Esta camada não emite documentos fiscais sem provedor real. NF-e, NFC-e e
NFS-e têm cadastros/payloads e fluxo comum, mas validações legais, cálculos e
comunicação dependem de um adaptador aprovado para cada cobertura do provedor.
O registro `providers.ADAPTERS` fica vazio na entrega local.

## Contrato de integração

O adaptador implementa `Provider` em `providers/base.py`: `emitir(payload,
idempotency_key)`, `consultar(protocolo)` e `cancelar(protocolo, justificativa)`.
Retorna `FiscalResult`; autorização exige número e protocolo reais. XML/PDF
retornados são validados e armazenados como documentos privados da organização.
Transições são auditadas por `services.executar`; a chave de idempotência combina
UUID da organização, ID do documento e ambiente. Não repetir emissão após timeout sem consultar o
provedor. É necessário implementar tratamento de falhas e reconciliação da
resposta para a API escolhida antes de habilitar seu uso real.

A fábrica registrada recebe organização e ambiente. Deve obter segredos
externos específicos daquela organização, mantendo sandbox/produção separados.
Não usar imports escolhidos pelo usuário, tokens no cadastro, certificados no
repositório, valores fiscais presumidos ou respostas simuladas em produção.

## Dados necessários na próxima etapa

1. Escolher provedor, verificar suporte ao município/UF e aos tipos de nota
   utilizados; obter documentação oficial e acesso de sandbox.
2. Confirmar com o contador CNPJ/inscrições, endereço, município/UF, regime
   tributário, códigos de serviço/NCM/CFOP/CST/CSOSN e impostos/retenções.
3. Definir série, regras de numeração/cancelamento e cadastro do emitente com
   o provedor. Informar certificados/credenciais de prefeitura somente se o
   provedor e o município exigirem, por canal seguro e configuração externa.
4. Disponibilizar tokens/chaves/certificados do provedor em cofre ou variáveis
   externas; os nomes e endpoints só serão definidos pela integração escolhida.
5. Implementar e registrar o adaptador, cobrir respostas reais e falhas de
   rede/idempotência, validar XML/PDF e homologar emissão/consulta/cancelamento.
6. Decidir uma ativação em produção separadamente, após homologação fiscal.

Nenhum token, certificado, endpoint fiscal ou credencial foi inventado.
