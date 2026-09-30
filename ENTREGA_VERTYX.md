# Entrega VERTYX — fundação SaaS multiempresa

Data: 30/09/2026. Projeto atualizado diretamente em `tecnolmed_erp`.
Referência desta fase: `tecnolmed_erp_os.zip`, com os 34 testes anteriores.
O relatório anterior `ENTREGA_OS.md` e sua auditoria de arquivos foram mantidos.
Não houve deploy, push, contratação de serviços, reset de banco ou exclusão de
migrations. O ZIP final contém código; não contém dados empresariais, credenciais
nem arquivos produzidos pelos ensaios locais.

## 1. Estado inicial encontrado

Antes de modificar a arquitetura, foram executados os 34 testes existentes:
todos aprovados. `manage.py check` não apontou problemas e
`makemigrations --check --dry-run --settings=tecnolmed.test_settings` não apontou
alterações. PostgreSQL/Docker não estavam disponíveis para validação local;
foi usado o ambiente isolado de testes da fase anterior.

Existiam cadastros funcionais e OS com início/finalização, localização inicial e
final, fotos, conferência, assinatura, versão, PDF, auditoria e reabertura.
Usuários eram globais e o perfil também; superuser era tratado como administrador
do ERP. Clientes/equipamentos permitiam escrita para qualquer usuário autenticado.
Fotos de OS já eram privadas; mídia de equipamentos ainda tinha exposição genérica
em DEBUG. PDF era identificado com TECNOLMED no código.

## 2. Arquitetura anterior

| App/model | Relações e responsabilidade original |
|---|---|
| `contas.Usuario` | AUTH_USER_MODEL global; perfil, Groups e Permissions Django |
| `contas.Tecnico` | Ficha profissional; OneToOne opcional para Usuario |
| `clientes.Cliente` | Documento globalmente único; raiz de cadastro |
| `Unidade` / `ContatoCliente` | ForeignKey obrigatório para Cliente |
| `CategoriaEquipamento` | Nome globalmente único |
| `Equipamento` | Cliente e categoria obrigatórios; unidade opcional; foto/manual/QR |
| `OrdemServico` | Cliente/equipamento/técnico obrigatórios; unidade opcional |
| `Localizacao` / `Foto` / `Auditoria` | OS e usuário; histórico do atendimento |
| `Conferencia` | OS, usuário, revisão/ciclo, JSON/digest e localização final |
| `Assinatura` | OS, conferência, responsável/cargo, imagem/digest e usuário |
| `core` | Painel de cadastros e seed; sem novas tabelas |
| `tecnolmed` | Settings PostgreSQL/Render, URLs e autenticação Django |

Os ManyToMany de Groups/Permissions eram os do User Django; não havia associação
multiempresa. A auditoria incluiu views, formulários, templates, URLs, arquivos,
storage e migrations, além das ForeignKeys. As regras específicas de manutenção
permanecem no app `ordens` e nos cadastros existentes.

## 3. Nova arquitetura

Banco compartilhado, com tenant explícito nas raízes empresariais e derivação
pelos relacionamentos obrigatórios dos filhos. A identidade de login continua
global; papel/status e habilitação são por membership.

```text
Usuario → OrganizationMembership → Organization
                   ↓                    ↓
             MembershipERP        OrganizationERP
                   └───── ERPCatalog ────┘
                               ↓
                      VERTYX | ASSISTÊNCIA
                               ↓
                    cadastros/OS do tenant
```

Não foi duplicada `organization` em cada evidência: localização, foto,
conferência, assinatura e auditoria de OS derivam de `ordem.organization`.
Unidade e contato derivam de `cliente.organization`. Isso evita duas colunas de
tenant contraditórias no mesmo registro. Managers filtram essas relações no SQL.

## 4. Apps criados

Somente `platform_core`: organizações, catálogo, memberships, grants, Home,
seleção de tenant, isolamento, administração central, auditoria e métricas mínimas.
Os apps anteriores e o nome técnico `tecnolmed` foram preservados.

## 5. Arquivos criados

O novo app contém `models`, `context`, `tenancy`, `access`, `middleware`, `forms`,
`validators`, `views`, `urls`, `admin`, `business_admin`, `media_views`, `audit`,
`metrics`, testes e migrations. Foram criados o template da Home, o teste de
migração legada, este relatório e `AUDITORIA_VERTYX_ARQUIVOS.json`.
O inventário completo, com caminhos exatos, está no apêndice e no manifesto JSON.

## 6. Arquivos modificados

Models, forms, views e admins empresariais; permissões de contas; serviços, PDF,
storage e fixtures de OS; settings e URLs centrais; seed_demo; templates de login,
navegação e cadastros; scripts de validação/pacote; README, deploy e `.env.example`.
O manifesto compara todos os arquivos com a entrega de OS, lista preservados,
modificados e criados, e verifica que não houve remoções.

## 7. Models criados

| Model | Campos/conceito |
|---|---|
| Organization | ID, UUID público, slug, razão social, nome fantasia, CNPJ, email, telefone, status, datas, logo_key, document_details |
| ERPCatalog | Código único, nome, descrição, ativo |
| OrganizationERP | Organização/ERP únicos; enabled, datas de habilitação/desabilitação |
| OrganizationMembership | Organização/usuário únicos; papel, status, entrada/saída |
| MembershipERP | Membership/ERP únicos; enabled |
| PlatformAudit | Organização, ERP quando aplicável, usuário, ação, registro, mudanças JSON e data |

Status de organização: ATIVA/INATIVA/SUSPENSA. Membership:
ATIVO/INATIVO/BLOQUEADO. Papel: ADMIN/GESTOR/TECNICO/ESTOQUE/FINANCEIRO/CONTABILIDADE.
Suspensão/desativação são estados de acesso, sem regras de cobrança.

CNPJ é normalizado, formatado e validado por dígitos verificadores. Suporta
numérico e alfanumérico, seguindo o [manual da Receita Federal](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/documentos-tecnicos/cnpj/manual-dv-cnpj.pdf).
É opcional para permitir upgrade sem inventar dados; valores preenchidos são
únicos. O formulário aceita a máscara de 18 caracteres e armazena 14 normalizados.

## 8. Models modificados

- Cliente, CategoriaEquipamento, Equipamento, Tecnico e OrdemServico receberam
  organização obrigatória, protegida contra exclusão e mudança de tenant.
- CPF/CNPJ de cliente e nome de categoria são únicos por organização.
- Tecnico.usuario passou de OneToOne para ForeignKey, com unicidade por
  organização/usuário: a mesma identidade pode ter fichas em várias empresas.
- Unidade/ContatoCliente e os seis models de OS usam managers isolados.
- Conferencia recebeu `issuer` como metadado separado para emissor legado.
- Auditoria de OS expõe organização derivada e código `assistencia`.
- Usuario manteve tabela, AUTH_USER_MODEL e campo legado perfil; propriedades
  de autorização consultam o papel do membership atual, sem bypass de superuser.

ForeignKeys Django geram índices nas raízes; foi acrescentado índice composto de
OS por organização/status/abertura. Unicidades por tenant também têm suporte de
índice. Consultas não carregam todas as empresas para filtrar em Python.

## 9. Migrations criadas

Onze migrations incrementais, além de todos os arquivos anteriores intactos:

| App | Migration |
|---|---|
| platform_core | 0001_initial |
| clientes | 0002_cliente_organization_alter_cliente_cpf_cnpj_and_more |
| contas | 0002_tecnico_organization_alter_tecnico_usuario_and_more |
| equipamentos | 0002_categoriaequipamento_organization_and_more |
| ordens | 0003_ordemservico_organization_and_more |
| ordens | 0004_conferencia_issuer |
| platform_core | 0002_tecnolmed_backfill |
| clientes | 0003_require_organization |
| contas | 0003_require_organization |
| equipamentos | 0003_require_organization |
| ordens | 0005_require_organization |

O grafo garante campos nullable → backfill/validação → campos obrigatórios.
O script `tests/verify_source.py` compara byte a byte todas as migrations da
referência e registra SHA-256 no manifesto desta fase.

## 10. Data migrations criadas

`platform_core/0002_tecnolmed_backfill.py` usa models históricos e o alias do banco
da migration. Cria tenant, catálogo, habilitação, memberships/grants; associa
raízes antigas e registra emissor em conferências legadas sem alterar seu JSON.
Valida ausência de raízes sem tenant e coerência dos vínculos empresariais.
A reversão de dados é noop para não apagar associação/histórico; atualização é
planejada para frente. Não é um mecanismo de rollback operacional.

## 11. Como TECNOLMED foi criada como tenant

Migration cria `slug=tecnolmed`, identificação TECNOLMED, status ATIVA, Assistência
ativo no catálogo e habilitado para a empresa. Razão social provisória também
é TECNOLMED; CNPJ/email/telefone ficam vazios até informação oficial. O upgrade
não depende de cadastro manual para os dados antigos funcionarem.

## 12. Como dados antigos foram migrados

Clientes, categorias, equipamentos, técnicos e OS sem organização recebem
TECNOLMED. Filhos continuam com os mesmos FKs/IDs. Usuários comuns recebem
membership com papel antigo, status conforme is_active e acesso Assistência.
Superusers não viram funcionários automaticamente; contas/técnicos/histórico
continuam existentes, e o operador pode conceder vínculo explícito.

Não são renumeradas OS, movidos arquivos, recalculadas assinaturas, alterados
snapshots/digests antigos, apagadas localizações ou auditorias. O teste legada
verifica chaves/nomes de arquivos, JSON, digest, imagem e IDs após upgrade.
Ele usa banco temporário novo, nunca rollback/reset de banco existente.

## 13. Como Membership funciona

Uma identidade participa de várias empresas com papéis/status independentes.
A sessão guarda somente organização selecionada; middleware revalida o vínculo
a cada requisição. Sem escolha válida: uma associação ativa é automática;
várias exigem seleção na Home; nenhuma impede operação empresarial.
Inativar vínculo preserva registro e data de saída. Não desativa a conta global
nem outro membership. Edição local não altera senha, identidade, staff/superuser.
O administrador não pode retirar seu próprio acesso administrativo por essa tela.

## 14. Como acesso aos ERPs funciona

Usuário ativo + organização ATIVA + membership ATIVO + catálogo ativo +
OrganizationERP enabled + MembershipERP enabled + permissão da operação.
`has_erp_access` e `require_erp` centralizam o cálculo. Ter empresa, perfil global
ou is_superuser não basta. Revogação é verificada no próximo request, sem confiar
em autorização antiga na sessão. Não foram criados Groups globais para papéis
locais, pois o mesmo usuário pode ser ADMIN numa empresa e TECNICO em outra.

## 15. Como Home VERTYX funciona

Login Django foi mantido e identificado como VERTYX. Home `/vertyx/` mostra
saudação, organização atual, seletor com memberships autorizados e card
Assistência somente com ambos os grants. Seleção é POST com CSRF, UUID validado,
membership do próprio usuário e rotação da sessão; evento fica auditado.
Dentro do ERP: VERTYX | ASSISTÊNCIA e Voltar para VERTYX.
`/` redireciona à Home; painel antigo está em `/assistencia/`; URLs de cadastros,
OS, QR e login permanecem. Nenhuma rota `/loja/` foi implementada.

## 16. Como isolamento multiempresa funciona

`OrganizationMiddleware` define o contexto; ContextVar separa requests/tarefas,
e o contexto é limpo ao terminar. `TenantManager` filtra SQL pela organização
direta ou derivada; sem tenant retorna `.none()`. Forms recriam querysets de
relacionamentos no contexto atual. Save/clean verificam organização e FKs;
update/bulk_update/bulk_create empresariais são bloqueados para impedir bypass.
Gerenciamento legítimo de cadastros ocorre em transações e gera auditoria.

As rotas empresariais exigem ERP no middleware; serviços de OS também autorizam
diretamente. Cadastros escritos exigem ADMIN/GESTOR. Técnico só atende suas OS.
Managers são uma defesa de aplicação, não PostgreSQL RLS: `all_objects`, SQL
direto e operador do banco são privilegiados. Não usar essas APIs em views.

## 17. Como IDOR foi prevenido

Lookups usam managers isolados antes da autorização da operação. ID de outra
empresa dá 404; permissões insuficientes no próprio tenant dão 403. Sem vínculo,
o usuário retorna à Home e não recebe dados. IDs de foto/assinatura/PDF também
devem pertencer à OS autorizada. Token de conferência vincula usuário/OS e expira.
Seleção de organização não aceita UUID alheio; IDs enviados em FK de forms não
passam no queryset/validação. Reabertura e todas as mutações de OS seguem a mesma
checagem. Não existem novas rotas genéricas de exclusão ou download sem guarda.

## 18. Alterações em clientes/equipamentos

Criação/edição de clientes, unidades, equipamentos e categorias exige membership,
ERP e ADMIN/GESTOR no backend. Consultas, QR e AJAX de unidades são por tenant.
Técnico não ganha escrita por conhecer a URL. Formsets de contatos permanecem
associados ao cliente no contexto correto, inclusive criação conjunta.
Unidade deve pertencer ao cliente do equipamento; categorias não cruzam empresas.
Duplicados dentro da empresa são erros de formulário, preservando mesmo documento
ou categoria em empresas distintas. Menus/botões acompanham permissões.
Categorias têm criação/edição no ERP porque o Admin empresarial passou a consulta.

## 19. Proteção de fotos

Fotos de OS usam PrivateStorage e rota autenticada com OS/foto autorizadas.
Novas chaves incluem UUID da empresa; chaves antigas permanecem válidas.
Storage não fornece URL pública. Respostas são private/no-store e nosniff.
Mídias legadas de equipamentos em `/media/<chave>` agora exigem ERP e equipamento
da empresa; manual é download. A rota pública genérica em DEBUG foi removida.
Não expor essas pastas diretamente em proxy/CDN.

## 20. Proteção de assinaturas

Imagem, responsável, cargo, data/usuário, ciclo, conferência e hashes permanecem
no banco. Rota da imagem exige OS e assinatura do tenant, além de autorização
do atendimento. Versionamento, auditoria, reabertura e bloqueio após finalização
foram mantidos. Técnico de outra OS não pode obter a imagem; empresa alheia dá 404.

## 21. Proteção de PDFs

PDF é produzido por rota autenticada com lookup isolado de OS e assinatura,
sem arquivo público persistido. `gerar_pdf` também valida tenant em chamada direta.
Foto/snapshot/imagem são verificados pelos hashes anteriores. Mismatch de emissor
ou indisponibilidade/integridade das evidências impede produção do comprovante.
Resposta private/no-store. O PDF baixado pelo usuário autorizado é uma cópia fora
do sistema; revogar acesso não recolhe arquivos já baixados.

## 22. Como branding do PDF foi adaptado

Novas conferências capturam identificação da Organization no snapshot e no issuer.
Nome, razão social, CNPJ, telefone/email, informações documentais e logo_key
podem ser usados pelo documento. Conferência antiga recebe issuer separado;
seu JSON/digest assinado fica intacto. Mudanças posteriores na empresa não trocam
a identificação histórica textual. Ausência de logo usa o nome da organização.
PDF não depende mais de TECNOLMED_LOGO_PATH nem de filesystem.path.

Logo é chave privada `organizations/<UUID>/branding/...`, lida por Storage.open.
O modelo recusa prefixo de outra empresa e travessia de diretório. Não há upload
de branding nessa fase. Futuro upload deve gerar chaves novas e imutáveis;
substituir bytes de uma chave existente alteraria a imagem de documentos antigos.
Chave/texto são capturados, sem novo mecanismo de hash da logomarca nesta fase.

## 23. Testes adicionados

37 testes novos em `platform_core.tests`, incluindo o cenário de upgrade legado.
Os 34 de OS continuam com o mesmo escopo, adaptando fixtures ao contexto/membership.
Cobertura nova: A/B nos dois sentidos; Cliente/Unidade/Contato/Categoria/Equipamento/
Técnico/OS/Localizacao/Foto/Conferencia/Assinatura/Auditoria; GET/POST por IDs;
IDs de arquivos trocados; forms/FKs/duplicados; AJAX/listas/QR/media; serviços/PDF
diretos; grants/catálogo/status revogados; técnico; admin local; superuser e Admin
empresarial; múltiplas empresas com papéis distintos; CSRF/seletor; auditoria;
branding histórico; storage; métricas; ContextVar concorrente e CNPJ.
Cadastro completo de cliente com contato e formulário inválido também são testados.

O ensaio adicional em Chromium executou Home/entrada/retorno, mobile 390 px,
início com GPS simulado, edição/foto, GPS final negado, conferência, limpar
assinatura, bloqueio de canvas vazio, redesenho, finalização e PDF. Sem overflow
horizontal ou erros JavaScript. Foi executado em Empresa B para validar a marca.
Home, conferência e as duas páginas do PDF foram inspecionadas visualmente.
Artefatos do ensaio ficam em `tmp/validation`, fora do pacote.

## 24. Quantidade total de testes

71 testes Django: 34 regressões OS + 37 da fundação VERTYX.
O roteiro Chromium é validação adicional e não entra nessa contagem.

## 25. Resultado dos testes

Suíte completa: `Ran 71 tests in 27.953s` — `OK`, em SQLite isolado.
Upgrade com dados legados passou, incluindo preservação de snapshot/digest,
imagem, caminhos e IDs. Não houve teste de migrations ou locks em PostgreSQL.
O ensaio do navegador passou com GPS simulado; não equivale a validação de GPS
em aparelho físico nem à concorrência real no PostgreSQL.

## 26. Resultado do check

`python manage.py check`, settings padrão PostgreSQL:
`System check identified no issues (0 silenced).`
Checks da suíte/settings isoladas também passaram. Check de configuração não
confirma conexão com PostgreSQL ou adequação completa de produção.

## 27. Resultado do makemigrations --check --dry-run

Com `--settings=tecnolmed.test_settings`: `No changes detected`, saída 0.
`migrate --noinput` aplicou as migrations incrementais na base isolada; ao final,
`No migrations to apply`. Migração fresca com dados antigos também passou.
`collectstatic --noinput` com settings padrão passou. Nenhuma migration foi gerada
em startup/deploy. Os arquivos antigos são verificados no empacotamento.

## 28. Limitações

- PostgreSQL e Docker indisponíveis localmente; concorrência/locks, custo do
  backfill e execução no banco real precisam de homologação.
- Sem deploy Render, integração S3 ou persistência externa contratada.
- Isolamento é do backend Django, sem RLS; código privilegiado/SQL pode furar
  o escopo. Novos apps/views/tarefas devem seguir os mesmos contratos.
- Cadastro global de identidade existente em outra empresa é vinculado pelo
  operador, sem busca global exposta ao administrador da organização.
- Auditoria da plataforma preserva mudanças do ERP e operação central; o operador
  tem consulta global de auditorias. Não há painel comercial, exportador genérico
  nem trilha completa de tentativas HTTP negadas. Banco privilegiado pode alterar
  dados e logs; imutabilidade no aplicativo não substitui backup/acesso operacional.
- Logo oficial/dados legais de TECNOLMED não foram fornecidos; identificação
  textual permite concluir a fase.

## 29. Pendências e extensão futura

Homologar upgrade/restauração em cópia PostgreSQL; confirmar dados legais;
conceder memberships explícitos aos operadores que também atuam no ERP;
configurar persistência/backups de mídias e validar celular/HTTPS.
O [Render usa filesystem efêmero](https://render.com/docs/disks); o blueprint
gratuito mantido não inclui disco. Consulte o guia de deploy atualizado.

PrivateStorage é uma fachada da API Django Storage. Aceita definição
`PRIVATE_STORAGE = {'BACKEND': '...', 'OPTIONS': {...}}` nas settings e usa
FileSystemStorage em PRIVATE_MEDIA_ROOT quando ausente. Pode receber backend
S3-compatible com bucket privado; credenciais devem vir do ambiente/provedor.
Backend S3 e suas dependências não foram instalados. Exemplo conceitual futuro:

```python
PRIVATE_STORAGE = {
    'BACKEND': 'storages.backends.s3.S3Storage',
    'OPTIONS': {
        'bucket_name': config('PRIVATE_BUCKET'),
        'default_acl': 'private',
        'querystring_auth': True,
        'file_overwrite': False,
    },
}
```

Configurar endpoint/região/credenciais e regras de acesso conforme provedor e
[documentação oficial django-storages](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html).
As views continuam intermediando acesso; URLs do backend não são expostas.
Mídia legada de equipamentos ainda usa o storage padrão, portanto deve ter
persistência/migração própria ao adotar object storage. PDFs abrem streams,
não dependem de caminho local. Preservar chaves antigas na migração de arquivos.

Plan/Subscription/Entitlement ficam documentados, sem tabelas comerciais sem uso:
Plan poderá definir ofertas/versionamento; Subscription ligará organização à
contratação/status/período; Entitlement materializará acesso e limites por ERP.
OrganizationERP é o ponto de habilitação atual, não comprovante de pagamento.
Futuro billing deverá atualizar habilitações por serviço auditado/idempotente,
mantendo MembershipERP e permissões locais. Nenhuma quota foi implementada.

`assistance_usage(user)` fornece counts SQL do tenant para ADMIN/GESTOR: membros,
ativos, clientes, equipamentos, OS, OS no mês, fotos e comprovantes assinados.
Não limita uso nem faz varredura de arquivos. Bytes/chamadas de IA/NFS-e exigirão
contadores próprios e eventos idempotentes quando esses serviços existirem.

IA futura deve exigir ORGANIZAÇÃO + ERP + USUÁRIO + PERMISSÕES antes de buscar
dados; contexto também em tarefas, caches, ferramentas e índices vetoriais.
Não enviar dados privados de outro tenant. Loja Hospitalar será um app/ERP próprio,
com catálogo, rotas/cards e autorização por código, reutilizando identidade,
memberships/organizações. Não foi desenvolvido nesta fase.

## 30. Riscos encontrados

As permissões globais antigas, escrita de cadastros por qualquer autenticado,
queries por ID sem tenant, mídia genérica e marca fixa foram tratados nesta fase.
A revisão também fechou consulta de OS no Admin sem grant ERP e corrigiu
validação de filhos sem cliente/OS para produzir erro de formulário.

Riscos operacionais remanescentes: mídia sem persistência, ausência de validação
PostgreSQL, backfill de volume grande em janela inadequada, uso indevido de
`all_objects`/SQL, proxy público de mídia e segredos/defaults de desenvolvimento.
Defaults originais de desenvolvimento não são credenciais de produção; configure
valores próprios no ambiente. Não alteramos versões de dependências nesta fase;
revisão/atualização de segurança deve anteceder exposição operacional do serviço.
Backup deve incluir banco e arquivos; o ZIP não substitui backup. Numeração de OS
mantém PK global por compatibilidade, sem renumeração por empresa.

## Checklist de aceite manual

1. Em homologação, backup/restore PostgreSQL e arquivos; aplicar migrations.
2. Conferir TECNOLMED, IDs e comprovantes antigos; preencher dados oficiais.
3. Usuário com uma empresa entra no contexto automaticamente; com duas seleciona.
4. Confirmar Home só oferece Assistência quando os dois grants estão ativos.
5. Trocar IDs/UUIDs entre A/B em cadastro, OS, QR, conferência e arquivos: negar.
6. Técnico não edita cadastros nem atende OS alheia; ADMIN/GESTOR exercem seu papel.
7. Revogar vínculo/grant; confirmar bloqueio na próxima requisição.
8. Superuser acessa central; ERP e consulta empresarial exigem vínculo/grants.
9. Executar atendimento/GPS/foto/conferência/assinatura/PDF/reabertura em HTTPS.
10. Confirmar nome da organização e versões antigas no PDF; testar restart e backup.

Fase encerrada no limite solicitado. Nenhuma etapa comercial, IA ou Loja iniciada.


## Apêndice — inventário completo desta fase

Comparação com `tecnolmed_erp_os.zip`: 63 arquivos preservados, 39 modificados, 33 criados; nenhum removido. Hashes das migrations anteriores constam no manifesto.

### Arquivos criados

- `AUDITORIA_VERTYX_ARQUIVOS.json`
- `ENTREGA_VERTYX.md`
- `clientes/migrations/0002_cliente_organization_alter_cliente_cpf_cnpj_and_more.py`
- `clientes/migrations/0003_require_organization.py`
- `contas/migrations/0002_tecnico_organization_alter_tecnico_usuario_and_more.py`
- `contas/migrations/0003_require_organization.py`
- `equipamentos/migrations/0002_categoriaequipamento_organization_and_more.py`
- `equipamentos/migrations/0003_require_organization.py`
- `ordens/migrations/0003_ordemservico_organization_and_more.py`
- `ordens/migrations/0004_conferencia_issuer.py`
- `ordens/migrations/0005_require_organization.py`
- `platform_core/__init__.py`
- `platform_core/access.py`
- `platform_core/admin.py`
- `platform_core/apps.py`
- `platform_core/audit.py`
- `platform_core/business_admin.py`
- `platform_core/context.py`
- `platform_core/forms.py`
- `platform_core/media_views.py`
- `platform_core/metrics.py`
- `platform_core/middleware.py`
- `platform_core/migrations/0001_initial.py`
- `platform_core/migrations/0002_tecnolmed_backfill.py`
- `platform_core/migrations/__init__.py`
- `platform_core/models.py`
- `platform_core/tenancy.py`
- `platform_core/tests.py`
- `platform_core/urls.py`
- `platform_core/validators.py`
- `platform_core/views.py`
- `templates/platform_core/home.html`
- `tests/legacy_migration.py`

### Arquivos modificados

- `.env.example`
- `DEPLOY_RENDER.md`
- `README.md`
- `clientes/admin.py`
- `clientes/forms.py`
- `clientes/models.py`
- `clientes/views.py`
- `contas/admin.py`
- `contas/forms.py`
- `contas/models.py`
- `contas/permissions.py`
- `contas/views.py`
- `core/management/commands/seed_demo.py`
- `core/urls.py`
- `equipamentos/admin.py`
- `equipamentos/forms.py`
- `equipamentos/models.py`
- `equipamentos/urls.py`
- `equipamentos/views.py`
- `ordens/admin.py`
- `ordens/forms.py`
- `ordens/models.py`
- `ordens/reports.py`
- `ordens/services.py`
- `ordens/storage.py`
- `ordens/tests.py`
- `tecnolmed/settings.py`
- `tecnolmed/urls.py`
- `templates/base.html`
- `templates/clientes/cliente_detail.html`
- `templates/clientes/cliente_list.html`
- `templates/contas/usuario_form.html`
- `templates/contas/usuario_list.html`
- `templates/equipamentos/equipamento_detail.html`
- `templates/equipamentos/equipamento_list.html`
- `templates/registration/login.html`
- `tests/browser_flow.cjs`
- `tests/prepare_browser.py`
- `tests/verify_source.py`
