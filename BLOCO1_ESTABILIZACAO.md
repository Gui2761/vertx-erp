# VERTYX — Bloco 1: estabilização

Data: 02/10/2026. Base de código: `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261`, branch `main`. Trabalho realizado na pasta original do projeto. A auditoria anterior foi lida e preservada como registro da etapa 0.

**Estado: concluído e validado localmente.** Base pronta para iniciar o Bloco 2, mantendo a publicação atual sem alterações. Evidências consolidadas em `VALIDACAO_BLOCO1.json`.

## Correções e regras adotadas

### Dependências

Django 5.0.9 foi substituído por **5.2.17 LTS**, em ambiente virtual isolado, preservando o ambiente anterior. Os demais pins de produção permanecem iguais. O plano, as fontes oficiais, o inventário e o limite da análise estão em `PLANO_DEPENDENCIAS_BLOCO1.md`.

PostgreSQL usa o mesmo backend psycopg2. Os adaptadores django-storages/boto3, PDFs ReportLab/Pillow, PWA, WhiteNoise e demais componentes atuais foram mantidos. O projeto não ganhou framework, worker, banco ou módulo paralelo. O runner de estoque não foi ativado.

### Parcelamento e origem financeira

- `Lancamento.origem_raiz` mantém a conta original vinculada a OS, orçamento, contrato, venda ou compra. `Parcela.origem` continua registrando a conta imediatamente parcelada; reparcelamentos também apontam para a mesma raiz.
- Mantidas as unicidades existentes: não se replica a FK de OS/orçamento/contrato em cada parcela, evitando cobranças duplicadas e conflito com constraints.
- Cliente/fornecedor, emissão, competência e classificação são preservados nas parcelas novas. Contas históricas mantêm seus valores, datas e estados; a migration apenas preenche o novo vínculo raiz das parcelas existentes.
- Divisão em centavos inteiros: o resto é distribuído entre as primeiras parcelas, com diferença máxima de R$ 0,01. O somatório é exatamente o valor original. Valores que produziriam parcela inferior a R$ 0,01 são rejeitados, sem cancelar a conta original.
- Reenvio com os mesmos parâmetros devolve as mesmas parcelas; parâmetros diferentes não recriam a cobrança. A conta original é cancelada pelo fluxo auditado, sem baixa de caixa.
- Consultas, filtro de origem na lista, filtros dos relatórios por equipamento/unidade/técnico, histórico financeiro e indicadores usam a origem raiz. Categorias de receita não classificam parcelas de OS como manuais. O detalhe de contrato inclui suas parcelas.
- Cancelar uma OS também verifica suas parcelas. Pagamento parcial ou integral bloqueia o cancelamento; contas não pagas são canceladas pelo serviço financeiro dentro da mesma transação.

### Pagamentos, saldo e rastreabilidade

- `Pagamento`, `EventoFinanceiro` e `MovimentoCaixa` permanecem as estruturas oficiais. Cada pagamento reduz apenas o saldo restante; a conta só passa a `LIQUIDADO` quando esse saldo chega a zero. A liquidação integral posterior a um pagamento parcial usa o saldo restante.
- `request_id` identifica a intenção de pagamento. Reenvio igual retorna o pagamento existente; dados diferentes são rejeitados. A disputa concorrente do mesmo token entre contas não deixa movimento bancário da operação perdedora.
- Conta/cliente/fornecedor continuam vinculados ao lançamento, cuja raiz identifica venda, OS, contrato, orçamento ou compra. Auditoria registra usuário, pagamento, token, origem, valor e saldo.
- **Sem banco informado:** o pagamento é registrado como **não bancarizado**, permanece no histórico, relatório de recebimentos/pagamentos e indicadores financeiros, reduz o saldo da conta e pode quitá-la. Não é inventada uma conta bancária nem alterado um saldo bancário. A tela explica esse controle e exibe seus totais separadamente, já incluídos no total financeiro.
- **Com banco/caixa informado:** a baixa cria o movimento de entrada/saída correspondente na `ContaBancaria` escolhida, com o mesmo identificador de operação. Conta de outra organização não é aceita.
- Liquidações legadas sem `Pagamento` permanecem nos indicadores uma vez; quando não há vínculo bancário demonstrado, são tratadas como histórico sem banco vinculado, sem criar movimentação fictícia. Vinculação bancária posterior, estorno, juros e multas não foram desenvolvidos neste bloco.

### FEFO, custo e devolução

- O cálculo e a execução compartilham o mesmo planejamento dos lotes válidos, ordenados pelo FEFO existente, respeitando depósito e reservas. A transação bloqueia produto, saldos e lotes; estoque insuficiente, lote vencido ou erro desfazem toda a saída.
- Cada `MovimentacaoLote` grava o custo unitário e o custo total correspondente à sua quantidade. `Movimentacao.custo_total` consolida exatamente esses detalhes; divergência provoca rollback. Transferência soma somente a saída, sem contabilizar saída e entrada como dois custos.
- Quantidade com três casas × custo unitário com duas casas resulta em custo total com **cinco casas decimais**, preservado em Decimal. O custo unitário médio exibido é arredondado para duas casas, mas não é multiplicado novamente para substituir o total exato.
- A venda confirmada atualiza `ItemVenda` com o custo realmente consumido e a margem usa esse total. A OS apura custo líquido das saídas e devoluções; novos snapshots incluem lotes, quantidades e custos. Snapshots assinados anteriormente não são reescritos.
- Devolução de OS restaura os lotes/depósito efetivamente usados e reverte seu custo documentado; não aceita quantidade maior que o consumo líquido. A concorrência não devolve o mesmo consumo duas vezes.
- **Histórico legado:** novos campos econômicos ficam nulos nos movimentos e vendas antigos. O fallback preserva o custo anteriormente documentado e os snapshots novos identificam quando o movimento antigo usa estimativa. A devolução de uma saída antiga sem custo de lote registrado reverte o custo que aquela saída documentou, sem reprecificar a saída pelo custo atual do lote. Correção retroativa de margem/custo exige tratamento separado e não foi feita silenciosamente.

### Compras e reposição

| Status atual | Abate a necessidade? | Motivo |
|---|---|---|
| `RASCUNHO` | Não | Intenção de compra ainda não aprovada. Quantidade consultável separadamente em `em_solicitacao`. |
| `APROVADA` | Sim | Compra aprovada com fornecedor e itens definidos; compromisso de reposição ainda não recebido. |
| `PEDIDO` | Sim | Pedido pendente de recebimento. |
| `RECEBIDA` | Não como pendência | Quantidade já incorporada aos lotes e estoque físico pelo recebimento atual. |
| `CANCELADA` | Não | Não há recebimento esperado. |

A recomendação continua usando estoque válido disponível, reservas de OS/vendas, mínimo/ideal, vencimento/substituição e histórico de consumo do serviço atual. A pendência aprovada é descontada uma vez, e o recebido não é descontado novamente como compra pendente. O relatório semanal e a geração de `Compra`/`ItemCompra` reutilizam essa mesma regra; relatórios históricos não são apagados ou recalculados.

O recebimento atual permanece integral. Recebimento parcial de compras e devolução comercial de vendas são ampliações posteriores, não simulações inseridas no cálculo atual.

## Arquivos do bloco

| Arquivos modificados | Finalidade |
|---|---|
| `requirements.txt` | Pin Django validado. |
| `gestao/models.py`, `gestao/forms.py`, `gestao/services.py` | Raiz financeira, proteção de edição, custo da movimentação e snapshots. |
| `gestao/views.py`, `gestao/reporting.py` | Consultas, detalhes e filtros respeitando origem. |
| `operacao/models.py`, `operacao/stock_models.py` | Custo consolidado da venda/lotes e classificação dos pagamentos. |
| `operacao/services.py`, `operacao/stock.py` | Parcelamento, pagamentos transacionais, consumo/devolução FEFO e pendência de compras. |
| `operacao/executive.py`, `operacao/reporting.py`, `operacao/history.py`, `operacao/forms.py` | Indicadores, relatórios, histórico e explicação do pagamento sem conta. |
| `ordens/models.py` | Custo líquido da OS a partir dos movimentos existentes. |
| `templates/gestao/detalhe.html`, `templates/gestao/financeiro.html`, `templates/gestao/lista.html` | Histórico de pagamentos, controle não bancarizado e filtro de origem; sem reformulação visual. |
| `operacao/test_stock.py`, `operacao/test_planning.py` | Fixtures de pendência passam a aprovar compras reais; rascunhos explicitamente não abatem a necessidade. Nenhum teste anterior foi removido. |

Novos arquivos funcionais: `gestao/financial_origin.py` (helper de consultas dos models atuais), `operacao/test_stabilization.py` e as três migrations abaixo. Documentos novos do bloco: este relatório, `PLANO_DEPENDENCIAS_BLOCO1.md` e `VALIDACAO_BLOCO1.json`.

## Migrations aditivas

1. `gestao/0006_estabilizacao_bloco1`: adiciona origem raiz nullable e custo total nullable da movimentação.
2. `operacao/0006_estabilizacao_bloco1`: adiciona custos nullable de item de venda e detalhe de lote.
3. `gestao/0007_origem_parcelas_existentes`: preenche somente a nova FK das parcelas históricas. Verifica organizações e ciclos antes de atualizar; inconsistência interrompe a migration transacional.

Os dois arquivos 0006 respeitam as dependências existentes; 0007 depende de ambos. Não houve alteração de migration antiga, remoção de campo/tabela, reset, flush ou reescrita de valores financeiros/saldos históricos. Nenhuma migration foi executada no banco publicado.

## Validação

| Verificação final | Resultado |
|---|---|
| Suíte completa PostgreSQL | **293/293**, 258 anteriores + 35 novos, 263.946 s, nenhum ignorado. |
| Regressões específicas | **35/35**, 29.985 s; cinco testes novos de concorrência real. |
| `python manage.py check` | Aprovado, nenhuma ocorrência. |
| `python manage.py makemigrations --check --dry-run` | Aprovado, nenhuma mudança faltante. |
| `pip check` | Aprovado, dependências consistentes. |
| Ensaio incremental PostgreSQL existente local | Três migrations aplicadas; 1470 registros anteriores em 71 tabelas preservados, com todas as colunas anteriores iguais. Reexecução idempotente aprovada. |
| `collectstatic` e manifesto/compressão do storage atual | Aprovados; 145 entradas do manifesto com arquivos existentes. |
| PDFs, snapshots, PWA, uploads e S3 simulado | Cobertos pela suíte completa aprovada. |
| Revisão Git, migrations antigas e segredos | `main`/HEAD preservados, nenhuma migration antiga modificada; varredura dos arquivos alterados sem valores de credenciais detectados. |

Comandos Django executados pelo Python do ambiente isolado com `--settings=tecnolmed.test_postgres_settings`. A seleção de settings restringe banco/uploads à infraestrutura local sintética; configurações de produção permanecem iguais.

Durante as verificações foram corrigidos o bloqueio PostgreSQL em join opcional (restrito à tabela do lançamento), fixtures antigas que confundiam rascunho com compra aprovada e duas assertivas dos testes novos. A execução final não possui falhas. Logs ERROR/503 nos testes de falha de storage são cenários negativos esperados, com assertions aprovadas; não são erros no serviço publicado. As evidências locais ficam em `tmp/validation/` e o ambiente de testes em `tmp/provision/bloco1-venv/`, ambos ignorados pelo Git.

A execução está restrita ao PostgreSQL 16.15 sintético de loopback já provisionado. Os testes Django usam uma base temporária. O ensaio incremental usa a base sintética existente, com comparação por chave primária de todas as colunas anteriores, sem imprimir dados. Static é validado também com `CompressedManifestStaticFilesStorage`, em diretório isolado.

As regressões específicas cobrem origem dos cinco fluxos, filtros/indicadores, centavos/dízimas, reenvio, pagamentos parciais/quitação, bancos, rollback, FEFO, custo fracionário, validade, estoque insuficiente, devolução nova/legada, reposição, permissões e isolamento. Cinco testes novos exercitam concorrência PostgreSQL real, além dos anteriores.

## Riscos e próximos passos

- Aceitação local não equivale a homologação publicada. R2 real, Render e PostgreSQL publicado não foram acessados nesta etapa; S3 usa o simulador da suíte. O startup Linux/Gunicorn no Render não foi executado.
- O histórico econômico anterior fica preservado com fallback explícito. Este bloco não promete recuperar custos por lote que nunca foram gravados nem corrigir retroativamente a margem de vendas antigas.
- As bibliotecas mantidas foram verificadas por resolução e regressões; não foi realizada auditoria completa de advisories/CVEs de todos os pacotes. Novas atualizações exigem avaliação própria, não substituição automática dos pins.
- Nenhuma alteração em credenciais, `.env`, settings de infraestrutura, `DATABASE_URL`, `SECRET_KEY`, Render, R2, Docker/startup ou banco real. Nenhum commit, push ou deploy. Nenhum novo módulo fiscal/comercial, certificado A1, chamado/SLA ou grande mudança visual.
- Conclusão de prontidão para o Bloco 2: **sim, para desenvolvimento na base local validada**. O escopo do Bloco 2 deve ser confirmado antes de implementação; os demais pontos da auditoria permanecem registrados, sem declaração de ERP ampliado integralmente concluído.
