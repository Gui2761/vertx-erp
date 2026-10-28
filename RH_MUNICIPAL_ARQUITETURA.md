# RH Municipal — arquitetura e limites da primeira implementação

## Fronteiras de produto

- **ERP Assistência:** o RH já homologado permanece em `operacao.workforce_models`: `Funcionario`, `Departamento`, `JornadaTrabalho`, `EscalaFuncionario`, ponto, ajustes, fechamento e hora extra. Suas rotas continuam em `/rh/` e `/ponto/` e o middleware continua exigindo o catálogo `assistencia`.
- **ERP Loja Hospitalar:** a auditoria não encontrou módulo ou modelo de RH da Loja. O catálogo `loja-hospitalar` é criado como identidade de produto para a separação futura. Nenhum servidor municipal ou funcionário da Assistência é apresentado como funcionário da Loja.
- **ERP Gestão Pública:** usa o catálogo `gestao-publica`, rotas sob `/gestao-publica/rh/`, app Django `rh_municipal` e modelos próprios. Organização, identidade de usuário, membership, auditoria e storage privado continuam sendo serviços comuns.

## RH Municipal criado

Hierarquia isolada: Secretaria → Departamento → Setor → Unidade → Servidor. Catálogos municipais próprios incluem Cargo, Função, Vínculo e Jornada. A ficha de servidor possui sua própria chave pública e não usa `Funcionario` nem `Tecnico` da Assistência.

Papéis municipais independentes do papel global do membership: `ADMIN_MUNICIPAL`, `GESTOR_RH`, `RH_OPERADOR`, `CHEFIA` e `SERVIDOR`. O acesso exige simultaneamente ERP habilitado na organização, membership ERP Gestão Pública habilitado e papel municipal ativo. O primeiro administrador municipal pode ser provisionado pelo comando `atribuir_admin_rh_municipal`, que exige organização, conta-alvo, autorizador ADMIN da mesma organização e confirmação explícita.

As views atuais oferecem painel, cadastro/listagem de servidores, consulta da estrutura/cargos, concessão auditada de papéis, registro e decisão de solicitações, captura idempotente de ponto e portal de consulta do servidor. Todas as consultas usam o tenant da organização ativa; IDs e referências municipais são filtrados por esse tenant e por seus relacionamentos.

## Compartilhado e específico

Compartilhados: autenticação, Organization, membership, catálogo ERP, trilha PlatformAudit, contexto de tenant e mecanismo de storage. Específicos: servidores, hierarquia municipal, papéis, jornadas, pontos, férias, afastamentos, documentos e solicitações municipais. Nenhuma regra de RH da Assistência é aplicada ao servidor municipal.

## Limites que permanecem

- Não há RH da Loja implementado; o catálogo apenas permite testar fronteira de acesso.
- Folha, integrações, cálculo legal de jornada/banco de horas, políticas de férias e afastamentos, workflow completo de documentos, upload/storage municipal, edição histórica da ficha, escala municipal avançada e PWA/offline do servidor dependem de regras e homologação próprias.
- A jornada aceita parâmetros JSON, e o ponto registra eventos brutos idempotentes; a aplicação não calcula conformidade, folha ou direitos trabalhistas.
- Os dados do CPF são armazenados como campo cadastral no modelo, mas não há importação nem cadastro real nesta etapa.
- O comando de bootstrap não foi executado e nenhuma membership real recebeu papel municipal.

## Migration

`rh_municipal.0001_initial` cria somente tabelas municipais e adiciona entradas de catálogo para ERP Loja Hospitalar e Gestão Pública usando `get_or_create`. Não altera nem reverte migrations existentes e não concede ERP a nenhuma organização.

## Fases E–G — incrementos locais

### Processo Digital, transparência e atendimento público (E)

Os modelos e serviços ficam em `phase_e_models.py` / `phase_e_services.py`; publicações passam por uma camada própria de revisão e não expõem diretamente tabelas internas. Ouvidoria e E-SIC possuem número de protocolo e trilha de eventos. Documentos e versões permanecem separados. A confirmação registrada de assinatura não equivale, por si só, a assinatura qualificada ou validade jurídica certificada. PNCP, TCE e demais integrações continuam pendentes.

### Tributação e território (F)

O cadastro compartilhado do imóvel (`ImovelMunicipal`) serve ao território e à fundação de IPTU; contribuintes, regras versionadas, lançamentos, parcelas, pagamentos manuais auditados, dívida ativa e rascunhos de NFS-e são tenant-owned. Os códigos `tributos_municipais`, `gestao_territorial` e `nfse_municipal` entraram apenas no catálogo global. A migration 0020 registra metadados do catálogo e não concede módulo a Prefeituras.

As regras tributárias não presumem legislação, alíquota, valor venal, descontos ou atualização monetária: lançamento só é possível com parâmetro explicitamente cadastrado e snapshot da regra. Pagamento é manual, idempotente e sem integração bancária. NFS-e permanece rascunho; transmissão oficial está bloqueada. A estrutura ainda não implementa fotos de imóveis, mapas/cartografia, planta municipal de valores, conciliação bancária ou fluxo oficial de dívida ativa.

### Saúde SUS (G — fundação operacional)

Saúde SUS é um módulo contratual separado (`saude_sus`), sem concessão automática a qualquer tenant. Os registros usam Organization e escopo municipal; o cadastro comum de unidade e a ficha de servidor são reutilizados. A frota sanitária referencia `VeiculoMunicipal`/`CondutorMunicipal`, sem duplicar veículos. Foram modelados unidade de saúde, equipe, profissional, cidadão/paciente, família, agenda, atendimento, evolução, prescrição, visitas ACS/ACE, medicamentos/lotes/dispensação, vigilância sanitária/epidemiológica, regulação, TFD, transporte e rascunhos de produção AIH/APAC.

O dashboard apresenta agregados e não lista pacientes. Conteúdo de evolução, prescrição, visitas e outros campos protegidos usa payload binário cifrado por serviço; prontuário exige capacidade sensível, escopo e justificativa e grava auditoria antes da leitura. Sem `MUNICIPAL_HEALTH_ENCRYPTION_KEY` no ambiente, criação/leitura clínica falha fechada. Nenhuma chave ou registro de saúde foi provisionado no ambiente local nesta etapa.

As operações implementadas e cobertas por testes incluem cadastro de cidadão/paciente, agenda/atendimento com capacidade, leitura auditada de conteúdo clínico cifrado, dispensação FEFO transacional/idempotente, alteração de prioridade de regulação com justificativa e auditoria, e registro online de visitas ACS/ACE. A tela de campo exige módulo/permissão/escopo, vincula agente e referências existentes do próprio tenant, cifra observações, audita o registro e protege reenvios por identificador idempotente; a listagem não revela as observações. O cadastro de cidadão, os fluxos de farmácia e visitas possuem interface profissional. A fila offline, sincronização, GPS e anexos de campo ainda não estão implementados. As demais entidades ainda não têm workflow de tela completo. e-SUS, CNES, protocolos clínicos, AIH/APAC, transmissão, classificação oficial de agravos e faturamento não estão integrados/homologados; o módulo não declara conformidade SUS, clínica ou legal.

As migrations locais da Fase F são `platform_core.0020` e `rh_municipal.0008`; da Fase G são `platform_core.0021`, `rh_municipal.0009` e `rh_municipal.0010`. As alterações de catálogo são globais e não criam linhas em `ModuloOrganizacao`, contratos, planos ou memberships de tenants. Backups pré-migration e estado de preservação ficam registrados no relatório de homologação local desta execução.

### Controle Interno e Governança Municipal (I — primeira tranche operacional)

O módulo contratual `controle_interno` acrescenta registros tenant-owned de riscos (probabilidade e impacto registrados separadamente, sem escore normativo), controles, achados, recomendações e planos de ação. A conclusão de um plano exige capacidade distinta de validação; o encerramento de achado exige capacidade e justificativa. Evidências usam o storage privado já existente, nome de objeto com UUID sob o identificador público da organização, limite de 25 MB, formatos definidos, SHA-256 e download autenticado sem URL pública. Criações, transições e leituras de evidência geram eventos imutáveis.

As capacidades `governance.*` dependem do módulo contratado e ativo, membership ERP, acesso municipal ativo, permissão e escopo. Referências entre risco/controle/achado/recomendação/plano/evidência validam tenant e consistência de hierarquia. A migração `platform_core.0023` registra somente metadados globais do produto/módulo e recursos; `rh_municipal.0012` cria tabelas e não concede o módulo a nenhuma Prefeitura.

Esta primeira tranche oferece painel, formulários de registro, recomendação, plano, transição, encerramento e anexação/consulta privada de evidências. Ela não determina conformidade legal, matriz de riscos oficial, parecer jurídico, auditoria independente ou padrões de controladoria; não tem importação automática de contratos/processos, calendário de auditoria, amostragem, workflow de aprovação multi-etapa nem relatórios regulamentares. Esses itens exigem desenho e validação próprios antes de uso institucional.

As verificações de domínio do risco são reforçadas por `rh_municipal.0013`, com constraints de banco que limitam probabilidade e impacto ao intervalo de 1 a 5. Essa faixa é apenas uma entrada estruturada e não representa um escore normativo.

### Educação Municipal (H — primeira tranche)

`educacao_municipal` é um módulo independente de contrato, adicionado ao catálogo global sem concessão automática a nenhuma organização. A configuração de escola se vincula a uma `UnidadeMunicipal` existente; docentes reutilizam `Servidor`; alunos e responsáveis referenciam identidades do cadastro municipal comum; refeições podem referenciar `ItemAlmoxarifadoMunicipal` e rotas usam `VeiculoMunicipal`. Matrículas, frequência, avaliações/notas e calendário são registros próprios da Educação, com escopo municipal e validações contra referências cruzadas de outro tenant.

O painel apresenta contagens agregadas, listas limitadas pelo escopo e PWA sob `/gestao-publica/educacao/` com service worker de rede, sem cache offline de páginas autenticadas. Serviços iniciais cobrem configuração escolar sobre unidade existente, criação de identidade compartilhada e matrícula transacional, capacidade/duplicidade de turma, frequência corrigível com trilha de eventos e validação de notas por turma e teto de avaliação. Nenhuma escola, turma, pessoa, matrícula ou módulo de tenant é criado automaticamente por migration.

Esta tranche não conclui o ERP escolar: edição completa de salas/turmas, workflow de lotação docente, diário de classe, registro de responsáveis pela interface, calendário CRUD, gestão de cardápio/distribuição com baixa integrada ao estoque e operação detalhada do transporte precisam de telas e serviços adicionais. SIGE/INEP e integrações nacionais permanecem pendentes. A migration global `platform_core.0022` registra apenas o catálogo e recursos; `rh_municipal.0011` cria os modelos. Nenhum dado existente de organização é transformado nem módulo concedido.

### Portal do Cidadão (J — agregador público)

`/gestao-publica/publico/<slug>/` resolve uma organização municipal ativa e apresenta somente os canais públicos cujo módulo foi contratado, liberado e está ativo para aquele tenant: Transparência, Ouvidoria e E-SIC. O portal não consulta tabelas internas de outros tenants nem publica dados protegidos; cada canal segue a sua própria camada pública já existente. O acompanhamento exige protocolo e segredo privado, a resposta não é armazenada em cache e a página do formulário usa `no-store` e `no-referrer`. A tela do portal não substitui fluxos completos de serviços públicos, tributos ou consultas individuais; módulos não contratados continuam indisponíveis.


### Painel Executivo municipal (K — indicadores agregados)

`/gestao-publica/executivo/` exige acesso municipal, `dashboard.view` e `executive.dashboard.view`. Cada bloco exige ainda o produto/módulo contratado, ativo, permissão própria e escopo do usuário; a consulta aplica `organization` e `scoped_queryset` antes de contar registros. O painel exibe contagens agregadas, sem linhas individuais nem valores de saúde identificáveis. Receitas, despesas, saldo executado e conformidade contábil oficial são declarados indisponíveis enquanto os fluxos legais e integrações correspondentes não forem implementados e validados. Não há módulo nem permissão concedidos automaticamente a tenants.
# Fase L — preparação segura de integrações oficiais

O núcleo municipal inclui configuração tenant-scoped para PNCP, TCE, SIAFIC,
eSocial, sistemas SUS, e-SUS e CNES. A configuração exige produto, módulo
contratado, membership e permissão municipal no tenant atual. O acesso à tela
fica em `/gestao-publica/integracoes/`.

Nesta fase todos os registros permanecem desabilitados. Não há clientes HTTP,
transmissão, validação remota, emissão fiscal nem integração oficial. Endpoints
aceitam somente HTTPS sem credenciais, query ou fragmento; credenciais são
representadas apenas por referências `cofre://UUID`/`vault://UUID`. Valores de
segredo nunca são recebidos pelo formulário. Tentativas de operação são
idempotentes e ficam marcadas como bloqueadas enquanto não houver adaptador.

Corpos de requisição e resposta não são persistidos nesta fundação: somente o
digest SHA-256 da requisição (e, futuramente, da resposta) pode ser armazenado.
O armazenamento de payloads brutos exige uma especificação posterior de
minimização, redação, retenção, criptografia e controle de acesso. Não afirmar
conformidade ou comunicação com PNCP/TCE/SIAFIC/eSocial/SUS/CNES com base nesta
preparação. Cada adaptador real deverá ter homologação e autorização próprias.

# Fase M — contratos multierp, níveis e limites

Cada item `ItemContratoSaaS` guarda snapshot imutável por linha comercial de
módulos, limites, preço, periodicidade e nível de indicadores. A migration
`platform_core.0024` adiciona o snapshot do nível de indicadores sem reescrever
assinaturas, módulos ou memberships existentes.

O Admin SaaS pode ativar/suspender explicitamente um contrato com POST e
auditoria. Ativar valida organização, catálogo, plano, snapshots e conflito de
vigência, e habilita apenas `OrganizationERP`; não cria nem modifica
`MembershipERP`, permissões municipais ou módulos locais. Suspender desabilita o
produto quando não há outro item vigente. Assinaturas legadas que sobreponham o
mesmo produto impedem ativação até uma migração comercial explícita.

A política de módulos e indicadores considera início/fim de vigência e falha
fechado diante de linhas conflitantes, suspensas ou expiradas. Quotas
operacionais recebem o produto explicitamente, usam snapshots dos contratos
vigentes e bloqueiam operação sem contrato para produto sob controle contratual.
O uso medido continua agregado por tenant para os medidores existentes; limites
por produto são mostrados no detalhe SaaS e aplicados conservadoramente à
utilização tenant-wide enquanto os registros operacionais não tiverem
classificação uniforme de produto. Isso pode bloquear antes do limite nominal,
mas não permite excedê-lo por divisão artificial de produto.

Não há sincronização automática das permissões individuais; o Admin da
Prefeitura continua concedendo acesso às pessoas depois de o produto estar
contratado e ativo.

# Fase G — vigilância sanitária e epidemiológica (homologação local)

A tranche local acrescenta cadastro de estabelecimentos sujeitos à vigilância,
inspeções sanitárias e notificações epidemiológicas de referência interna. Os
serviços validam tenant, membership, produto/módulo, permissão municipal e
escopo; registram auditoria e evitam repetição por chave de operação. Anotações
de inspeção e detalhes epidemiológicos são cifrados em repouso e não aparecem
nas listagens. Transições epidemiológicas são auditadas e não permitem reabrir
uma notificação encerrada. O acesso fica em
`/gestao-publica/saude/vigilancia/`.

Esta entrega é fundação de homologação, não um fluxo de vigilância oficial. Não
há classificação epidemiológica oficial, transmissão ao SINAN/e-SUS, integração
com CNES, emissão de licença, gestão de anexos, autos/notificações sanitárias,
validação normativa por município/UF ou protocolo oficial. Não alegar
conformidade sanitária/SUS. Permanecem pendentes os fluxos municipais completos
de TFD/transporte e produção/BI, além de homologação com as áreas responsáveis.
Nenhuma migration ou dado de produção é necessário para esta tranche.

### Incremento TFD e produção SUS

As rotas `/gestao-publica/saude/tfd/` e `/gestao-publica/saude/producao/`
reutilizam `TFDMunicipal` e `RegistroProducaoSUS`, com capacidades separadas,
consultas limitadas ao escopo, chave de idempotência e auditoria de criação e
decisão. O destino/finalidade/acompanhante do TFD são cifrados; as colunas
legadas recebem apenas o marcador genérico e a interface não mostra a identidade
do cidadão. O ciclo local permite PENDENTE para AUTORIZADA/NEGADA e AUTORIZADA
para CONCLUÍDA, sem reabertura.

Registros de produção e rascunhos AIH/APAC permanecem `NAO_TRANSMITIDO`; a lista
não apresenta nomes de pacientes. Ainda não existe vínculo relacional de TFD a
uma viagem da frota, agendamento de transporte sanitário, despesa, fluxo de
reembolso, validador de procedimento, faturamento ou transmissão. A frota
municipal continua seu domínio separado até uma modelagem relacional revisada.
Nenhuma migration foi criada neste incremento.

### Regulação e fila municipal

`/gestao-publica/saude/regulacao/` acrescenta solicitações de regulação,
capacidade por vaga, agendamento vinculado a atendimento e transições
ATENDIDO/CANCELADO com retorno auditável à fila quando cancelado. A migration
`rh_municipal.0015` cria somente o vínculo `AgendamentoRegulacaoSaude`; não
altera registros clínicos, vagas, atendimentos ou organizações existentes.
Criação de solicitações e vagas usa UUID de operação e auditoria para
idempotência; o agendamento bloqueia a vaga e conta reservas ativas antes de
confirmar capacidade. A priorização exige justificativa, registra apenas seu
conteúdo cifrado na auditoria e mantém um marcador genérico no campo legado.

A tela e os serviços exigem permissões municipais distintas para consulta,
gestão e priorização, além de tenant e escopo. Esta fundação não faz triagem
clínica automática, classificação de risco oficial, integração com sistemas de
regulação externos, transporte TFD, comunicação com prestadores ou confirmação
de presença externa. Nenhuma vaga, solicitação ou agenda é criada pela
migration.
