# VERTYX — preparação da homologação R2

## Escopo e estado

- Branch local: `codex/homologacao-r2`, criada a partir de `a51a7ab512965e06dfd9e3a78b4e40357c728849`.
- `main` preservada; nada foi commitado, enviado ou publicado.
- Serviço autorizado: `vertyx-erp` (`srv-dauq0560tbcc73c81nqg`).
- Serviço a preservar: `tecnolmed-erp` (`srv-dauphinpn0mc738kee2g`).
- PostgreSQL permitido: `vertyx-postgres-testes` (`dpg-dbm7jfc9v7es7393tsig-a`), banco `vertyx_testes`, usuário `vertyx_testes_user`, porta 5432, PostgreSQL 16.
- DATABASE_URL do serviço de testes foi salvo anteriormente com Save only na conexão interna; o processo antigo não foi reiniciado.
- Última consulta remota somente leitura: PostgreSQL 16.15, zero tabelas de aplicação, django_migrations ausente, zero outras conexões de cliente.
- Isso não comprova isolamento de rede absoluto: o banco admite IPs externos 0.0.0.0/0. Não alteramos essa regra.

## Executor de preflight e plano — sem aplicação

`scripts/homologation_migrations.py` não implementa migrate, --apply, criação de
banco, schema, tabelas, usuários ou fixtures. O argumento --apply é rejeitado.
O plano descreve o que será aplicado após nova autorização; não executa funções
RunPython/RunSQL nem sinais post_migrate. Não carrega .env nem as settings
operacionais, não consulta o R2 e não herda DATABASE_URL de produção.

Plano offline, para banco vazio, sem conexão:

```text
python -B scripts/homologation_migrations.py --offline
```

Preflight remoto e plano (somente leitura), depois de disponibilizar ao processo
as variáveis temporárias descritas abaixo:

```text
python -B scripts/homologation_migrations.py
```

- `VERTYX_TEST_DATABASE_URL`: conexão existente do banco autorizado, informada
  por ambiente seguro; não colocar em argumento, arquivo, chat ou log. Usar o
  endpoint externo apenas no executor local; preservar o interno no Render.
- `VERTYX_TEST_SSLROOTCERT`: caminho para um bundle CA confiável já disponível.
  Não gerar certificados, chaves clínicas ou credenciais. Se não houver CA ou
  acesso seguro à conexão, interromper; nunca desabilitar validação TLS.
- Hosts exatos aceitos: `dpg-dbm7jfc9v7es7393tsig-a` (rede Render) ou
  `dpg-dbm7jfc9v7es7393tsig-a.oregon-postgres.render.com` (executor externo).
- Rejeita host, banco, usuário ou porta diferentes, query strings, fragments,
  senha ausente, fallback para DATABASE_URL e configurações TLS alternativas.
- Exige verify-full, validação do hostname e CA. A sessão já nasce somente
  leitura, com search_path=public, connect_timeout=5s, lock_timeout=5s e
  statement_timeout=30s.
- Após conectar, valida banco/usuários/porta/versão/owner, TLS >=1.2, estado fora
  de recuperação, banco vazio e nenhuma outra conexão de cliente.
- Faz apenas SELECT; rollback e close ao final, inclusive em falha. Mensagens de
  erro são fixas, sem DSN, exceções brutas, senha ou traceback.
- O plano completo identifica dependências, operações de dados e hash do código
  de cada migration, com normalização de quebras de linha para Windows/Linux.

O preflight real deste executor ainda depende do ambiente temporário seguro e
do bundle CA. Testes locais usam mocks e não comprovam TLS real do executor.
A consulta remota de metadados foi realizada pelo conector Render em read-only.

## Plano Django para banco vazio

Total: **137 migrations**, com grafo resolvido e sem conflitos. Inventário
completo em `docs/HOMOLOGACAO_R2_MIGRATIONS_PLAN.json`.

Hash do plano: `bdf38109ef7ed3abeb746685229dcbd2629a75056a1c494d7a85a97135104ed2`.

| App | Migrations |
| --- | ---: |
| admin | 3 |
| auth | 12 |
| clientes | 5 |
| commercial | 1 |
| contas | 9 |
| contenttypes | 2 |
| equipamentos | 7 |
| gestao | 17 |
| operacao | 28 |
| ordens | 12 |
| platform_core | 24 |
| rh_municipal | 16 |
| sessions | 1 |

O plano termina, entre outros, em platform_core.0024, operacao.0028,
ordens.0012 e rh_municipal.0016. Não aplicar apenas a 0016 num banco vazio:
suas dependências e as demais tabelas necessárias ainda não existem.

Há **23 migrations com RunPython/RunSQL**. Isso inclui seed do catálogo
comercial, produtos, módulos e um tenant legado com slug tecnolmed em
platform_core.0002. São dados definidos nas migrations, não cópia de dados reais.
A inicialização futura não será apenas DDL: Django também cria content types e
permissões por post_migrate. Nenhuma dessas operações foi executada nesta etapa.
Não alterar migrations históricas, não gerar migration nova e não criar DEMO,
contas ou registros operacionais junto da inicialização sem autorização.

## Startup separado, sem migrations

`scripts/start-homologation.sh` recusa settings diferentes de
tecnolmed.homologation_settings e executa somente Gunicorn. Proposta de Docker
Command para vertyx-erp, após autorização:

```text
/bin/sh /app/scripts/start-homologation.sh
```

O Dockerfile e scripts/start.sh existentes foram preservados. O CMD padrão
continua executando migrate_locked; portanto é obrigatório configurar e conferir
o override antes de publicar a homologação. Conferir também pre-deploy hooks,
Blueprints e jobs. Não executar start.sh nem migrate_locked nesta preparação.
O collectstatic do build não deve abrir banco ou bucket; revalidar no ensaio da
imagem final. Não aplicar render.yaml automaticamente.

## R2 — configuração pendente, não aplicada nesta etapa

Manter as chaves existentes no Render, sem exibir, alterar, criar ou revogar.
A origem/validade dessas chaves ainda não foi comprovada pelo teste real.
Configuração proposta somente no vertyx-erp:

| Variável | Valor |
| --- | --- |
| DJANGO_SETTINGS_MODULE | tecnolmed.homologation_settings |
| HOMOLOGATION_STORAGE | r2 |
| DEBUG | False (preservar) |
| S3_BUCKET_NAME | vertyx-homologacao (preservar) |
| S3_ENDPOINT_URL | endpoint HTTPS S3 da conta R2, sem /bucket (preservar) |
| S3_REGION_NAME | auto (preservar) |
| S3_ADDRESSING_STYLE | path (preservar) |
| AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY | credenciais existentes (preservar) |

HOMOLOGATION_STORAGE=disabled continua padrão. Configuração incompleta mantém
uploads bloqueados; configuração inválida falha sem mostrar segredos. Não há
fallback local em homologação. Uploads habilitados usam prefixes por organização
e autorização Django; não publicar bucket nem habilitar r2.dev/custom domains.

## Sequência sujeita a autorizações separadas

1. Revisar e aprovar o SHA e este plano; somente então commit local dos arquivos
   revisados, excluindo material_comercial, temporários, bancos, logs e segredos.
2. Autorizar push exclusivo da branch codex/homologacao-r2, sem merge/push main.
   Verificar antes os serviços, autodeploy e Blueprint: tecnolmed-erp é gerenciado
   por Blueprint e deve permanecer inalterado. Congelar autodeploy da homologação.
3. Autorizar configuração somente de vertyx-erp: branch exclusiva, autodeploy
   off, settings, seletor R2 e Docker Command sem migrate; sem deploy implícito.
4. Autorizar especificamente a inicialização manual do banco vertyx_testes.
   Antes de escrever, ampliar o executor em revisão própria para reutilizar as
   mesmas guardas em TODAS as conexões, repetir identidade/banco vazio, comparar
   SHA aprovado/hash do plano e exigir confirmação explícita. Usar lock de
   migração, timeout e usuário autorizado; nenhum fallback ou outro alias.
   O executor atual é deliberadamente somente leitura e não pode aplicar nada.
5. Após aprovação, aplicar uma vez as migrations do SHA revisado somente ao
   banco autorizado. Revalidar identidade antes da primeira escrita e confirmar
   137 migrations, tabelas, constraints e ausência de pendências ao final.
   Em erro, parar sem fake, reset, drop, retries ou reparo automático.
6. Autorizar deploy manual exclusivamente do vertyx-erp, fixando o SHA aprovado;
   validar /health, TLS, cookies, logs e ausência de migrations no startup.
7. Autorizar dados DEMO/usuários para testes em duas organizações fictícias,
   usando serviços de planos/produtos/memberships/convites existentes.
8. Executar checklist funcional abaixo e registrar evidências por módulo.

Rollback de código não reverte schema. Confirmar imagem de retorno e
compatibilidade antes do deploy. No banco inicialmente vazio, falha de migration
pode deixar migrations anteriores aplicadas: não apagar ou desfazer automaticamente.
Não restaurar DATABASE_URL para o banco suspenso como contingência.

## Homologação funcional planejada

- Autenticação, convite/primeiro acesso, logout, sessão, papéis somente leitura,
  CSRF, auditoria e IDOR entre duas organizações.
- Assistência: clientes/unidades/equipamentos, OS do cadastro à assinatura/PDF,
  peças, estoque e saldo, contratos, vendas/PDV e financeiro.
- R2: foto, logo, documento/anexo e PDF fictícios, hash/integridade, download
  autenticado, negativa entre tenants, acesso anônimo negado no S3 e exposição
  pública desabilitada; excluir apenas objetos de teste identificados.
- Falha de conexão: mensagem sanitizada, sem fallback, alteração parcial ou
  exposição de credenciais; registrar eventuais objetos órfãos sem limpeza ampla.
- PWA/cache: não armazenar arquivos privados/clínicos, tokens ou conteúdo sensível.
- Produtos municipais/saúde: liberar somente após validação própria de permissões,
  vínculo profissional, auditoria e criptografia com configuração legítima. Não
  gerar chave clínica, prontuários ou expor módulos com bloqueios conhecidos.
- Inventariar todas as telas existentes, classificando cada módulo com evidências;
  licitações com falha conhecida e integrações fiscais/bancárias/governamentais
  reais continuam bloqueadas. Não declarar a plataforma inteira pronta com base
  apenas nos testes de R2. A suíte completa não foi executada nesta etapa.


## Verificações desta preparação

- 10 testes do executor/startup aprovados, sem banco real.
- 8 testes de configuração R2/disabled aprovados; Django informou que o banco
  default não foi utilizado. Todas as conexões de banco e rede estavam bloqueadas.
- check sem problemas; check --deploy apenas avisos HSTS W005 e W021.
- Grafo offline com 137 migrations e dependências coerentes; nenhuma aplicada.
- git diff --check aprovado; nenhuma migration histórica modificada nesta etapa.
- scripts/start.sh e Dockerfile existentes preservados. Startup novo verificado
  estaticamente; não foi iniciado um servidor ou executado shell de produção.
- Schema remoto conferido exclusivamente por SELECT em transação read-only.
- Evidências locais em output/homologation_preparation_20261105 (não versionar).
