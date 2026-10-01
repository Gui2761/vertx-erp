# VERTYX | ASSISTÊNCIA

Fundação SaaS multiempresa sobre o projeto Django TECNOLMED existente.
Versão local preparada em 01/10/2026 para homologação final: módulos existentes
ampliados, compras, vendas, bancos, preventivas/checklists, portal, documentos,
notificações, PWA, camada fiscal substituível e 31 relatórios integrados.
Validação atual: 258 testes aprovados em PostgreSQL 16.15 (208 anteriores + 50 novos);
SQLite: 246 aprovados e 12 exclusivos de PostgreSQL ignorados.
Central de operações com calendário/lista/timeline, fila, conflitos auditados,
OS rápida sem técnico/data e painel de TV com atualização e permissão específicas.
Consulte [CENTRAL_OPERACOES.md](CENTRAL_OPERACOES.md) para uso, segurança e migrations.
Estoque ampliado com lotes/FEFO, reservas, ocorrências duráveis, relatórios semanais
e geração pelo fluxo de compras atual; painel VERTYX Gestão com dados reais.
Infraestrutura/credenciais preservadas; nenhum deploy externo foi executado.

Consulte [ENTREGA_ESTOQUE_GESTAO.md](ENTREGA_ESTOQUE_GESTAO.md) para esta ampliação e
[AUTOMACAO_ESTOQUE.md](AUTOMACAO_ESTOQUE.md) para ativar o runner local/futuro Render.
[ENTREGA_FINAL.md](ENTREGA_FINAL.md) para funcionalidades, limites e
homologação, [INVENTARIO_FINAL.md](INVENTARIO_FINAL.md) para modelos e URLs,
[VALIDACAO_FINAL.json](VALIDACAO_FINAL.json) para resultados e
[AUDITORIA_FINAL.md](AUDITORIA_FINAL.md) para a análise desta fase.
[ENTREGA_MODULOS.md](ENTREGA_MODULOS.md) registra a fase anterior,
[AUDITORIA_MODULOS.md](AUDITORIA_MODULOS.md) para a auditoria inicial,
[ENTREGA_HOMOLOGACAO.md](ENTREGA_HOMOLOGACAO.md) para a homologação anterior,
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
- Peças, fornecedores e movimentações auditadas; utilização/devolução em OS,
  saldo protegido contra valor negativo e alertas de mínimo.
- Orçamentos com itens, descontos, estados, PDF e conversão idempotente em OS.
- Contratos, cobertura, preventivas recorrentes e cobranças por competência.
- Planejamento de contratos e consulta às datas preventivas dos equipamentos.
- Compras com cotação, aprovação, pedido, recebimento, estoque e conta a pagar;
  vendas com pedido, baixa do estoque e conta a receber.
- Financeiro: pagamentos parciais, parcelas, contas bancárias, caixa,
  transferências, conciliação manual, centros de custo e fluxo mensal.
- Preventivas/checklists e calendário dia/semana/mês; PWA do técnico.
- Documentos privados, portal do cliente, configurações e avisos internos.
- Fiscal preparado para provedor real, sem emissão simulada ou credenciais.
- 31 relatórios com filtros da organização, CSV, PDF, Excel e impressão.

TECNOLMED é criada automaticamente pela migration de dados. Registros antigos
e usuários comuns são vinculados a ela; superusers não recebem vínculo de
funcionário automaticamente. CNPJ e dados legais devem ser preenchidos com
informação real pelo operador; nenhum CNPJ fictício foi criado.

Emissão fiscal real, integrações bancárias, envio de e-mail/WhatsApp, checkout
público, cobrança da assinatura SaaS e IA dependem de etapas posteriores.
Não há quotas comerciais nem assinatura de serviços. A operação comercial
interna está disponível; limites explícitos constam em ENTREGA_FINAL.md.

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
| ADMIN | Todos os módulos da própria organização e gestão de usuários/vínculos locais |
| GESTOR | Cadastros, técnicos, OS e módulos de gestão; sem gestão de usuários |
| TECNICO | Atendimento das OS atribuídas, consulta de peças e uso/devolução em suas OS; planejamento e relatórios operacionais |
| ESTOQUE | Peças, fornecedores, depósitos, movimentações, compras e relatórios de estoque |
| FINANCEIRO | Financeiro, cadastros auxiliares e relatórios financeiros |
| CONTABILIDADE | Consulta financeira e relatórios/exportações; sem lançamentos ou liquidações |
| CLIENTE | Portal com vínculos explícitos a clientes; sem acesso ao ERP interno |
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

O ambiente Render informado já existe. O Blueprint mantém o Web Service
`plan: free`, usa DATABASE_URL existente e não provisiona outro PostgreSQL.
Para uma atualização futura autorizada, consulte DEPLOY_RENDER.md e mantenha
o banco, bucket e variáveis atuais. Nenhuma atualização remota foi executada.
Credenciais, `.env`, bases SQLite e mídias de teste ficam fora do ZIP.
O pacote entrega código completo, não um backup de dados reais.

## Estrutura

| Camada | Responsabilidade |
|---|---|
| `platform_core` | Organizações, memberships, catálogo/acesso, contexto, isolamento, Home, auditoria, métricas básicas |
| `contas` | Identidade Django e fichas de técnicos; administração local de vínculos |
| `clientes` / `equipamentos` | Cadastros empresariais existentes |
| `ordens` | Atendimento, evidências, assinatura, histórico e PDF |
| `gestao` | Estoque, orçamentos, contratos/planejamento, financeiro e relatórios |
| `operacao` | Compras, vendas, depósitos, bancos, planos/checklists, documentos, portal, PWA, calendário, avisos e configurações |
| `fiscal/providers` | Contrato de integração fiscal substituível; sem provedor real configurado |
| `core` | Painel existente em `/assistencia/` e seed de demonstração |
| `tecnolmed` | Configuração e URLs; nome técnico preservado |

URLs de cadastros, QR e OS foram preservadas. `/` redireciona para Home VERTYX;
o painel antigo permanece disponível em `/assistencia/`.
