# NFC-e / Sergipe — laboratório local da Fase 2

## Atualização local — pré-transmissão, 10/10/2026

Esta etapa acrescenta o checklist final do responsável fiscal, o adaptador de
cofre não provisionado e um ensaio criptográfico real com certificado sintético.
As observações históricas abaixo sobre testes positivos apenas com duplos e
XSD assinado pendente descrevem o estado anterior. O ensaio atual usa RSA-2048
em memória, XMLDSig RSA-SHA1/C14N/SHA1 exigidos pelo XSD oficial, certificado
X509 e cadeia sintéticos; não usa nem comprova um A1 real/ICP-Brasil.

`vault.AdaptadorCofre` verifica referência vinculada ao tenant/estabelecimento/
HOMOLOGAÇÃO/CNPJ antes de chamar qualquer provedor. Exige identidade e metadados
de validade/titular/fingerprint, certificado público, cadeia, âncoras pinadas no
backend e atestado de revogação. O CNPJ é lido do otherName ICP-Brasil
2.16.76.1.3.3, não do arquivo ou CN. O certificado público/cadeia só circulam no
backend; não são salvos na ficha nem devolvidos pelo checklist. Não há PFX,
senha, CSC, loader de chave privada, HTTP ou fallback. Sem provedor, o estado é
**COFRE NÃO PROVISIONADO**. Transmissão permanece incondicionalmente bloqueada
no novo adaptador. Provisionamento real, raízes ICP-Brasil e revogação atual
dependem de uma futura integração autorizada.

`certificates.verificar_cadeia` verifica validade, vínculo issuer/subject,
assinaturas RSA, CA/KeyUsage/path length, unicidade e âncora explicitamente
pinada. Não descobre confiança pela rede nem presume que uma raiz sintética é
ICP-Brasil. O recorte é cadeia RSA; extensões críticas desconhecidas falham.
CRL/OCSP, políticas completas e provisionamento do provedor permanecem externos.

Cinco XSDs públicos do PL 010f v1.04 foram incorporados sem alteração em
`schemas/PL_010f_v1.04/`, com origem e hashes no manifest. Seu escopo é somente
ENSAIO_LOCAL_SINTETICO; `aplicabilidade_confirmada=false`. A chamada normal do
validador recusa esse pacote, impedindo que o teste ative emissão real.
`ensaio_local=True` exige o laboratório PostgreSQL `test_*` em localhost e
storage local. O XML integral assinado é validado pelo XSD oficial; XML sem
Signature, emitente ausente, namespace/versão adulterados e XSD alterado são
recusados. A assinatura é obrigatória no XSD: antes dela há validações de
estrutura/totais pelo gerador; o XSD completo ocorre após assinar. Isso não
equivale às regras de negócio/autorização da SEFAZ. Reconfirmar aplicabilidade,
envelopes/eventos e NT/cronograma na data do primeiro envio.

`pretransmission.validar_ensaio` reutiliza a venda/pagamentos e os documentos/
reservas atuais. Exige `fiscal_emitir`, contexto exato, assinatura/cadeia
sintéticas e SEFAZ desabilitada. Retorna evidência pública/auditada
**PRONTO PARA TRANSMISSÃO / PRONTO PARA HOMOLOGAÇÃO OFICIAL** exclusivamente no
ensaio sintético. Documento continua PENDENTE, sem protocolo, tentativa de
envio ou artefato autorizado; venda, caixa, pagamentos e estoque não são
modificados. Não há novo status persistido, nova migration ou rota de emissão.
O cadastro documental da TECNOLMED continua bloqueado pelas travas existentes.

QR v3 online usa chave|3|2 e dispensa CSC nesse leiaute, conforme manual oficial.
As tentativas por Web/terminal falharam, mas a consulta pelo navegador ao
catálogo oficial ENCAT confirmou as bases publicadas por ambiente:
HOM QR `http://www.hom.nfe.se.gov.br/nfce/qrcode?`, consulta
`http://www.hom.nfe.se.gov.br/nfce/consulta`; PROD QR
`http://www.nfce.se.gov.br/nfce/qrcode?`, consulta
`http://www.nfce.se.gov.br/nfce/consulta`. São referências documentais,
**não configurações ativadas**. As tabelas publicam HTTP; não se presumiu uma
versão HTTPS. Compatibilidade atual com QR v3, protocolo e requisitos seguros
da integração precisam ser confirmados com SEFAZ antes do primeiro envio.
O motor exige HTTPS atualmente; essa proteção não foi relaxada. PROD permanece
bloqueado. O portal geral NFC-e SE não foi tratado como base de QR.
Nenhuma URL foi inferida de outro ambiente, estado ou biblioteca.
As evidências e limitações finais estão em
`RELATORIO_PRETRANSMISSAO_NFCE_TECNOLMED_LOCAL.md` e seu JSON de validação.

Implementação exclusiva do modelo 65. Não habilita emissão fiscal real, produção,
contingência fiscal, NF-e ou NFS-e. A fila comercial offline do PDV não é alterada.

## Fronteira VERTYX × clientes

VERTYX é o SaaS. TECNOLMED é um tenant cliente, sem identidade fiscal global,
certificado padrão ou privilégio de emitente da plataforma. A pessoa jurídica
proprietária terá sua própria Organization quando seus dados forem fornecidos;
nenhum cadastro jurídico foi criado nesta consolidação. NFS-e de mensalidade
pertencerá à organização emitente da VERTYX; NFS-e/NF-e/NFC-e de clientes
pertencem exclusivamente às suas organizações. Faturamento SaaS automático
continua pendente, sem fluxo paralelo ou emissão real implementada.

Administração SaaS (`is_staff`/`is_superuser`) não substitui membership ativa,
acesso ao ERP e capacidades fiscais do tenant. A política existente continua
centralizada em `platform_core.modules`, incluindo negativas explícitas.
Ter `operar_pdv` não concede administração fiscal.

Antes de consultar o cofre, o motor revalida documento, configuração, série,
credencial, vínculo explícito, estabelecimento ativo e ambiente. Instâncias
carregadas em outro tenant também são rejeitadas. O cofre recebe em todas as
operações `organization_id`, `estabelecimento_id`, `ambiente` e `emitente_cnpj`.
Sua identidade deve atestar o mesmo contexto autorizado; o estabelecimento é
um escopo de autorização do cofre, não um campo inventado no certificado A1.
Outro estabelecimento, mesmo com o mesmo CNPJ, não ganha acesso implícito.
XML de outra chave, emitente ou ambiente é recusado antes da assinatura/envio.

`CofreFiscal` é somente contrato de backend. O provedor futuro deverá aplicar
esse escopo na ACL do cofre, validar titular/validade/cadeia e registrar o uso
sem segredos. Não existe implementação real de cofre, transporte ou fallback
global. Referências persistidas são opacas e vinculadas por
`VinculoCredencialFiscal`; não é necessário alterar o schema nesta etapa.

Evidências e dados documentais da TECNOLMED:
`RELATORIO_CONSOLIDACAO_FISCAL_MULTITENANT.md`. Dados fornecidos não são seeds,
fixtures, configurações globais nem autorização de transmissão.

## Estado e bloqueios

`MotorNFCeSimulado` permanece disponível. `resolver('NFCE', 'HOMOLOGACAO')`
seleciona `MotorNFCeHomologacao`, cujas dependências padrão bloqueiam o envio.
O motor não implementa cliente HTTP nem carregamento de PFX/senha/CSC.

O laboratório exige simultaneamente `FISCAL_NFCE_LOCAL_ENABLED`, PostgreSQL em
`127.0.0.1` com nome iniciado por `test_`, e armazenamento privado local.
Os flags são ausentes/desabilitados nas configurações normais da aplicação.
Nenhuma configuração do Render deve ser alterada para esta fase.

`FISCAL_NFCE_SEFAZ_APPROVED` é uma trava adicional do transporte. **Não ativar**
sem apresentar os requisitos e receber autorização para acesso externo. Esse
flag sozinho não fornece cofre, certificado, mTLS ou XSD e não habilita produção.

## Dados e configuração

Reutilizam-se Organization, FilialEmpresa, ConfiguracaoEmpresa,
PerfilFiscalEstabelecimento, ConfiguracaoFiscal, CredencialFiscal,
VinculoCredencialFiscal, SerieFiscal, RegraTributariaFiscal, DocumentoFiscal,
DetalhesNFCe, SolicitacaoFiscal, ReservaNumeracaoFiscal, TentativaFiscal,
EventoFiscal, Peca, Venda, ItemVenda e PagamentoVenda.

As extensões ConfiguracaoNFCe, TributacaoProdutoNFCe, PagamentoFiscalNFCe e
ArtefatoNFCe são específicas desse fluxo e usam as mesmas FKs e auditoria.
Não há cadastro paralelo de produtos, emitentes, vendas, estoque ou caixa.

Cada dado deve ser fornecido explicitamente no laboratório isolado. Não existe
seed ou migration que preencha a TECNOLMED com CNPJ, IE, série, número ou tributo.
A série permitida pelo recorte desta implementação é 0–889, com próximo número
explicitamente informado; cada reserva é permanente e nunca reutilizada.

Os produtos reutilizam GTIN, NCM, CEST, CFOP, origem, CST/CSOSN e unidade base
de Peca. A regra versionada define os parâmetros públicos de tributação.
Ausência de GTIN ou não aplicação de CEST/RTC exige declaração explícita.
O recorte atualmente aceito é operação presencial interna de venda, CFOP
5101/5102, CSOSN 102, CRT 1/4 e dispensa RTC explicitamente configurada, até
2026. PIS/COFINS 01 exigem alíquotas explícitas; códigos NT suportados são
04/06/07/08/09. Outros enquadramentos, IBS/CBS/IS e operações especiais bloqueiam
a preparação; exigem extensão validada contra a NT/XSD aplicável e o contador.
Este recorte técnico **não determina o enquadramento fiscal da TECNOLMED**.

Pagamento comercial não presume código fiscal. São aceitos códigos 01, 03, 04,
17 e 20, com vínculo explícito a FormaPagamento. Cartão/PIX precisam do tipo de
integração; integração 1 fica bloqueada sem os dados por transação. O XML usa
valor recebido e vTroco; a diferença deve coincidir exatamente com o total.

## Cofre e assinatura

O contrato CofreFiscal recebe referência `cofre://UUID` e determina identidade
(tenant, ambiente, CNPJ, validade, ICP-Brasil e fingerprint público), assina no
backend e delega o transporte mTLS. Nunca devolve chave privada ou senha.
O provedor real/chain trust do cofre não foi implementado nesta fase.

`signature.verificar` valida integridade, referência Id, digest SHA-1, transforms,
C14N, RSA-SHA1, fingerprint, validade do certificado público e assinatura.
A confiança ICP-Brasil e identidade jurídica devem ser atestadas pelo provedor
do cofre; a cadeia ICP-Brasil não é validada independentemente por este código.
Os testes locais positivos de fluxo usam duplos explícitos, **sem certificado**.
Não validam uma assinatura A1 real. Testes negativos bloqueiam assinatura ausente,
alteração de XML e identidade/certificado de outro tenant/ambiente/emitente.
XML assinado/processado contém X509 público por exigência do XMLDSig, mas nessa
fase permanece no backend. A rota de download bloqueia XML desse motor até
para ADMIN; PDFs privados não contêm certificado. Nenhum PFX/CSC vai ao PWA.

## XSD

XML 4.00 / SOAP 1.2. Não foi embutido um XSD inventado nem declarado vigente um
pacote antigo. Na retomada de 09/10/2026 foi obtido diretamente do catálogo
oficial o PL 010f v1.04 (publicação de 31/08/2026). O ZIP e seus cinco XSDs
foram arquivados com SHA-256 em `tmp/validation/nfce-se-20261009/`.
Esse arquivo de pesquisa não foi ativado na configuração do motor. A
aplicabilidade ao enquadramento/cronograma de Sergipe e a validação positiva
do XML integral assinado continuam pendentes. O XML sintético sem assinatura
foi confrontado com esse XSD real e recusado apenas pela ausência de Signature;
versão incorreta e emitente ausente também foram recusados.
Um pacote complementar PL 010d v1.03 foi arquivado separadamente para mensagens;
a consulta XML gerada pelo motor passou no consSitNFe_v4.00.xsd oficial, sem
transmissão. Isso não valida positivamente a NFC-e assinada ou o evento fiscal.
Os imports `file:` são normalizados para caminhos locais, inclusive no Windows
com espaços, antes da comparação com os arquivos pinados. Imports remotos e
arquivos fora do conjunto verificado continuam proibidos.
Consulte `RELATORIO_PREPARACAO_NFCE_SEFAZ_SE.md` para fontes, requisitos,
checklists e a distinção entre pacote publicado e regras ainda não implantadas.

`FISCAL_NFCE_SCHEMA_DIR` apontará futuramente para pacote **público local**
verificado, com `manifest.json` contendo `release`, `fonte` oficial HTTPS,
`aplicabilidade_confirmada` e `sha256` para cada XSD (incluindo imports).
Não contém segredos. Fonte aceita: Portal Nacional, SVRS ou SEFAZ/SE.
Sem manifest, hash íntegro, release coincidente e confirmação, a validação falha.
Imports são restritos aos arquivos locais pinados; DTD/entidades/rede são
bloqueados. O XML inteiro assinado deve passar no XSD antes do envio.
Antes da assinatura, os campos e totais são validados pelo código; a validação
XSD completa depende da assinatura exigida pelo leiaute. Isso não substitui
validação do XSD oficial nem as regras de negócio do autorizador.

## Transmissão, respostas e reconciliação

`preparar` lê a venda finalizada, determina tenant no backend, valida configuração
e congela snapshot fiscal. Não altera venda, pagamento, caixa, estoque ou RH.
`solicitar` cria uma única operação EMITIR por documento/sale/ambiente, reserva
um número sob lock PostgreSQL e mantém a mesma chave e data nas consultas.
`processar` usa lease persistida, grava tentativa e XML preparado/assinado antes
do envio. Resposta XML privada, código (3/4 dígitos), recibo, protocolo e hora
são preservados em artefatos imutáveis e auditados. Motivo permanece no XML
original privado; nenhuma exceção do provedor é exibida ou gravada em logs.

Autorização exige schema, chave, ambiente 2, UF 28, protocolo, data e digest
correspondentes. Rejeição não altera o estado comercial. Correção/reenvio de
rejeição fica bloqueado até regra explícita posterior. Timeout/duplicidade/
retorno inválido levam a RESULTADO_DESCONHECIDO; uma operação já marcada enviada
somente consulta, mesmo após queda do processo. Consulta "não encontrada" não
autoriza reenvio automático. Solicitação, chave e numeração não são duplicadas.

Cancelamento prepara evento 110111 / versão 1.00 com justificativa de 15–255
caracteres. Retorno 135/155 correspondente confirma o cancelamento. Conserva
XML, chave e protocolo originais de autorização; protocolo do evento fica em
artefato próprio. Timeout de cancelamento bloqueia reenvio; reconciliação de
eventos pelo provedor real ainda está pendente. Inutilização tem endpoint
mapeado, mas não foi implementada nem executada; nunca libera números usados.

DANFE local identifica HOMOLOGAÇÃO / SEM VALOR FISCAL e exige autorização/
XML processado. O QR v3 online monta chave|3|2, sem CSC. Sua implantação e URLs
de Sergipe não foram confirmadas; por isso não há URL SE presumida no catálogo.
O leiaute PDF precisa de conferência com o manual vigente e homologação física.
O PDF de evidência usa exclusivamente vetor unitário e URLs `example.invalid`,
com aviso "NÃO É A TECNOLMED". Não é um DANFE autorizado pela SEFAZ.

## Endpoints propostos — nenhum chamado nesta fase

Fonte: [serviços oficiais SVRS](https://dfe-portal.svrs.rs.gov.br/Nfce/Servicos).

| Serviço | Método SOAP proposto | URL homologação |
|---|---|---|
| Autorização 4.00 | nfeAutorizacaoLote | https://nfce-homologacao.svrs.rs.gov.br/ws/NfeAutorizacao/NFeAutorizacao4.asmx |
| Consulta 4.00 | nfeConsultaNF | https://nfce-homologacao.svrs.rs.gov.br/ws/NfeConsulta/NfeConsulta4.asmx |
| Retorno de recibo 4.00 | nfeRetAutorizacaoLote | https://nfce-homologacao.svrs.rs.gov.br/ws/NfeRetAutorizacao/NFeRetAutorizacao4.asmx |
| Evento / WS 4.00, payload 1.00 | nfeRecepcaoEvento | https://nfce-homologacao.svrs.rs.gov.br/ws/recepcaoevento/recepcaoevento4.asmx |
| Inutilização 4.00 | nfeInutilizacaoNF | https://nfce-homologacao.svrs.rs.gov.br/ws/nfeinutilizacao/nfeinutilizacao4.asmx |
| Status 4.00 | nfeStatusServicoNF | https://nfce-homologacao.svrs.rs.gov.br/ws/NfeStatusServico/NfeStatusServico4.asmx |

O futuro provedor deve confirmar WSDL/actions e validar contrato antes do
primeiro acesso autorizado. NFC-e online envia um único documento síncrono.
Retorno de recibo foi mapeado para diagnóstico, sem nova emissão assíncrona.
Não há endpoints de produção disponíveis no motor desta fase.

## Fontes oficiais verificadas em 08/10/2026

- [SEFAZ/SE: FAQ](https://www.sefaz.se.gov.br/SitePages/faq.aspx): NFC-e, contribuinte, homologação e certificado ICP-Brasil.
- [Portal Nacional: informação SE/SVRS](https://www.nfe.fazenda.gov.br/Portal/informe.aspx?AspxAutoDetectCookieSupport=1&UF=SE&ehCTG=true).
- [SVRS: webservices NFC-e](https://dfe-portal.svrs.rs.gov.br/Nfce/Servicos).
- [Portal Nacional: schemas](https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?AspxAutoDetectCookieSupport=1&tipoConteudo=BMPFMBoln3w%3D): metadados disponíveis; download/versão aplicável ainda pendentes.
- [SVRS: documentos e notas técnicas](https://dfe-portal.svrs.rs.gov.br/Nfe/Documentos): catálogo de schemas, MOC e NTs RTC.
- [SVRS: cronograma atualizado de NTs](https://dfe-portal.svrs.rs.gov.br/Nfce/Avisos/3008): mudanças anunciadas para 26/10/2026 em homologação não foram presumidas vigentes em 08/10.
- [CONFAZ: MOC 7, leiaute e regras](https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/moc7-anexo-i-leiaute-e-rv.pdf).
- [Portal Nacional: NT 2023.002](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=4m9xb5EYa%2Fw%3D): série do contribuinte e envio síncrono de um documento NFC-e.
- [SEFA/PR: QR Code e manual 6.0](https://sped.fazenda.pr.gov.br/NFCe/Pagina/QR-Code): formato nacional QR v3 online. A URL do Paraná não foi usada como URL de Sergipe.

## Antes de qualquer acesso externo

1. Homologar a entrega local, resultados de testes e limitações.
2. Fornecer/conferir cadastro real da TECNOLMED por canal/aplicação autorizado,
   incluindo estabelecimento, CNPJ, IE, CRT/regime, endereço, município, UF,
   atividade, série e próximo número. Validar regras de cada produto/pagamento
   com o responsável fiscal. Não modificar dados reais por inferência.
3. Confirmar credenciamento NFC-e de homologação em SE e URLs/versão QR vigentes.
4. Obter e pinçar o pacote XSD oficial aplicável, suas NTs, arquivos e hashes.
5. Definir provedor de cofre A1/mTLS, cadeia ICP-Brasil, segregação tenant/ambiente,
   prazo de validade, revogação, logs sem material sensível e timeouts limitados.
   Certificado e eventual CSC somente pelo canal seguro do backend, nunca chat.
6. Executar testes de assinatura real, XSD, cadeia e contract/WSDL em laboratório.
7. Apresentar endpoints/métodos/versões, dados a enviar, certificado necessário,
   credenciamento, dependências, riscos de numeração e responsabilidades.
8. Obter autorização **antes** da primeira consulta/transmissão de homologação.
9. Testar autorização/rejeição/cancelamento/reconciliação e DANFE/QR reais de
   homologação, mantendo produção, caixa OKOK e PWAs preservados.

Fase 2 local preparada com limitações; emissão oficial de homologação PENDENTE.
