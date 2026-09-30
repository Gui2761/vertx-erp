# VERTYX | ASSISTÊNCIA

Fundação SaaS multiempresa sobre o projeto Django TECNOLMED existente.
Preparação de homologação de 30/09/2026: 89 testes aprovados em PostgreSQL 16.15,
incluindo os 71 anteriores (34 de OS). SQLite explícito: 89 executados, 87
aprovados e dois exclusivos de PostgreSQL ignorados. Storage S3 privado e deploy
Docker/Render preparados. Nenhum recurso externo ou deploy Render foi criado.

Consulte [ENTREGA_HOMOLOGACAO.md](ENTREGA_HOMOLOGACAO.md) para a entrega atual,
[ENTREGA_VERTYX.md](ENTREGA_VERTYX.md) para a fundação,
[ENTREGA_OS.md](ENTREGA_OS.md) para a entrega anterior e
[DEPLOY_RENDER.md](DEPLOY_RENDER.md) para operação/homologação.

## Funcionalidades disponíveis

- Login Django com identidade VERTYX, Home e seleção de organização.
- Memberships com papel e status próprios por empresa; usuário pode ter vários.
- Catálogo e habilitação do ERP por organização e por membership.
- Clientes, unidades, contatos, categorias, equipamentos, QR e técnicos.
- OS, atendimento, GPS inicial/final, fotos, conferência, assinatura,
  versionamento, PDF, auditoria e reabertura.
- Consultas empresariais filtradas por organização no banco; proteção de IDs,
  relacionamentos e arquivos. PDF com identificação da empresa emissora.
- Administração da organização no ERP e operação VERTYX no Django Admin.

TECNOLMED é criada automaticamente pela migration de dados. Registros antigos
e usuários comuns são vinculados a ela; superusers não recebem vínculo de
funcionário automaticamente. CNPJ e dados legais devem ser preenchidos com
informação real pelo operador; nenhum CNPJ fictício foi criado.

Loja Hospitalar, cobrança, IA, financeiro avançado, NFS-e e Open Finance
permanecem futuros. Não há quotas comerciais nem assinatura de serviços.

## Execução local com PostgreSQL

Requisitos: Docker Desktop/Compose. Na pasta extraída `tecnolmed_erp`:

```powershell
Copy-Item .env.example .env
# Desenvolvimento: DEBUG=True, UPLOAD_STORAGE=local,
# DATABASE_SSL_REQUIRE=False, ALLOWED_HOSTS=localhost,127.0.0.1.
# Deixe DATABASE_URL vazio para usar POSTGRES_* do Compose.
# Defina POSTGRES_PASSWORD e SECRET_KEY próprios, sem versioná-los.
docker compose up --build
```

O build coleta estáticos; Compose também os coleta no volume local. O start
aplica migrations versionadas com lock PostgreSQL antes do Gunicorn. Não gera
migrations no deploy. Não remova volumes/banco ao atualizar.

Acesse `http://localhost:8000/vertyx/`. Para criar o operador da plataforma:

```powershell
docker compose exec web python manage.py createsuperuser
```

Em `/admin/`, o superuser gerencia organizações, memberships e habilitações.
Para um usuário trabalhar no ERP, cadastre um OrganizationMembership ativo com
o papel adequado e um MembershipERP habilitado para Assistência; o
OrganizationERP da empresa também deve estar habilitado. O campo legado
`Usuario.perfil` não concede acesso. Prefira contas comuns para a equipe.

O administrador da organização usa `/contas/usuarios/` para criar contas e
gerenciar vínculos somente da empresa selecionada. A edição do vínculo não
altera a identidade global nem memberships de outras empresas. Vincular uma
identidade já existente a outra organização é tarefa do operador VERTYX nesta
fase. Categorias podem ser criadas pelo botão em Equipamentos e editadas em
`/equipamentos/categorias/<id>/editar/`.

```powershell
# Opcional, somente em ambiente de demonstração:
docker compose exec web python manage.py seed_demo --organization tecnolmed
```

## Permissões

Todo acesso exige usuário/organização/membership ativos e as duas liberações
de ERP, além da permissão da operação.

| Papel da organização | Acesso nesta fase |
|---|---|
| ADMIN | Cadastros, técnicos, usuários/vínculos locais, todas as OS, reabertura |
| GESTOR | Cadastros e técnicos, todas as OS, reabertura; sem gestão de usuários |
| TECNICO | Consulta de clientes/equipamentos; atendimento e arquivos das OS atribuídas |
| ESTOQUE / FINANCEIRO / CONTABILIDADE | Sem funções desses módulos; nenhuma concessão administrativa |
| Superuser VERTYX | Administração central; ERP exige vínculo e liberações explícitos |

## Validação

Instale `requirements-test.txt` no ambiente de testes, com base PostgreSQL
isolada e usuário com permissão para criar bases temporárias. Configure a
DATABASE_URL desse banco. Nunca use settings de teste no Web Service.

```powershell
python manage.py check --settings=tecnolmed.test_postgres_settings
python manage.py makemigrations --check --dry-run --settings=tecnolmed.test_postgres_settings
python manage.py migrate --noinput --settings=tecnolmed.test_postgres_settings
python manage.py test --noinput --settings=tecnolmed.test_postgres_settings
```

Para validar o código sem PostgreSQL, use Python 3.12 e um ambiente virtual,
instale `requirements-test.txt` e execute:

```powershell
python manage.py check --settings=tecnolmed.test_settings
python manage.py makemigrations --check --dry-run --settings=tecnolmed.test_settings
python manage.py migrate --noinput --settings=tecnolmed.test_settings
python manage.py test --noinput --settings=tecnolmed.test_settings
```

`test_settings` é exclusivamente local: SQLite separado e hash de senha
simplificado. Nunca use em produção. O teste de migração cria um banco temporário
com o schema antigo e aplica o upgrade; não reverte nem reseta bancos existentes.

## Arquivos e operação

Com DEBUG=False, DATABASE_URL PostgreSQL, chave forte e UPLOAD_STORAGE=s3 são
obrigatórios; configuração ausente/inválida falha explicitamente.
As fotos de OS usam storage privado (S3 ou PRIVATE_MEDIA_ROOT no desenvolvimento).
Assinaturas e snapshots permanecem no banco; PDF é gerado na rota autorizada.
Fotos/manuais/QR legados de equipamentos em `MEDIA_ROOT` também são entregues
pela rota autenticada. Nunca configure o proxy para servir `/media/` ou arquivos
privados diretamente. Faça backup conjunto do banco e dos dois storages.

O Render depende da criação do banco/bucket e preenchimento das variáveis
reais: veja o guia com a ordem exata e o checklist de celular físico.
Credenciais, `.env`, bases SQLite e mídias de teste ficam fora do ZIP.
O pacote entrega código completo, não um backup de dados reais.

## Estrutura

| Camada | Responsabilidade |
|---|---|
| `platform_core` | Organizações, memberships, catálogo/acesso, contexto, isolamento, Home, auditoria, métricas básicas |
| `contas` | Identidade Django e fichas de técnicos; administração local de vínculos |
| `clientes` / `equipamentos` | Cadastros empresariais existentes |
| `ordens` | Atendimento, evidências, assinatura, histórico e PDF |
| `core` | Painel existente em `/assistencia/` e seed de demonstração |
| `tecnolmed` | Configuração e URLs; nome técnico preservado |

URLs de cadastros, QR e OS foram preservadas. `/` redireciona para Home VERTYX;
o painel antigo permanece disponível em `/assistencia/`.
