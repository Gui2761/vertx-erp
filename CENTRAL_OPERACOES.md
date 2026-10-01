# Central de operações e painel operacional — VERTYX

Ampliação sobre `vertyx_estoque_gestao.zip`, conferido byte a byte antes das alterações.
OS, preventivas, contratos, estoque, compras, financeiro, documentos e portal
continuam nos mesmos modelos e serviços. Não há tabela paralela de atividades.

## Utilização

Em Assistência > Planejamento estão calendário (dia/semana/mês), lista e linha do
tempo. Hoje, anterior/próximo período, data, filtros, busca e Nova OS usam os dados
da organização selecionada. A semana continua sendo a visão inicial existente.
No mês aparecem até três atividades por dia; “+ outras” abre a lista completa do
dia. A lista vira cartões no celular. A fila Não planejadas pode ser recolhida.

Os indicadores abrem as pendências correspondentes: atrasadas, sem planejamento,
com conflito, aguardando peças e preventivas atrasadas. A fila identifica cliente,
unidade, equipamento, tipo, prioridade, abertura, prazo e contrato. Os detalhes
abrem em um painel lateral, mantendo o planejamento atrás. Agendamento, atribuição
e prioridade usam um formulário curto e retornam à central após salvar.

Nova OS rápida permite selecionar cliente → unidade → equipamento, tipo, contrato
opcional, prioridade, descrição, prazo e agenda. Técnico e data são opcionais.
Sem ambos preenchidos a OS permanece Aberta e aparece como Não planejada. Com
ambos passa a Agendada. O início de atendimento exige um técnico responsável.

O término previsto é opcional e independente das horas trabalhadas. Sem ele,
a linha do tempo mostra um marcador “duração não informada”, com zero horas
estimadas; não presume duração ou disponibilidade futura. O intervalo 07h–17h é
uma faixa visual, não uma regra de jornada. No celular, os cartões mostram também
as atividades fora dessa faixa. A carga diária mostra atividades, horas previstas
informadas, concluídas, pendentes, atrasadas e conflitos. Mais de dez horas previstas
é destacado como ocupação superior à faixa exibida, sem interpretação trabalhista.

OS em execução sem agendamento aparece pelo início real. Concluídas aparecem pela
conclusão real, inclusive quando não possuíam agendamento. Nenhum horário histórico
é preenchido retrospectivamente. Atraso significa prazo vencido, início previsto
ultrapassado sem início real ou término previsto ultrapassado em uma OS pendente.

PreventivaProgramada e AgendaPreventiva continuam como origens existentes. Após a
conversão, aparece apenas a OS, com indicação da origem/contrato. A visita contratual
anterior que gerava OS sem horário continua exigindo agendamento explícito na
central. O gerador anterior de plano mantém o horário 08h já adotado naquele fluxo;
a central não adiciona uma duração. ADMIN/GESTOR pode abrir a origem no painel lateral.

Aguardando peça mostra reservas daquela OS, depósito, disponível e quantidade
em compra, calculados por `operacao.stock.metrics`. Textos manuais não viram saldo
nem uma compra presumida. Movimentar peças continua usando o fluxo auditado atual.

Minha agenda mostra Hoje, Atrasadas, Próximas, Sem agendamento e Concluídas hoje.
Técnicos veem suas próprias atividades. Os atalhos usam os fluxos atuais de OS,
GPS, checklist, fotos, peças, conferência, assinatura e conclusão. Não existe estado
“em deslocamento” ou “cheguei” na base atual; eles não foram inventados.

## Conflitos e auditoria

Intervalos conhecidos usam início inclusivo e fim exclusivo: 09h–10h e 10h–11h
não conflitam. Horários iguais sem duração, ou um horário sem duração situado
dentro de um intervalo conhecido, são identificados conservadoramente como
conflito. Um horário anterior sem término não permite garantir que a agenda estará
livre depois; informe o término para verificar sobreposição completa.

Agendamento manual, criação rápida e criação/edição pelo formulário anterior de
OS verificam conflitos. A autorização exige ADMIN/GESTOR e justificativa explícita
no planejamento. PLANEJADOR/ATENDIMENTO não autoriza sobreposição. São registrados
usuário, organização, OS, técnico, horários, prioridade, antes/depois, justificativa
e as OS conflitantes. A revisão da OS impede sobrescrever outra sessão. No
PostgreSQL, o lock da organização serializa alterações de agenda, inclusive duas
criações simultâneas para o mesmo técnico. O teste concorrente comprova uma criação
e uma rejeição. OS em execução/encerrada não é reprogramada pela central.

Os geradores anteriores de preventivas continuam operando; conflitos de seus
horários legados são destacados pela central, sem cancelar preventivas ou modificar
suas regras. Essa compatibilidade evita interromper contratos já em funcionamento.

## Permissões

ADMIN/GESTOR planejam e mantêm suas permissões anteriores. Os papéis adicionais
PLANEJADOR e ATENDIMENTO têm acesso à central, detalhes operacionais e criação/
reprogramação; não recebem permissões de financeiro, estoque, administração,
aprovação ou edição completa de OS. TÉCNICO consulta apenas suas OS e preventivas.
ESTOQUE/FINANCEIRO/CONTABILIDADE continuam sem acesso ao planejamento.

O painel de TV exige **Visualizar painel operacional**, um grant no MembershipERP
da organização e ERP selecionados. Todos os grants existentes recebem `False`.
Em Configurações > Usuários, ADMIN deve editar o vínculo e habilitar essa permissão.
O campo deixa claro que ela permite ler dados operacionais de toda a organização,
inclusive quando atribuída a um técnico. Não amplia as demais permissões do usuário.

Para a TV, recomenda-se uma conta com papel **Somente painel operacional** (PAINEL),
acesso ao ERP e essa permissão. Esse papel acessa somente o painel/dados, a seleção
de organização e login/logout; os demais módulos são bloqueados pelo middleware.
Não é um link público. Login, cookies seguros, sessão e organização continuam
validados. Revogar grant, ERP ou membership interrompe a consulta seguinte.

## Painel de TV / projetor

Assistência > Painel operacional ou Modo TV abre a tela dedicada. Ela contém
indicadores, atividades agora com início/tempo transcorrido e próxima OS, equipe,
fila, concluídas hoje, preventivas, alertas e linha do tempo. Estado da equipe
significa “Em atendimento” ou “Sem atendimento em execução”, conforme OS reais;
não significa presença, GPS contínuo, intervalo ou ponto.

Em Configurações > Painel operacional, ADMIN escolhe blocos, tema claro/escuro e
intervalo 15/30/60 segundos (padrão 30). O navegador faz GET autenticado em
`/painel-operacional/dados/`, sem recarregar a página inteira, WebSocket, Redis,
worker adicional ou novo serviço Render. A consulta usa joins para evitar consultas
por OS; o teste verifica que o número de consultas não cresce com cada atividade.
Mais registros nos blocos alternam páginas automaticamente a cada consulta, com
total e página visíveis. Isso acomoda equipes maiores sem operação do mouse.

O relógio/tempo transcorrido atualiza a cada segundo. A última consulta bem-sucedida
aparece com segundos. Falha de rede mantém os últimos dados com aviso destacado e
tenta novamente. Sessão/permissão indisponível interrompe a atualização e pede
novo acesso. Render Free indisponível/retomando não é apresentado como dados atuais.
Não há promessa de disponibilidade da infraestrutura externa.

Tela cheia oculta os controles; Esc retorna. F11 é alternativa quando o navegador
não permite a Fullscreen API. Não há acesso ao Django Admin na tela.

O JSON de TV usa uma lista explícita de campos operacionais. Não envia CPF/CNPJ,
contatos, endereço, texto livre de defeito/diagnóstico/observações, anexos,
documentos, valores financeiros, custos, salários ou dados clínicos. Ele não usa
o snapshot de documentos de OS. Respostas são `private, no-store`, com permissão
revalidada por consulta. Não se guarda conteúdo empresarial em localStorage.

## Migrations e implantação futura

Quatro migrations novas; nenhuma migration anterior foi alterada:

- `contas.0006`: amplia choices de perfil, preservando valores anteriores;
- `platform_core.0004`: grant de TV desabilitado por padrão e choices de papel;
- `ordens.0009`: adiciona término previsto e permite técnico nulo na FK existente;
- `operacao.0005`: adiciona preferências do painel na Configuracao atual.

Permitir técnico nulo relaxa a restrição anterior de uma coluna existente. É a
extensão necessária para a OS sem responsável pedida nesta fase; preserva a FK,
o PROTECT e todos os vínculos existentes. No PostgreSQL, não recria a tabela.
Não há exclusão, reset ou preenchimento artificial de técnico/horários.

O ensaio de upgrade em PostgreSQL local verificou 71 tabelas e 1.098 registros
anteriores, comparando todos os valores das colunas anteriores antes/depois.
Render, Compose, storage, runner de estoque e credenciais não foram alterados.
Nenhum deploy, push, commit ou acesso ao banco de produção foi realizado.

Quando a atualização for autorizada para o ambiente publicado, os procedimentos
de migrations/backup da instalação continuam os existentes. Depois da atualização,
ADMIN deve conceder a permissão de TV às contas desejadas e configurar o painel.
O agendamento de estoque a cada 30 minutos/semanal permanece documentado em
`AUTOMACAO_ESTOQUE.md`; o polling de TV não o substitui.

## Verificações e limites

Resultados finais estão em VALIDACAO_FINAL.json, com histórico da validação de
estoque anterior. A lista de arquivos e hashes das migrations anteriores está em
AUDITORIA_OPERACOES_ARQUIVOS.json. INVENTARIO_FINAL.md inclui os campos e rotas.
Testes novos estão em operacao/test_planning.py; navegador e fixtures em
tests/planning_browser_flow.cjs e tests/planning_browser_fixture.py.

A validação usa dados sintéticos apenas no PostgreSQL/HTTPS/Moto S3 local. Ela
não certifica celulares físicos, TVs físicas, produção ou desempenho com volume
muito maior de dados. A ausência de duração limita a detecção de sobreposição;
nenhuma duração foi inventada. Mapas/rotas atuais continuam disponíveis no
atendimento técnico; não foi implementado rastreamento ou ponto/RH. Drag-and-drop
não foi incluído: agendamento/reagendamento utiliza o formulário auditado.
