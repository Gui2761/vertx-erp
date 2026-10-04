# Rollback compatível — Piloto TECNOLMED

Continuação do PREDEPLOY em 03/10/2026. **Contingência VALIDADA no banco restaurado; pacote pronto para autorização de homologação controlada.** Operação com dados reais ainda depende de PostgreSQL persistente e smoke tests autorizados no ambiente real. Nenhum commit, push, deploy, acesso/alteração em produção, mudança de credencial/plano ou sincronização de Blueprint foi realizado.

| Item | Resultado |
| --- | --- |
| ROLLBACK COMPATÍVEL | VALIDADO — cópia PostgreSQL existente, WSGI e escritas essenciais |
| BACKUP | VALIDADO anteriormente, sem repetição |
| RESTORE | VALIDADO anteriormente; mesma cópia reutilizada |
| 25 MIGRATIONS NA CÓPIA | VALIDADO; 82 totais, nenhum avanço/reversão nesta etapa |
| HEALTH /health/ | VALIDADO nos dois modos, com banco real local |
| HEALTH CHECK RENDER | PREPARADO documentalmente; ainda vazio no serviço, não alterado |
| R2 PRIVADO | VALIDADO anteriormente, sem repetir auditoria |
| POSTGRESQL | Tornar persistente antes de operação real; Free apenas para homologação temporária |
| PACOTE GIT | PRONTO; sem stage/commit; arquivo completo e manifesto privados locais |
| DEPLOY | PRONTO PARA AUTORIZAÇÃO de homologação controlada; operação real permanece condicionada |

## Código e artefato de contingência

O ponto de contingência é **o pacote atual do piloto com o mesmo conjunto de models/migrations**, usando o entrypoint `/bin/sh /app/scripts/start-contingency.sh`. O script seleciona `tecnolmed.contingency_settings`, que herda as configurações usuais e muda somente `CONTINGENCIA_JORNADA_CONTRATUAL=True`. Nenhuma configuração de banco, autenticação, TLS, tenant, storage ou credencial muda. O modo normal continua desativado por padrão e usa `/bin/sh /app/scripts/start.sh`.

Artefato congelado: `tmp/contingency/VERTYX_CONTINGENCIA_PILOTO_TECNOLMED.zip`. Manifesto de SHA-256 do ZIP e de cada arquivo: `tmp/contingency/VERTYX_CONTINGENCIA_PILOTO_TECNOLMED.manifest.json`. Ambos ficam fora do pacote Git em `tmp/`. Não contêm `.env`, credenciais, banco, backup, media privada ou ambientes locais. O bundle inclui os dois entrypoints; os hashes demonstram que as fontes testadas são as do bundle. Não é um commit Git nem uma imagem publicada, e não há novo SHA de commit a informar.

**Não retornar ao código fe6c554.** A incompatibilidade de suas escritas com as 63 colunas novas permanece. A contingência preserva os models novos, os campos obrigatórios e todos os documentos; não reverte migrations nem troca DATABASE_URL. Após a futura publicação autorizada do pacote, a ativação no serviço existente será pela mudança autorizada do **Docker Command** para `/bin/sh /app/scripts/start-contingency.sh`, mantendo o mesmo commit/pacote. Alternativamente, a reconstrução usa o bundle congelado, após autorização de envio. Nenhuma dessas ações foi executada. O startup compartilhado confere migrations incrementais; no schema alvo elas já estão aplicadas, portanto não existe downgrade nem migration nova para a contingência.

## Comportamento operacional

Em contingência, a configuração da Jornada Contratual deixa de bloquear/linkar a OS. Iniciar jornada, registrar eventos, solicitar/decidir correções e gravar configuração pela interface ficam recusados com 403. O histórico administrativo permanece acessível para leitura. As configurações por contrato e os eventos/horários existentes não são modificados.

Login, seleção da organização, ERP/memberships, papéis, isolamento e regras normais de status da OS continuam exigidos. Técnicos continuam limitados às OS atribuídas e não ganham acesso financeiro. Atendimento/conferência/assinatura do cliente continuam funcionando; requisitos adicionais específicos da Jornada Contratual ficam suspensos. Toda auditoria de OS nesse modo recebe `modo_operacional=CONTINGENCIA_JORNADA_CONTRATUAL`. Um aviso destaca o modo na interface autenticada. Não houve alteração grande de UI nem desenvolvimento de módulo comercial.

O rollback é uma contingência operacional da Jornada Contratual. Ele **não** é uma garantia de corrigir qualquer regressão arbitrária em estoque/financeiro ou indisponibilidade de infraestrutura. A reativação exige revisar jornadas abertas e OS atendidas durante a suspensão, com registros/auditoria; não preencher retroativamente horários ou medições fictícias. Valores provisórios não devem ser usados como faturamento definitivo. Documento/PDF anteriormente emitido continua imutável.

## Teste de troca sobre o mesmo banco

Reutilizada a cópia `predeploy_restore_907cb941b43e` em `127.0.0.1:55432`. Integridade e ausência de migrations pendentes foram verificadas somente para confirmar adequação ao teste, sem novo backup/restore, reset, flush ou mudança de schema. Havia 82 migrations Django aplicadas: 57 do snapshot e as 25 ensaiadas no PREDEPLOY.

1. Executado o candidato em processo com `tecnolmed.settings`; criadas fixtures claramente sintéticas em duas organizações próprias. Jornada normal e bloqueio de OS permaneceram ativos.
2. Inicializada a aplicação WSGI no loopback; `/health/`, login HTTP com CSRF e cadastro HTTP de cliente passaram. Telas de plataforma/dashboard, clientes, equipamentos, OS, estoque, financeiro, compras, documentos e jornadas responderam 200. Técnico recebeu 403 no financeiro; organização diferente recebeu 404 na OS.
3. Processo candidato encerrado; inicializada a mesma aplicação com `tecnolmed.contingency_settings`, apontando ao mesmo banco. **Nenhuma migration foi revertida/aplicada.**
4. Repetidas somente as verificações necessárias da nova contingência: inicialização, saúde, login, cadastro HTTP, leitura das telas, bloqueios de papel/tenant, download privado e PDF anterior idêntico. A OS antes bloqueada tornou-se acessível pelo técnico autorizado.

Escritas aprovadas na contingência:

- cliente: criar/editar pelo ORM do modelo atual e criar pela view HTTP com CSRF;
- equipamento: criar/editar com categoria obrigatória e campos novos;
- técnico: INSERT incluindo o default de `competencias`, que falhava no código fe6c554;
- OS: criar, iniciar, registrar diagnóstico/serviço, conferir e finalizar com assinatura do cliente;
- estoque: entradas e saídas oficiais auditadas por lote/FEFO; saldo final esperado 6;
- financeiro: liquidar saldo parcial anterior de 6,68; novo recebimento de 4,07 com movimento de caixa e saldo exato; pagamento sem banco permaneceu rastreável;
- documentos: upload pelo formulário/service existente em armazenamento privado local, leitura e download; PDF assinado anterior com SHA-256 inalterado;
- Jornada Contratual: mutações recusadas e registro histórico anterior inalterado;
- auditoria: operações da OS identificadas como contingência.

Dados preexistentes restaurados foram preservados por PK/hash. Novos dados sintéticos permanecem apenas na cópia local; suas alterações operacionais esperadas não são tratadas como perda de dados originais. Usuário real restaurado, organização e memberships originais não foram alterados. As senhas temporárias usadas nos usuários QA foram geradas em memória; não há senha de produção nem credencial nova em código/artefato.

Dois problemas de fixtures foram corrigidos: colisão do nome `admin` com o usuário restaurado e falta da categoria obrigatória no equipamento de teste. O primeiro não deixou dados persistidos (transação de teste); o segundo reverteu integralmente a fase sintética de contingência. A fase candidata já aprovada foi preservada, sem repetição, e somente a etapa de contingência pendente foi retomada.

## Testes e limites da evidência

**11/11 testes automatizados novos PostgreSQL PASS**, zero falhas/skips. Rodaram diretamente na cópia restaurada com isolamento transacional, sem criar banco de teste ou executar migrations. Os registros anteriores a esses testes ficaram idênticos. Check e makemigrations --check --dry-run das novas settings de contingência passaram; nenhuma migration nova. Comparação das settings: diferença única é a flag de contingência.

Os 441 testes anteriores continuam registrados como aprovados na execução anterior e **não foram repetidos**. São 441 anteriores + 11 novos em execuções distintas; não declarar que uma suíte completa de 452 testes foi reexecutada sobre o código modificado. Foram realizados testes HTTP automatizados sobre WSGI real, sem nova rodada de homologação visual/Bloco 3H. Gunicorn/Linux/container Render, dispositivos físicos e uso real da nova versão permanecem não validados nesta etapa local.

## Health Check preparado

Endpoint correto: `/health/`, definido em `platform_core/health.py`, com consulta PostgreSQL `SELECT 1`, resposta 200 `{"status":"ok"}` e 503 em falha de banco; não requer login. Sua resposta não certifica I/O do bucket nem todos os módulos.

No momento autorizado da publicação: abrir exclusivamente `vertyx-erp` (`srv-dauq0560tbcc73c81nqg`) → Settings → Health Checks → editar **Health Check Path** para `/health/` → revisar/salvar na janela autorizada e acompanhar eventuais efeitos no deploy. Não selecionar o serviço histórico `tecnolmed-erp`, não sincronizar Blueprint e não alterar `render.yaml`. A configuração ainda está vazia conforme a auditoria preservada. Documentação oficial: https://render.com/docs/health-checks.

## PostgreSQL — recomendação final

**Atualizar o PostgreSQL existente para um plano persistente aprovado antes de iniciar operação real** é a opção recomendada, preservando recurso e dados sempre que o upgrade do provedor permitir. Se essa opção não for escolhida, planejar migração validada para PostgreSQL persistente, com autorização específica. Não criar/substituir banco automaticamente. Nenhuma contratação foi realizada.

O Free atual, com expiração documentada em **30/10/2026**, serve temporariamente para homologação com dados de teste e backups privados. Não iniciar nele o piloto real que armazenará OS, vínculos de fotos/assinaturas, jornadas e histórico. R2 protege os objetos, mas não substitui o banco de metadados/autorização. Free tem expiração e não possui o mecanismo de recuperação/backup dos planos pagos; referência oficial: https://render.com/docs/free e https://render.com/docs/postgresql-backups. Definir política de backup/restore, retenção e continuidade antes da primeira operação real, sem assumir valor/plano não aprovado.

## R2 — procedimento funcional temporário, ainda não executado

A privacidade do bucket `vertyx-homologacao` foi validada no PREDEPLOY e não foi auditada novamente. Nenhum objeto R2 foi enviado/removido nesta etapa. As operações de documentos testadas acima usaram **armazenamento local isolado**, não R2.

Após autorização para o smoke funcional:

1. Usar o backend `private_storage` e as variáveis já existentes da aplicação; não copiar secrets para script, log ou Git. Confirmar o recurso da evidência anterior e a organização de homologação autorizada.
2. Gerar UUID único e conteúdo sintético sem dados pessoais, por exemplo `VERTYX R2 SMOKE <UUID>`. Salvar somente um objeto com chave nova sob `homologacao/<UUID>/r2-smoke.txt` no backend privado (que acrescenta seu prefixo `private/`). Não sobrescrever qualquer objeto existente e não definir ACL pública.
3. Registrar apenas UUID, resultado e SHA-256; capturar a chave efetivamente retornada pelo backend. Ler o objeto por esse backend e comparar bytes/hash/tamanho. Confirmar que o fluxo autenticado da aplicação continua protegido, sem criar URL pública nem alterar permissões.
4. Em `finally`, remover **somente a chave retornada desta execução**, verificando prefixo/UUID antes de remover. Confirmar `exists=False`. Se a remoção falhar, interromper e informar a chave temporária ao responsável para limpeza controlada; não listar/remover objetos alheios.
5. Registrar PUT/GET/DELETE e ausência do objeto ao final. Esse procedimento valida object storage; upload/download completo de foto/assinatura/PDF pela interface continua parte do smoke pós-publicação autorizado.

## Publicação futura e parada

Autorizar explicitamente o pacote completo e as 25 migrations automáticas antes de qualquer push para main: Auto-Deploy continua On Commit. Confirmar novamente backup próximo da janela apenas se dados mudaram; não substituir este restore aprovado sem necessidade. Configurar Health Check na janela autorizada. Preservar banco, variáveis, R2, plano e runner desativado. Validar smoke real e logs antes de liberar escrita de usuários.

Se houver falha específica da Jornada após a publicação, ativar o entrypoint de contingência do **mesmo pacote/schema** autorizado, acompanhar inicialização/Live/health e confirmar a flag pelo aviso e operações essenciais. Após resolver a causa, restaurar entrypoint normal mediante autorização e revisão do período suspenso. Não usar rollback para fe6c554 nem desfazer migrations. Se o defeito exceder esse modo, suspender operação e aprovar correção compatível; restauração destrutiva em produção exige autorização própria.

Riscos remanescentes: PostgreSQL Free; I/O R2 e PWA física; validação real de Gunicorn/Render; limitações da contingência à Jornada; novas operações durante eventual falha de deploy; pacote sem commit/imagem publicada até autorização. Operação real não está liberada por esta entrega. **Parar e aguardar autorização; não iniciar Bloco 4.**

## Arquivos desta etapa

- `tecnolmed/settings.py`
- `tecnolmed/contingency_settings.py`
- `platform_core/contingency.py`
- `scripts/start-contingency.sh`
- `operacao/contract_workday.py`
- `operacao/contract_workday_views.py`
- `ordens/services.py`
- `templates/base.html`
- `operacao/test_contingency.py`
- `ROLLBACK_COMPATIVEL_PILOTO_TECNOLMED.md`
- `VALIDACAO_ROLLBACK_PILOTO_TECNOLMED.json`
- `PREDEPLOY_PILOTO_TECNOLMED.md`
- `VALIDACAO_PREDEPLOY_PILOTO_TECNOLMED.json`
- `PACOTE_GIT_PREDEPLOY_PILOTO_TECNOLMED.md`

Helpers/logs/evidências e ZIP/manifesto estão em `tmp/validation` e `tmp/contingency`, ignorados pelo Git. Sem alteração de requirements, migration antiga, credencial ou Render.
