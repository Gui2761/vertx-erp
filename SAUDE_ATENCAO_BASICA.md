# Atenção Básica / UBS — primeira tranche

Rota: `/gestao-publica/saude/atencao-basica/`.

Reutiliza o catálogo `saude_sus`, contratação, tenant, hierarquia municipal,
`UnidadeSaudeMunicipal`, `EquipeSaudeMunicipal`, `FamiliaTerritorialSaude`,
`CidadaoSaudeMunicipal`, `VinculoFamiliaSaude` e `AuditoriaAcessoSaude`.
Não cria tabelas ou migrations.

## Operação

- Filtrar UBS/Centro de Saúde ativo e consultar contagens de famílias e equipes.
- Cadastrar família com código interno, endereço, microárea e equipe da unidade.
- Vincular cidadão ativo já cadastrado por CPF/CNS exato, sem listar pacientes.
- Exigir a mesma unidade de referência, uma única família ativa por cidadão e
  no máximo um cidadão de referência por família no fluxo deste serviço.
- Repetir um vínculo com os mesmos dados preserva o registro; dados diferentes
  geram erro, sem sobrescrever o vínculo.

Permissões: `saude.primary.view` para leitura, `saude.primary.manage` para cadastro
e, adicionalmente, `saude.patients.view` para vínculo de cidadão. Administradores
municipais seguem a regra de acesso existente. O escopo da capacidade usada é
aplicado às consultas; um acesso amplo sem essa capacidade não amplia a UBS.

## Proteção e auditoria

A tela agregada não retorna nomes, documentos, endereços ou conteúdo clínico.
CPF/CNS são enviados somente no formulário POST de vínculo. Respostas usam
`no-store`. Consultas agregadas e criações são auditadas sem copiar endereço,
documentos ou parentesco para detalhes de auditoria. O audit de vínculo mantém
somente os identificadores internos necessários à rastreabilidade.

Os serviços de escrita usam transação; o vínculo bloqueia cidadão e família
antes de validar conflitos. Concorrência real entre conexões PostgreSQL não é
validada pelos testes SQLite desta tranche.

## Limites

Não inclui edição, transferência ou encerramento de vínculos familiares;
nem validação oficial de CPF/CNS, CNES, e-SUS ou transmissão ao SUS. Não altera
o fluxo clínico, a regulação, o TFD, a farmácia ou a produção SUS existentes.
Essas áreas seguem para tranches posteriores. O endereço usa o modelo
territorial existente; esta tranche não acrescenta cifragem nesse campo.

Teste direcionado: `rh_municipal.test_primary_care`. Executar somente com
configuração SQLite isolada, nunca apontando o teste para banco operacional.

## Validação desta tranche

- 16 testes de UBS aprovados em SQLite temporário isolado.
- 26 testes existentes de `rh_municipal.test_phase_g` aprovados como regressão.
- `manage.py check`: sem problemas.
- `makemigrations --check --dry-run`: nenhuma alteração detectada.
- `git diff --check`: sem erros de whitespace.

Não foi executada a suíte completa, nem acessado PostgreSQL operacional.
