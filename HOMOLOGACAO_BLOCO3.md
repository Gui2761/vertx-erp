# VERTYX — Bloco 3H: homologação final local

Data: 03/10/2026. Pasta original `tecnolmed_erp`. Navegador: Codex In-app Browser. Dados exclusivamente sintéticos no PostgreSQL 16.15 local preexistente. Python 3.12.14 / Django 5.2.17. HEAD `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261`, branch `main`, repositório `tecnolmedengclinica-spec/vertx-erp`.

**Etapa local encerrada: 404/404 testes PostgreSQL PASS, zero skips, jornadas previstas executadas pela interface.** Isso não certifica os dispositivos físicos nem o ambiente publicado. O Bloco 3 conserva funcionalidades parciais e exclusões documentadas; não há autorização implícita de publicação.

## Distinção das evidências

| Categoria | Resultado |
|---|---|
| VALIDADO AUTOMATICAMENTE | 404 testes; check, migrations seco, collectstatic, pip check e diff check PASS |
| VALIDADO EM BANCO SINTÉTICO | Testes PostgreSQL, preservação incremental e 39 conferências dos registros gerados pela UI |
| VALIDADO PELA INTERFACE | PDV, caixa, devolução, orçamento, compras/recebimentos, inventário, transferência, assistência, ponto e gestor |
| VALIDADO EM DISPOSITIVO REAL | Nenhum dispositivo físico disponível/testado nesta execução |
| PENDENTE DE DISPOSITIVO REAL | Celular, touch, câmera/QR físico, leitor, GPS permitido/negado/indisponível no aparelho, Smart TV |
| NÃO VALIDADO EM PRODUÇÃO | Todos os recursos deste bloco; Render, PostgreSQL publicado e R2 não foram acessados |

Os 401 testes anteriores foram preservados; três testes de regressão foram acrescentados. Os 335 testes pré-Bloco 3 continuam na suíte, junto aos 66 do Bloco 3 e aos três desta homologação. Nenhum teste foi removido para obter PASS.

## Estado inicial e segurança do trabalho

Working tree conferido antes das correções. Os 328 arquivos de código/templates/JS/dependências coincidiam com os hashes da versão testada do Bloco 3. Sintaxe Python e integridade verificadas; não havia arquivo parcialmente escrito identificado. Os 69 arquivos dos diretórios de migrations, incluindo inicializadores, continuam idênticos. Nenhum reset, checkout destrutivo, flush, recriação do banco existente, mudança de migration antiga ou alteração de permissões para facilitar testes.

As alterações dos Blocos 1/2/3 foram preservadas. Apenas sete arquivos de código/template/teste diferem do início de 3H. Não foram alterados models, services, dependências ou arquitetura nesta etapa. As contas e operações financeiras citadas abaixo são fixtures locais, sem transações externas.

## PDV, caixa e devolução

| Venda local | Cenário pela UI | Total original | Resultado |
|---|---|---|---|
| VENDA-000011 | Duas unidades; desconto de 1,00; dinheiro 7,00 com recebido 10,00; PIX 12,00 | 19,00 | Finalizada por F8; troco 3,00; duas unidades FEFO do lote 37; custo 14,66 |
| VENDA-000012 | Dinheiro simples | 10,00 | Finalizada, recebível liquidado e saldo zero |
| VENDA-000013 | Crediário com limite autorizado no cliente sintético | 10,00 | Recebível pendente; nenhum recebimento/caixa fictício |
| VENDA-000014 | Orçamento aprovado convertido; pagamento PIX | 10,00 | Finalizada; origem ORC-000004 preservada; repetição recuperou a mesma venda |
| VENDA-000015 | Código de barras simulado por teclado; F2/F4/F8 em 390×844 | 10,00 | Finalizada e liquidada; custo 7,33 do lote 38 |

Busca, seleção, quantidade, desconto e pagamento foram usados na interface. Código `QA-BARRAS-3` entrou por teclas e Enter; F4 levou foco a `forma-1`; F8 submeteu o pagamento. Isso não é aprovação de leitor físico: **PENDENTE DE HOMOLOGAÇÃO COM LEITOR FÍSICO**.

Sessão de caixa 1: contagem inicial 50,00; esperado 67,00; contado 66,00. Fechamento sem justificativa foi rejeitado; com motivo, diferença -1,00 preservada. Sessão 2: abertura zero, venda 10,00 e fechamento 10,00, diferença zero. Contagens de abertura/fechamento não geraram receita nem movimentos financeiros artificiais.

Uma unidade da venda 11 foi devolvida formalmente: valor 9,50, reposição no mesmo lote 37 pelo custo original 7,33 e reembolso no banco sintético. Snapshot e ItemVenda originais permanecem integralmente iguais aos anteriores. A venda permanece parcialmente devolvida. Não foi forçada devolução de recebível parcelado: o bloqueio deliberado continua preservado e validado automaticamente.

Comprovante não fiscal foi gerado e inspecionado pela interface. Valores/itens presentes; o modelo atual não detalha formas de pagamento, troco e desconto de cada item no comprovante. Recomendação de apresentação, sem ampliação silenciosa de escopo.

## Comercial e compras

ORC-000004 foi criado, recebeu produto, enviado, aprovado e convertido em VENDA-000014. Conversão repetida após a finalização abriu a mesma venda; conferência confirmou uma única venda com essa origem e sem nova baixa/recebível.

Compra 16, já em PEDIDO na etapa anterior: recebimento parcial de 5 unidades no lote B3H-FEFO-PRIMEIRO (09/10/2026) e final de 15 no B3H-FEFO-SEGUNDO (01/12/2026), custo 7,33. Total recebido 20; conta a pagar 146,60 criada no final.

Na OS 50, necessidade de 1 unidade com estoque suficiente teve criação de compra corretamente bloqueada. Foi regularizada com histórico. Uma necessidade de 20 unidades, com 15 disponíveis no depósito, gerou Compra 17 / ItemCompra 17 de **5 unidades**. A cotação foi criada e selecionada, a compra aprovada e o pedido registrado.

Recebimento parcial de 2 unidades (B3H-OS50-A, validade 01/05/2027): estoque passou para 18 e **nenhuma conta a pagar existia para a compra 17**. Snapshot de leitura preservado antes do recebimento final. Recebimento final de 3 (B3H-OS50-B, validade 01/06/2027): Compra RECEBIDA e conta 42 de 36,65. Necessidade regularizada e atendimento retomado. **Política mantida: parcial aumenta estoque; conta a pagar apenas no recebimento final.**

## Inventário e transferência

Inventário 1: lote 37 tinha uma unidade, contagem de duas; lote 38 tinha 15, contagem de 15. Aprovação gerou ajuste de +1 pelo movimento 61, com usuário, motivo e trilha. Nenhuma edição silenciosa de saldo.

Transferência 1: depósito 20 → trânsito 22 → destino 21. Enviada e recebida pela UI. Grupo, número, validade 09/10/2026 e custo 7,33 preservados nas representações do lote. Trânsito zerado; uma unidade no destino. As duas etapas possuem movimentos e histórico; saldo global não é receita/consumo por transferência.

Após todas as cinco vendas, devolução, inventário, dois consumos técnicos e recebimentos: **19 unidades** no produto/lotes/depósitos, sendo 18 na origem, 1 no destino e 0 em trânsito. Todas as 17 variações de lote reconciliam anterior + movimentação = posterior e custo = quantidade × custo unitário. FEFO entre múltiplos lotes demonstrado na UI; lotes vencidos, insuficiência e concorrência também estão cobertos pela suíte automatizada, sem atribuir a ela cliques que não ocorreram.

## VERTYX Técnico

OS 50: chamado → triagem → técnico → OS → agenda → equipamento por UUID → diagnóstico → atendimento → checklist Sim / medição 2,5 bar → foto sintética → peça oficial → necessidade/compra/recebimentos → retomada → assinatura sintética → finalização → PDF.

OS 51: repetição diretamente em **390×844**, com chamado 9, triagem, agenda do papel TECNICO, fallback de identificação por UUID, formulário técnico, checklist Sim / 2,7 bar, upload pelo navegador, consumo FEFO de uma unidade do lote 38, assinatura desenhada no canvas móvel e finalização. A reposição necessária já foi homologada na OS 50. Não se criou estoque técnico paralelo.

Fotos 14 e 15 vieram de `icon-512.png`, imagem de teste explicitamente descrita como sintética, não de câmera física. Arquivos privados normalizados e hashes SHA-256 conferidos. Assinaturas sintéticas 17/18 e seus hashes conferidos. Localização inicial registrou timeout; final da OS 50, timeout; final da OS 51, permissão negada no navegador. Falhas não impediram continuação controlada e ficaram na auditoria. Nenhuma coordenada real foi obtida/inventada.

PDFs OS-000050-v1 e OS-000051-v1 baixados pelos controles da aplicação, três páginas cada. Todas as seis páginas renderizadas e inspecionadas: dados, checklist, foto, falha de localização, assinatura e hashes legíveis. No PDF da OS 51, a nota final da assinatura ficou isolada na terceira página; débito de paginação, sem perda de dados.

## Ponto

Funcionário sintético Técnico Bloco 3, vinculado à jornada existente. ENTRADA → SAIDA_INTERVALO → RETORNO_INTERVALO → SAIDA registradas pela interface às 15:17, com segundos efetivos do servidor. São quatro eventos de teste em intervalo curto, **não uma jornada real de trabalho nem marcações retroativas**. Marcar ponto não iniciou/finalizou OS.

Espelho outubro/2026 aberto pelo link da página. Solicitação de ajuste da entrada para 15:16, com motivo, foi rejeitada pelo administrador com justificativa. Original, horário e hash preservados; decisão auditada; encadeamento e conteúdo de cada marcação revalidados por SHA-256.

PDF do espelho baixado pela interface: duas páginas A4 paisagem, ambas inspecionadas; Excel com 32 linhas incluindo cabeçalho, nove colunas e 31 dias, contendo as quatro marcas. Outubro ainda aberto: fechamento corretamente bloqueado. Setembro, competência sintética anterior sem marcas reais: fechamento permitido com snapshot/jornada/hash e saldo preservado. Isso não representa presença real nem certificação REP, conformidade legal ou folha.

## Gestor, segurança e indicadores

Papel GESTOR: dashboard → orçamento → venda → estoque → compras → financeiro → assistência → ponto. Oito domínios acessíveis com a permissão existente. Visão final sem filtros: vendas líquidas 49,50; custo documentado 36,65; margem comercial 12,85; recebido 49,00, pago 9,50 e recebível pendente 10,00. Não apresenta margem como DRE completa.

Com filial/centro selecionados, OS, lotes e funcionários aparecem **Sem base**, conforme falta de alocação legada; nenhum número foi inferido. Valores comerciais filtrados seguem as vendas com a alocação efetivamente registrada, não a Unidade do cliente.

Papel PDV: financeiro, espelho do técnico e foto da OS retornaram 403, sem conteúdo privado. Nenhuma permissão foi ampliada. Isolamento entre organizações, IDOR, arquivos, QR, caixa/PDV, estoque, financeiro, ponto, relatórios, pesquisa e capacidades estão cobertos pelos testes PostgreSQL preservados. Não houve teste de invasão/carga externo. Sem erro 500 observado nas jornadas. Os dois logs 503 da suíte são cenários intencionais de indisponibilidade em `platform_core/test_deployment.py`, ambos PASS.

## Responsividade e acessibilidade

Oito telas (PDV, caixa, produto, compra, estoque, dashboard, Técnico e Ponto), em **1440×900 / 768×1024 / 390×844**: 24 capturas finais. Dimensões `innerWidth/innerHeight` confirmadas; `scrollWidth <= clientWidth` em todas as páginas. Tabelas largas mantêm rolagem horizontal no próprio contêiner. Formulário PDV também usado nas três dimensões; finalização F8 em móvel. Menus, botões, labels, foco, formulários, disclosures e mensagens inspecionados. Não houve modal nesses cenários; não se certificam modais não acionados nem conformidade WCAG integral.

Limitação da ferramenta: screenshots mostram a área visível do painel do navegador (altura até 802 pixels), às vezes com exclusão da barra vertical. O viewport DOM tem as dimensões exigidas; não se afirma que o PNG possui o tamanho integral do viewport ou que é captura da página inteira. Índice com dimensões reais e hashes: `tmp/validation/bloco3h/artefatos.json`.

Capturas: `tmp/validation/bloco3h/{pdv,caixa,produto,compra,estoque,dashboard,tecnico,ponto}-{1440x900,768x1024,390x844}.png`. Evidências adicionais: assinatura/finalização OS 51, caixa móvel fechado, comprovante, transferência, compra final e espelho/fechamento de ponto. Viewport temporário restaurado ao concluir inspeções.

## Erros encontrados e correções mínimas

| Erro | Causa / correção | Revalidação |
|---|---|---|
| Limite de crédito ausente no formulário de cliente autorizado | Campo já existia no form/model, faltava renderização no template; exibido somente quando o form permite | Campo visível ao administrador, salvo localmente, crediário finalizado; teste nega campo ao PDV |
| Link/export/campo de ano do ponto usava 2.026 | Localização de número aplicada em parâmetros; filtro unlocalize em ano/mês | Link real, PDF/Excel, bloqueio e fechamento pela UI; teste percorre links e campos |
| Menu móvel sem nome acessível | Botão só continha ícone; aria-label/controls/expanded adicionados | Enter abriu/recolheu menu; teste de nome e alvo |
| Links amarelos de estoque com contraste fraco | Variante outline-warning sobre fundo claro; somente dois links passaram a outline-dark | Texto RGB 33/37/41 conferido, capturas novas; teste mantém rotas/filtro/alerta |

Três testes novos, em `operacao/test_block3_security.py` (dois) e `operacao/test_block3_workforce.py` (um). O teste de acessibilidade cobre os dois últimos ajustes. Sete arquivos de código/template/teste modificados: `operacao/test_block3_security.py, operacao/test_block3_workforce.py, templates/base.html, templates/clientes/cliente_form.html, templates/gestao/lista.html, templates/operacao/ponto.html, templates/operacao/ponto_mirror.html`. Documentos: RELATORIO_BLOCO3.md / VALIDACAO_BLOCO3.json / HOMOLOGACAO_BLOCO3.md. Helpers e evidências locais em `tmp/validation/`, ignorados pelo Git.

Houve timeouts transitórios de captura/upload na ferramenta e necessidade de reiniciar apenas o servidor local com reaproveitamento da mesma base sintética para recarregar templates. A primeira execução parcial da suíte foi interrompida ao detectar os ajustes de acessibilidade; não conta como PASS. Duas execuções completas posteriores passaram; a última após as jornadas, com código inalterado durante o teste, é a referência final.

## Regressão final e preservação

| Comando | Resultado final |
|---|---|
| manage.py check | PASS, nenhum problema |
| manage.py makemigrations --check --dry-run | PASS, nenhuma migration pendente no código |
| manage.py test --noinput --parallel 2, settings PostgreSQL local | **404 PASS**, zero skips, 436.703 s |
| collectstatic --noinput | PASS, 0 copiados / 149 preservados |
| pip check | PASS, No broken requirements found |
| git diff --check | PASS |
| Integridade / sintaxe Python | PASS, hashes finais correspondem aos arquivos testados |
| Reconciliação adicional dos dados da UI | PASS, 39 conferências de leitura |

Logs: `tmp/validation/bloco3_3h_final_{0_check,1_makemigrations,2_test,3_collectstatic}.log`; resultados `bloco3_3h_final_results.json`; integridade `bloco3h_integrity.json`; conciliação `bloco3h/reconciliacao.json`.

O teste de migração legada/preservação passou novamente na suíte completa. Evidência incremental detalhada B2→B3 preservada da etapa anterior: 1.836 linhas sintéticas, colunas/valores/relações anteriores e 14 migrations aditivas PASS (`bloco3_baseline_rehearsal.json` / `bloco3_incremental_preservation.json`). Esses ensaios anteriores não foram refeitos nem apresentados como acesso ao banco publicado. Nesta etapa, as 69 migrations têm os mesmos hashes de início e nenhuma foi criada/editada. Dados novos da UI são acréscimos normais da fixture de homologação.

Migrations do Bloco 3 ainda não aplicadas por este trabalho em produção: clientes0005, contas0008, platform_core0005, gestao0009–0013, operacao0008–0013 (14). Alterações locais anteriores B1/B2 também permanecem; a lista efetiva pendente no serviço publicado deverá ser consultada somente em futura etapa autorizada. Nenhuma nova migration ou dependência em 3H.

## Limitações e recomendações

**RECOMENDAÇÃO DE UX — INDICADOR/BOTÃO DE SINCRONIZAÇÃO DO PDV**: não há indicador permanente claro de online, última atualização/sincronização ou comunicação no PDV atual. Os POSTs e mensagens operacionais existentes foram mantidos. Futuramente a sincronização normal deverá ser automática; botão “Sincronizar / Atualizar dados” pode auxiliar atualização manual e diagnóstico. Nenhum indicador novo, fila offline de vendas ou modo offline empresarial foi implementado nesta homologação.

**PENDENTE DE HOMOLOGAÇÃO EM DISPOSITIVO REAL**: celular físico, touch, câmera/QR, GPS permitido/negado/indisponível no aparelho e Smart TV. **PENDENTE DE HOMOLOGAÇÃO COM LEITOR FÍSICO**. Entrada por teclado, canvas com mouse e viewport móvel não substituem essas provas. Não foram homologados outros navegadores.

Débitos preservados: política segura para devolução de recebível parcelado; KPIs/DRE completos; alocação legada por filial/centro; auditoria integral de todas as combinações de módulos/capacidades sobre agregados antigos; desempenho sob carga real; governança de ponto fechado; revisão de diferenças de caixa; apresentação do comprovante e paginação do PDF. Custos antigos sem documento não foram reescritos. Planos SaaS permanecem metadados, sem billing/enforcement; fiscal informativo. Exclusões de NF-e/NFS-e/NFC-e/A1/TEF/gateway, folha/eSocial, app nativo/offline complexo e demais integrações continuam respeitadas.

## Pendências para publicação e parada

1. Autorização específica para commit/push/deploy da versão revista.
2. Homologação em dispositivos e navegadores reais escolhidos pelo usuário.
3. Revisão dos cadastros reais pelo administrador, incluindo contas/formas, filial/centro, depósitos e jornadas.
4. Em etapa autorizada: identificar novamente serviço/banco existentes, backup, plano incremental de migrations, storage privado R2, Render/Gunicorn/logs e jornadas pós-deploy. Não criar/recriar infraestrutura ou presumir credenciais.

**Nenhum commit, push, deploy, acesso ao PostgreSQL publicado, alteração de Render/R2/secrets ou início do Bloco 4.** Esta entrega encerra a etapa local de 3H; aprovação de produção e encerramento integral do produto permanecem separados. Aguardar autorização do usuário.
