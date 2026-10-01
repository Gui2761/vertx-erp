# Auditoria anterior à implementação dos módulos

30/09/2026. Base: código local de tecnolmed_erp e ZIP vertyx_homologacao.zip.
O ambiente Render publicado não foi acessado e não foi alterado.

| Módulo | Model / migration / formulário / view / URL / template funcional | Causa do menu desabilitado |
|---|---|---|
| Peças e Estoque | Ausentes; existe somente OrdemServico.pecas, texto livre sem movimentação | Link disabled, href #, título Etapa 3 em templates/base.html |
| Orçamentos | Ausentes | Link disabled, href #, título Etapa 5 |
| Contratos | Ausentes | Link disabled, href #, título Etapa 5 |
| Financeiro | Ausentes; perfil FINANCEIRO já disponível | Link disabled, href #, título Etapa 5 |
| Relatórios | Ausentes como central; ordens.reports já gera comprovante PDF de OS | Link disabled, href #, título Etapa 6 |

Não há feature flag configurando esses cinco módulos. Os títulos anunciam
desenvolvimento futuro; remover disabled sozinho criaria links sem funcionalidade.
core.models está vazio; core.views possui apenas PainelView. Nenhuma tabela
dos cinco módulos é criada pelas migrations locais existentes.

Arquitetura aproveitável: OrganizationOwned/TenantOwned e TenantManager filtram
SQL por organização de ContextVar, validam FKs e impedem transferência entre
tenants. OrganizationMiddleware seleciona membership ativo e require_erp
verifica usuário/organização, OrganizationERP, catálogo e MembershipERP.
contas.permissions já fornece decorator e mixin por papéis do vínculo.
TenantModelForm renova choices por organização a cada request. PlatformAudit
registra alterações e ordens.services mantém transações, snapshots e assinatura.

Relacionamentos atuais: cliente possui unidades; equipamento exige cliente e
unidade coerentes; OS exige equipamento do cliente/unidade e técnico do tenant.
Técnico pode ter conta vinculada à mesma organização. Equipamento possui datas
e periodicidade de preventiva/calibração, reaproveitáveis pelo planejamento.
O PDF de OS existente deve permanecer com snapshots antigos imutáveis.

Divergência informada ao usuário: Planejamento também é marcador disabled
Etapa 4 nesta cópia, sem endpoint próprio, embora o pedido informe que funciona
em produção. A fonte de produção precisa ser confirmada para afirmar equivalência.
Nenhum endpoint de produção foi removido/substituído pela auditoria.

Infraestrutura preservada: requirements, env, credenciais, DATABASE_URL,
SECRET_KEY, AWS/S3, Docker, scripts de start, Gunicorn e render.yaml. Novas
tabelas devem usar migrations incrementais e a mesma autenticação/organização.
