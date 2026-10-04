# VERTYX — pré-deploy controlado do Piloto TECNOLMED

## Atualização — contingência compatível validada em 03/10/2026

O bloqueador de retorno operacional da Jornada Contratual foi resolvido pelo ponto de contingência do mesmo pacote/schema. A troca candidato → contingência passou na cópia PostgreSQL existente, incluindo login HTTP, saúde e escritas essenciais; 11 testes novos passaram. Nenhuma migration nova, backup/restore repetido ou alteração remota. Health Check está preparado para configuração futura.

**Pronto para autorização de homologação controlada. Operação real requer PostgreSQL persistente antes de registrar dados reais.** Teste funcional R2 e PWA física ainda pendentes. O rollback direto para fe6c554 continua inseguro; utilizar o entrypoint `scripts/start-contingency.sh` do pacote congelado.

Entrega atual: `ROLLBACK_COMPATIVEL_PILOTO_TECNOLMED.md` e `VALIDACAO_ROLLBACK_PILOTO_TECNOLMED.json`. A lista atual de candidatos está em `PACOTE_GIT_PREDEPLOY_PILOTO_TECNOLMED.md`. Os 441 testes anteriores foram preservados, sem repetir a suíte completa; os testes novos cobrem somente a mudança de contingência. Sem commit, push ou deploy.

## Registro histórico da auditoria original, antes da contingência


Auditoria de 03/10/2026. **Auditoria concluída; deploy não executado e ainda não liberado tecnicamente.** Backup, restore e ensaio das 25 migrations passaram. Existe incompatibilidade confirmada do rollback apenas do código, que precisa de uma estratégia preparada e validada antes do deploy. Esta etapa não desenvolveu funcionalidades nem criou migrations.

## Ambiente efetivamente utilizado

| Item | Verificado |
| --- | --- |
| Serviço correto | `vertyx-erp` — `srv-dauq0560tbcc73c81nqg` |
| URL | https://vertyx-erp.onrender.com |
| Workspace | TECNOLMED's workspace |
| Projeto / ambiente no painel | My project / Production |
| Repositório | `tecnolmedengclinica-spec/vertx-erp` |
| Branch | `main` |
| Commit Live e HEAD remoto | `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261` |
| Web Service | Docker, Free, Oregon |
| PostgreSQL vinculado | `vertyx-postgres-homologacao` — `dpg-daunorm0tbcc73c06o4g-a` |
| Banco / versão consultada | `vertyx` / PostgreSQL 16.15 |
| PostgreSQL plano / região | Free / Ohio |
| Storage | Cloudflare R2, bucket existente `vertyx-homologacao` |
| Privacidade R2 | Public Access Disabled; conta e bucket coincidem com configuração do serviço |
| Conteúdo R2 | 0 objetos, 0 bytes na consulta; nenhum objeto criado ou removido |
| Endpoint de saúde | `/health/` retornou `{"status":"ok"}` pela interface do navegador |
| Health Check Path do Render | **Vazio**; não foi alterado |
| Runtime Python publicado | Série 3.12 conforme Dockerfile; patch exato não confirmado no container |
| Django publicado / pacote local | 5.0.9 / 5.2.17 |
| Python local de validação | 3.12.14 |
| Auto-Deploy | **On Commit** |

O serviço histórico `tecnolmed-erp` existe e está com deploy falho. Não é o serviço Live correto. O `render.yaml` local ainda usa esse nome histórico e declara `/health/`. **Não aplicar/sincronizar Blueprint:** ele não representa fielmente o serviço existente. A publicação futura deve atualizar exclusivamente o serviço `vertyx-erp` conectado ao repositório/branch confirmados. Nenhum arquivo de configuração foi alterado nesta auditoria.

O painel informa expiração do PostgreSQL Free em **30/10/2026**, com exclusão caso não haja upgrade. A continuidade precisa de decisão do responsável antes desse prazo; nenhum upgrade, contratação ou mudança de plano foi realizado. Web Oregon e banco Ohio são a configuração existente. As regras externas atuais do banco permitem IPv4 `0.0.0.0/0`; a conexão utilizada exigiu TLS e autenticação, e nenhuma regra foi alterada.

## Configurações e comandos

O vínculo da `DATABASE_URL` existente foi comparado com o PostgreSQL acima sem revelar host autenticado, usuário, senha ou URL. `SECRET_KEY` existe. Permanecem `DEBUG=False`, `TIME_ZONE=America/Maceio`, `UPLOAD_STORAGE=s3` e `S3_ADDRESSING_STYLE=path`.

Variáveis necessárias já configuradas: `SECRET_KEY`, `DATABASE_URL`, `DEBUG`, `TIME_ZONE`, `UPLOAD_STORAGE`, `S3_BUCKET_NAME`, `S3_ENDPOINT_URL`, `S3_REGION_NAME`, `S3_ADDRESSING_STYLE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. As variáveis de superusuário existentes não foram alteradas nem usadas para login. Credenciais R2 estão presentes; leitura/escrita de objetos com as credenciais da aplicação não foi testada. O painel de privacidade foi efetivamente verificado na sessão autenticada da Cloudflare.

O Render utiliza a raiz do repositório, contexto Docker `.`, Dockerfile `./Dockerfile`, sem override do comando Docker e sem pre-deploy command. O build instala `requirements.txt` e executa `python manage.py collectstatic --noinput`. O CMD chama `/bin/sh /app/scripts/start.sh`:

```sh
set -eu
python manage.py migrate_locked --noinput
exec gunicorn tecnolmed.wsgi:application --config gunicorn.conf.py
```

**O primeiro deploy do pacote aplicará automaticamente todas as 25 migrations pendentes antes de iniciar o Gunicorn.** O comando existente usa lock PostgreSQL para serialização; não gera migrations. Com falha, `set -e` impede o Gunicorn. O lock não garante que todo o conjunto de migrations seja uma transação única nem torna o código antigo compatível com schema parcialmente atualizado. Gunicorn usa a configuração versionada (2 workers, 2 threads, timeout 60 e bind na porta do ambiente). Não ativar Cron/runner nesta publicação.

## Backup e restauração

Backup realizado: **SIM**. Origem: serviço `vertyx-erp`, PostgreSQL `vertyx-postgres-homologacao`, banco `vertyx`.

- Início: 2026-10-03T23:33:31.143771+00:00 (20:33:31 America/Sao_Paulo).
- Fim: 2026-10-03T23:34:21.654941+00:00 (20:34:21 America/Sao_Paulo).
- Tamanho: **359439 bytes**.
- SHA-256: `a3da75425768cf209afb399e3c1bbd0d260a7f3dce06de8e2a5d7c355a6875d6`.
- Mecanismo: pg_dump 16.15, formato custom, `--no-owner --no-acl`, snapshot PostgreSQL exportado em transação repeatable-read/read-only compartilhado com o inventário. Senha fornecida por ambiente do processo, sem argumentos autenticados em linha de comando.
- Arquivo privado: `C:\Users\StartReparos\Documents\ChatGPT\saas vertyx\tecnolmed_erp\tmp\predeploy-backup-private\vertyx-postgres-20261003T233331Z.dump`.
- ACL: herança desabilitada; acesso do usuário local responsável e SYSTEM. Diretório ignorado pelo Git. O backup contém dados privados e não deve ser anexado ao repositório/chat.
- Validação do arquivo com `pg_restore --list`: **PASS**.
- Restore real isolado: **PASS**, no cluster PostgreSQL local preexistente `127.0.0.1:55432`, banco `predeploy_restore_907cb941b43e`. Nenhum novo serviço/banco no Render foi criado e nenhum banco existente foi sobrescrito.

As 72 tabelas restauradas coincidiram com o snapshot: contagens, colunas e hashes dos valores de todos os registros. O ensaio incremental aplicou as 25 migrations somente nessa cópia. **411 registros anteriores preservados**, com colunas/valores/PKs anteriores intactos; chaves estrangeiras válidas; usuário, organização e memberships preservados. Novos registros de permissões/migrations são esperados. Total após ensaio: **82 migrations Django**, sendo 64 do projeto e 18 do framework. A cópia local permanece disponível, sem reset/drop.

Contagens principais do banco publicado no snapshot: 1 usuário, 1 organização, 1 OrganizationMembership e 1 MembershipERP; clientes, equipamentos, OS, contratos, peças, compras, vendas e lançamentos financeiros estão com **zero registros**. Isso descreve o estado encontrado; não comprova perda histórica nem valida jornadas com dados reais. O teste sintético anterior do piloto é evidência separada. A consulta final ao banco publicado confirmou dados e migrations inalterados desde o backup.

## Migrations

No banco publicado: **57 aplicadas = 39 do projeto + 18 do Django**. No pacote local: **25 pendentes = 3 Bloco 1 + 5 Bloco 2 + 14 Bloco 3 + 3 Piloto**. Não se limitar às três últimas migrations do piloto.

Ordem calculada pelo executor Django e aplicada no ensaio:

1. `clientes.0005_fundacao_bloco3`
2. `contas.0007_operacao_bloco2`
3. `contas.0008_fundacao_bloco3`
4. `equipamentos.0007_operacao_bloco2`
5. `platform_core.0005_fundacao_bloco3`
6. `operacao.0006_estabilizacao_bloco1`
7. `gestao.0006_estabilizacao_bloco1`
8. `gestao.0007_origem_parcelas_existentes`
9. `gestao.0008_operacao_bloco2`
10. `operacao.0007_operacao_bloco2`
11. `gestao.0009_fundacao_bloco3`
12. `gestao.0010_fundacao_bloco3`
13. `operacao.0008_fundacao_bloco3`
14. `operacao.0009_fundacao_bloco3`
15. `gestao.0011_fundacao_bloco3`
16. `operacao.0010_fundacao_bloco3`
17. `gestao.0012_fundacao_bloco3`
18. `operacao.0011_fundacao_bloco3`
19. `gestao.0013_fundacao_bloco3`
20. `ordens.0010_operacao_bloco2`
21. `ordens.0011_piloto_jornada_contratual`
22. `operacao.0012_fundacao_bloco3`
23. `operacao.0013_fundacao_bloco3`
24. `operacao.0014_piloto_jornada_contratual`
25. `ordens.0012_piloto_jornada_contratual`

Operações revisadas: AddField, CreateModel, AddConstraint, AddIndex, AlterField e uma RunPython. Não há DeleteModel, RemoveField ou RunSQL nas pendentes. `gestao.0007_origem_parcelas_existentes` preenche somente o novo campo de origem raiz, preserva valores anteriores e rejeita ciclos/organizações inconsistentes. Migrations publicadas não foram editadas. O ensaio passou com o estado real do snapshot; se novos dados entrarem antes da publicação, reavaliar constraints e atualizar o backup.

Aplicadas no publicado (inventário completo, agrupado por aplicativo; a ordem abaixo é de inventário, não uma ordem para reaplicação):

### admin

- `admin.0001_initial`
- `admin.0002_logentry_remove_auto_add`
- `admin.0003_logentry_add_action_flag_choices`

### auth

- `auth.0001_initial`
- `auth.0002_alter_permission_name_max_length`
- `auth.0003_alter_user_email_max_length`
- `auth.0004_alter_user_username_opts`
- `auth.0005_alter_user_last_login_null`
- `auth.0006_require_contenttypes_0002`
- `auth.0007_alter_validators_add_error_messages`
- `auth.0008_alter_user_username_max_length`
- `auth.0009_alter_user_last_name_max_length`
- `auth.0010_alter_group_name_max_length`
- `auth.0011_update_proxy_permissions`
- `auth.0012_alter_user_first_name_max_length`

### clientes

- `clientes.0001_initial`
- `clientes.0002_cliente_organization_alter_cliente_cpf_cnpj_and_more`
- `clientes.0003_require_organization`
- `clientes.0004_cliente_inscricao_estadual_and_more`

### contas

- `contas.0001_initial`
- `contas.0002_tecnico_organization_alter_tecnico_usuario_and_more`
- `contas.0003_require_organization`
- `contas.0004_alter_usuario_perfil`
- `contas.0005_alter_usuario_perfil`
- `contas.0006_alter_usuario_perfil`

### contenttypes

- `contenttypes.0001_initial`
- `contenttypes.0002_remove_content_type_name`

### equipamentos

- `equipamentos.0001_initial`
- `equipamentos.0002_categoriaequipamento_organization_and_more`
- `equipamentos.0003_require_organization`
- `equipamentos.0004_organization_upload_paths`
- `equipamentos.0005_equipamento_criticidade_equipamento_data_aquisicao_and_more`
- `equipamentos.0006_alter_equipamento_criticidade`

### gestao

- `gestao.0001_initial`
- `gestao.0002_contrato_cobertura_pecas_contrato_cobertura_servicos_and_more`
- `gestao.0003_movimentacao_destino_movimentacao_origem_and_more`
- `gestao.0004_orcamento_numero_personalizado`
- `gestao.0005_movimentacao_detalhamento_peca_controla_validade`

### operacao

- `operacao.0001_initial`
- `operacao.0002_compra_pedido_relatorio_id_compra_selecao_relatorio_and_more`
- `operacao.0003_detalhar_saldos_legados_em_lotes`
- `operacao.0004_compra_compra_relatorio_request_unico`
- `operacao.0005_configuracao_painel_blocos_and_more`

### ordens

- `ordens.0001_initial`
- `ordens.0002_localizacao_geo_resultado_coerente_and_more`
- `ordens.0003_ordemservico_organization_and_more`
- `ordens.0004_conferencia_issuer`
- `ordens.0005_require_organization`
- `ordens.0006_private_object_key_length`
- `ordens.0007_ordemservico_valor_cobranca_and_more`
- `ordens.0008_ordemservico_agendada_para_ordemservico_checklist_and_more`
- `ordens.0009_ordemservico_agendada_ate_alter_ordemservico_tecnico`

### platform_core

- `platform_core.0001_initial`
- `platform_core.0002_tecnolmed_backfill`
- `platform_core.0003_alter_organizationmembership_role`
- `platform_core.0004_membershiperp_visualizar_painel_operacional_and_more`

### sessions

- `sessions.0001_initial`

## Git e validações preservadas

Pacote completo: **418 arquivos**; candidatos ao futuro commit: **179 arquivos modificados/novos**, listados integralmente em `PACOTE_GIT_PREDEPLOY_PILOTO_TECNOLMED.md`. Os demais arquivos versionados continuam no pacote. Comparação dos 47 arquivos publicados dos diretórios de migrations (39 migrations + 8 init) passou. Index permaneceu vazio/inalterado; nenhum git add, commit, fetch, push ou deploy.

Varredura de padrões de credenciais e valores conhecidos: PASS; comparação dos segredos Render/R2 feita exclusivamente em memória: PASS, zero correspondências no pacote. `.env.example` é um template com campos sensíveis vazios; a URL autenticada encontrada em `platform_core/test_deployment.py` é um literal sintético de teste. Não entra nenhum `.env` real, banco local, dump, chave, certificado, token, upload privado, virtualenv, static coletado ou `tmp/validation`.

Única alteração de dependência acumulada versus publicado: Django 5.0.9 → 5.2.17, já validada no piloto. Nenhuma dependência foi atualizada nesta etapa. As fontes da aplicação coincidem com os hashes da suíte anterior **441/441 testes PostgreSQL PASS, zero falhas/skips**. Check, makemigrations --check --dry-run e collectstatic anteriores passaram; não foram repetidos. Nenhuma homologação do Bloco 3H foi refeita.

Jornada Contratual, bloqueio da OS e PDF mantêm os resultados locais documentados em `RELATORIO_IMPLANTACAO_PILOTO_TECNOLMED.md` e `VALIDACAO_IMPLANTACAO_PILOTO_TECNOLMED.json`. PWA permanece pronta localmente e pendente de homologação física. Essas jornadas não foram executadas com a nova versão em produção nesta auditoria. O GET de saúde acordou o Web Free; não foi solicitado restart/deploy. Logs do deploy publicado confirmaram Django 5.0.9 e inicialização; não foi realizada uma auditoria exaustiva de erros 500 nem login com escrita de sessão nesta etapa.

## Risco confirmado de rollback

**Reverter somente o código para fe6c554 após aplicar as migrations não é seguro para escrita.** Foram identificadas **63 colunas novas NOT NULL sem default persistente em tabelas anteriores**. A inserção pelos campos do código publicado em `contas_tecnico`, na cópia local migrada, falhou com PostgreSQL **23502** no campo novo `competencias`. A transação da prova foi integralmente revertida. Nenhum registro de teste foi inserido no banco publicado. Essa falha esperada confirma incompatibilidade; não é falha do ensaio das migrations nem dos 441 testes.

Um retorno de código compatível com o schema novo ainda não foi preparado/testado. Não alterar migrations antigas nem inverter automaticamente migrations para tentar resolver. A preparação de uma versão de contingência compatível, ou um plano equivalente de recuperação aprovado, precisa de autorização específica; não foi implementada nesta etapa de auditoria. **Não autorizar o push/deploy enquanto essa pendência não estiver resolvida.**

## Sequência futura de deploy — executar somente após autorização

1. Resolver e validar o rollback compatível com o schema alvo; decidir a continuidade do banco Free antes de 30/10. Confirmar janela, responsável e suspensão de novas operações pelos usuários. O plano Free atual não disponibiliza manutenção gerenciada nesta configuração; não contratar recurso pago nem alterar settings implicitamente.
2. Reconfirmar remoto `main`, commit Live, vínculo do banco/R2 e ausência de alterações inesperadas. Se o remoto avançou, preservar sua história e interromper para reconciliar; não forçar/amendar/resetar. Revalidar pacote e segredos antes do commit. Não reconstruir funcionalidades nem repetir a suíte sem mudança de fonte/risco novo.
3. Produzir backup consistente atualizado imediatamente antes da janela se houver mudanças desde este snapshot; validar arquivo e restore correspondente. Arquivo/credenciais permanecem privados. Garantir disponibilidade do backup fora do container efêmero Render; a cópia local atual exige guarda segura pelo responsável.
4. Preparar o commit com a lista explícita de candidatos; inspecionar o diff staged, exclusões, migrations antigas e fontes testadas. Não usar `git add .` indiscriminadamente. Commit só após autorização para esta publicação.
5. Push normal para `origin/main`, preservando histórico. **On Commit dispara o deploy imediatamente**, portanto autorização de push deve incluir as 25 migrations automáticas. Não fazer push preparatório separado pensando que as migrations esperarão autorização posterior.
6. Acompanhar build: Python 3.12 da imagem, pip/requirements (Django 5.2.17), COPY e collectstatic; conferir o SHA exato da imagem/deploy. Falha de build antes da execução não aplica migrations; confirmar estado do serviço anterior e do banco.
7. Acompanhar start: `migrate_locked --noinput` executa as 25 pendentes na ordem acima, usando a DATABASE_URL existente. Conferir recurso e plano antes da execução. Não chamar makemigrations, flush, fake indiscriminado ou reset. Esperado: 82 migrations totais; o banco pode ter alterações parciais se uma migration falhar, exigindo inspeção e plano aprovado.
8. Gunicorn inicia somente depois do sucesso das migrations. Conferir bind/boot/workers, ausência de erro de inicialização e status Live. Verificar `/health/` manualmente e confirmar commit novo. O Health Check Path vazio no serviço **não permite prometer checagem automática específica de `/health/`**. Se for configurá-lo, pedir autorização específica para essa alteração de setting, sem sincronizar o Blueprint divergente.
9. Comparar contagens e hashes dos registros antigos antes de liberar escrita. Testar login/organização/perfis e módulos principais: clientes, equipamentos, OS, triagem/técnico, contratos/Jornada Contratual/bloqueio, planejamento/preventivas, estoque/FEFO/necessidade de peça, compras/recebimento, vendas, financeiro, orçamentos, relatórios/PDF e Painel TV. Executar smoke controlado de upload/leitura privada R2 com registros identificados de homologação, só na autorização de publicação. Validar PWA no dispositivo real, HTTPS, instalação, câmera/assinatura e comportamento offline conforme escopo. Não ativar Cron/runner. Inspecionar logs por erros 500 e registrar quais jornadas realmente passaram.
10. Liberar operação apenas após aceite das verificações. Não declarar homologação real completa com base apenas nos testes sintéticos. Registrar commit, migrations, contagens e pendências efetivas.

## Contingência e rollback

- Antes de qualquer alteração do banco: se o build falhar, manter/verificar o serviço Live anterior e investigar sem reaplicar migrations. Reavaliar também qualquer efeito de inicialização se o container já chegou ao start.
- Após uma ou mais migrations: suspender escrita e registrar schema aplicado. Não clicar em rollback para fe6c554 e presumir compatibilidade: o teste local demonstrou falha. Usar somente a versão de contingência previamente preparada/testada ou recuperação/correção incremental aprovada, acompanhando logs e integridade.
- Restauração em produção é uma operação diferente, pode perder alterações posteriores ao backup e requer autorização explícita, janela e plano de preservação. Não está autorizada nesta etapa. Não fazer downgrade destrutivo, drop, reset, flush ou restore automático sobre o banco publicado.
- Não há ainda artefato de rollback compatível aprovado. Esse é o bloqueio técnico remanescente para um deploy controlado com retorno seguro.

## Limites e registro de segurança

Nesta etapa houve leitura autorizada do ambiente publicado e backup, sem escrita no banco remoto. O restore/ensaio/prova de rollback ocorreram exclusivamente em banco local isolado no cluster já existente. Nenhuma funcionalidade, credencial, infraestrutura ou migration antiga foi alterada. Nenhum commit, push, deploy ou runner foi realizado/ativado.

A revisão automática rejeitou a tentativa de persistir chaves AWS e SECRET_KEY em arquivo protegido, por ausência de autorização específica e disponibilidade de auditoria em memória. Um arquivo temporário de transferência havia sido criado e foi removido imediatamente; esses valores não permaneceram em disco nem no Git. A auditoria foi concluída em memória. A conexão do banco, necessária ao backup autorizado, permanece somente na pasta privada ignorada com ACL restritiva.

Pendências: rollback compatível; continuidade do PostgreSQL Free; Health Check Path vazio; I/O funcional R2; patch Python publicado não aferido; jornadas novas com dados reais, PWA física e observação de logs pós-publicação. **Parar e aguardar autorização.**
