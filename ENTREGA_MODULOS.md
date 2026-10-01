# VERTYX Assistência — entrega dos módulos de gestão

30/09/2026. Alterações feitas diretamente em tecnolmed_erp, sobre o código
local do pacote vertyx_homologacao.zip. Nenhum commit, push, deploy, recurso
externo ou alteração no banco publicado foi executado.

## Auditoria e causa

Auditoria realizada antes da implementação, registrada em AUDITORIA_MODULOS.md:
os cinco módulos eram marcadores de etapas futuras no menu, com disabled e
href="#". Não existiam models, migrations, formulários, views, URLs ou templates
funcionais correspondentes. Não havia feature flag bloqueando implementações
existentes. O campo textual OrdemServico.pecas e o PDF de OS foram reaproveitados
e preservados; o texto livre continua sem movimentar estoque por conta própria.

Nesta cópia, Planejamento também era marcador da Etapa 4, sem URL/view. Isso
diverge da informação de que o Planejamento funciona em produção. Foi pedida
confirmação da fonte e ainda não recebida. O trabalho usa esta cópia local:
incluiu uma agenda real e ligou o marcador a ela. Nenhum endpoint de planejamento
funcional existente nesta fonte foi substituído. Antes de publicar, compare
com o código efetivamente no Render; se houver uma implementação adicional de
Planejamento em produção, preserve-a e incorpore a agenda de contratos nela.

## Implementação persistida

Uma única app Django gestao reutiliza autenticação, OrganizationOwned,
TenantManager, contexto de organização, OrganizationMembership, MembershipERP,
OrganizationERP, require_erp e PlatformAudit. Não cria organizações/autenticação
paralelas nem outro ERP no catálogo. Todas as novas tabelas empresariais possuem
Organization, filtros SQL por organização e validação de relacionamentos.

| Área | Models novos | Comportamento |
|---|---|---|
| Estoque | Fornecedor, Peca, Movimentacao | Cadastro completo, saldo decimal, entrada/saída/ajuste/devolução/uso em OS, mínimo, usuário/data/organização e justificativa |
| Orçamentos | Orcamento, ItemOrcamento | Número automático, validade, cliente/unidade/equipamento/OS, serviços/peças, quantidades, valores/descontos, condições, estados, PDF e conversão |
| Contratos | Contrato, ContratoUnidade, ContratoEquipamento, AgendaPreventiva | Cobertura, vigência, valor por cobrança, periodicidade, visitas/SLA, alertas e geração de agenda/OS |
| Financeiro | CategoriaFinanceira, CentroCusto, FormaPagamento, Lancamento, EventoFinanceiro | Contas a pagar/receber, categorias/centros/formas, origem automática, liquidação/cancelamento e histórico |

São 14 models concretos novos. OrdemServico recebeu valor_cobranca (padrão 0)
e vencimento_cobranca (opcional); os registros anteriores ficam sem cobrança
automática. Usuario.perfil recebeu a opção CONTABILIDADE para cadastro pelo
administrador; autorização continua dependente do papel do membership.

### Regras operacionais

- Peças começam com saldo zero. Use entrada para saldo inicial; ajuste registra
  o novo saldo absoluto e exige motivo. Saída/uso não permitem saldo negativo.
  Uso de peça vencida é bloqueado. Devolução vinculada à OS não excede o uso
  líquido registrado nela. Históricos são imutáveis; custos/preços da peça no
  momento da movimentação ficam registrados.
- Movimentar peça vinculada à OS bloqueia a linha da OS e da peça, incrementa
  revisão e invalida uma conferência anterior. OS finalizada exige reabertura
  pelo fluxo existente. Seu PDF incorpora as movimentações ao snapshot; PDFs
  assinados anteriores usam seus snapshots preservados.
- Orçamentos: rascunho → enviado → aprovado/recusado; enviado pode voltar a
  rascunho. Vencimento é calculado pela data, sem escrita em GET. Enviar/aprovar
  exige itens, total positivo e validade vigente. Valores usam Decimal e
  arredondamento para centavos. O desconto global é validado antes do envio.
- Converter orçamento aprovado exige equipamento/técnico da organização.
  Copia diagnóstico, serviços e peças; reutiliza OS vinculada não finalizada
  ou cria uma OS. Repetir retorna a mesma OS. Itens previstos não baixam estoque;
  registre o uso real pela ação de estoque da OS.
- Contratos geram agenda por equipamento coberto e periodicidade em meses,
  a partir do início, limitada pela vigência/quantidade de visitas. Visita
  abrange os equipamentos selecionados. 0 visitas significa todas as
  ocorrências do período. Selecionar nenhuma unidade significa cobertura de
  todas as unidades do cliente; equipamentos precisam ser selecionados.
- Encerrar/suspender o contrato preserva como concluídas as preventivas já
  realizadas; ocorrências restantes ficam canceladas na agenda.
- Cobranças de contrato são geradas para toda a vigência, com valor por
  ocorrência, vencimento/competência ancorados no início. Repetir geração não
  duplica. Suspender/encerrar bloqueia novas gerações; contas já criadas são
  preservadas e devem ser canceladas individualmente, com motivo, se necessário.
- Condições contratuais já cobradas são preservadas. Renove em outro contrato
  para mudar cliente, valor, vigência ou periodicidade financeira. Preventivas
  geradas não são apagadas nem reagendadas automaticamente ao editar periodicidade.
- A agenda cria uma OS PREVENTIVA por ocorrência/técnico. Finalizar uma
  preventiva atualiza a última preventiva do equipamento quando a data é mais
  recente. Planejamento também consulta as datas já cadastradas nos equipamentos.
- OS com valor positivo gera conta a receber na finalização. Orçamento pode
  gerar conta ao aprovar, por opção explícita. Bloqueios/constraints impedem
  duplicar a cobrança da mesma OS/orçamento/competência, inclusive na disputa
  entre aprovação de orçamento e finalização da OS.
- Liquidação integral registra pagamento/recebimento e evento imutável. Somente
  conta pendente pode ser cancelada, com justificativa. Conta liquidada não
  pode ser alterada/cancelada. Classificação, forma de pagamento e observações
  das contas automáticas pendentes podem ser editadas sem mudar condições.
- Dashboard financeiro: pendentes/vencidas consideram todas as contas abertas;
  recebido/pago/resultado de caixa usam datas de liquidação do período. Fluxo
  mensal separa previsto pelo vencimento e realizado pela liquidação.

Não há emissão fiscal, pagamentos parciais, estorno, conciliação bancária ou
envio de orçamento ao cliente por e-mail. Origens estáveis do lançamento,
valores decimais, organização, serviços transacionais e eventos/auditoria
permitem que futura integração NF-e/NFS-e referencie esses registros, sem
misturar emissão fiscal com liquidação. Nenhum provedor fiscal foi configurado.

## Rotas adicionadas

Rotas anteriores permanecem. Todos os caminhos abaixo usam sessão/autorização
existentes; operações de escrita exigem POST/CSRF.

| Caminho | Função |
|---|---|
| /estoque/, /estoque/novo/, /estoque/&lt;id&gt;/, /estoque/&lt;id&gt;/editar/ | Peças |
| /estoque/fornecedores/ e respectivos novo/detalhe/editar | Fornecedores |
| /estoque/movimentar/ | Movimentação, incluindo uso/devolução da OS |
| /orcamentos/ e respectivos novo/detalhe/editar | Orçamentos |
| /orcamentos/&lt;id&gt;/itens/novo/ | Item |
| /orcamentos/&lt;id&gt;/itens/&lt;item&gt;/editar/ ou remover/ | Edição/remoção de item de rascunho |
| /orcamentos/&lt;id&gt;/status/&lt;ação&gt;/ | Transição de estado |
| /orcamentos/&lt;id&gt;/converter/ ou pdf/ | Conversão / PDF |
| /contratos/ e respectivos novo/detalhe/editar | Contratos |
| /contratos/&lt;id&gt;/gerar/planejamento/ ou cobrancas/ | Geração idempotente |
| /contratos/planejamento/ | Agenda e consulta às preventivas dos equipamentos |
| /contratos/planejamento/&lt;id&gt;/gerar-os/ | Criar OS preventiva |
| /financeiro/ | Dashboard e fluxo mensal |
| /financeiro/lancamentos/ e respectivos novo/detalhe/editar | Contas |
| /financeiro/lancamentos/&lt;id&gt;/operacao/liquidar/ ou cancelar/ | Operação financeira |
| /financeiro/categorias/, /financeiro/centros-custo/, /financeiro/formas-pagamento/ e respectivos novo/detalhe/editar | Cadastros financeiros |
| /relatorios/ | Central autorizada por perfil |
| /relatorios/&lt;chave&gt;/ | Filtros, resultados, export=csv / export=pdf |

18 chaves: os_periodo, os_status, os_tecnico, os_cliente,
equipamentos_cliente, equipamentos_situacao, equipamentos_restricao,
equipamentos_inoperantes, preventivas_realizadas, preventivas_pendentes,
preventivas_proximas, pecas_utilizadas, movimentacao_estoque, estoque_minimo,
contratos_ativos, contratos_proximos, receitas, despesas.

Filtros: período, cliente, unidade, técnico, estado e equipamento quando
aplicáveis. Financeiro considera OS, orçamento e cobertura/agenda de contrato
nos filtros de relacionamento. CSV UTF-8 com BOM, separador ponto e vírgula e
neutralização de fórmulas; PDF paginado. Exportações exigem a mesma autorização
da consulta. Limites: CSV 10.000 linhas, PDF 1.000; reduza filtros para mais dados.
Imprimir página imprime a página corrente; PDF exporta os resultados filtrados.
Período: abertura para OS, conclusão para preventivas realizadas, cadastro para
equipamentos, data prevista para agenda, movimentação para estoque, data final
para contratos e emissão para receitas/despesas. No dashboard financeiro,
recebido/pago usam a data de liquidação. Saldo mínimo é a situação atual.

## Permissões dos novos módulos

| Papel do membership | Estoque | Orçamentos/Contratos | Planejamento | Financeiro | Relatórios |
|---|---|---|---|---|---|
| ADMIN | Gestão | Gestão | Gestão | Gestão | Todos da própria empresa |
| GESTOR | Gestão | Gestão | Gestão | Gestão | Todos da própria empresa |
| TECNICO | Consulta e uso/devolução em suas OS | Sem acesso | Consulta das OS atribuídas e datas dos equipamentos | Sem acesso | Operacionais e suas peças utilizadas |
| ESTOQUE | Gestão | Sem acesso | Sem acesso | Sem acesso | Estoque |
| FINANCEIRO | Sem acesso | Sem acesso | Sem acesso | Gestão | Financeiros |
| CONTABILIDADE | Sem acesso | Sem acesso | Sem acesso | Leitura | Financeiros, CSV/PDF |

Menu usa permissões reais; links habilitados apenas para usuários autorizados.
Backend repete verificação em cada consulta/POST. Trocar ID/relacionamento para
outra organização resulta em 404 ou erro de seleção, sem expor dados. Usuário,
empresa, membership, catálogo, OrganizationERP e MembershipERP precisam estar
ativos/habilitados. Superuser exige vínculo explícito para o ERP. O CRUD
de organização/usuários existente e os demais módulos mantêm suas permissões.

## Migrations incrementais

1. contas/0004_alter_usuario_perfil.py: acrescenta escolha Contabilidade.
2. ordens/0007_ordemservico_valor_cobranca_and_more.py: campos opcionais de cobrança.
3. gestao/0001_initial.py: 14 tabelas, FKs de proteção e constraints de valores,
   datas, saldo e unicidade de movimentação/origem/competência/agenda.

Nenhuma migration anterior modificada; nenhuma tabela/dado anterior removido.
O manifesto AUDITORIA_MODULOS_ARQUIVOS.json compara arquivos e SHA-256 das
migrations antigas com vertyx_homologacao.zip. Banco de teste PostgreSQL já
existente recebeu as três migrations com migrate_locked e preservou os registros
locais anteriores. Migrações novas foram exercitadas em bases temporárias pelos
testes. Não foi ensaiado o volume do banco real de produção.

## Verificação

- Python 3.12.14, Django 5.0.9, PostgreSQL 16.15.
- manage.py check: sem problemas.
- makemigrations --check --dry-run: nenhuma alteração pendente.
- migrate --plan após upgrade local: nenhuma operação pendente.
- pip check: dependências íntegras; requirements não modificados.
- Suíte completa PostgreSQL: 136 testes aprovados (89 anteriores + 47 novos).
- Suíte SQLite: 136 encontrados; 130 aprovados, seis ignorados por exigirem
  bloqueio/advisory lock real do PostgreSQL.
- Novos testes: CRUD, model/forms, roles, grants revogados, IDOR/FKs,
  estoque/OS/snapshot, orçamento/conversão/PDF, contrato/agenda/cobranças,
  liquidação/cancelamento/classificação, dashboard, filtros/CSV/PDF e paginação.
- Concorrência PostgreSQL: duas saídas não criam saldo negativo, duas conversões
  criam uma OS, duas liquidações criam um evento e aprovação/finalização
  simultâneas não duplicam cobrança.
- Chromium real contra HTTPS local, DEBUG=False, PostgreSQL e S3 simulado:
  criação de peça, entrada 10, orçamento com serviços/peças e PDF, conversão,
  uso de duas peças (saldo 8), contrato/agenda/OS, liquidação e CSV/PDF filtrados.
  Quinze telas em 390 e 1365 px, menu mobile, sem overflow/erros JavaScript.
- Fluxo anterior no navegador passou novamente: Home/retorno, início GPS
  simulado, edição, foto no S3 simulado, localização negada, conferência,
  limpeza/assinatura vazia bloqueada/assinatura touch, finalização e PDF.
- Duas empresas em sessões HTTPS novas: oito tentativas cruzadas de acesso a
  OS/foto/assinatura/PDF retornaram 404; hashes de foto/assinatura/snapshot e
  leitura do PDF conferidos. O ensaio inicial com cookies de uma execução
  anterior precisou ser repetido com sessões atuais após renovar a chave local.
- PDFs novos de orçamento e peças renderizados e inspecionados visualmente.

Todos os ambientes/dados/credenciais de ensaio são locais e ficam em tmp,
fora do Git/ZIP. Testes que simulam indisponibilidade geram logs 503 esperados.
Não houve acesso ao PostgreSQL/S3/Render publicados nem teste em celular físico
no ambiente de produção.
check --deploy no simulador local mantém os dois avisos da configuração
anterior sobre HSTS_INCLUDE_SUBDOMAINS e HSTS_PRELOAD. Nenhum erro de segurança
foi apontado; esses parâmetros de domínio não foram alterados nesta entrega.

## Publicação no Render e etapas manuais

1. Confirme o código que está efetivamente publicado, especialmente Planejamento.
   Compare a versão local com seu repositório de produção antes de substituir
   arquivos; integre eventuais diferenças existentes. O ZIP contém código,
   não um backup de dados. Não envie tmp, .env, banco, mídia ou credenciais.
2. Faça backup válido do PostgreSQL e dos objetos existentes antes do upgrade.
3. Revise/commite o código com as três migrations novas no repositório já usado
   pelo Web Service e faça o deploy nele. Não crie outro banco/service/bucket
   nem reaplique Blueprint para esta atualização. Mantenha as variáveis atuais.
4. O scripts/start.sh existente executa migrate_locked --noinput antes do
   Gunicorn. Confira logs das três migrations e health check. Não execute
   makemigrations, flush, reset, seed_demo ou exclusão de volumes em produção.
5. Depois do deploy, valide login/seleção da organização e cadastros/OS anteriores.
   Confira permissões dos memberships. ADMIN/GESTOR habilitados no ERP já
   recebem os novos módulos; não precisam de um novo grant por módulo.
   Para Estoque/Financeiro/Contabilidade, atribua o papel ao vínculo da empresa e
   mantenha o ERP Assistência habilitado nele e na organização.
6. Valide uma pequena entrada/uso real de estoque, orçamento, contrato/agenda,
   conta e relatórios com dados de homologação claramente identificados. Entre
   em uma segunda empresa e confira que seus dados não aparecem nela.

Nenhuma variável de ambiente nova é exigida. SECRET_KEY, DATABASE_URL,
AWS/S3, .env.example, requirements, Docker, Gunicorn, scripts e render.yaml
estão preservados. Web Service e PostgreSQL continuam plan: free no arquivo.
Não foi feita verificação do plano real da instalação já publicada.

Pendências externas: confirmar equivalência da fonte de produção, revisão/
commit/deploy por você e validação no ambiente publicado. Nenhuma funcionalidade
solicitada ficou dependente de uma nova credencial ou de novo serviço externo.

## Arquivos

Implementação principal: gestao/models.py, forms.py, services.py, permissions.py,
views.py, reporting.py, urls.py, admin.py, apps.py, templatetags/modulos_erp.py,
tests.py, migrations/0001_initial.py e templates/gestao/*.html.

Integrações: tecnolmed/settings.py (registro da app), tecnolmed/urls.py,
contas/models.py e sua migration, ordens/models.py/forms.py/services.py e sua
migration, templates/ordens/detalhe.html, core/views.py,
templates/core/painel.html, templates/base.html, templates/paginacao.html.

Verificação/documentação: tests/modules_browser_fixture.py,
tests/modules_browser_flow.cjs, AUDITORIA_MODULOS.md, ENTREGA_MODULOS.md,
README.md e AUDITORIA_MODULOS_ARQUIVOS.json. O manifesto relaciona exatamente
arquivos preservados, modificados e criados; nenhuma remoção é permitida pelo
empacotador tests/verify_source.py. Relatórios de etapas anteriores permanecem
como histórico e não substituem esta entrega.
