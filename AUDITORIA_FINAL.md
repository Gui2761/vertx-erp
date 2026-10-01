# Auditoria de arquitetura — antes da ampliação final

## Ampliação de estoque — auditoria antes da implementação

Base desta fase: `vertyx_final.zip`, verificada byte a byte com os 249 arquivos
locais antes de alterações. Lidos inventário de 62 modelos/378 rotas, validação
de 165 testes e código dos modelos, serviços, views, forms e comandos de estoque.

Peca tem lote/validade globais legados; Movimentacao é histórico imutável e
atualiza Peca.quantidade_atual e SaldoDeposito dentro da mesma transação.
Deposito é cadastro tenant. Compra/ItemCompra/CotacaoCompra já cobrem solicitação,
cotação, aprovação, pedido, recebimento e pagável; recebimento atualmente não
individualiza lotes. Notificacao tem leitura por destinatário/chave, mas o scan
de estoque usa a data na chave e não acompanha resolução operacional.
`atualizar_alertas` exige organização/ERP/admin ativos e só executa manualmente.

Reutilizar esses fluxos e acrescentar detalhamento por lote e reservas, nunca um
segundo saldo agregado. Preservar os campos globais como históricos, retirando-os
do cadastro novo. Migrar o saldo legado para lotes identificados como legado,
sem movimentos físicos fictícios ou alteração de registros históricos.
Saídas/OS/vendas usarão FEFO válido; devoluções preservarão o lote de origem.
Ocorrências abertas/resolvidas terão histórico separado da leitura da notificação.
Relatórios semanais terão snapshots imutáveis e gerarão Compra/ItemCompra atuais.

Automação: comando independente com estado persistente e lock por organização,
modo contínuo local/Compose e modo de execução única para scheduler externo.
Render Cron é serviço com cobrança própria (https://render.com/docs/cronjobs),
não disponível como cron gratuito. Preparar instruções, sem modificar o Web
Service free, provisionar recursos, acessar produção ou presumir credenciais.
Somente migrations aditivas, testes de isolamento e regressão integral.

01/10/2026. Fonte local: tecnolmed_erp, entrega vertyx_modulos.zip.
Não foi acessado nem alterado o ambiente publicado.

Apps analisadas: contas (identidade/técnicos), platform_core (organizações,
memberships, catálogo/grants, isolamento e arquivos), clientes (cliente,
contatos/unidades), equipamentos (ficha/QR), ordens (atendimento, GPS, foto,
conferência, assinatura, histórico/PDF), core (painel) e gestao (estoque,
orçamento, contrato/agenda, financeiro e 18 relatórios).

Models, forms, views/URLs, templates, decorators/mixins, migrations e testes
existentes foram inventariados. Base anterior: 136 testes, incluindo bloqueios
PostgreSQL e privacidade S3. Cada mudança preservará migrations antigas e será
verificada contra o ZIP de referência pelo empacotador existente.

## Reutilizar

- OrganizationOwned/TenantOwned, TenantManager e TenantModelForm: escopo SQL
  por organização, validação de FKs e proibição de transferência entre tenants.
- OrganizationMiddleware, require_erp e perfis_requeridos: usuário/empresa/
  membership ativos e ERP habilitado nos dois níveis.
- ordens.services: linha bloqueada, revisão/ciclo, GPS, snapshots assinados,
  auditoria e reabertura. Snapshots antigos não serão reescritos.
- gestao.services: estoque sem negativo, idempotência, conversão de orçamento,
  cobrança por origem, agenda contratual, liquidação/cancelamento auditados.
- Storage privado atual: S3/R2 por ambiente; streaming autorizado, sem .path.
- Bootstrap local: componentes básicos presentes; CSS atual é pequeno e
  carece de tokens, navegação modular, breadcrumbs e dashboard gráfico.

## Lacunas

Cadastros: inscrições/responsável do cliente; e-mail/observações da unidade;
aquisição/localização/criticidade do equipamento; central de anexos privados.
OS: três estados, quatro tipos, sem agenda/prioridade/contrato/checklist/horas.
Preventivas: agenda contratual mensal, sem plano/checklist/intervalos curtos.
Planejamento: lista, sem calendário dia/semana/mês.
Estoque: saldo único por peça, sem depósitos/transferência/máximo/categoria.
Financeiro: liquidação integral, sem parcelas/contas bancárias/movimentos/
conciliação. Compras/vendas/chamados/portal/fiscal/notificações/configuração:
não implementados. Relatórios: PDF/CSV, sem XLSX/produtividade/comercial.

## Segurança a ampliar

Portal reutilizará a identidade e os grants existentes, com papel CLIENTE e
vínculo explícito ao cliente; consultas deverão restringir também o cliente,
não somente a organização. Rotas internas não poderão aceitar esse papel.
Novos documentos, movimentos e auditorias terão organização e autorização
antes do acesso ao storage. Escritas exigirão POST/CSRF e transação.

## Infraestrutura

Dockerfile coleta estáticos no build; scripts/start.sh aplica migrations
versionadas com advisory lock antes do Gunicorn. settings.py lê segredos do
ambiente; PRIVATE_STORAGE é preservado. Nenhuma credencial será criada/trocada.
render.yaml ainda declara databases e fromDatabase para um novo PostgreSQL;
o pedido atual exige retirar esse provisionamento e usar DATABASE_URL existente.
Segundo https://render.com/docs/blueprint-spec, sync:false preserva valores em
updates e pede preenchimento apenas na criação inicial. Somente o YAML local
será ajustado; não haverá sincronização/deploy no Render.

## Etapas de implementação/validação

1. Design system e cadastros completos, mantendo ações/URLs anteriores.
2. OS/mobile/checklist/chamados, planos preventivos e calendário integrados.
3. Depósitos/transferência, compras/recebimento e vendas/estoque/contas.
4. Parcelas/caixa/bancos/conciliação, fiscal substituível, documentos/portal.
5. Configuração, notificações internas/outbox sem envio, dashboard/relatórios.
6. Migrations/check/suítes SQLite e PostgreSQL, storage/HTTP/mobile/PDF, pacote
   sem dados de teste/credenciais e relatório de homologação externa pendente.


## Resultado da ampliação de estoque e Gestão — 01/10/2026

Reutilizados Peca, Movimentacao, Deposito, SaldoDeposito, Compra, ItemCompra,
CotacaoCompra, Notificacao e auditoria/contexto tenant atuais. Seis modelos
complementares detalham lotes, movimentos por lote, reservas, ocorrências e
snapshots de relatório. Nenhum saldo agregado, compra ou backend paralelo.
Campos globais antigos de lote/validade preservados como históricos.

Migrations aditivas gestao.0005/operacao.0002/0003/0004. Ensaio PostgreSQL
do detalhamento verificou 65 tabelas preexistentes/718 registros: todas as
colunas anteriores idênticas. A constraint adicional foi aplicada verificando
71 tabelas/756 registros, igualmente preservados. Nenhum reset/apagamento
ou edição de migration anterior. Hashes ficam no manifest desta entrega.

FEFO válido integrado às movimentações atuais; saídas protegem reservas, consumo
da própria OS/venda não duplica baixa, transferências/devoluções mantêm identidade
e validade. Descarte de vencidos exige lote explícito/movimento auditado.
Ocorrências reutilizam identificação aberta e resolvem automaticamente; leitura
de notificação é independente. Novos ciclos preservam os anteriores.

Relatórios com histórico imutável, tela/PDF/Excel e seleção editável geram Compra
e ItemCompra atuais. Quantidade disponível, validade, reservas, consumo e compras
pendentes influenciam recomendações; excesso exige justificativa. UUID protege
duplo envio. Metadados do recebimento não alteram condições econômicas aprovadas.

Runner processar_estoque, scheduler transacional e serviço estoque_runner no
Compose: padrão 30 minutos, semana configurável, estado durável e lock por empresa.
Não depende do Gunicorn nem de visitas. Código/instruções Render preparados;
Cron externo não ativado. render.yaml mantém Web Free, banco/storage existentes
e seus segredos. Cron Render tem cobrança própria, conforme documentação oficial.

Painel ADMIN/GESTOR com filtros, financeiro realizado, bancos, agenda, operações,
estoque, contratos e comercial usando dados reais; menu agrupado/recolhível com
ícones SVG locais próprios. Técnico mantém operação e limites financeiros.
Faturamento gerencial/classificação dependem das origens existentes; datas de
reajuste ausentes são informadas como não cadastradas. Sem dados fictícios.

Validação: suíte integral de 208 testes PostgreSQL (165 anteriores + 43 novos);
SQLite 197 aprovados/11 exclusivos PG ignorados. Três novos ensaios de concorrência
cobrem FEFO, reservas e runners simultâneos. Django check sem problemas,
makemigrations check/dry-run sem mudanças, migration plan sem pendências,
collectstatic concluído. Check de deploy preserva W005/W021 de HSTS existentes.

Chromium HTTPS local: 27 telas anteriores e 17 telas novas em 320/390/768/1365 px.
Fluxo lotes -> FEFO -> reserva -> relatório PDF/Excel -> seleção -> cotação ->
pedido -> recebimento -> conta a pagar; resolução e histórico conferidos.
Menu recolhido, permissões e ausência de erro JavaScript verificados. Tabelas
rolam dentro do contêiner no mobile. PDF/Excel finais inspecionados, com 15 campos,
colunas numéricas e proteção contra fórmulas em texto. Atendimento original,
GPS simulado/negado, foto/assinatura/PDF repetidos em duas empresas com Moto S3
privado; oito tentativas cruzadas retornaram 404. Teste de browser passou a
aguardar a foto carregar antes de conferir contagem, preservando a asserção.

Não houve deploy/commit/push/acesso a produção/alteração de credenciais.
Configurações sintéticas, banco, mídia, logs e cookies ficam em tmp e excluídos
do pacote. A ativação externa está em AUTOMACAO_ESTOQUE.md; resultados estruturados
em VALIDACAO_FINAL.json, inventário de 68 modelos/387 rotas em INVENTARIO_FINAL.md.
ENTREGA_FINAL.md e demais documentos anteriores permanecem como histórico.


## Fase central de operações / TV — 01/10/2026

Antes da implementação foram relidos esta auditoria, INVENTARIO_FINAL.md,
VALIDACAO_FINAL.json e models/services/views/comandos atuais. O pacote imediatamente
anterior vertyx_estoque_gestao.zip foi conferido: 281 arquivos idênticos ao source,
CRC válido, migrations originais intactas e Render preservado. SHA256 da referência:
3a8249c4be2cfa82c86f801c9d6fb7393ae05b9ce43682a5e19bddf322160a52.

Limitações encontradas: planejamento simples, OS exigindo técnico, ausência de
término previsto e ausência de permissão/tela de projetor. A implementação amplia
operacao/planning.py e integra os mesmos registros, sem nova tabela de atividades.
Detalhes completos estão em CENTRAL_OPERACOES.md. Fluxos anteriores de estoque,
compras, financeiro, documentos e portal permanecem nos mesmos serviços.

Incluídos: calendário/lista/linha do tempo; fila recolhível; filtros/busca; detalhe
lateral; criação rápida; agendamento/atribuição/prioridade auditados; sobreposição
com autorização justificada por ADMIN/GESTOR; revisão/lock; carga técnica; origens
de preventivas/contratos sem duplicação; reservas/disponibilidade/compras da OS;
agenda móvel própria; dashboard com horários/clientes/unidades/técnicos/status.

TV tem tela própria, temas claro/escuro, Fullscreen API, blocos configuráveis,
paginação automática, relógio e polling autenticado 15/30/60s. Acesso novo exige
grant específico desabilitado por padrão; papel PAINEL restringe os demais módulos.
PLANEJADOR/ATENDIMENTO acessam apenas a central operacional, sem conceder financeiro,
estoque, administração ou edição completa de OS. Técnico mantém escopo próprio;
grant de TV explícito permite leitura operacional da organização, conforme aviso
no formulário de usuários. A revogação é aplicada em cada consulta.

Privacidade: DTO de TV não usa snapshot de documentos nem transmite textos livres,
documentos, CPF/CNPJ, contatos, endereço ou valores/custos. DOM dinâmico usa
textContent. Respostas privadas não são cacheadas. Não há URL pública de TV,
localização contínua, ponto/RH, estado de deslocamento ou duração presumida.

Quatro migrations novas (contas.0006, platform_core.0004, ordens.0009,
operacao.0005). São extensões compatíveis: novos campos/preferences/grant/choices
e relaxamento da restrição NOT NULL da FK técnico existente para a fila sem
responsável. No PostgreSQL não recriam tabelas; preservam FK/PROTECT e todos os
valores prévios. O upgrade local conferiu 71 tabelas e 1.098 linhas anteriores,
comparando todas as colunas anteriores antes/depois. Migrations anteriores são
conferidas byte a byte pelo manifest; nenhum arquivo anterior foi removido.

Suíte final: 258/258 aprovados em PostgreSQL 16.15, incluindo todos os 208 anteriores
e 50 novos. SQLite: 246 aprovados, 12 ignorados por exigirem locks PostgreSQL.
Checks, makemigrations --check --dry-run e migrate --plan aprovados. Check --deploy
com DEBUG=False mantém apenas os dois avisos anteriores sobre HSTS subdomínios e
preload, que dependem da configuração do domínio real.

Navegador Chromium em HTTPS local/Moto S3: central, fila, criação sem técnico/data,
conflito/autorização, detalhe, peças, início GPS negado registrado, conclusão pelo
serviço existente, polling/aviso de falha, permissões e temas. Responsividade em
320/390/768/1365 e TV 1920×1080; sem overflow horizontal/erro JavaScript/HTTP 500.
Fluxos anteriores repetidos: 27 telas de módulos, 17 telas de estoque/compras,
GPS simulado/negado/foto/conferência/assinatura/PDF em duas organizações, hashes
foto/assinatura/snapshot e oito acessos cruzados retornando 404.

Arquivos modificados/criados e hashes em AUDITORIA_OPERACOES_ARQUIVOS.json; 68
modelos concretos e 393 rotas em INVENTARIO_FINAL.md. VALIDACAO_FINAL.json guarda
resultados desta fase e o relatório anterior como histórico. Não houve deploy,
commit/push, alteração de credenciais, banco de produção ou mudança de Render,
Compose/storage/runner. Limites de duração, geradores legados, volume, aparelhos
físicos e ativação externa de estoque estão documentados, sem declarar produção
homologada por esta bancada local.
