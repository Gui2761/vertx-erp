# Aprovação separada — inicialização do PostgreSQL de homologação

Nenhuma migration foi aplicada. A revisão é estática, do sentido de aplicação,
seguindo o grafo para banco vazio. Não foi executada a suíte completa nem foram
criados dados DEMO/usuários nesta etapa.

## Destino e código

- Exclusivamente banco `vertyx_testes`, recurso Render `dpg-dbm7jfc9v7es7393tsig-a`.
- Usuário esperado `vertyx_testes_user`, PostgreSQL 16, porta 5432, TLS verificado.
- Plano de 137 migrations: `HOMOLOGACAO_R2_MIGRATIONS_PLAN.json`.
- Hash do plano: `bdf38109ef7ed3abeb746685229dcbd2629a75056a1c494d7a85a97135104ed2`.
- A execução futura deverá conferir o SHA publicado na branch codex/homologacao-r2,
  o fingerprint do plano e os hashes de origem. Interromper se divergirem.
- Produção tecnolmed-erp, main, banco suspenso anterior e bucket R2 ficam fora do
  executor. Nunca usar variável/alias ou hostname como fallback.

## As 23 migrations com operações de dados

Estes efeitos são esperados ao aplicar o conjunto completo sobre banco vazio.
Não confundir ausência de dados de negócio com ausência de seeds obrigatórios.

| Migration | Efeito esperado em banco inicialmente vazio | Tenants, usuários e permissões / limites |
| --- | --- | --- |
| `contenttypes.0002_remove_content_type_name` | Nenhuma operação de dados no sentido de aplicação; RunPython.noop. A remoção do campo name é alteração de schema. | Nenhum tenant ou usuário. |
| `auth.0011_update_proxy_permissions` | Reassocia permissões de modelos proxy existentes; sem permissões legadas para atualizar num banco novo. | Não cria usuários nem concede permissões a usuários; pode criar content types de proxies existentes no estado histórico. |
| `platform_core.0002_tecnolmed_backfill` | Cria 1 Organization ativa com slug tecnolmed e nome TECNOLMED, 1 ERPCatalog assistencia e 1 OrganizationERP habilitado. | Não copia dados reais. Com contas vazias, não cria Membership/MembershipERP. Não cria usuários/superusuários, contratos, OS ou assinaturas. Este tenant não é a futura organização DEMO. |
| `commercial.0001_initial` | Cria 4 PlanoComercial: basico, profissional, empresarial e personalizado, com metadados e preços definidos na migration. | Catálogo global; sem clientes, usuários ou concessões a tenants. |
| `operacao.0003_detalhar_saldos_legados_em_lotes` | Sem efeito de dados: não há peças ou saldos para detalhar em depósitos/lotes legados. | Não cria depósito Principal nem lotes sem peças com saldo positivo. |
| `gestao.0007_origem_parcelas_existentes` | Sem efeito de dados: não há lançamentos ou parcelas para vincular à origem raiz. | Não cria movimentações financeiras. |
| `platform_core.0008_expand_saas_entitlements` | Atualiza os 3 planos comerciais padronizados e cria 3 PlanoSaaS mensais (basico/profissional/empresarial) a partir das ofertas globais. | Não cria assinatura, contrato, tenant ou usuário; valida preços seedados. |
| `platform_core.0009_core_modules_all_plans` | Inclui módulos de core nas listas dos planos e recursos das ofertas criados anteriormente. | Fiscal aparece no catálogo; isso não autoriza transmissão fiscal, que continua bloqueada nas settings/capabilities. |
| `platform_core.0010_core_customer_product_entitlements` | Acrescenta módulos clientes/produtos/core aos planos existentes na sequência de inicialização. | Não cria clientes, produtos, memberships ou usuários. |
| `operacao.0015_funcionario_contato` | Sem efeito de dados: não há funcionários para copiar telefone/email do usuário vinculado. | Não cria pessoas ou funcionários. |
| `operacao.0016_hora_extra_aprovacao` | Sem efeito de dados: não há funcionários, marcações ou ajustes para criar referências de jornada legadas. | Não cria pontos, escalas ou usuários. |
| `platform_core.0012_planosaas_nivel_indicadores` | Define níveis de indicadores e módulo de relatórios nos PlanoSaaS já seedados: básico, avançado e completo conforme oferta. | Não concede permissões individuais. |
| `platform_core.0014_multierp_catalog_and_contracts` | Registra 8 produtos do catálogo multierp e seus módulos/recursos; completa metadados de assistencia e gestao-publica quando já existentes. | Não cria tenants, usuários ou contratos nem concede módulos a organizações. Não significa que os 8 produtos estejam implementados. |
| `platform_core.0015_alter_moduloorganizacao_codigo` | Registra módulos/recursos globais de planejamento, orçamento, contabilidade e tesouraria pública. | Sem concessões a tenant ou usuários. |
| `platform_core.0018_alter_moduloorganizacao_codigo` | Registra catálogo global de patrimônio, almoxarifado e frotas municipais. | Sem patrimônio, estoque, veículos ou concessões reais. |
| `platform_core.0019_alter_moduloorganizacao_codigo` | Registra catálogo global de processo digital, transparência, ouvidoria e E-SIC. | Não cria publicações, manifestações ou pedidos. |
| `platform_core.0020_alter_moduloorganizacao_codigo` | Registra catálogo global de tributos, gestão territorial e preparação NFS-e. | Não cria contribuintes, imóveis, débitos ou documentos fiscais. |
| `platform_core.0021_alter_moduloorganizacao_codigo` | Registra saude_sus e seus recursos globais. | Não cria paciente, prontuário, chave clínica ou acesso de profissional/tenant. |
| `platform_core.0022_alter_moduloorganizacao_codigo` | Registra educacao_municipal e seus recursos globais. | Não cria aluno, matrícula, escola ou acesso de tenant. |
| `platform_core.0023_alter_moduloorganizacao_codigo` | Registra controle_interno e seus recursos globais. | Não cria achados, evidências ou permissões individuais. |
| `rh_municipal.0001_initial` | Garante os produtos loja-hospitalar e gestao-publica no ERPCatalog usando o alias da migration. | Não cria prefeitura, servidor ou usuário. O catálogo final inclui loja-hospitalar além dos produtos da 0014. |
| `rh_municipal.0004_ataregistroprecosmunicipal_contratopublicomunicipal_and_more` | Registra catálogo global de compras, licitações, registro de preços e contratos públicos. | Não cria processos de licitação, contratos reais ou concessões a tenant. |
| `rh_municipal.0005_pontoservidor_endereco_ip_pontoservidor_latitude_and_more` | Registra ponto_digital e recursos globais. | Não cria marcações de ponto, servidores ou concessões a tenant. |

Além dessas 23 migrations, o comando Django migrate executa sinais post_migrate:
cria content types e permissões padrão/customizadas declaradas pelos modelos.
Isso NÃO cria usuários, superusuários, grupos com membros ou concessões de
permissões a contas. A criação dos três avaliadores, convites e duas organizações
DEMO é uma operação posterior, separadamente autorizada.

As variáveis DJANGO_SUPERUSER_* já existentes no Render serão preservadas, mas o
novo startup não executa createsuperuser. A revisão do startup, AppConfig e das
funções de dados não encontrou criação automática de usuário nesse caminho.

O tenant legado tecnolmed é criado por uma migration histórica. Não remover,
renomear ou ignorar a migration automaticamente; confirmar a aceitação desse
registro na autorização da inicialização. Não usar esse tenant como cliente real
nem importar seus dados de qualquer outro banco.

## Procedimento proposto, ainda não autorizado

1. Reconfirmar que somente vertyx-erp foi configurado para branch exclusiva,
   autodeploy Off e `/bin/sh /app/scripts/start-homologation.sh`. Não executar
   deploy, build remoto, start.sh, migrate_locked ou hooks nesta autorização.
2. Preparar executor de aplicação manual em revisão própria. O executor atual
   scripts/homologation_migrations.py permanece SOMENTE LEITURA e rejeita --apply.
   A futura implementação deve reaproveitar as guardas de destino/TLS em cada
   conexão, exigir confirmação explícita do banco e hash/SHA aprovados.
3. Obter a conexão já existente por ambiente temporário seguro, sem criar/revogar
   chave ou salvar DSN em disco/repositório/logs. Para execução local usar a URL
   externa exata do mesmo recurso, TLS verify-full e CA confiável; manter a URL
   interna do serviço Render intacta.
4. Em sessão read-only, validar nome/host/porta/usuários/owner/versão/SSL, ausência
   de recuperação, zero tabelas e nenhuma outra sessão de cliente. Se o banco
   deixar de estar vazio, parar e revisar; não fazer drop/fake/reset.
5. Verificar plano e hashes. Registrar backup lógico/estrutura inicial antes da
   escrita, se autorizado; conferir procedimento de recuperação sem apagar o
   banco. Fixar lock_timeout=5s e um statement_timeout limitado, apropriado ao
   ensaio prévio, e obter advisory lock exclusivo para evitar dois migradores.
6. Apenas com nova autorização, permitir escrita em uma conexão que passou por
   todas as guardas e executar migrate --database=default --noinput do SHA
   aprovado. Não aceitar outro alias/target, opções fake/run-syncdb ou retries.
   O advisory lock não substitui checagem de identidade nem bloqueia toda
   concorrência externa; revalidar imediatamente antes da primeira escrita.
7. Validar 137 entradas no histórico, tabelas/colunas/constraints, inclusive
   rh_municipal.0016, e nenhuma pendência. Verificar zero usuários e zero dados
   operacionais; conferir tenant legado, catálogos e permissões descritos acima.
8. Encerrar conexão e descartar variáveis temporárias; relatório sem segredos.
   Em falha, parar: migrations anteriores podem ter sido confirmadas. Não repetir,
   desfazer, recriar cluster ou restaurar automaticamente.
9. Solicitar aprovação independente do deploy, depois dos usuários/fixtures e dos
   testes funcionais online/R2 entre organizações fictícias.

Rollback de aplicação não reverte migrations. Não voltar à imagem antiga ou ao
banco suspenso sem verificar compatibilidade e autorização. O banco ainda vazio
não permite login antes da inicialização e da criação autorizada das contas.
