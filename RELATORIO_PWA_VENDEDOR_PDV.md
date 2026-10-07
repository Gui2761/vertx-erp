# Central PWA do Vendedor e PDV VERTYX — homologação local

Data: 06/10/2026. Working tree na branch `main`, base `d82d6e1ba9782fe847b23c2beb64b665582e61d8`.

A tela visual está pronta para avaliação local. A referência `foto pdv.pdf` foi usada somente para composição de caixa; marca e textos próprios VERTYX. Os fluxos já existentes de venda, caixa, estoque e financeiro foram reutilizados. A última orientação de entregar primeiro a prévia visual foi respeitada: nenhuma publicação e nenhuma integração externa nova.

## Implementado

- Login compartilhado identifica a membership ativa VENDEDOR/PDV e abre `/vendedor/`. Múltiplas organizações exigem seleção. ADMIN/GESTOR mantêm ERP; TÉCNICO mantém sua operação.
- Home com vendas próprias do dia/mês, ticket líquido de devoluções, meta mensal configurável por gestor, progresso, valor restante e ritmo diário calculado sobre dias corridos restantes. Nenhuma meta comercial padrão foi inventada.
- Minhas vendas por hoje, ontem ou período; consulta de pagamentos e comprovantes próprios. Comissão apresenta `A definir`: não calcula remuneração sem regras aprovadas.
- Menu exclusivo e restrição de rotas/capabilities no backend. Troca de organização recalcula a experiência. IDs de vendas, clientes, metas, notificações e documentos respeitam tenant e vendedor.
- PDV desktop com VERTYX | PDV, venda, vendedor autenticado, estado do caixa, busca à esquerda, consumidor/resumo à direita, total destacado e barra F1–F11.
- Mobile com layout em coluna, controles grandes, total/finalização persistentes e navegação PDV | Vendas | Meta | Ponto | Alertas.
- Busca por nome, SKU, código de barras e referência; inclusão por código exato/leitor; câmera usa BarcodeDetector quando disponível e adiciona pelo serviço oficial. Nenhuma imagem é enviada.
- Carrinho usa add/edit/remove existentes, quantidades, preços, subtotais e desconto combinado de itens + venda.
- Autorização de desconto: solicitação idempotente, decisão ADMIN/GESTOR com justificativa, auditoria e notificação. A aprovação está vinculada ao carrinho e é invalidada por alteração relevante. Limite vem da ConfiguracaoPDV existente.
- Cliente opcional ou seleção/cadastro limitado no model Cliente existente, sem gestão de limite de crédito pelo vendedor.
- Fechamento em janela própria; até três meios apresentados na interface, reaproveitando backend de pagamentos múltiplos existente. Dinheiro/troco, PIX informado, débito/crédito e formas cadastradas. Confirmação mantém UUID/idempotência, FEFO, reservas, estoque e financeiro oficiais.
- Caixa próprio: abertura, resumo por forma de pagamento, saldo esperado e conferência/fechamento pelo serviço existente. Retirada/suprimento continuam exigindo responsável autorizado.
- Meu Ponto, jornada do funcionário e hora extra reaproveitados, sem alterações em seus serviços/models.
- Alertas próprios e mensagens internas do gestor usam Notificacao existente. Sem SMS, e-mail, push externo ou comissão inventada.
- Mesmo manifest/worker PWA. Páginas privadas usam no-store; não foi criada venda offline nem armazenamento privado em cache. Assets alterados possuem versão na URL para evitar CSS/JS antigo.

## Limites e pendências explícitos

- F4 identifica o vendedor autenticado; não permite trocar para outro vendedor. F10/F11 informam a exigência de responsável; não relaxam a autorização existente.
- F5 abre entrada por código exato, complementar à busca existente. Não foi desenvolvido novo mecanismo de filtros avançados.
- F6 importação permanece desabilitada, `A definir`.
- Comissão tem apenas base de configuração; percentual, regras, fechamento e pagamentos dependem de definição comercial.
- Venda a prazo reaproveita recebível/limite de crédito existentes; novo assistente de parcelamento no PDV não foi implementado nesta entrega visual.
- Não há confirmação automática de PIX, adquirente, pagamento real ou emissão fiscal. Comprovante é não fiscal e preserva o template atual.
- Câmera física e instalação/abertura no iPhone do PWA Vendedor ainda precisam de homologação real. O navegador local não oferece BarcodeDetector; a entrada manual foi validada. Não afirmar câmera validada pelo teste de SKU.
- Offline é informativo e não confirma vendas. Sincronização transacional offline não foi criada.
- Referência e layout foram inspecionados no navegador desktop emulado; não substituem validação de impressão/câmera/periféricos de uma loja real.

## Migrations e preservação

Uma migration aditiva: `operacao/migrations/0017_seller_central.py`, dependente de 0016, cria somente MetaVendedor e SolicitacaoDescontoPDV. Não modifica migrations antigas, não cria estoque/venda/pagamento paralelo, não apaga campos ou registros. Aplicada exclusivamente aos bancos sintéticos locais de teste e prévia. Ainda não aplicada em produção.

Teste PostgreSQL de migration compara registros/identidades/valores de organizações, memberships, usuários, clientes, OS, estoque, vendas, financeiro, documentos e RH antes/depois da migration e confirma as duas novas tabelas. Retorno temporário a 0016 ocorre somente dentro do banco descartável deste teste, nunca na base do projeto ou em produção. Resultado: aprovado.

## Validações

- Suite completa PostgreSQL: **605/605 aprovados**, zero falhas/erros, 1051,291 segundos. Log em tmp/validation/seller_full_final.log e resultado do runner em tmp/validation/seller_full_final_result.json.
- 52 testes novos no módulo `operacao.test_seller_pwa`, incluindo concorrência e preservação de schema.
- Após o último ajuste de apresentação, três testes dirigidos de menu/HTML do console/resumo e bloqueio financeiro passaram novamente (3/3). Não somar essa repetição ao total de 605 testes da suite.
- Rodada dirigida de 64 testes identificou ausência de enviado_por no fixture de documento; fixture corrigido e teste isolado aprovado. Não foi afrouxada a restrição de documentos.
- A primeira suite sobre banco de testes reutilizado encontrou expectativas antigas de redirecionamento, um hash de Decimal `0` versus `0.00`, e ausência do seed inicial após flush executado pelo próprio TransactionTestCase. Corrigidas expectativas, hash canônico e fixture. A suite final utiliza um banco sintético novo, criado pelo runner, para validar migrations/seed completos; a base local principal foi preservada.
- `manage.py check`: aprovado, zero problemas.
- `manage.py makemigrations --check --dry-run`: aprovado, nenhuma alteração pendente de model.
- `node --check`: aprovado para seller-pdv.js, vertyx.js e pdv.js.
- `git diff --check`: aprovado; avisos de conversão LF/CRLF não são erros de whitespace.

VALIDADO AUTOMATICAMENTE: permissões, tenant/vendedor, redirecionamento, carrinho/Decimal/desconto/aprovação, cliente, meios de pagamento, troco, idempotência, FEFO/reservas/financeiro, metas, ponto/hora extra, notificações, preservação ADMIN/GESTOR/TÉCNICO e manifest/cache.

VALIDADO PELA INTERFACE EM BANCO SINTÉTICO: login do vendedor, Home, busca, quantidade +/−, solicitação de desconto e aprovação pelo gestor, venda dinheiro + PIX com troco, comprovante, inclusão direta por SKU, novo fechamento mobile, F8 abrindo pagamento, resumo do caixa próprio.

Jornada de referência: venda de R$ 79,80, desconto autorizado R$ 10,00, total R$ 69,80; dinheiro R$ 20,00 recebido R$ 25,00 + PIX R$ 49,80, troco R$ 5,00. Após reorganização visual: inclusão por SKU VT-300, total R$ 99,70; dinheiro R$ 20,00 recebido R$ 25,00 + PIX R$ 79,70; venda finalizada e comprovante conferido. Todos os valores e cadastros são sintéticos.

Responsividade: Home/PDV em viewports 320×740, 390×844, 768×1024 e 1365×768 sem overflow horizontal; controles principais mobile >=48px. Barra inferior do PDV desktop termina dentro do viewport. JPEGs do navegador representam a área de conteúdo, excluindo barras de rolagem/moldura, e podem ter dimensões físicas menores que o viewport configurado.

NÃO VALIDADO EM PRODUÇÃO: esta versão inteira, migration 0017, câmera física, impressão/periféricos e PWA Vendedor instalado no iPhone.

## Evidências visuais

Arquivos em `evidencias/pwa_vendedor/`: home_1365x768.jpg, home_390x844.jpg, pdv_1365x768.jpg, pdv_390x844.jpg, pdv_320x740.jpg, carrinho_390x844.jpg, fechamento_1365x768.jpg, fechamento_390x844.jpg, resumo_caixa_390x844.jpg, comprovante_390x844.jpg e layout_metrics.json.

Prévia sintética: `http://127.0.0.1:8883/vendedor/` e `http://127.0.0.1:8883/pdv/`. Nenhuma credencial real registrada nas evidências.

## Arquivos da implementação

Modificados: clientes/views.py; commercial/tests.py; contas/views.py; operacao/commerce.py; operacao/models.py; operacao/navigation.py; operacao/pdv.py; operacao/permissions.py; operacao/urls.py; operacao/test_block3_integration.py; operacao/test_employee_central.py; operacao/test_overtime.py; operacao/test_technician_pwa.py; platform_core/middleware.py; platform_core/modules.py; platform_core/views.py; static/js/vertyx.js; static/pdv.js; templates/base.html; templates/platform_core/home.html.

Novos: operacao/seller.py; operacao/seller_access.py; operacao/seller_models.py; operacao/seller_services.py; operacao/test_seller_pwa.py; operacao/migrations/0017_seller_central.py; static/css/seller.css; static/js/seller-pdv.js; templates/operacao/seller_home.html; seller_terminal.html; seller_pdv.html; seller_cart.html; seller_checkout.html; seller_customer_select.html; seller_discount.html; seller_sales.html; seller_goal.html; seller_commission.html; seller_alerts.html; seller_customer.html; seller_management.html; este relatório; VALIDACAO_PWA_VENDEDOR_PDV.json; evidências visuais.

Arquivos privados de execução/fixtures ficam em tmp, ignorados pelo Git. Dependências, render.yaml, configurações fiscais, R2, credenciais e variáveis de produção não foram alterados. Não houve commit, push, deploy, migration/acesso a produção ou alteração de usuário/membership real.

Status: aguardando homologação visual do usuário. Nenhuma publicação autorizada nesta etapa.
