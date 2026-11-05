# VERTYX 1.0 Comercial — publicação controlada

Preparação de 05/11/2026. Este documento não autoriza push, deploy, migrations
remotas ou criação de usuários remotos. O pacote parte de `5f57d01`; registrar
o SHA final do commit local aprovado antes de publicar.

## Destino exclusivo

Confirmado pelo responsável: serviço `vertyx-erp`, branch `main`, URL
`https://vertyx-erp.onrender.com`, Live anterior `4844fc5`; novo PostgreSQL 16
`vertyx-postgres-testes`, Oregon. O banco antigo está suspenso e deve permanecer
intocado. O nome do recurso Render não equivale necessariamente ao nome SQL.

O GitHub atual ainda precisa ser reconfirmado por acesso autenticado. Não
considerar a referência local `origin/main` prova de atualização remota.

## Checklist antes de qualquer publicação

- Confirmar serviço, região, repositório, branch e SHA escolhido no painel.
- Controlar Auto-Deploy antes de qualquer push futuro. Não sincronizar Blueprint
  automaticamente: o `render.yaml` não provisiona o banco nem aprova planos.
- Usar a Internal Database URL copiada do recurso **novo**, nunca do suspenso.
- Confirmar `default`, nome SQL, host, porta, versão e ausência de recuperação
  antes de qualquer comando de escrita. Não imprimir a URL ou senha.
- Se houver dados no destino, exigir backup validado e ensaio de restauração;
  não presumir vazio somente pelo nome do banco.
- Selecionar `DJANGO_SETTINGS_MODULE=tecnolmed.homologation_settings`.
- Conferir `DEBUG=False`, `DATABASE_SSL_REQUIRE=True`, `SECRET_KEY` adequada,
  hosts/origens HTTPS específicos e `UPLOAD_STORAGE=s3`.
- Usar bucket privado exclusivo DEMO, credenciais restritas e persistência
  verificada. Não apontar a dados operacionais existentes.
- Revisar Environment Groups, credenciais externas, Cron Jobs e Background
  Workers. Não iniciar `processar_estoque --loop` nesta rodada.
- Não configurar certificados fiscais, pagamentos, mensageria ou integrações
  governamentais reais. Nenhuma chave clínica deve ser gerada ou substituída.
- Validar o build Docker Linux autorizado. Ele não foi executado localmente.

As settings de homologação descartam e-mails com backend dummy, desligam
simulação fiscal/NFC-e local e usam cookies exclusivos. Não mudam banco ou
storage por conta própria nem bloqueiam todo serviço externo de terceiros:
a revisão de credenciais e tarefas no painel continua necessária.

Para trocar `DATABASE_URL`: banco novo → Connect → Internal Database URL;
Web Service → Environment → editar a variável existente. **Save only** não
publica e só entra em vigor no próximo deploy. As outras opções de salvamento
podem iniciar publicação. Não importar `.env` local.

## Inicialização e migrations

O Dockerfile executa `collectstatic` e inicia `scripts/start.sh`. Esse script
executa `migrate_locked --noinput` antes do Gunicorn: **o startup aplica todas
as migrations pendentes**, não apenas as comerciais. A autorização de deploy
deve contemplar esse efeito. O advisory lock serializa migradores, mas não é
um backup nem garante ausência de locks de negócio.

Um PostgreSQL 16.15 vazio recebeu as 137 migrations no ensaio local, sem
pendências. Nenhuma migration foi criada ou editada nesta preparação. A
alteração histórica do alias da `rh_municipal/0001` já pertence a `5f57d01`.

## Organização DEMO e três contas

O preparo é explícito, transacional e nunca roda em startup ou migrations:

```sh
python manage.py prepare_commercial_demo \
  --accounts-json /tmp/vertyx-accounts.json \
  --expected-host HOST_INTERNO_CONFIRMADO \
  --expected-database NOME_SQL_CONFIRMADO \
  --private-output /tmp/vertyx-invites.json \
  --confirm-demo-database
```

**Executar somente após autorização remota**, com as settings de homologação
selecionadas. O comando verifica a conexão `default`, versão PostgreSQL 16,
porta e recuperação. Os arquivos de entrada e saída devem ficar fora do
repositório/imagem. A saída é criada exclusivamente, com modo 0600 no Linux;
não sobrescreve links anteriores e não imprime tokens ou senhas no terminal.
Usar diretório privado do operador e conferir ACL se executar em Windows.

Formato de entrada (exemplo fictício; preparar os dados dos titulares apenas
em arquivo privado, fora do Git):

```json
[
  {"nome": "Proprietário DEMO", "email": "proprietario@example.test"},
  {"nome": "Avaliador operacional DEMO", "email": "operacional@example.test"},
  {"nome": "Avaliador financeiro DEMO", "email": "financeiro@example.test"}
]
```

Perfis: proprietário `ADMIN` da organização, avaliadores `TECNICO` e
`FINANCEIRO`. Todos têm `is_staff=False`, `is_superuser=False`, senha
inutilizável até o primeiro acesso e somente o produto Assistência. O técnico
é vinculado à OS DEMO; o financeiro acessa o escopo financeiro. Não possuem
administração da plataforma, usuários ou Django Admin. O proprietário conduz
os fluxos de contratos e operações que exigem administração da organização.

São criados somente dados fictícios: cliente com identificador `DEMO-DOC-001`,
unidade, equipamento, profissional, peça, entrada de estoque, OS, contrato,
recebíveis, orçamento e uma venda em dinheiro no caixa fictício. A venda
reutiliza o serviço comercial e reduz o saldo de 10 para 9. Não há emissão
fiscal nem transferência real; a sessão do caixa DEMO permanece aberta para
avaliação. A organização legada criada pelas migrations não é reutilizada.

O comando recusa DEMO já existente e e-mails de contas existentes, sem alterar
suas senhas ou vínculos. Erros de preparo revertem a transação. Não repetir
automaticamente em caso de falha: conferir estado e arquivo privado primeiro.

Cada link dura 48 horas, é de uso único e permite definir a senha individual.
Somente o digest fica no banco. O resgate revalida usuário, organização e
membership; avaliadores também exigem acesso ativo à Assistência. Contas já
ativadas não podem ter senha redefinida por esse fluxo. CSRF continua exigido.
Entregar os links individualmente por canal privado; e-mail automático está
desligado. O arquivo privado deve ser protegido e removido pelo operador quando
não for mais necessário, conforme política de retenção.

Há serviços `convidar_avaliador` e `reemitir_convite_avaliador`, restritos ao
administrador ativo da mesma organização. A reemissão invalida links pendentes
e não redefine contas ativadas. Não há nova tela de convite nesta tranche:
a preparação inicial usa o comando e reemissões usam o serviço por operador
autorizado, mantendo a saída privada. A reemissão do proprietário permanece
separada e não seleciona o convite mais recente de um avaliador.

## Produtos bloqueados e validação após publicação

Não conceder Gestão Pública, acessos municipais ou prontuário a estas contas.
Licitações, módulos clínicos e integrações oficiais não fazem parte da rodada.
O fiscal integra o core dos planos; omiti-lo da lista de módulos não o remove.
O preparo DEMO nega explicitamente todas as capabilities fiscais para as três
contas, além dos bloqueios nas settings e serviços.

- `/health/` saudável, TLS válido, sem traceback público, cookies seguros.
- Primeiro acesso individual, login e logout; links consumidos/expirados negados.
- Avaliadores sem acesso a usuários, plataforma, Django Admin e produtos bloqueados.
- IDOR por GET/POST entre organizações negado; anexos privados sem acesso cruzado.
- Percorrer cliente/equipamento, OS, estoque, contrato, orçamento/venda e financeiro.
- Conferir auditoria, saldo, recebíveis e persistência dos anexos após reinício.
- Confirmar ausência de operações fiscais, bancárias, governamentais ou mensagens reais.
- Registrar bugs com módulo, passos, esperado/observado e evidência fictícia;
  não anexar senhas, links de convite ou dados reais.

## Rollback e contingência

Registrar SHA publicado, plano de migrations e estado inicial antes da mudança.
Em falha, interromper novas tentativas, preservar logs e restringir acesso de
avaliadores. **Não voltar automaticamente a `4844fc5` sobre o schema novo.**
Não desfazer migrations, apagar bancos ou reconectar ao banco suspenso.

Preferir correção progressiva ou imagem comprovadamente compatível com o schema.
`scripts/start-contingency.sh` só desliga Jornada Contratual; não é rollback geral
desta versão. Restauração exige autorização, backup validado e proteção dos
registros posteriores. Nunca considerar rollback de imagem como rollback de banco.

## Evidências locais

Testes direcionados de convites, reemissão, CSRF, revogação, isolamento, quotas,
auditoria e DEMO; regressões selecionadas de autenticação, SaaS, OS, estoque,
contratos, vendas, financeiro e S3 simulado. A instalação vazia foi ensaiada
em PostgreSQL 16.15 exclusivo, porta 55437, sem ler `.env` operacional e com
conexões externas/outros bancos bloqueadas. O cluster foi parado ao final.

`check`, `makemigrations --check --dry-run` e `git diff --check` aprovados.
`check --deploy` aponta apenas HSTS de subdomínios/preload, mantidos desligados
pois não controlamos os demais subdomínios de `onrender.com`.

O bucket real, TLS do PostgreSQL remoto, build e fluxos online ainda precisam
ser validados após autorização. Testes locais não certificam produção.
