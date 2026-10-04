# VERTYX — relatório do Bloco 3, atualizado após 3H

Atualização: 03/10/2026. Pasta original, branch main / HEAD fe6c554. **Homologação local concluída: 404/404 testes PostgreSQL PASS e jornadas locais pela interface.** Dispositivos físicos e produção permanecem pendentes; funcionalidades parciais/exclusões não se tornam completas por esse resultado. Nenhum Bloco 4, commit, push ou deploy.

O relatório detalhado está em [HOMOLOGACAO_BLOCO3.md](HOMOLOGACAO_BLOCO3.md); dados verificáveis em [VALIDACAO_BLOCO3.json](VALIDACAO_BLOCO3.json). O resultado anterior de 401 testes e a limitação de navegador de 02/10 foram preservados como histórico no JSON; foram superados pela homologação local descrita nesta atualização.

## Funcionalidades implementadas


- Fundação SaaS no domínio atual: Organization continua representando o tenant e a PJ principal; filiais próprias são distintas das unidades de clientes. Configuração empresarial/fiscal informativa, módulos por organização, capacidades por membership e metadados de plano/limites. Nenhuma regra identifica TECNOLMED pelo nome; nenhuma cobrança ou limite comercial é ativado retroativamente.
- Cadastro comercial no mesmo `Peca`: códigos/GTIN/alternativos, descrição, fornecedores, unidades e fatores de compra/venda, fracionamento, lote obrigatório, dados fiscais/ANVISA informativos e imagem pelo GED privado. Conversões usam Decimal e rejeitam quantidade base inexata; a unidade de compra não pode ser injetada no PDV para reduzir preço.
- PDV sobre `Venda/ItemVenda`: busca e código de barras como entrada de teclado, cliente opcional, vendedor, carrinho com alteração/remoção, descontos e motivo/limite, acréscimo, observação, reserva/cancelamento, finalização idempotente, comprovante e snapshot histórico. FEFO usa o motor oficial, incluindo lote e custo efetivamente consumidos.
- Pagamentos mistos e troco; venda a prazo com cliente/crédito permitido. Reutiliza `Lancamento`, `Pagamento`, `EventoFinanceiro` e `MovimentoCaixa`. Abertura de caixa registra conferência de saldo existente e não fabrica receita. Sessões por operador/conta, suprimento/sangria/ajuste auditados, fechamento com esperado/contado/diferença e bloqueio após fechamento.
- Orçamento aprovado convertido idempotentemente em venda, preservando recebível existente. Conversão comercial restrita a itens representados em produtos; orçamento com serviços continua no fluxo de OS existente. Devolução formal mantém venda original, valor, quantidade, lotes/custos originais, retorno físico e evento financeiro. Abatimento de crédito não é recebimento de dinheiro. Troca referencia devolução e nova venda.
- Compras mantêm `Compra/ItemCompra/CotacaoCompra`, unidades comerciais e recebimentos parciais/finais oficiais. Rascunho/cancelada não cobrem reposição; APROVADA/PEDIDO consideram somente quantidade pendente. Conta a pagar continua sendo gerada no recebimento final, conforme política anterior expressamente preservada.
- Inventário por depósito/lote com contagem/recontagem, detecção de movimentação posterior, divergência, aprovação e ajuste com movimento auditado. Transferência por fases utiliza os mesmos lotes/movimentos e reserva de trânsito; depósito de trânsito deve ser configurado explicitamente. Transferência direta legada permanece.
- Visão executiva comercial com vendas líquidas, devoluções, custo/margem registrados, vendedor, período e filtros por filial própria/centro. Dashboard anterior restaurado e preservado. Financeiro usa autorização própria, sem concessão implícita pela capacidade executiva. Relatório de margem passa a descontar devoluções formais.
- Técnico mantém agenda/chamados/OS/checklist/fotos/peças/assinatura do Bloco 2, com atalho para leitor QR pela câmera e fallback digitado. Não há cache offline de dados privados nem sincronização empresarial offline.
- RH/ponto: funcionário ligado ao usuário/técnico existente, departamento/gestor/jornada/escala, marcações com hora do servidor, tokens, sequência e cadeia de hashes; localização opcional e autorizada. Solicitação/decisão de correção preserva a marcação original. Espelho mensal em tela/PDF/Excel e fechamento mensal imutável com snapshot de configuração e saldo de banco de horas parametrizado. Sem jornada configurada, extras/faltas ficam sem apuração e fechamento é impedido.
- Novos papéis PDV, VENDEDOR, COMPRAS, RH e PAINEL_TV respeitam membership/organização; papéis antigos preservados. GED estendido a produto/funcionário/compra/venda, autorização de arquivo privado, pesquisa por dados permitidos, navegação e avisos internos de venda pendente, diferença de caixa, ajuste de ponto e inventário. Mecanismo anterior de notificações permanece, com leitura separada da resolução operacional.

“Implementado” descreve código e integração automatizada, não homologação completa de cada tela, dispositivo ou produção.


## Resultado da homologação 3H

- VALIDADO AUTOMATICAMENTE: 404 PASS, zero skips; 401 anteriores mais três testes novos. Check, migrations seco, collectstatic, pip check e diff check PASS. Última suíte após jornadas: 436.703 s; hashes de código inalterados durante/depois da execução.
- VALIDADO EM BANCO SINTÉTICO: suíte e preservação incremental; 39 conferências dos saldos, custos, pagamentos, snapshots, uploads, assinaturas e hashes dos registros criados pela interface. Estoque final 19,000 reconciliado por produto/lote/depósito.
- VALIDADO PELA INTERFACE: cinco vendas (simples, mista, troco, crediário e teclado móvel), caixa sem receita de abertura, diferença justificada, devolução de uma unidade, orçamento convertido sem duplicação, compra originada da OS com cotação/aprovação/pedido/recebimentos, inventário e trânsito, duas OS finalizadas (uma em 390×844), upload, assinatura/PDF, quatro marcas de ponto, ajuste rejeitado, espelho/PDF/Excel e fechamento permitido de mês anterior, navegação do gestor nos oito domínios e bloqueios do PDV.
- Responsividade: oito telas × três viewports confirmados (1440×900 / 768×1024 / 390×844), sem overflow da página; tabelas com rolagem interna. Capturas são da área visível do painel, não imagens da página inteira; ver dimensões no índice de evidências. Menus/foco/labels/contraste/formulários/disclosures/mensagens inspecionados, sem certificação WCAG integral.
- VALIDADO EM DISPOSITIVO REAL: nenhum. **PENDENTE DE HOMOLOGAÇÃO EM DISPOSITIVO REAL** e **PENDENTE DE HOMOLOGAÇÃO COM LEITOR FÍSICO**. **NÃO VALIDADO EM PRODUÇÃO**: todos os recursos deste bloco.

O recebimento parcial aumenta estoque/lote imediatamente; a conta a pagar permanece exclusiva do recebimento final. A venda devolvida mantém snapshot/item original; lote e custo repostos; reembolso formal. Nenhuma devolução parcelada bloqueada foi forçada.

PDFs OS 50/51 têm três páginas cada; espelho, duas. Todas as oito páginas foram renderizadas e inspecionadas. Excel com 31 dias, 32 linhas incluindo cabeçalho e nove colunas. Fotos e assinaturas sintéticas conferidas por hash. GPS timeout e negativa registrados no navegador; câmera e localização real não foram simulados como aparelhos físicos. Nota de assinatura isolada na terceira página da OS 51 é débito de paginação.

## Correções de 3H e arquivos

Campo de limite de crédito autorizado passou a aparecer no formulário existente; ano/mês em links/campos do ponto deixam de usar localização numérica; botão do menu móvel recebe nome/alvo acessíveis; dois links de alerta de estoque passam a texto escuro. Somente correções mínimas e três testes de regressão, sem novo módulo/refatoração.

Arquivos de código/template/teste alterados nesta etapa: `operacao/test_block3_security.py, operacao/test_block3_workforce.py, templates/base.html, templates/clientes/cliente_form.html, templates/gestao/lista.html, templates/operacao/ponto.html, templates/operacao/ponto_mirror.html`. Documentos atualizados/criados: os três da entrega. Helpers/evidências locais em tmp/validation são ignorados pelo Git; não contêm credenciais de produção. Model/service/dependência/migration não mudou em 3H.

## Funcionalidades parciais, riscos e exclusões

KPIs gerenciais completos, DRE, alocação histórica por filial/centro e matriz integral de agregados legados por flags/capacidades continuam débitos. Dashboard comercial não presume despesas/impostos; com filtros de filial/centro, OS/lotes/funcionários sem alocação aparecem “Sem base”, confirmado pela UI. Plano SaaS é metadata, não cobrança/enforcement; fiscal é informativo.

Recebível parcelado mantém bloqueio seguro de devolução até política específica. Ponto é interno, sem REP/conformidade legal/folha. Diferenças de caixa mantêm rastreabilidade e exigem revisão. Carga real, custos antigos estimados, governança de períodos fechados e cadastros reais precisam homologação/revisão próprias.

**RECOMENDAÇÃO DE UX — INDICADOR/BOTÃO DE SINCRONIZAÇÃO DO PDV**: ausência de indicador permanente de online/última atualização/sincronização; futura atualização automática e botão manual auxiliar. Nenhuma fila offline ou nova funcionalidade foi implementada. Comprovante atual não detalha formas/troco; melhoria de apresentação pendente.

Não implementados por exclusão: NF-e/NFS-e/NFC-e/A1/SAT/TEF, gateway/PIX automático/Open Finance, integrações externas de comunicação/IA/ANVISA, folha/eSocial/comissões complexas, app nativo/offline empresarial e grandes módulos públicos. Não se declarou homologação de outros navegadores, hardware ou ambiente publicado.

## Preservação e migrations


Ensaio isolado no cluster PostgreSQL local já existente: schema anterior e 1.836 registros sintéticos → 14 migrations do Bloco 3 → comparação de colunas/valores/registros/relações anteriores. PASS. Outro ensaio sobre a base sintética existente confirmou as mesmas 1.836 linhas preservadas. Hashes dos 55 arquivos anteriores do diretório de migrations, incluindo inicializadores, permanecem iguais. Não foi usado banco publicado nem reset do banco existente. Bases temporárias de testes não são infraestrutura nova de produção.

Migrations novas deste bloco, todas incrementais, sem operações RemoveField/DeleteModel/drop/flush/reset:

- `clientes/0005_fundacao_bloco3`
- `contas/0008_fundacao_bloco3`
- `platform_core/0005_fundacao_bloco3`
- `gestao/0009_fundacao_bloco3` a `0013_fundacao_bloco3`
- `operacao/0008_fundacao_bloco3` a `0013_fundacao_bloco3`

Alterações incluem novos campos/tabelas/constraints/índices e ampliação compatível de choices/nullability, mantendo PKs e dados existentes. Nenhuma migration deste bloco foi aplicada em produção. Também permanecem como alterações locais os arquivos dos Blocos 1/2: contas0007, equipamentos0007, gestao0006–0008, operacao0006–0007 e ordens0010. A lista efetiva de pendentes no serviço publicado deverá ser confirmada em futura etapa autorizada; não foi consultada nesta etapa.

Dependências: nenhuma alteração adicional no Bloco 3. Ambiente: Python 3.12.14, Django 5.2.17 LTS, PostgreSQL 16.15. A alteração de requirements já pertence ao Bloco 1. Configurações Render/R2/credenciais não foram modificadas.


Na homologação 3H: **zero migrations novas; todos os 69 arquivos preexistentes mantiveram hashes**. O teste de preservação/migração legada passou novamente na suíte completa. Os ensaios detalhados de 1.836 linhas citados acima são evidência anterior B2→B3, não novo acesso a produção. Novos registros sintéticos da interface são acréscimos normais, com histórico.

## Histórico de implementação e arquivos do Bloco 3


O working tree inclui também alterações anteriores dos Blocos 1/2; `git diff HEAD` não é um diff exclusivo do Bloco 3. Inventário exato de arquivos versionáveis e migrations consta em `VALIDACAO_BLOCO3.json`.

Novos serviços/modelos/views/testes: `platform_core/company.py`, `modules.py`; `gestao/products.py`, `product_views.py`; `operacao/commerce.py`, `commerce_scope.py`, `commercial_models.py`, `pdv.py`, `purchase_scope.py`, `inventory.py`, `inventory_models.py`, `inventory_views.py`, `workforce.py`, `workforce_models.py`, `workforce_views.py`, `mobile.py`, `block3_notices.py` e nove `test_block3_*.py`. Novos templates: company, PDV (home/cash/sale/products/receipt), inventory/transfers, RH/ponto/adjustments/mirror, mobile_qr, product_links e executive_commercial. Novos JS: pdv, ponto e mobile-qr. Migrations e documentos adicionais listados separadamente.

Arquivos existentes estendidos neste bloco: models/formulários/views de clientes; models de contas; models/forms/services/permissions/urls/views/reporting de gestão; models/forms/services/permissions/stock/stock_models/reporting/executive/navigation/notifications/urls/views de operação; middleware/models/urls de plataforma; base e templates de produto/técnico/dashboard existentes. Não se atribuem aqui todas as alterações do working tree a este bloco.

Regressões intermediárias encontradas e corrigidas: o módulo e o fragmento do dashboard existente haviam sido substituídos durante integração; ambos foram restaurados com a interface anterior, mantendo a nova visão em template próprio e a classificação por origem raiz do Bloco 1. Campo tipo de centro de custo não pode invalidar formulários antigos. Corrigidos link de imagem/GED, descoberta duplicada de testes e encerramento de streaming em fixture de segurança. Logs de falhas intermediárias são preservados; a aprovação final só se refere aos arquivos efetivamente retestados.


## Publicação e regra de parada

Homologação local entregue; dispositivos reais, cadastros reais, backup/verificação do serviço existente, migrations/publicação e R2/Render/Gunicorn/logs dependem de futura etapa autorizada. A lista exata de migrations pendentes no serviço publicado não foi consultada nesta execução.

Nenhum commit, push, deploy, acesso ou alteração de PostgreSQL publicado/Render/R2/credenciais e nenhum início do Bloco 4. Aguardar autorização do usuário. PLANO_BLOCO4.md continua apenas planejamento.
