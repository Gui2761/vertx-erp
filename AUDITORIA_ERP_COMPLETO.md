# Auditoria do ERP VERTYX — levantamento antes da evolução

Data: 01/10/2026. Etapa 0: auditoria e plano de evolução.

Base auditada: pasta de trabalho existente `tecnolmed_erp`, branch `main`, commit `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261`, repositório `tecnolmedengclinica-spec/vertx-erp`. Serviço oficial informado e identificado na auditoria anterior: `vertyx-erp`.

## Resultado

A versão tem um núcleo operacional integrado e testado. Ainda não atende integralmente aos 28 pontos do novo pedido. As maiores lacunas estão na continuidade comercial, nas exceções de compras/financeiro, no histórico completo, no SLA, na apuração de custos e nas integrações externas. A existência de um cadastro, relatório ou adaptador vazio não foi tratada como conclusão do fluxo correspondente.

Nenhuma funcionalidade, migration, dependência, configuração do Render, credencial, banco publicado ou storage foi alterado nesta etapa. Não houve commit, push ou deploy. Os documentos anteriores de validação foram preservados; esta auditoria é um suplemento com escopo próprio.

### Evidências e limites

- Leitura de `AUDITORIA_FINAL.md`, `INVENTARIO_FINAL.md`, `VALIDACAO_FINAL.json`, documentação operacional e código dos models, services, permissões, views, relatórios, portal, planejamento, estoque, fiscal, inicialização e testes relacionados ao pedido.
- Nova execução integral: **258/258 testes aprovados no PostgreSQL local, em 236,335 segundos, sem testes ignorados**. A suíte inclui concorrência real, isolamento entre organizações/clientes, permissões, rollback, FEFO/reservas, financeiro, PDF, uploads, S3 simulado, planejamento e painel operacional.
- `check`: aprovado; `makemigrations --check --dry-run`: nenhuma alteração detectada; `showmigrations --plan`: migrations existentes aplicadas na base local de validação. O Django aplica também as migrations à base temporária da suíte, sem modificar a base publicada.
- Cinco reproduções adicionais, separadas da suíte de aceitação, confirmaram limitações descritas abaixo. O resultado esperado desses testes é reproduzir a limitação, e não aprovar a funcionalidade solicitada.
- Testes utilizaram o PostgreSQL **local sintético já provisionado**, com guarda explícita de host `127.0.0.1`, porta 55432 e nome da base local. A base temporária de testes foi criada e removida pelo Django. Nenhuma conexão com PostgreSQL do Render ou R2 real foi feita.
- Evidências visuais anteriores da mesma versão foram revisadas: dashboard desktop e agenda mobile; resultados de navegador em 320, 390, 768 e 1365 px, TV em 1920×1080. Esses ensaios foram realizados anteriormente em HTTPS local com dados sintéticos; **não foram reexecutados no navegador nesta etapa**. Ausência de overflow não equivale a homologação de acessibilidade ou aprovação estética completa.
- A auditoria anterior confirmou deploy Live, migrations, collectstatic, Gunicorn e health/login públicos. Esta etapa **não confirma login autenticado, contagem de registros antigos, restore de backup, permissões reais do bucket ou fluxos completos no ambiente publicado**. Não houve nova auditoria da infraestrutura.
- Logs 503 durante a suíte são dos testes deliberados de indisponibilidade de banco/storage; a suíte encerrou com `OK`.

## O que já está implementado e validado

Estas capacidades podem ser preservadas e reutilizadas:

1. Cadastros PF/PJ, contatos, várias unidades e equipamentos vinculados, com validação de relações e organização.
2. Atendimento de OS com técnico autorizado, início, diagnóstico/serviço, checklist, fotos, conferência, assinatura, finalização, PDF e snapshots/auditoria preservados após reabertura.
3. Planejamento diário/semanal/mensal, lista, timeline, fila sem técnico/data, conflito de agenda, revisão concorrente e painel operacional com grant específico e dados reduzidos.
4. Chamado convertido em uma OS; orçamento aprovado convertido em uma OS; planos/visitas contratuais gerando OS; contratos gerando cobranças periódicas. Reexecuções dos fluxos existentes são protegidas contra duplicação dentro de cada origem.
5. Estoque único baseado em `Peca`, `Movimentacao`, `Deposito` e `SaldoDeposito`; lotes simultâneos, validade, FEFO, bloqueio de consumo vencido, reservas, transferência e devolução de peça de OS ao lote original.
6. Compra recebida integralmente gerando lote/estoque e conta a pagar; venda confirmada gerando baixa FEFO e conta a receber, com transação e proteção de reenvio.
7. Pagamentos parciais, saldo pendente, caixa/bancos quando escolhidos, transferências e conciliação manual; proteção contra pagamento acima do saldo e concorrência nas operações cobertas.
8. Documentos privados, downloads autenticados, isolamento do portal por cliente, aprovação/recusa de orçamento e exportações gerenciais CSV/PDF/Excel existentes.
9. Ocorrências operacionais de estoque abertas/resolvidas, alertas sem duplicação a cada execução, relatório semanal com histórico e geração de compra usando os models atuais.

Os itens acima descrevem capacidades concretas. Não significam que todo o módulo atende às ampliações solicitadas agora.

## Matriz dos 28 pontos

| # | Módulo / requisito | Estado atual | O que falta para o novo escopo |
|---|---|---|---|
| 1 | Painel executivo | Parcial. Dados reais do ERP, contas, realizado, inadimplência, OS, estoque, contratos, comercial, bancos e período. | Chamados/compras mais claros; separação das preventivas previstas/próximas/atrasadas e das duas origens; documentação uniforme de período versus saldo atual; classificação de receitas após parcelamento; custo/lucro confiável. |
| 2 | Clientes e unidades | Cadastro completo do núcleo PF/PJ, inscrições, endereço, contatos, responsáveis, unidades e histórico integrado. Parcial no histórico completo. | Paginação/filtros para todo o histórico; trilha explícita de alterações/exclusões dos contatos; ergonomia da ficha consolidada. |
| 3 | Equipamentos | Parcial. Cliente/unidade, patrimônio e código interno, série, fabricante/modelo/categoria, localização, instalação, garantia, situação, foto/manual, QR e históricos. | Marca e tensão como campos próprios; classificação de fotos; dados/resultado técnico de calibração; atualizar a última calibração ao concluir o fluxo; histórico navegável sem cortes. |
| 4 | OS | Fluxo principal implementado; parcial para as ampliações. Dez tipos, agenda, km/horas, diagnóstico, peças, checklist, fotos, assinatura, PDF, histórico e estados comerciais. | Deslocamento como evento/etapa, fotos antes/depois estruturadas, compartilhamento externo seguro e custo efetivo dos lotes consumidos. Texto livre de peças continua legado e não movimenta estoque. |
| 5 | Planejamento/agenda | Núcleo implementado com calendário/lista/timeline, filtros, técnico, conflito, filas, atrasos e TV. Parcial no escopo ampliado. | Chamados ainda não convertidos não têm evento próprio de agenda; compromissos gerais sem OS não estão modelados; testar fluxo de visitas de contrato até agenda/finalização; desempenho com grande volume. Preservar a agenda existente. |
| 6 | Chamados | Parcial. Cliente, unidade, equipamento, contrato, problema, prioridade, autor/data/status e conversão idempotente. | Responsável de atendimento, prazo/SLA calculado, mudanças com histórico consultável e transporte dessas informações para OS. Autor não substitui responsável. |
| 7 | Preventivas | Núcleo implementado. Plano/contrato/equipamentos, checklist, periodicidades mensal, bimestral, trimestral, semestral, anual e dias personalizados. | Política para evitar sobreposição entre plano preventivo e visita contratual do mesmo equipamento; reagendamento/cancelamento controlado; visão completa no portal. Idempotência atual é por origem, não deduplicação global entre os dois modelos existentes. |
| 8 | Contratos | Parcial. Vigência, valores, periodicidade, visitas, ativos/unidades, SLA em horas, coberturas, regra textual de reajuste, documentos, cobranças e planejamento. | Objeto/responsável explícitos, base/data/índice do reajuste, renovação/versionamento e política de encerramento das ocorrências futuras já geradas. Não reescrever cobranças existentes. |
| 9 | Orçamentos | Parcial. Itens/serviços/peças, desconto, validade, condições, PDF, estados, decisão no portal, OS e recebível opcional. | Conversão em venda; alocação de serviços/produtos de orçamento misto, sem duplicar recebíveis; versões/revisões e envio externo. Conversão em OS copia as peças em texto, sem reserva ou baixa automática. |
| 10 | Peças/estoque | Núcleo implementado com lotes, FEFO, entradas/saídas, OS, venda, ajuste justificado, transferências, devolução de OS, reservas e relatórios. | Inventário com sessão de contagem/fechamento; devolução comercial/estorno; custo efetivo por lote; política de solicitações rascunho na necessidade de compra. Saldo negativo é proibido para todos os perfis; não há autorização excepcional. |
| 11 | Depósitos | Múltiplos depósitos/saldos e transferências auditadas implementados. Parcial na classificação. | Tipo loja/assistência/galpão/veículo e vínculo opcional técnico/veículo; mínimos por local se a operação precisar. Hoje isso pode ser descrito no nome/endereço, sem vínculo estruturado. |
| 12 | Compras | Parcial. Solicitação, cotação global, aprovação, pedido, recebimento integral, estoque/lote e contas a pagar. | Recebimento parcial/múltiplos lotes no mesmo item ao longo do recebimento, frete/impostos/rateio, documento privado da compra, comparação de cotação por item e cadastro ampliado de fornecedor. Separar solicitação de pedido efetivo na previsão de recebimento. |
| 13 | Vendas | Parcial. Rascunho com itens, vendedor cadastrado, confirmação, estoque/FEFO, conta a receber e vínculo fiscal. | Origem em orçamento/pedido, perfil vendedor, devolução/cancelamento auditado, reservas no fluxo comercial e documentos. Sem duplicar o módulo `Venda`. |
| 14 | Financeiro | Parcial. Receber/pagar, origem, classificação, vencimento, pagamentos parciais, forma, observações, cancelamento e parcelamento. | Juros/multa/desconto realizados como ajustes auditados, anexos vinculados, estornos, origem das parcelas nos filtros/indicadores e divisão segura de centavos. Parâmetros de juros/multa existem, mas não são aplicados por `pagar`. |
| 15 | Caixa/bancos | Parcial. Contas, entradas/saídas, saldo, transferências e conciliação manual por valor/data. | Importação OFX/CSV validada e idempotente; categorias/centro de custo dos movimentos avulsos; vínculo posterior de pagamentos sem conta; tratamento amigável de disputa de conciliação; integração bancária futura. |
| 16 | Documentos | Parcial. Vínculos cliente/equipamento/OS/contrato/orçamento/fiscal e autorização privada. | Vínculos próprios com compra/venda/lançamento; permissões desses vínculos, histórico/paginação e retenção. `documento_entrada` da compra/lote é texto, não anexo da central. |
| 17 | Relatórios | Parcial. Catálogo atual de 31 relatórios, CSV/PDF/Excel, filtros e segregação de acesso. | Lucro efetivo de OS/venda incluindo lote, mão de obra e despesas; receitas de orçamento misto e parcelas; filtros completos nos relatórios com regras específicas; volumes grandes sem carregar todos os dados. Margens atuais são estimativas, não contabilidade de lucro líquido. |
| 18 | Usuários/permissões | Perfis atuais e proteção no backend implementados. Parcial no novo escopo. | Perfil `VENDEDOR` e matriz comercial; conferir segregação entre solicitar/aprovar/receber compras. Hoje ADMIN/GESTOR/ESTOQUE podem executar as três operações de compra. Não conceder gestão/financeiro apenas para habilitar vendas. |
| 19 | Portal do cliente | Parcial. Isolamento por clientes vinculados, OS/PDF/fotos, equipamentos, contratos resumidos, documentos, orçamentos/decisões e financeiro/exportação. | Agenda/ocorrências preventivas, ficha técnica e histórico completos, detalhamento de contrato, paginação e jornada consistente. Isolamento tem testes na mesma organização e entre organizações. |
| 20 | Técnico/PWA | Núcleo mobile implementado: agenda própria, início/fim, atendimento/checklist/fotos/peças/assinatura e conclusão. | Homologação em aparelhos reais, permissões GPS/câmera e recuperação de falha de rede; classificação antes/depois e uso prolongado. PWA possui shell público offline; não guarda OS, sessão ou documentos nem envia operações offline. |
| 21 | Fiscal | Arquitetura preparada, emissão real ausente. Registro de adaptadores vazio; emissão sem provedor é bloqueada. | Escolher cobertura/provedor com contador; cadastro fiscal completo; adaptador, consulta/cancelamento, timeouts/reconciliação/webhooks e XML/PDF idempotentes. Nenhum número/protocolo foi inventado. |
| 22 | E-mail/WhatsApp | Preparação limitada. Avisos internos e model `SaidaNotificacao` existem. | Adaptadores reais, fila/outbox efetiva, remetentes/destinatários, consentimento/templates, retries, entrega/falha e links autenticados. O model da saída não equivale a mecanismo de envio pronto. |
| 23 | Auditoria | Núcleo implementado nas ações transacionais, cadastros, OS, estoque/lote e financeiro. Parcial na abrangência. | Auditoria individual do formset de contatos; alterações M2M; política de exclusão/estorno consistente; telas de consulta por entidade. Nem todo `save` direto gera auditoria automaticamente. |
| 24 | Backup/segurança | Isolamento tenant, grants, CSRF, HTTPS/cookies, uploads validados, arquivos privados e transações implementados/testados. Parcial na operação. | Atualizar Django sem suporte, revisar advisories das demais dependências, recuperação de backup comprovada, proteção contra abuso de login e política operacional de retenção. Configuração/restore reais não foram auditados nesta etapa. |
| 25 | Estética/experiência | Parcial. Identidade VERTYX, menu agrupado/recolhível, cards, SVGs locais, layout responsivo, agenda e TV especializados. | Listas/detalhes ainda genéricos; consolidar fichas e ações contextuais, grupos de formulário, filtros persistentes, loading/duplo clique, erros/estados vazios e acessibilidade por teclado/contraste. Não substituir dashboard/planejamento já aprovados. |
| 26 | Integrações | Núcleo integrado; parcial nas ampliações. | Orçamento→venda; recibos financeiros→banco obrigatório ou classificação explícita; custo de lote→OS/margem; documento→compra/venda/financeiro; fiscal/envio reais. Matriz detalhada abaixo. |
| 27 | Testes/homologação | Suíte anterior integralmente aprovada novamente. | Testes novos para lacunas, cenários de exceção, concorrência de conciliação, preservação de origem, timeout externo e grandes históricos. Homologação autenticada publicada e experiência em aparelhos reais continuam separadas. |
| 28 | Método | Levantamento inicial e plano concluídos nesta etapa. | Implementar as etapas abaixo, uma por vez, informando arquivos/migrations/testes/pendências. Deploy dependerá de autorização específica. |

## Problemas e riscos confirmados

### A01 — Dependência sem manutenção de segurança — prioridade alta

`requirements.txt` fixa Django 5.0.9. A série 5.0 encerrou suporte em 02/04/2025. Isso não é resolvido pela aprovação dos testes funcionais. Recomenda-se avaliar a linha 5.2 LTS suportada, com atualização em ambiente de desenvolvimento isolado, revisão das bibliotecas e execução de toda a suíte antes de qualquer publicação. Nenhum upgrade foi realizado nesta etapa. [Calendário oficial do Django](https://www.djangoproject.com/download/).

### A02 — Parcelamento perde origem nos filtros e indicadores — prioridade alta

`operacao/services.py:parcelar` cria novos `Lancamento` com `Parcela.origem`, mas sem os vínculos diretos `ordem`, `orcamento`, `contrato` e competência. O original é cancelado. A rastreabilidade pela `Parcela` existe, porém filtros e classificadores que consultam apenas a origem direta deixam de encontrar as contas ativas e podem classificar receita como sem origem. Confirmado com uma conta de OS parcelada.

Solução deve resolver origem por `Parcela.origem` ou evoluir a modelagem com cuidado: copiar simplesmente os campos para todas as parcelas violaria as constraints atuais de unicidade de recebível por origem.

### A03 — Divisão de centavos rejeita parcelamento possível — prioridade média

Arredondar todas as primeiras parcelas e deixar a diferença somente na última pode produzir valor final zero/negativo. Confirmado: R$ 0,09 em seis parcelas é rejeitado, embora três parcelas de R$ 0,01 e três de R$ 0,02 somem o valor. A transação faz rollback integral, sem apagar/cancelar a conta original. Corrigir distribuição de centavos com regressões para somatório, mínimos e idempotência.

### A04 — Solicitação rascunho reduz a recomendação de compra — prioridade alta

`operacao/stock.py:metrics` inclui `RASCUNHO`, `APROVADA` e `PEDIDO` em `em_compra`. Confirmado: produto disponível zero, mínimo dois, solicitação ainda rascunho de dois resulta em sugestão zero. Isso ajuda a não repetir solicitações, mas mistura intenção de compra com recebimento comprometido. Separar no cálculo e na interface solicitações abertas de pedidos efetivos; documentar a política antes de alterar os relatórios.

### A05 — Custo registrado não acompanha o lote consumido — prioridade alta

O FEFO físico está correto; a apuração financeira é incompleta. `gestao/services.py:movimentar` usa `Peca.custo_aquisicao` nas saídas, e `ItemVenda.custo_unitario` é preenchido ao editar o item. O detalhamento de lote registra quantidades, sem consolidar custo efetivo no movimento/item. Confirmado: entrada em lote a R$ 25,00, custo cadastral R$ 10,00, saída para OS registra R$ 10,00. Não chamar a margem atual de lucro real. Definir custo dos lotes efetivamente consumidos, devoluções e rateio, sem reescrever movimentos históricos.

### A06 — Pagamento sem conta não alimenta banco — prioridade média

`Pagamento.conta` e `PagamentoForm.conta` são opcionais. `pagar` cria `MovimentoCaixa` somente se a conta for informada; `liquidar` também pode chamar esse fluxo sem conta. Confirmado: recebimento parcial reduz saldo e entra no realizado financeiro, mas não cria movimento bancário. Os dois indicadores representam bases diferentes; não há duplicação. Definir opção explícita de pagamento não bancarizado ou conta obrigatória para novos pagamentos, preservando legados e oferecendo classificação posterior auditada.

### A07 — Histórico existe, mas a tela corta registros — prioridade média

`operacao/history.py:related` usa limites de 30/50 registros; plano mostra até 200 ocorrências e portal mostra até 50 OS/chamados. Não há exclusão dos dados: o problema é acesso ao restante sem paginação/filtros nessas telas. O teste atual verifica presença do bloco de histórico, não a consulta completa de grande volume.

### A08 — Calibração não atualiza o marco do equipamento — prioridade média

`ordens/services.py:finalizar` atualiza `data_ultima_preventiva` e execução do plano. Não há atualização equivalente de `data_ultima_calibracao` para OS de calibração. A OS permanece no histórico, mas o cálculo da próxima calibração pode continuar baseado em data anterior. Validar também reabertura e conclusão fora de ordem temporal.

### A09 — Infraestrutura descrita pelo YAML difere do serviço oficial — atenção operacional

`render.yaml` ainda declara `name: tecnolmed-erp`; a aplicação oficial é `vertyx-erp`. O arquivo não declara novo PostgreSQL e mantém `plan: free`, mas não deve ser sincronizado inadvertidamente como Blueprint para representar o serviço oficial. O YAML não foi alterado, aplicado ou usado para deploy. Alinhar a documentação/configuração declarativa apenas em etapa específica autorizada, preservando o vínculo do serviço existente e suas variáveis.

### A10 — Rotina de estoque preparada, mas não ativada no ambiente oficial

`processar_estoque --loop` chama `stock_scheduler.run`; por organização, `tick` trava a configuração, respeita intervalo de 30 minutos e agenda semanal no fuso configurado. `scan_stock` mantém ocorrências abertas, atualiza a mesma notificação, resolve automaticamente e permite nova ocorrência depois. O relatório automático é único por semana e organização, com histórico imutável.

Esse runner não é iniciado por `scripts/start.sh`, pelo Gunicorn ou por requisições. Sem executor externo ativo, não existe garantia de execução periódica no Render. Não foi ativado Cron Job, worker ou runner nesta etapa. A rotina de estoque não substitui a verificação de todos os alertas de contrato/OS/financeiro do comando `atualizar_alertas`. Não criar serviço pago como consequência desta auditoria.

## Riscos que precisam de testes específicos antes da implementação

- Conciliação de duas linhas com o mesmo movimento: o `OneToOneField` protege o banco, mas o serviço trava apenas a linha do extrato. Testar corrida e converter disputa em mensagem controlada, sem erro 500. Não foi reproduzida essa corrida nesta etapa.
- Fiscal: chamada externa acontece dentro da transação; timeout pode deixar emissão efetivada externamente sem estado local confirmado. Adaptador deve consultar por referência antes de repetir; consultas sucessivas não devem duplicar XML/PDF. Registro atual vazio impede uso real desse caminho.
- Arquivo em storage não participa do rollback SQL: falha depois de gravar arquivo pode deixar objeto órfão. Planejar compensação/limpeza segura, sem apagar arquivos válidos existentes.
- Dashboard, histórico e planejamento fazem agregações/iterações em Python e várias consultas por produto/conta. Sem ensaio de carga, não existe comprovação de desempenho para grande quantidade de dados.
- Chamados, contratos e planos usam referências de cliente/equipamento validadas, mas regras completas de SLA e sobreposição precisam de novos testes de negócio.
- Listas de equipamentos/clientes podem ser consultadas por perfis internos com ERP habilitado; técnicos têm OS própria, mas documentos sem OS podem ser visíveis dentro da organização. Formalizar essa matriz antes de restringir ou ampliar acesso.
- Testes existentes verificam isolamento e revogação. Não foi feita auditoria independente de toda cadeia de dependências/CVEs, teste de invasão ou teste de recuperação de backup real.

## Integrações que serão reutilizadas

| Fluxo | Implementação atual | Próxima extensão |
|---|---|---|
| Chamado → OS | `operacao.services.chamado_os`, sem duplicar OS | Responsável/SLA/prazo e histórico. |
| Plano → ocorrência → OS | `datas_plano`, `gerar_plano`, `preventiva_os` | Reagendamento e política entre plano/visita. |
| Contrato → agenda/cobrança | `gestao.services.gerar_planejamento`, `agendar_os`, `gerar_cobrancas` | Datas coerentes no planejamento, renovação/reajuste. |
| Orçamento → OS/recebível | `converter_orcamento`, `gerar_do_orcamento` | Conversão para `Venda`; proteger contas já geradas. |
| Compra → lote/estoque/pagar | `compra_acao` → `movimentar` → `move_lots` → `Lancamento` | Recebimentos parciais com múltiplos lotes e rateio. |
| Venda → estoque/receber | `venda_confirmar` → `movimentar` → `Lancamento` | Origem comercial, devolução/custo/fiscal. |
| Peça de OS → lote/histórico | `movimentar`, `MovimentacaoLote`, `pecas_snapshot` | Custo efetivo por lote; evitar texto livre como evidência de baixa. |
| OS concluída → equipamento | OS no histórico; data preventiva atualizada | Calibração e ficha técnica consolidada. |
| Pagamento → caixa/painel | `pagar`/`caixa`, `financial_dashboard`/`executive` | Conta explícita, ajustes, estorno, parcelas/origem. |
| Documento → entidade | `Documento`, `documento_salvar`, `documents` | FKs e permissões para compra/venda/financeiro. |
| Fiscal → OS/venda/financeiro | `DocumentoFiscal`, `fiscal.services`, contrato de `Provider` | Adaptador real, tratamento de falha e reconciliação. |

## Dependências externas e decisões de operação

Não impedem os ajustes locais de models/services/views/testes. Só serão necessárias nas respectivas etapas de integração ou homologação publicada:

1. **Fiscal:** município/UF do emitente, regime/cadastros e códigos com contador; escolha de fornecedor e cobertura; sandbox; credenciais/certificado por canal externo seguro. Não escolher nem cadastrar provedor automaticamente.
2. **Comunicação:** provedor de e-mail/remetente e domínio verificado; WhatsApp oficial/fornecedor compatível, conta/número, templates e consentimento; segredos externos; habilitação de envios somente após ensaios. Sem credenciais fictícias.
3. **Bancos:** instituições e formatos reais de extrato anonimizado, política de conciliação e futura API; certificados/tokens ficam externos.
4. **Backup:** política e recursos já existentes de PostgreSQL/R2, retenção, responsáveis, objetivo de recuperação e evidência de restore em ambiente seguro. Não testar restore sobre produção.
5. **Executor periódico:** autorização futura e mecanismo compatível com a infraestrutura/limites existentes. Runner está preparado; sua ativação permanece pendente e não implica criação de serviço.
6. **Homologação da operação:** perfis de uso, regras de autorização de compra, atendimento/SLA, composição de orçamento misto, apuração de custo e telas prioritárias; dados e cenários de trabalho representativos. As etapas podem começar com defaults conservadores sem acesso a dados publicados.

### Alternativas fiscais, sem contratação ou escolha

Consulta de fontes oficiais em 01/10/2026:

| Alternativa | Possibilidade documentada | Requisitos a confirmar antes de integrar |
|---|---|---|
| Focus NFe | API com NF-e, NFS-e e NFS-e nacional; autenticação, ambiente e referência de emissão documentados. | Cobertura do município, cadastro do emitente, token externo, certificado/requisitos municipais, sandbox e retorno/consulta/cancelamento. [Introdução oficial](https://doc.focusnfe.com.br/reference/introducao), [ambientes](https://doc.focusnfe.com.br/reference/ambiente). |
| Nuvem Fiscal | APIs documentadas para NF-e/NFS-e e documentos; NF-e exige empresa, certificado e token com escopo apropriado. | Cobertura municipal, empresa/certificado, OAuth e escopos, sandbox, quotas e operações necessárias. [Documentação oficial](https://dev.nuvemfiscal.com.br/docs/), [NF-e](https://dev.nuvemfiscal.com.br/docs/nfe/), [referência da API](https://dev.nuvemfiscal.com.br/docs/api/). |
| Integração direta NFS-e nacional | Documentação governamental de API do emissor e ambientes de teste. É alternativa para serviços, não substitui NF-e de produtos. | Enquadramento/cobertura do contribuinte, parâmetros municipais, DPS/leiautes, autenticação/assinatura exigidas e manutenção das notas técnicas. [Documentação técnica oficial](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual). |

A adequação comercial/municipal e os custos não foram verificados; não há recomendação de contratação nesta etapa. O adaptador atual deve ser reutilizado e completado, sem criar outro módulo fiscal.

## Ordem de implementação por etapas pequenas

Cada etapa deve produzir uma alteração local revisável, regressões específicas, suíte anterior, check e verificação de migrations. Se houver mudança de schema, usar migrations aditivas preservando campos/dados legados; validar upgrade local com dados sintéticos e leitura de compatibilidade. Não reescrever migrations antigas. Publicação permanece uma decisão separada.

| Etapa | Resultado concreto | Estrutura a reutilizar | Aceitação mínima |
|---|---|---|---|
| 1 | Base de dependências suportada e compatível | `requirements`, settings, testes atuais | Toda suíte PostgreSQL, PDF/uploads, deprecations, check; sem mudança silenciosa de comportamento/schema. |
| 2 | Parcelamento seguro com origem preservada nas consultas | `Lancamento`, `Parcela`, reporting/executive | Somatório exato, centavos, origem OS/orçamento/contrato/compra/venda, filtros, concorrência e sem nova cobrança. |
| 3 | Recebimentos/pagamentos com vínculo explícito e ajustes | `Pagamento`, `EventoFinanceiro`, `MovimentoCaixa` | Juros/multa/desconto separados e auditados, parcial/total, estorno, legado sem banco, idempotência/concorrência. |
| 4 | Central de documentos completa | `Documento`, forms, permissions e history | Compra/venda/lançamento, financeiro/estoque/vendedor por origem, cliente/tenant IDOR, uploads/rollback e PDF. |
| 5 | Chamado com responsável/SLA e continuidade para OS | `Chamado`, `OrdemServico`, services atuais | Conversão sem redigitação, prazo correto, histórico, isolamento e atraso. |
| 6 | Ficha técnica e históricos completos | `Equipamento`, `Foto`, históricos e finalização existentes | Marca/tensão, calibração, fotos antes/depois, paginação, snapshots antigos e mobile. |
| 7 | Fluxo comercial e acesso de vendedor | `Perfil`, membership/grants, `Orcamento`, `Venda` | Orçamento aprovado→venda, misto→OS/venda, recebível anterior, desconto, estoque, permissões/concorrência. |
| 8 | Recebimento parcial e custos completos de compra | `Compra`, `ItemCompra`, `CotacaoCompra`, lotes e `Lancamento` | Várias entregas/lotes, quantidades restantes, frete/impostos/rateio, AP sem duplicação e rollback. |
| 9 | Estoque/custo e exceções comerciais | `Movimentacao`, `MovimentacaoLote`, `ItemVenda`, reservas | FEFO físico e custo real; devoluções/estorno; inventário auditado; rascunho versus pedido na sugestão. |
| 10 | Contratos/preventivas com continuidade de agenda | `Contrato`, `AgendaPreventiva`, `PlanoPreventivo`, calendário | Reajuste/renovação, histórico, visitas no planejamento e regra de sobreposição preservando ocorrências realizadas. |
| 11 | Caixa/bancos e importação de extrato | `ContaBancaria`, `ExtratoBancario`, `conciliar` | Parser OFX/CSV, validação, dedup, preview, transação e corrida sem 500; sem conectar banco externo automaticamente. |
| 12 | Indicadores/relatórios e consulta do portal completos | `executive`, reporting, portal/history | Origem e custos corretos, período explícito, grandes volumes, preventivas no portal, isolamento/PDF/Excel. |
| 13 | Integrações de comunicação/fiscal revisadas | `SaidaNotificacao`, notificações e `fiscal.providers` | Outbox/retry e referência idempotente; sandbox real quando houver credenciais; nenhum envio/emissão fictícios. |
| 14 | Homologação operacional final e recuperação | Testes, documentação e infraestrutura já existente | Fluxos diários com usuários, aparelhos reais, carga/acessibilidade, backup/restore comprovado fora de produção; autorização separada para deploy. |

**Estética acompanha todas as etapas**, sem esperar a etapa 14: manter tokens/cores/tipografia/menu atuais, agrupar formulários por tarefa, oferecer ações contextuais, loading/erros/estados vazios e validar desktop/tablet/mobile em cada tela alterada. Etapas de UI não devem alterar regras financeiras ou permissões incidentalmente.

Cada etapa terá um registro com arquivos alterados, migrations novas, comandos/resultado dos testes, evidências visuais, dependências e riscos. Não haverá novos módulos paralelos de estoque, compras, vendas, financeiro, agenda ou fiscal.

## Entrega desta etapa

- Arquivos novos versionáveis: `AUDITORIA_ERP_COMPLETO.md` e `AUDITORIA_ERP_COMPLETO.json`.
- Ferramentas/evidências locais ignoradas pelo Git: `tmp/validation/erp_audit_run.py`, `erp_audit_probes.py`, `erp_audit_validate_documents.py`, logs e JSONs da execução.
- Arquivos funcionais alterados: nenhum. Migrations criadas: nenhuma. Deploy/commit/push: nenhum.
- A conclusão desta etapa é o levantamento; a homologação integral do ERP ampliado permanece pendente das etapas de implementação. As limitações reproduzidas não foram corrigidas nesta auditoria.
