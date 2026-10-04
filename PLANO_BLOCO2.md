# VERTYX — plano do Bloco 2

Data: 02/10/2026. Base: `fe6c554`, branch `main`, acrescida das alterações locais validadas do Bloco 1. Plano registrado antes das alterações funcionais deste bloco. Estado inicial: auditoria concluída; implementação e aceitação ainda pendentes.

## Evidências e arquitetura preservada

Lidos `VALIDACAO_BLOCO1.json`, `PLANO_DEPENDENCIAS_BLOCO1.md` e `BLOCO1_ESTABILIZACAO.md`. A evidência anterior registra 293 testes PostgreSQL aprovados (258 anteriores e 35 de estabilização), Django 5.2.17, Python 3.12.14, PostgreSQL 16.15, 1470 registros locais preservados e três migrations aditivas. Esses resultados pertencem ao Bloco 1; não certificam antecipadamente as alterações do Bloco 2.

Auditados models, serviços, formulários, views, URLs, relatórios, templates, testes e migrations de `operacao`, `ordens`, `equipamentos`, `contas`, `gestao` e a infraestrutura de organização/permissões em `platform_core`. Os fluxos usam `OrganizationOwned`/`TenantManager`, validação de relacionamentos, `PlatformAudit`, auditoria de OS e serviços transacionais. O portal exige vínculo explícito usuário/cliente. Os dois agendamentos preventivos oficiais (`PreventivaProgramada` e `AgendaPreventiva`) devem permanecer, com apresentação consolidada.

Não criar aplicativos paralelos de estoque, compras, financeiro, contratos, documentos ou auditoria. Novas entidades representam apenas detalhes ausentes dos fluxos oficiais: recebimentos, alocações de reservas, necessidades de peças e artigos técnicos. Novos campos históricos opcionais não serão preenchidos com informações presumidas. Nenhuma migration histórica será editada.

## JÁ EXISTE

| Requisito | Estrutura a preservar |
|---|---|
| Clientes/unidades e organização | Cadastros e validação de vínculos por organização. |
| OS, assinatura eletrônica e PDF | OS numerada, execução, fotos privadas, conferência congelada, assinatura mouse/touch, PDF com hashes e versões históricas. |
| Estoque e custos | Peça, depósito, saldo, lotes, FEFO, movimento e detalhe de lote; custos Decimal exatos e devolução pelo movimento original. |
| Financeiro e centro de custo | Lançamento/origem raiz, parcelas, pagamentos, eventos, caixa/banco, pagamentos não bancarizados e classificações atuais. |
| Compras, vendas, cotações e reposição | Models e fluxos oficiais; rascunhos não descontam necessidade; aprovadas/pedidos descontam pendência. |
| Contratos | Cliente/unidades/equipamentos, vigência, cobertura, visitas, periodicidade, SLA e situação calculada. |
| Multiempresa, auditoria e segurança básica | Gerenciadores por organização, validação de FKs, permissões no backend, CSRF, documentos privados e hashes. |
| PWA e TV | Manifesto, service worker, assets locais e painel com autorização explícita e DTO sem valores financeiros. |

## EXISTE PARCIALMENTE

| Área / seções da solicitação | Gap real e extensão prevista |
|---|---|
| Chamados (3, 35) | Completar contato, origem, tipo, prazo/SLA, agenda, responsável, estados, anexos e prioridade solicitada. Preservar vínculo único com OS e status histórico CONVERTIDO. |
| OS/status (4–5) | Campos técnicos adicionais, auxiliares, deslocamento/aguardando aprovação; transições auditadas com estado anterior correto. |
| Checklist (6) | Modelo atual de caixas obrigatórias: ampliar com respostas tipadas, critérios de aplicação e validação de fotos. Copiar modelo para execução e manter snapshot assinado. |
| Fotos/PDF (8–9) | Categorias de fotos e dados técnicos novos, respostas/medições/recomendações no PDF; campos novos condicionais preservam PDFs antigos. |
| Equipamentos/QR/histórico (10–12) | Acrescentar somente metadados ausentes e situação de ciclo de vida; manter situação operacional existente. Consolidar fontes oficiais em linha do tempo; etiqueta e acesso apropriado do cliente. |
| Preventivas (13–14) | Quadrimestral, unidade/tipo/equipe, apresentação conjunta das duas fontes, cálculo ancorado ao plano e conclusão idempotente. |
| Planejamento/técnicos (15–17) | Chamados e auxiliares na agenda/conflitos, campos profissionais faltantes e documentos na central existente. |
| Reservas (19) | Reserva atual é agregada por peça/depósito; falta identificar lotes comprometidos. Alocar FEFO dentro da reserva existente e liberar no cancelamento. |
| Compras/fornecedores (21–23) | Previsão, progresso e histórico de recebimentos; ampliar fornecedor sem duplicar cadastro. |
| Alertas (25, 43) | Notificações existentes são lidas/não lidas; alguns alertas usam chave diária. Usar ocorrência operacional estável, resolução automática e reabertura sem spam. |
| Dashboard/TV/indicadores (26–27, 33) | Incorporar novos estados e fontes, chamadas, contratos, equipamentos e pendências; fórmulas explícitas e dados reais. |
| Caixas/bancos (29) | Completar filtros período/origem e separar visualização não bancarizada sem inventar saldo. |
| Documentos (31) | Completar vínculos, categorias, emissão, validade e observação; manter upload validado e autorização individual. |
| Relatórios (32) | Ampliar filtros contrato/tipo e relatórios de pendências, consumo/custo registrado, contratos e compras pendentes; reutilizar exportadores. |
| Portal (34–35) | Equipamento/histórico/preventivas, acompanhamento de chamado e anexos; somente dados do cliente associado e documentos liberados. |
| Responsividade/UX (39–41) | Reutilizar cards, filtros e tabelas com rolagem; testar jornadas técnicas, estoque, gestão e portal em tamanhos distintos. |

## PRECISA SER CORRIGIDO

1. Recebimento integral não representa saldo parcialmente recebido: pendência deverá somar somente quantidades não recebidas de APROVADA/PEDIDO. Recebidas legadas sem detalhe continuarão integralmente recebidas, sem fabricar registros históricos.
2. Conflitos consideram somente técnico principal: incluir auxiliares e chamados agendados, sem inventar duração de eventos sem horário final.
3. Alertas contratuais/preventivos com chave diária podem repetir o mesmo problema. Separar leitura de resolução operacional.
4. Auditoria de início de OS registra ABERTA mesmo quando veio de AGENDADA: registrar estado anterior real.
5. QR administrativo não atende o perfil CLIENTE protegido pelo middleware: oferecer rota de portal autorizada e manter restrições do ERP.

## PRECISA SER IMPLEMENTADO

| Extensão | Decisão |
|---|---|
| Recebimento parcial (22) | Cabeçalho idempotente e itens imutáveis ligados à Compra/ItemCompra e ao movimento oficial. Bloquear compra/produtos; validar excesso, lotes, depósito e custo. Pedido permanece PEDIDO até conclusão. Preservar regra financeira atual de uma conta oficial gerada ao recebimento final; recebimentos parciais ficam explicitamente visíveis enquanto isso. |
| Necessidade de peça (20) | Detalhe vinculado à OS; quantidade, urgência e observação. Integrar reserva/reposição/solicitação oficial de compra com identificação de intenção para evitar duplicação. |
| Pesquisa global (42) | Busca nas entidades oficiais, com escopo e autorização no backend. Sem uso de gerenciador irrestrito em endpoints. |
| Base de conhecimento (44–45) | Artigo técnico multiempresa com referências opcionais a equipamento/OS/manual, defeito, solução e procedimento; consulta interna estruturada. |
| Testes/evidências (48–58) | Acrescentar regressões, IDOR, permissões, concorrência real PostgreSQL, PDF/uploads e jornadas visuais. Validar banco limpo e incremental com comparação dos dados históricos. |

## FORA DO ESCOPO DESTE BLOCO

Integrações fiscais reais, certificado A1, e-mail/WhatsApp externos, gateways, Open Finance, IA/OCR externos, fabricante/ANVISA, roteirização avançada, aplicativo nativo, novo frontend, ERP Loja separado e sincronização offline complexa. Preservar adaptadores existentes sem apresentar integração não configurada como operacional. Não alterar Render, R2 real, credenciais ou banco publicado; não executar commit, push ou deploy.

## Sequência de implementação e validação

1. Registrar hashes das migrations/testes e executar check/makemigrations seco antes de novos models.
2. Ampliar cadastros, chamados, OS e checklist com campos opcionais e serviços autorizados.
3. Implementar recebimentos parciais e reservas por lote, necessidades de peças e transações/idempotência; validar regressões do Bloco 1.
4. Ampliar preventiva/agenda, documentos/histórico/portal, conhecimento e pesquisa nas estruturas existentes.
5. Consolidar indicadores, notificações, relatórios, TV, formulários e PDF sem alteração visual radical.
6. Revisar migrations aditivas e dependências; testar PostgreSQL limpo e incremental sintético, preservando todas as colunas anteriores.
7. Executar 293 testes anteriores e novos, concorrência, check, makemigrations seco, pip check, collectstatic/PWA, PDF/uploads e jornadas visuais desktop/tablet/celular.
8. Entregar `RELATORIO_BLOCO2.md`, `VALIDACAO_BLOCO2.json` e recomendação `PLANO_BLOCO3.md`. Resultados somente após execução; qualquer pendência deve ser explicitamente declarada.

Nenhuma etapa depende de configuração externa. O banco de validação é exclusivamente o PostgreSQL sintético em loopback já utilizado no Bloco 1.
