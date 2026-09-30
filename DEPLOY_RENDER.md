# VERTYX Assistência: homologação externa

Preparação concluída em 30/09/2026. Nenhum recurso externo, deploy ou push foi
feito. Não há URL Render, bucket, endpoint ou credencial externa configurados.
Preencha os valores em branco de `.env.example` com dados obtidos nos painéis.
Nunca publique `.env`, URL de banco com senha ou chaves no repositório. O ZIP
contém código, não backup de dados reais.

Plano escolhido pelo usuário: **Free** para Web Service e PostgreSQL, confirmado
na [referência Blueprint do Render](https://render.com/docs/blueprint-spec) em
30/09/2026. Docker, PostgreSQL, S3, migrations e demais opções foram mantidos.

## O que criar e em que ordem

### 1. Preparar o repositório e escolher a região

Disponibilize somente o código de `tecnolmed_erp` em seu repositório. Exclua
ambientes virtuais, `tmp`, mídias, bancos locais e secrets. Não houve envio ao
GitHub nesta entrega. Escolha uma região Render para o Web Service e PostgreSQL.

Se houver dados anteriores, primeiro faça e teste backup conjunto do banco,
`MEDIA_ROOT` e `PRIVATE_MEDIA_ROOT`. Uma instalação nova aplica todas as
migrations; uma atualização aplica somente as pendentes. Não gere migrations
durante deploy, não use `--fake`, não apague banco ou volumes.

### 2. Criar o PostgreSQL no Render

No painel: **New > Postgres**. Crie uma instância dedicada à homologação,
escolha PostgreSQL **16** (versão principal validada nesta entrega), a mesma
região do futuro Web Service e **Compute Plan: Free**. Nome de exibição,
nome do banco e usuário são sua escolha; o Render
também pode gerar os campos opcionais. Aguarde o banco ficar disponível.

Copie **Internal Database URL**, em **Connect**, para `DATABASE_URL` no serviço
web. Mantenha `DATABASE_SSL_REQUIRE=True`: o código exige TLS (`sslmode=require`).
Não substitua hostname por IP. Restrinja/desabilite acesso externo se não
precisar dele; em manutenção externa, libere somente o IP necessário e use
a URL externa fornecida pelo painel, com TLS. Veja a [documentação de criação
e conexão](https://render.com/docs/postgresql-creating-connecting).

O PostgreSQL Free tem 1 GB, expira em **30 dias**, não tem backup gerenciado e
permite uma instância gratuita ativa por workspace. Anote a data de expiração
e faça exportações locais com cliente PostgreSQL 16 (`pg_dump`), usando a
conexão externa real e credenciais guardadas com segurança. Teste restauração
em base isolada e preserve exportação antes de expirar. Pode validar restart
e redeploy dentro desse prazo; o plano não oferece persistência indefinida.
Consulte as [limitações gratuitas](https://render.com/docs/free).

### 3. Criar o storage Cloudflare R2

Recomendo **Cloudflare R2**, pela API S3-compatible e integração boto3 já usada
pelo projeto. Fotos/documentos passam pelo Django. A política de [preços do
R2](https://developers.cloudflare.com/r2/pricing/) não cobra egress do R2;
armazenamento e operações podem ter custo. Django Storage permite trocar para
outro provedor S3-compatible por ambiente. Não houve contratação nesta entrega.

No painel Cloudflare:

1. Ative **R2 Object Storage**, revendo a cobrança solicitada no painel.
2. Crie **um bucket privado dedicado à homologação**, com nome escolhido por
   você. Use classe Standard para este fluxo de leitura frequente.
3. Deixe **Public Development URL / r2.dev desabilitado** e não conecte domínio
   público ao bucket. Não crie lifecycle de expiração das evidências nesta fase.
4. Em R2, crie token de API com **Object Read & Write**, opção **Apply to
   specific buckets only**, selecionando somente esse bucket.
5. Guarde **Access Key ID** e **Secret Access Key** em gerenciador de segredos:
   são `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY`. Não use o texto do token
   REST como substituto das credenciais S3.
6. Copie o **S3 API endpoint** da sua conta/jurisdição para `S3_ENDPOINT_URL`.
   Não invente nem use URL pública de objeto. Configure `S3_REGION_NAME=auto`
   e `S3_ADDRESSING_STYLE=path`.

Não é necessário CORS de navegador, CDN, Worker, domínio público ou criação
manual de pastas. Backend faz upload/download e cria os prefixos `private` e
`media`. Veja [credenciais S3](https://developers.cloudflare.com/r2/get-started/s3/),
[boto3](https://developers.cloudflare.com/r2/examples/aws/boto3/) e
[acesso público](https://developers.cloudflare.com/r2/buckets/public-buckets/).

### 4. Criar um Web Service Docker no Render

No painel: **New > Web Service**, conecte repositório e branch desta entrega,
selecione **Docker**, mesma região do banco e **Instance Type: Free**. Uploads
continuam no R2, dados no PostgreSQL. Não precisa de disco persistente web.
O Free dorme após 15 minutos sem tráfego e não oferece Shell/SSH ou jobs
avulsos. Tráfego externo alto (incluindo storage) pode causar suspensão;
acompanhe Usage e use volume pequeno de homologação. [Limites Free](https://render.com/docs/free).

Se `Dockerfile` estiver na raiz do repositório, deixe Root Directory vazio.
Se o repositório contiver o diretório externo `tecnolmed_erp`, use Root Directory
`tecnolmed_erp`. Dockerfile Path: `./Dockerfile`, relativo a essa raiz.
Health Check Path: **`/health/`**. Nome de exibição é sua escolha; copie o
hostname real quando o Render o atribuir. Não há hostname antecipado aqui.

Alternativa: `render.yaml` como Blueprint para criar o par web/banco em Free.
Informe as variáveis `sync: false`. Os nomes
técnicos anteriores `tecnolmed-erp`/`tecnolmed-db` foram preservados. **Escolha
criação manual ou Blueprint**; não aplique o Blueprint depois de criar
manualmente o mesmo par. Na criação manual, cole a URL interna no ambiente;
no Blueprint, `fromDatabase` vincula a conexão. [Referência Blueprint](https://render.com/docs/blueprint-spec).

### 5. Configurar Environment do Web Service

Configure antes do primeiro deploy bem-sucedido. Segredos ficam somente no
painel. Nunca use settings de teste no serviço.

| Variável | Valor/fonte |
|---|---|
| `DEBUG` | `False` |
| `SECRET_KEY` | Aleatória e exclusiva, pelo menos 50 caracteres; gerada pelo Render no Blueprint ou por gerador seguro e inserida somente no painel |
| `DATABASE_URL` | Internal Database URL da etapa 2; contém senha |
| `DATABASE_SSL_REQUIRE` | `True` |
| `CONN_MAX_AGE` | `60` segundos; health checks de conexão já habilitados no código |
| `UPLOAD_STORAGE` | `s3` |
| `S3_BUCKET_NAME` | Nome exato do bucket criado |
| `S3_ENDPOINT_URL` | S3 API endpoint HTTPS copiado do painel R2 |
| `S3_REGION_NAME` | `auto` no R2 |
| `S3_ADDRESSING_STYLE` | `path` |
| `AWS_ACCESS_KEY_ID` | Access Key ID do token restrito ao bucket |
| `AWS_SECRET_ACCESS_KEY` | Secret Access Key do mesmo token |
| `ALLOWED_HOSTS` | Hostname real sem protocolo/caminho; adicionais separados por vírgula |
| `CSRF_TRUSTED_ORIGINS` | Origem HTTPS real sem caminho; adicionais separadas por vírgula |
| `LOG_LEVEL` | `INFO` |
| `WEB_CONCURRENCY` | `2` inicialmente; ajustar segundo RAM e carga |
| `TIME_ZONE` | `America/Maceio`, padrão preservado |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `False` inicialmente; habilitar somente com todos os subdomínios sob seu controle e HTTPS |
| `SECURE_HSTS_PRELOAD` | `False`; não solicitar preload nesta fase |

O Render injeta `PORT` e `RENDER_EXTERNAL_HOSTNAME`; não invente esses valores.
O código acrescenta automaticamente o hostname Render a hosts e origens CSRF.
Assim, os dois campos explícitos podem ficar vazios enquanto houver apenas
esse domínio automático; use dados reais ao adicionar domínio próprio. Nunca
use `*`. R2 com token normal não exige `AWS_SESSION_TOKEN`; deixe ausente.
Esse campo opcional é usado somente com credenciais temporárias de outro
provedor que o exija.

`POSTGRES_*`, `MEDIA_ROOT` e `PRIVATE_MEDIA_ROOT` são de desenvolvimento/migração
local, não são necessários no Render. Uma chave forte pode ser gerada por
Python `secrets.token_urlsafe(64)` em máquina de confiança, guardada e colada
somente no painel. Não imprima o ambiente inteiro em logs.

### 6. Deploy, migrations e primeiro operador

Em Docker, deixe Build Command e Docker Command/Start override sem comando
adicional: Render usa o [Dockerfile e CMD](https://render.com/docs/docker).

- Build instala `requirements.txt` e executa `python manage.py collectstatic
  --noinput`. Não conecta ao banco/bucket e não recebe segredos no Dockerfile.
- Start: `/bin/sh /app/scripts/start.sh`.
- O script executa `python manage.py migrate_locked --noinput`, depois
  `gunicorn tecnolmed.wsgi:application --config gunicorn.conf.py`.
- `migrate_locked` usa advisory lock PostgreSQL e espera até 120 segundos.
  Falha ao obter lock ou aplicar migration impede o serviço novo de iniciar.
  Deploys concorrentes não aplicam migrations simultaneamente.
- Deixe Pre-deploy Command vazio: esse recurso é pago e não é necessário.
  O start aplica as migrations com lock, como já configurado, e faz conferência
  sem efeitos quando não houver pendências. Nunca execute
  `makemigrations` gerando arquivos no deploy.

Confira **Live**, health 200 com `{"status":"ok"}`, login e estáticos.
Health verifica aplicação e uma consulta ao banco; S3 é verificado pelo teste
de upload. Como Free não tem Shell, execute os checks e crie o operador **na
sua máquina**, após o deploy aplicar as migrations:

1. Use Python 3.12 e um ambiente virtual na pasta desta entrega; instale
   `requirements.txt`. No ambiente já preparado, use o Python da venv existente.
2. Crie `.env` local a partir de `.env.example`. Preencha `DATABASE_URL` com
   **External Database URL** real do Render, `DATABASE_SSL_REQUIRE=True`,
   `DEBUG=False`, chave forte e configuração S3 real. Para esse processo local,
   defina `ALLOWED_HOSTS=localhost,127.0.0.1` e CSRF_TRUSTED_ORIGINS vazio.
   Não altere a URL interna usada no Web Service. Nunca versione esse `.env`.
3. Libere temporariamente seu IP para conexão externa do banco. Execute abaixo
   com Python da venv; informe a senha do administrador no prompt.
4. Ao terminar, restrinja novamente o acesso externo. Não imprima secrets nos
   logs nem copie credenciais para código, Git ou comandos versionados.

No Windows, se precisar criar o ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Com o `.env` preenchido, execute usando esse Python da venv:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py showmigrations
python manage.py check --deploy --fail-level ERROR
python manage.py createsuperuser
```

`check --deploy` tem avisos deliberados `security.W005` e `W021` sobre HSTS em
subdomínios/preload. HSTS de 3600 segundos, HTTPS, cookies seguros, nosniff e
proxy já estão configurados. Não silencie esses avisos para alegar validação
de domínios ainda desconhecidos; reavalie no domínio definitivo.

Em `/admin/`, confirme TECNOLMED e Assistência criadas pela migration. Preencha
os dados legais reais. Crie conta comum com OrganizationMembership ativo,
papel ADMIN, OrganizationERP e MembershipERP de Assistência habilitados.
Superuser é operador VERTYX, sem bypass no ERP. Crie contas comuns/técnicos
para a equipe e atribua OS. Não rode `seed_demo` em base com dados reais.

### 7. Validar a homologação externa e persistência

Execute [CHECKLIST_HOMOLOGACAO.md](CHECKLIST_HOMOLOGACAO.md): Home, duas empresas,
upload, assinatura, PDF, GPS e permissões. No R2 confirme novos objetos e que
requisição anônima à API não lê evidências. Revogue acesso de um usuário e
confirme bloqueio na próxima requisição.

Após criar OS, foto e assinatura, faça **Restart Service** e depois redeploy,
sem recriar banco/bucket. Confira OS, arquivos, hashes, snapshot e PDF. Registre
data, build, navegador/aparelho. Reinício local foi testado; Render e celular
físico ainda dependem desta configuração.

Execute a suíte numa base **exclusivamente de testes**, com usuário autorizado
a criar bases temporárias, nunca na base com dados reais. Instale
`requirements-test.txt` somente nesse ambiente e use
`--settings=tecnolmed.test_postgres_settings`. Teste backup/restauração conjunta
de banco e objetos antes de liberar dados reais.

## Migrar uploads existentes, quando houver

Fotos de OS/logomarca usam `private`; fotos/manuais/QR de equipamentos usam
`media`. Assinaturas e snapshots continuam no PostgreSQL. PDF é gerado pela
rota autorizada sem persistir em disco. Nunca sirva `/media/` diretamente por
proxy/CDN nem torne público o bucket.

Numa máquina de manutenção de confiança, com cópia do banco já migrada,
diretórios originais disponíveis, dependências e ambiente apontando para S3,
execute em janela sem escrita concorrente de uploads:

```sh
python manage.py migrate_uploads --source-private /copia/media_private --source-media /copia/media --manifest plano-upload.json
python manage.py migrate_uploads --source-private /copia/media_private --source-media /copia/media --manifest copia-upload.json --apply
```

Os caminhos são argumentos locais ilustrativos: substitua pelos diretórios do
backup. Primeiro comando planeja/verifica; segundo copia e verifica SHA-256.
Não altera banco, referências, snapshots ou hashes armazenados e não apaga
originais. Objeto idêntico existente é verificado; divergência/ausência falha.
Use execução única sem uploads concorrentes. Manifesto é privado, contém
chaves de objetos. Valide download autorizado e PDF de amostras antes de trocar
o serviço para S3. Mantenha backup original após validar.

## Ponto de parada

Crie os recursos das etapas 2–4 e configure os valores reais da etapa 5.
Sem isso não se pode verificar conectividade, permissões R2, certificado
Render, deploy/redeploy ou celular físico. Código preparado, nenhuma
credencial externa configurada e nenhuma infraestrutura criada.
