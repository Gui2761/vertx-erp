# Prontuário e Atendimento em Saúde

Esta tranche amplia os modelos existentes de cidadão, atendimento, evolução,
prescrição, profissionais, equipes, família e auditoria. Não cria outro cadastro
de paciente, prontuário ou atendimento.

## Operação

- Entrada em `/gestao-publica/saude/prontuarios/`; busca exata por CPF/CNS em POST,
  sem documentos na URL nem listagem geral de pacientes.
- Prontuário por cidadão, histórico de atendimentos e registros em ordem
  cronológica, com paginação. A navegação dos agendamentos abre o cidadão.
- Abertura de atendimento na unidade de referência, com responsável ativo;
  um atendimento agendado existente pode ser iniciado sem criar outro.
- Registros estruturados de acolhimento, consulta médica, enfermagem, queixa,
  avaliação, diagnóstico/CID informado, procedimentos, sinais vitais e evolução.
- Solicitações locais de exames e encaminhamentos com destino informado.
- Prescrição local com medicamento, quantidade, posologia e orientações;
  cancelamento justificado é registrado sem apagar o histórico.
- Anexos PDF até 2 MB, cifrados no próprio registro, com download autenticado.
- Retificações criam outra evolução vinculada à original. Não sobrescrevem
  registros anteriores. Uma versão já retificada não recebe outra retificação;
  a correção seguinte deve partir da versão atual.
- Profissional autor, responsável, unidade e equipe são identificados. Os
  registros estruturados preservam os vínculos e nomes daquela ocasião no
  conteúdo cifrado, mesmo que a equipe seja renomeada posteriormente.

## Autorização

Reutiliza membership, produto `gestao-publica`, contratação do módulo
`saude_sus`, hierarquia municipal e verificação por registro. O escopo de uma
capacidade não é ampliado por outro acesso sem essa capacidade.

- `saude.patients.view` e `saude.records.view`: identidade e histórico operacional.
- `saude.records.sensitive`: leitura do conteúdo clínico, com finalidade e auditoria.
- `saude.records.create`: abertura de atendimento e novos registros.
- `saude.records.edit`: retificações, cancelamento de prescrição e conclusão.

Novos registros clínicos também exigem vínculo profissional ativo do usuário na
unidade do atendimento. Nenhum perfil genérico de ERP substitui acesso municipal.
Leitores não fazem POST nas rotas de prontuário. A busca em POST é limitada a
operadores com criação; leitores entram pelo atendimento autorizado. A rota
clínica antiga também exige leitura, acesso sensível e criação para POST.

## Proteção de dados

Metadados são separados do conteúdo clínico. A abertura é auditada; recuperar
conteúdo exige finalidade padronizada e gera auditoria por evolução. Apenas os
eventos da página e do atendimento autorizado são recuperados.

Queixas, avaliação, diagnóstico, CID, procedimentos, sinais, evolução, pedidos,
motivos de retificação, documentos e snapshots profissionais usam o conteúdo
Fernet já existente. Novas prescrições cifram também o nome do medicamento;
posologia e orientações usam os campos cifrados existentes. Auditorias não
copiam esses conteúdos. IDs, datas, status e quantidade continuam relacionais.

Não há arquivo clínico em mídia pública nem URL pública de download. PDF é
entregue como attachment, sem execução inline. Respostas usam `no-store` e os
service workers municipal e Saúde ignoram explicitamente rotas clínicas.
Não há busca por documento em query string nem texto clínico em redirects.

A chave `MUNICIPAL_HEALTH_ENCRYPTION_KEY` existente deve estar provisionada.
Ausência de chave ou falha de integridade bloqueia recuperação e escrita clínica.

## Migration

`rh_municipal/0016_itemprescricao_nome_protegido`:

- permite deixar vazio o nome legado de medicamento;
- acrescenta o nome cifrado aos itens de prescrição;
- acrescenta a relação única de retificação entre evoluções.

Preserva todos os dados anteriores. Não reescreve nem cifra automaticamente nomes
legados; estes permanecem sujeitos às permissões clínicas. Nenhuma migration
histórica é alterada. Aplicação no PostgreSQL exige autorização posterior.

## Limites desta tranche

Não há transmissão e-SUS/SUS, catálogo oficial de CID/procedimentos, validação
oficial de conselho profissional, assinatura digital ou emissão de receita
oficial. Códigos e condutas são informados pelo profissional, nunca gerados
pelo sistema. Encaminhamentos clínicos não abrem automaticamente a fila de
regulação, que continua separada. Exames solicitados podem receber documentos
no atendimento; não há interface com laboratório nesta etapa.

A tela registra um medicamento por prescrição. PDF é limitado a 2 MB e não há
visualizador inline. Eventos usam envelope versionado `vertyx.clinical.v1`, sem
misturar um futuro adaptador oficial com a operação local. Não há reabertura de
atendimento concluído nem edição destrutiva de evoluções.

Testes desta tranche usam apenas SQLite temporário. Concorrência entre conexões
PostgreSQL, rotação de chaves e validação operacional de credenciais clínicas
não são comprovadas por esses testes.
