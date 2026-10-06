# RH/Ponto — hora extra com solicitação e aprovação

Data: 06/10/2026. Entrega local, aguardando homologação do usuário.

## Comportamento concluído

Jornada prevista → ponto efetivo → excedente identificado → solicitação PENDENTE → APROVADA ou RECUSADA → indicadores e histórico.

Permanência além da jornada não autoriza hora extra. Apenas a quantidade aprovada compõe horas extras e crédito do banco quando habilitado na referência do dia. Déficits mantêm a política já existente. Não há folha, percentuais legais ou integração financeira automática.

Meu Ponto → Solicitar hora extra / acompanhar → consultar data → verificar jornada/ponto/excedente → informar minutos e motivo → enviar. A quantidade é conferida pelo servidor, nunca tomada como verdade do formulário. São exigidos ponto concluído, jornada de referência e competência aberta. Reenvio com a mesma chave é idempotente; outra solicitação para o mesmo funcionário/dia é bloqueada.

RH → Funcionários → Horas extras → filtros e indicadores → justificar → Aprovar (inclusive quantidade parcial) ou Recusar. ADMIN/RH autorizados podem gerir a organização; GESTOR autorizado apenas os funcionários cujo gestor é ele. Ninguém decide o próprio pedido. Permissões de membership/capacidade, módulo e tenant permanecem aplicadas no backend.

O PWA Técnico usa somente o autoatendimento `/ponto/horas-extras/`; sua lista de rotas recebeu apenas essa rota operacional. Menu, logo, breadcrumbs e navegação inferior não foram alterados. `/rh/horas-extras/` continua bloqueado para TÉCNICO/VENDEDOR. VENDEDOR solicita por Meu Ponto e continua destinado ao PDV.

## História, cálculo e notificações

ReferenciaJornadaPonto congela por funcionário/dia jornada, escala, horários e parâmetros no início do registro. Uma mudança posterior de jornada não recalcula os dias já registrados. Solicitação e decisão são registros imutáveis, relacionados ao funcionário e à referência. Guarda-se evidência das marcações originais e efetivas, quantidade, justificativa, responsável e data/hora. A auditoria da decisão também contém o ponto conferido naquele momento.

Minutos são obtidos somando os segundos reais dos períodos antes da conversão para minutos inteiros completos. Horários originais e segundos permanecem preservados; não há arredondamento para cima, tolerância eliminando extra ou truncamento separado de cada período. Entrada 12:00 → intervalo 16:00–17:00 → saída 22:00 resulta em 480 previstos, 540 trabalhados e 60 excedentes; aprovação inicial zero.

Decisões e solicitações concorrentes usam locks PostgreSQL e constraints para evitar duplicação. Aprovação revalida o excedente atual e não excede o solicitado. Ajuste de ponto que invalidaria uma hora extra já aprovada é rejeitado atomicamente. Fechamento mensal exige decisão das solicitações pendentes. Fechamentos anteriores permanecem intactos, sem serem inventados como aprovações.

Notificações internas existentes avisam responsáveis autorizados pelo pedido e o funcionário pela decisão, incluindo a recusa. Avisos pendentes de aprovação são resolvidos após decidir. Nenhuma mensagem externa é enviada. A estrutura de eventos/auditoria/Notificacao permite futura integração de canais.

Relatório RH e espelho de ponto separam previsto, trabalhado, excedente, pendente, aprovado e recusado. Filtros: funcionário, departamento, cargo, jornada, período e status. Espelho mensal preserva exportações PDF/Excel.

## Validação

551/551 testes PostgreSQL aprovados (581.030 s), incluindo os 511 anteriores e 40 novos. Direcionados: 86/86 (128.848 s). `check`, `makemigrations --check --dry-run`, sintaxe JavaScript e `git diff --check` aprovados.

22 novos testes de hora extra: identificação, solicitação, pendência, aprovação parcial, recusa, proibição de decisão própria, integridade/hashes, indicadores/banco, isolamento, permissões, PWA e VENDEDOR, jornada histórica, minutos/segundos, notificações, ajustes, fechamento, virada de dia, falha transacional, concorrência e migration com dados legados. Um teste anterior de escala foi atualizado: folga configurada depois do ponto não altera a referência já registrada, conforme o requisito novo.

Pela interface: dois dias sintéticos com 510 minutos previstos, 570 trabalhados e 60 excedentes. Uma solicitação foi aprovada pelo GESTOR responsável (60 min); outra recusada (0 aprovado), com motivo consultável. Indicadores e filtro de aprovadas conferidos. PWA mostrou ambos os estados e notificações internas. No funcionário visual o banco está desabilitado; o crédito com banco habilitado foi validado automaticamente em PostgreSQL.

Capturas 1365 × 768 / 390 × 844 e verificação 320 px, sem overflow horizontal da página operacional. Tabelas gerenciais usam sua área própria de rolagem responsiva.

## Migration, arquivos e limites

`operacao.0016_hora_extra_aprovacao`: apenas três tabelas novas, constraints e referências aditivas de dias legados. Não altera/apaga marcações nem fechamentos existentes. Migration 0015 pertence ao cadastro central da etapa anterior desta sessão. Ambas validadas/aplicadas somente em PostgreSQL sintético local e ainda não aplicadas em produção; nenhuma migration anterior foi modificada.

Para marcas legadas sem versão histórica de jornada, a migration congela a referência disponível no momento da execução. Não inventa configuração antiga que nunca foi armazenada. Snapshots de competências já fechadas continuam sendo a fonte histórica original.

Uma solicitação por funcionário/dia. Não foi implementada reabertura/segunda solicitação após recusa nem “solicitar ajuste” de hora extra; revisão futura precisa de fluxo auditado. Consultas gerenciais aceitam até 367 dias e filtram departamento/cargo/jornada atuais do funcionário. O envio e a decisão exigem conexão; não há nova fila offline de aprovação. Regras futuras de adicional noturno, percentuais, feriados e folha permanecem fora do escopo.

Arquivos de hora extra: overtime.py, overtime_views.py, workforce.py, workforce_models.py, workforce_views.py, models.py, urls.py, technician_access.py (somente allowlist operacional), templatetags/ponto_horas.py, test_overtime.py, test_block3_workforce.py, migration 0016; templates overtime_own.html, overtime_management.html, ponto.html, ponto_mirror.html e rh.html; static/css/overtime.css. Lista completa e hashes em VALIDACAO_RH_PONTO.json. Dependências inalteradas.

Corrigidos durante o desenvolvimento: lock no lado nullable do JOIN PostgreSQL (lock agora somente na solicitação); teste precisava recarregar a relação após decisão. Sem erros/falhas pendentes na suíte final. Logs 503 emitidos por cenários negativos de indisponibilidade existentes não representam falha da suíte.

## Capturas e entrega

- [Solicitação mobile](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/overtime-evidence/solicitacao-mobile-390x844.jpg)
- [Solicitação completa mobile](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/overtime-evidence/solicitacao-mobile-full.jpg)
- [Aprovação desktop](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/overtime-evidence/aprovacao-desktop-1365x768.jpg)
- [Histórico completo no PWA](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/overtime-evidence/historico-pwa-full.jpg)
- [Recusa no PWA](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/overtime-evidence/recusa-pwa-390x844.jpg)
- [Notificações no PWA](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/overtime-evidence/notificacoes-pwa-full.jpg)

VALIDADO AUTOMATICAMENTE / VALIDADO PELA INTERFACE / VALIDADO EM BANCO SINTÉTICO. NÃO VALIDADO EM PRODUÇÃO nem iPhone físico. Aguarda avaliação visual do usuário antes de publicação. Nenhum commit, push, deploy, acesso à produção ou alteração de Render/R2/credenciais.
