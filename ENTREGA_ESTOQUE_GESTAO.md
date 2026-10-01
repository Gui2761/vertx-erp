# Entrega — Estoque e VERTYX Gestão

Base: `vertyx_final.zip`. A ampliação reutiliza os models, serviços, auditoria, permissões, contexto Organization e fluxos atuais. O pacote anterior permanece como referência. Não houve deploy, commit, push, acesso à produção ou alteração de credenciais.

## Estoque e validade

- Entradas/recebimentos registram número, fabricação opcional, validade, quantidade, fornecedor, custo, data de entrada, depósito/localização e documento por lote. Várias entradas do mesmo produto coexistem.
- Saídas, OS e vendas usam FEFO e excluem vencidos. Devoluções mantêm o lote/validade original; transferências preservam a identidade do lote e detalham saldos por depósito.
- Faixas VENCIDO, até 7/15/30/60/90 dias e normal aparecem na tela de lotes. Para peças não perecíveis, sem validade é permitido. Habilitar **Controla validade** torna lote e validade obrigatórios nas novas entradas.
- Estoque físico, mínimo, ideal/máximo, reservado, disponível válido, pendente e sugestão aparecem no produto/lista. Reservas firmes para OS/vendas/outras necessidades são registradas na tela existente de estoque ampliada; rascunhos editáveis sem reserva não comprometem saldo. Consumo utiliza a reserva da própria origem e protege as demais.
- O saldo agregado continua em `Peca.quantidade_atual` e `SaldoDeposito`. `LoteEstoque` detalha o saldo; `MovimentacaoLote` detalha as movimentações existentes. Não há estoque ou módulo de compras paralelo.
- Ocorrências operacionais persistentes acompanham mínimo/zero, falta de movimentação, vencidos e faixas de validade. Ler um aviso não resolve a ocorrência. Regularização resolve automaticamente na próxima rodada; retorno do problema cria novo ciclo.

## Compras e relatórios

O relatório semanal configurável guarda snapshots imutáveis; gerações manuais adicionais também preservam o histórico. Tela, PDF e Excel mostram produto/SKU/categoria, físico/reservado/disponível, mínimo/ideal, consumo, vencimentos, pendentes, recomendação, último fornecedor/custo e valor estimado. As colunas quantitativas do Excel são numéricas; textos não são interpretados como fórmulas. PDF usa fichas de produto para manter legibilidade.

A sugestão recompõe o ideal, descontando disponibilidade e compras pendentes. Inclui reposição estimada de lotes próximos do vencimento e média de consumo com histórico suficiente. Sem histórico suficiente, usa os parâmetros do produto. Estimativas não são uma ordem automática de compra.

Em **GERAR SOLICITAÇÃO DE COMPRA**, selecionar produtos e editar quantidades cria `Compra`/`ItemCompra` atuais. Necessidade é revalidada para evitar duplicação com compras pendentes; excesso exige justificativa. UUID protege duplo envio. O fluxo existente de `CotacaoCompra`, seleção de fornecedor, aprovação, pedido, recebimento, entrada em estoque e conta a pagar foi preservado. Produtos controlados precisam de lote/validade antes de receber; o recebimento não permite alterar silenciosamente quantidades/preços aprovados.

ADMIN configura padrões para novos produtos, intervalos/faixas, dia/horário semanal, ativação e janela de consumo. ADMIN/GESTOR/ESTOQUE consultam relatórios, registram reservas/entradas e geram solicitações; TÉCNICO mantém o estoque permitido para operação e não recebe telas de compras/financeiro.

## Gestão e experiência visual

ADMIN/GESTOR recebem painel executivo com saudação e período Hoje/Semana/Mês/Personalizado; indicadores financeiros clicáveis, realizado, inadimplência, gráficos de caixa em 7/30 dias ou 3/6/12 meses, faturamento mensal, contas bancárias e saldo consolidado. Cálculos usam lançamentos/pagamentos reais e excluem duplicação entre pagamentos e liquidações legadas.

Agenda de hoje, indicadores de OS, preventivas/corretivas executadas, produtividade, estoque/validade, necessidade de compras, contratos e comercial compartilham o backend atual. Faturamento é gerencial pela emissão de contas a receber; serviços/produtos/contratos/locações são classificados apenas quando existe origem suficiente. Valores sem origem inequívoca aparecem em **Sem classificação**. Datas de reajuste não existentes no schema são informadas como não cadastradas, sem inventar vencimentos.

Menu agrupado em Início, Assistência, Comercial, Estoque, Compras, Financeiro, Cadastros, Relatórios e Configurações, com ícones SVG locais próprios e opção de recolher no desktop. Mobile usa menu recolhido e tabelas com rolagem interna. TÉCNICO mantém a visão operacional. Não foi copiada marca/código da referência visual e não foram criados módulos paralelos para Gestão/Assistência.

## Automação e infraestrutura

`processar_estoque` executa uma rodada; `--loop` mantém runner independente. O Compose inicia automaticamente `estoque_runner`, reutilizando imagem, banco e ambiente. Estado/locks ficam no PostgreSQL; não há Redis/Celery. O comando anterior de alertas foi preservado.

A ativação futura no Render está detalhada em [AUTOMACAO_ESTOQUE.md](AUTOMACAO_ESTOQUE.md). Web Service continua `plan: free` e o PostgreSQL existente não é reprovisionado. Render Cron não oferece plano Free e tem custo próprio; nenhum serviço pago foi criado. É necessário ativar um executor autorizado para a rotina operar no ambiente publicado. O código não promete execução automática dentro de um Web Free suspenso.

## Segurança e validação

Somente migrations novas: `gestao.0005` e `operacao.0002/0003/0004`. Hashes das anteriores e diff de arquivos ficam em `AUDITORIA_ESTOQUE_ARQUIVOS.json`. A migration de dados detalha saldos legados sem inventar datas, apagar registros ou alterar colunas anteriores; inconsistências impedem o upgrade para análise.

Suíte integral: 208 testes no PostgreSQL; SQLite: 197 aprovados e 11 ignorados por exigirem bloqueios PostgreSQL. Inclui os 165 anteriores e 43 novos, com três novos ensaios de concorrência: FEFO no último lote, reservas concorrentes e runners simultâneos. Check, makemigrations dry-run, migration plan e collectstatic constam em `VALIDACAO_FINAL.json`.

Ensaio HTTPS local com PostgreSQL 16.15, simulador Moto S3 privado e Chromium: 27 telas/fluxos anteriores e 17 telas novas em 320/390/768/1365 px; ciclo de compra por relatório, PDF/Excel, leitura/resolução, permissões e menu. Atendimento original com GPS simulado/negado, foto, assinatura e PDF repetido nas duas empresas; oito tentativas cruzadas retornaram 404. PDFs e telas foram renderizados/inspecionados. Todos os dados e segredos do ensaio são sintéticos e ficam excluídos do ZIP.

Os avisos `security.W005`/`security.W021` do check de deploy refletem decisões existentes de HSTS subdomínios/preload que dependem do domínio real. Não foram alteradas configurações de infraestrutura por esta fase. Homologação física e ativação do scheduler na infraestrutura publicada continuam a cargo do operador, com autorização de deploy separada.

Consulte [VALIDACAO_FINAL.json](VALIDACAO_FINAL.json), [AUDITORIA_FINAL.md](AUDITORIA_FINAL.md) e [INVENTARIO_FINAL.md](INVENTARIO_FINAL.md) para evidências e inventário atualizado. O pacote completo novo é `vertyx_estoque_gestao.zip`; o ZIP de referência foi mantido.
