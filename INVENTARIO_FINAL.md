# Inventário final — VERTYX

Gerado por `tests/final_inventory.py` a partir do registry Django e do resolver.
Não consulta registros, variáveis secretas ou credenciais. Consulte ENTREGA_FINAL.md
e CENTRAL_OPERACOES.md para regras atuais de acesso e AUDITORIA_OPERACOES_ARQUIVOS.json para o diff.

Os modelos empresariais usam Organization/contexto tenant. Identidades, catálogo
ERP e tabelas internas Django são globais; memberships/grants delimitam acesso.
Tabelas intermediárias automáticas de relações M2M não aparecem como modelos
independentes. O Django Admin exige o operador autorizado da plataforma.

## Modelos e campos

### admin

#### admin.LogEntry — tabela `django_admin_log`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | AutoField | — |
| `action_time` | DateTimeField | — |
| `user` | ForeignKey | contas.Usuario |
| `content_type` | ForeignKey | contenttypes.ContentType |
| `object_id` | TextField | — |
| `object_repr` | CharField | — |
| `action_flag` | PositiveSmallIntegerField | — |
| `change_message` | TextField | — |

### auth

#### auth.Permission — tabela `auth_permission`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | AutoField | — |
| `name` | CharField | — |
| `content_type` | ForeignKey | contenttypes.ContentType |
| `codename` | CharField | — |

#### auth.Group — tabela `auth_group`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | AutoField | — |
| `name` | CharField | — |
| `permissions` | ManyToManyField | auth.Permission |

### contenttypes

#### contenttypes.ContentType — tabela `django_content_type`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | AutoField | — |
| `app_label` | CharField | — |
| `model` | CharField | — |

### sessions

#### sessions.Session — tabela `django_session`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `session_key` | CharField | — |
| `session_data` | TextField | — |
| `expire_date` | DateTimeField | — |

### contas

#### contas.Usuario — tabela `contas_usuario`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `password` | CharField | — |
| `last_login` | DateTimeField | — |
| `is_superuser` | BooleanField | — |
| `username` | CharField | — |
| `first_name` | CharField | — |
| `last_name` | CharField | — |
| `email` | CharField | — |
| `is_staff` | BooleanField | — |
| `is_active` | BooleanField | — |
| `date_joined` | DateTimeField | — |
| `perfil` | CharField | — |
| `telefone` | CharField | — |
| `groups` | ManyToManyField | auth.Group |
| `user_permissions` | ManyToManyField | auth.Permission |

#### contas.Tecnico — tabela `contas_tecnico`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `usuario` | ForeignKey | contas.Usuario |
| `nome` | CharField | — |
| `telefone` | CharField | — |
| `whatsapp` | CharField | — |
| `email` | CharField | — |
| `especialidades` | CharField | — |
| `registro_profissional` | CharField | — |
| `jornada` | CharField | — |
| `custo_hora` | DecimalField | — |
| `ativo` | BooleanField | — |
| `criado_em` | DateTimeField | — |
| `atualizado_em` | DateTimeField | — |

### clientes

#### clientes.Cliente — tabela `clientes_cliente`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `tipo_pessoa` | CharField | — |
| `nome_razao_social` | CharField | — |
| `nome_fantasia` | CharField | — |
| `cpf_cnpj` | CharField | — |
| `inscricao_estadual` | CharField | — |
| `inscricao_municipal` | CharField | — |
| `responsavel` | CharField | — |
| `telefone` | CharField | — |
| `whatsapp` | CharField | — |
| `email` | CharField | — |
| `endereco` | CharField | — |
| `numero` | CharField | — |
| `complemento` | CharField | — |
| `bairro` | CharField | — |
| `cidade` | CharField | — |
| `uf` | CharField | — |
| `cep` | CharField | — |
| `observacoes` | TextField | — |
| `ativo` | BooleanField | — |
| `criado_em` | DateTimeField | — |
| `atualizado_em` | DateTimeField | — |

#### clientes.ContatoCliente — tabela `clientes_contatocliente`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `nome` | CharField | — |
| `cargo` | CharField | — |
| `telefone` | CharField | — |
| `whatsapp` | CharField | — |
| `email` | CharField | — |
| `principal` | BooleanField | — |

#### clientes.Unidade — tabela `clientes_unidade`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `nome` | CharField | — |
| `setor` | CharField | — |
| `endereco` | CharField | — |
| `numero` | CharField | — |
| `bairro` | CharField | — |
| `cidade` | CharField | — |
| `uf` | CharField | — |
| `cep` | CharField | — |
| `responsavel_local` | CharField | — |
| `email` | CharField | — |
| `observacoes` | TextField | — |
| `telefone` | CharField | — |
| `ativo` | BooleanField | — |

### equipamentos

#### equipamentos.CategoriaEquipamento — tabela `equipamentos_categoriaequipamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `descricao` | CharField | — |

#### equipamentos.Equipamento — tabela `equipamentos_equipamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `codigo_publico` | UUIDField | — |
| `codigo_interno` | CharField | — |
| `numero_serie` | CharField | — |
| `nome` | CharField | — |
| `categoria` | ForeignKey | equipamentos.CategoriaEquipamento |
| `fabricante` | CharField | — |
| `modelo` | CharField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `unidade` | ForeignKey | clientes.Unidade |
| `setor` | CharField | — |
| `localizacao` | CharField | — |
| `patrimonio` | CharField | — |
| `data_aquisicao` | DateField | — |
| `criticidade` | CharField | — |
| `data_instalacao` | DateField | — |
| `data_fim_garantia` | DateField | — |
| `periodicidade_preventiva_meses` | PositiveIntegerField | — |
| `periodicidade_calibracao_meses` | PositiveIntegerField | — |
| `data_ultima_preventiva` | DateField | — |
| `data_ultima_calibracao` | DateField | — |
| `situacao_operacional` | CharField | — |
| `foto` | FileField | — |
| `manual` | FileField | — |
| `observacoes` | TextField | — |
| `qr_code` | FileField | — |
| `criado_em` | DateTimeField | — |
| `atualizado_em` | DateTimeField | — |

### ordens

#### ordens.OrdemServico — tabela `ordens_ordemservico`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `codigo` | UUIDField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `unidade` | ForeignKey | clientes.Unidade |
| `equipamento` | ForeignKey | equipamentos.Equipamento |
| `tecnico` | ForeignKey | contas.Tecnico |
| `tipo_atendimento` | CharField | — |
| `contrato` | ForeignKey | gestao.Contrato |
| `prioridade` | CharField | — |
| `agendada_para` | DateTimeField | — |
| `agendada_ate` | DateTimeField | — |
| `prazo` | DateTimeField | — |
| `horas` | DecimalField | — |
| `deslocamento_km` | DecimalField | — |
| `checklist` | JSONField | — |
| `numero_personalizado` | CharField | — |
| `defeito` | TextField | — |
| `diagnostico` | TextField | — |
| `servico_executado` | TextField | — |
| `pecas` | TextField | — |
| `observacoes` | TextField | — |
| `valor_cobranca` | DecimalField | — |
| `vencimento_cobranca` | DateField | — |
| `status` | CharField | — |
| `abertura` | DateTimeField | — |
| `inicio` | DateTimeField | — |
| `conclusao` | DateTimeField | — |
| `revisao` | PositiveIntegerField | — |
| `ciclo` | PositiveIntegerField | — |

#### ordens.Localizacao — tabela `ordens_localizacao`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `ciclo` | PositiveIntegerField | — |
| `evento` | CharField | — |
| `resultado` | CharField | — |
| `latitude` | DecimalField | — |
| `longitude` | DecimalField | — |
| `precisao` | FloatField | — |
| `registrado_em` | DateTimeField | — |
| `usuario` | ForeignKey | contas.Usuario |

#### ordens.Foto — tabela `ordens_foto`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `arquivo` | FileField | — |
| `descricao` | CharField | — |
| `sha256` | CharField | — |
| `criado_em` | DateTimeField | — |
| `usuario` | ForeignKey | contas.Usuario |

#### ordens.Conferencia — tabela `ordens_conferencia`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `usuario` | ForeignKey | contas.Usuario |
| `revisao` | PositiveIntegerField | — |
| `ciclo` | PositiveIntegerField | — |
| `dados` | JSONField | — |
| `digest` | CharField | — |
| `localizacao_final` | OneToOneField | ordens.Localizacao |
| `criado_em` | DateTimeField | — |
| `issuer` | JSONField | — |

#### ordens.Assinatura — tabela `ordens_assinatura`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `conferencia` | OneToOneField | ordens.Conferencia |
| `ciclo` | PositiveIntegerField | — |
| `nome` | CharField | — |
| `cargo` | CharField | — |
| `imagem` | TextField | — |
| `imagem_sha256` | CharField | — |
| `assinado_em` | DateTimeField | — |
| `usuario` | ForeignKey | contas.Usuario |

#### ordens.Auditoria — tabela `ordens_auditoria`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `usuario` | ForeignKey | contas.Usuario |
| `data` | DateTimeField | — |
| `acao` | CharField | — |
| `alteracoes` | JSONField | — |
| `justificativa` | TextField | — |

### platform_core

#### platform_core.Organization — tabela `platform_core_organization`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `public_id` | UUIDField | — |
| `slug` | SlugField | — |
| `razao_social` | CharField | — |
| `nome_fantasia` | CharField | — |
| `cnpj` | CharField | — |
| `email` | CharField | — |
| `telefone` | CharField | — |
| `status` | CharField | — |
| `logo_key` | CharField | — |
| `document_details` | TextField | — |
| `created_at` | DateTimeField | — |
| `updated_at` | DateTimeField | — |

#### platform_core.ERPCatalog — tabela `platform_core_erpcatalog`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `code` | SlugField | — |
| `name` | CharField | — |
| `description` | TextField | — |
| `active` | BooleanField | — |

#### platform_core.OrganizationERP — tabela `platform_core_organizationerp`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `erp` | ForeignKey | platform_core.ERPCatalog |
| `enabled` | BooleanField | — |
| `enabled_at` | DateTimeField | — |
| `disabled_at` | DateTimeField | — |

#### platform_core.OrganizationMembership — tabela `platform_core_organizationmembership`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `user` | ForeignKey | contas.Usuario |
| `status` | CharField | — |
| `role` | CharField | — |
| `joined_at` | DateTimeField | — |
| `left_at` | DateTimeField | — |

#### platform_core.MembershipERP — tabela `platform_core_membershiperp`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `visualizar_painel_operacional` | BooleanField | — |
| `membership` | ForeignKey | platform_core.OrganizationMembership |
| `erp` | ForeignKey | platform_core.ERPCatalog |
| `enabled` | BooleanField | — |

#### platform_core.PlatformAudit — tabela `platform_core_platformaudit`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `erp` | ForeignKey | platform_core.ERPCatalog |
| `user` | ForeignKey | contas.Usuario |
| `action` | CharField | — |
| `record` | CharField | — |
| `changes` | JSONField | — |
| `created_at` | DateTimeField | — |

### gestao

#### gestao.Fornecedor — tabela `gestao_fornecedor`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `documento` | CharField | — |
| `contato` | CharField | — |
| `telefone` | CharField | — |
| `email` | CharField | — |
| `ativo` | BooleanField | — |

#### gestao.Peca — tabela `gestao_peca`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `sku` | CharField | — |
| `descricao` | CharField | — |
| `fabricante` | CharField | — |
| `marca` | CharField | — |
| `referencia` | CharField | — |
| `categoria` | ForeignKey | operacao.CategoriaPeca |
| `estoque_maximo` | DecimalField | — |
| `ncm` | CharField | — |
| `cfop` | CharField | — |
| `cst_csosn` | CharField | — |
| `unidade_medida` | CharField | — |
| `quantidade_atual` | DecimalField | — |
| `estoque_minimo` | DecimalField | — |
| `localizacao` | CharField | — |
| `custo_aquisicao` | DecimalField | — |
| `preco_venda` | DecimalField | — |
| `fornecedor` | ForeignKey | gestao.Fornecedor |
| `lote` | CharField | — |
| `validade` | DateField | — |
| `controla_validade` | BooleanField | — |
| `ativo` | BooleanField | — |

#### gestao.Movimentacao — tabela `gestao_movimentacao`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `detalhamento` | JSONField | — |
| `peca` | ForeignKey | gestao.Peca |
| `origem` | ForeignKey | operacao.Deposito |
| `destino` | ForeignKey | operacao.Deposito |
| `tipo` | CharField | — |
| `quantidade` | DecimalField | — |
| `variacao` | DecimalField | — |
| `saldo_apos` | DecimalField | — |
| `custo_unitario` | DecimalField | — |
| `preco_unitario` | DecimalField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `usuario` | ForeignKey | contas.Usuario |
| `observacao` | TextField | — |
| `criado_em` | DateTimeField | — |
| `request_id` | UUIDField | — |

#### gestao.Orcamento — tabela `gestao_orcamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `numero_personalizado` | CharField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `unidade` | ForeignKey | clientes.Unidade |
| `equipamento` | ForeignKey | equipamentos.Equipamento |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `ordem_convertida` | ForeignKey | ordens.OrdemServico |
| `data` | DateField | — |
| `validade` | DateField | — |
| `diagnostico` | TextField | — |
| `servicos` | TextField | — |
| `desconto` | DecimalField | — |
| `deslocamento` | DecimalField | — |
| `impostos` | DecimalField | — |
| `observacoes` | TextField | — |
| `condicoes_pagamento` | TextField | — |
| `prazo_execucao` | CharField | — |
| `gerar_recebivel` | BooleanField | — |
| `status` | CharField | — |
| `criado_por` | ForeignKey | contas.Usuario |

#### gestao.ItemOrcamento — tabela `gestao_itemorcamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `orcamento` | ForeignKey | gestao.Orcamento |
| `tipo` | CharField | — |
| `peca` | ForeignKey | gestao.Peca |
| `descricao` | CharField | — |
| `quantidade` | DecimalField | — |
| `valor_unitario` | DecimalField | — |
| `desconto` | DecimalField | — |

#### gestao.Contrato — tabela `gestao_contrato`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `numero` | CharField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `data_inicial` | DateField | — |
| `data_final` | DateField | — |
| `valor` | DecimalField | — |
| `periodicidade_cobranca` | CharField | — |
| `tipo` | CharField | — |
| `quantidade_visitas` | PositiveIntegerField | — |
| `periodicidade_preventiva_meses` | PositiveIntegerField | — |
| `sla_horas` | PositiveIntegerField | — |
| `observacoes` | TextField | — |
| `reajuste` | CharField | — |
| `cobertura_servicos` | TextField | — |
| `cobertura_pecas` | TextField | — |
| `status` | CharField | — |
| `unidades` | ManyToManyField | clientes.Unidade |
| `equipamentos` | ManyToManyField | equipamentos.Equipamento |

#### gestao.ContratoUnidade — tabela `gestao_contratounidade`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `contrato` | ForeignKey | gestao.Contrato |
| `unidade` | ForeignKey | clientes.Unidade |

#### gestao.ContratoEquipamento — tabela `gestao_contratoequipamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `contrato` | ForeignKey | gestao.Contrato |
| `equipamento` | ForeignKey | equipamentos.Equipamento |

#### gestao.AgendaPreventiva — tabela `gestao_agendapreventiva`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `contrato` | ForeignKey | gestao.Contrato |
| `equipamento` | ForeignKey | equipamentos.Equipamento |
| `data_prevista` | DateField | — |
| `tecnico` | ForeignKey | contas.Tecnico |
| `ordem` | OneToOneField | ordens.OrdemServico |
| `cancelada` | BooleanField | — |

#### gestao.CategoriaFinanceira — tabela `gestao_categoriafinanceira`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |

#### gestao.CentroCusto — tabela `gestao_centrocusto`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |

#### gestao.FormaPagamento — tabela `gestao_formapagamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |

#### gestao.Lancamento — tabela `gestao_lancamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `tipo` | CharField | — |
| `descricao` | CharField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `fornecedor` | ForeignKey | gestao.Fornecedor |
| `categoria` | ForeignKey | gestao.CategoriaFinanceira |
| `centro_custo` | ForeignKey | gestao.CentroCusto |
| `forma_pagamento` | ForeignKey | gestao.FormaPagamento |
| `valor` | DecimalField | — |
| `data_emissao` | DateField | — |
| `vencimento` | DateField | — |
| `status` | CharField | — |
| `data_liquidacao` | DateField | — |
| `observacoes` | TextField | — |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `orcamento` | ForeignKey | gestao.Orcamento |
| `contrato` | ForeignKey | gestao.Contrato |
| `competencia` | DateField | — |
| `criado_por` | ForeignKey | contas.Usuario |

#### gestao.EventoFinanceiro — tabela `gestao_eventofinanceiro`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `lancamento` | ForeignKey | gestao.Lancamento |
| `tipo` | CharField | — |
| `valor` | DecimalField | — |
| `data` | DateField | — |
| `usuario` | ForeignKey | contas.Usuario |
| `observacao` | TextField | — |
| `criado_em` | DateTimeField | — |

### operacao

#### operacao.Configuracao — tabela `operacao_configuracao`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `painel_intervalo` | PositiveSmallIntegerField | — |
| `painel_tema` | CharField | — |
| `painel_blocos` | JSONField | — |
| `estoque_minimo_padrao` | DecimalField | — |
| `estoque_ideal_padrao` | DecimalField | — |
| `intervalo_alertas_minutos` | PositiveSmallIntegerField | — |
| `dias_alerta_validade` | JSONField | — |
| `relatorio_semanal_ativo` | BooleanField | — |
| `relatorio_dia_semana` | PositiveSmallIntegerField | — |
| `relatorio_horario` | TimeField | — |
| `consumo_historico_dias` | PositiveSmallIntegerField | — |
| `reposicao_dias` | PositiveSmallIntegerField | — |
| `ultima_verificacao_estoque` | DateTimeField | — |
| `endereco` | TextField | — |
| `prefixo_os` | CharField | — |
| `prefixo_orcamento` | CharField | — |
| `prefixo_contrato` | CharField | — |
| `digitos_numero` | PositiveSmallIntegerField | — |
| `prazo_financeiro_dias` | PositiveSmallIntegerField | — |
| `juros_mensal_percentual` | DecimalField | — |
| `multa_percentual` | DecimalField | — |
| `municipio_fiscal` | CharField | — |
| `codigo_servico` | CharField | — |
| `ambiente_fiscal` | CharField | — |
| `provedor_fiscal` | CharField | — |

#### operacao.Deposito — tabela `operacao_deposito`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |
| `endereco` | CharField | — |

#### operacao.SaldoDeposito — tabela `operacao_saldodeposito`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `deposito` | ForeignKey | operacao.Deposito |
| `peca` | ForeignKey | gestao.Peca |
| `quantidade` | DecimalField | — |

#### operacao.CategoriaPeca — tabela `operacao_categoriapeca`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |

#### operacao.Chamado — tabela `operacao_chamado`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `cliente` | ForeignKey | clientes.Cliente |
| `unidade` | ForeignKey | clientes.Unidade |
| `equipamento` | ForeignKey | equipamentos.Equipamento |
| `contrato` | ForeignKey | gestao.Contrato |
| `titulo` | CharField | — |
| `descricao` | TextField | — |
| `prioridade` | CharField | — |
| `status` | CharField | — |
| `ordem` | OneToOneField | ordens.OrdemServico |
| `criado_por` | ForeignKey | contas.Usuario |
| `criado_em` | DateTimeField | — |

#### operacao.ModeloChecklist — tabela `operacao_modelochecklist`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |
| `itens` | JSONField | — |

#### operacao.PlanoPreventivo — tabela `operacao_planopreventivo`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `contrato` | ForeignKey | gestao.Contrato |
| `checklist` | ForeignKey | operacao.ModeloChecklist |
| `tecnico` | ForeignKey | contas.Tecnico |
| `periodicidade` | CharField | — |
| `intervalo_dias` | PositiveIntegerField | — |
| `inicio` | DateField | — |
| `fim` | DateField | — |
| `ultima_execucao` | DateField | — |
| `observacoes` | TextField | — |
| `equipamentos` | ManyToManyField | equipamentos.Equipamento |

#### operacao.PlanoEquipamento — tabela `operacao_planoequipamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `plano` | ForeignKey | operacao.PlanoPreventivo |
| `equipamento` | ForeignKey | equipamentos.Equipamento |

#### operacao.PreventivaProgramada — tabela `operacao_preventivaprogramada`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `plano` | ForeignKey | operacao.PlanoPreventivo |
| `equipamento` | ForeignKey | equipamentos.Equipamento |
| `data` | DateField | — |
| `ordem` | OneToOneField | ordens.OrdemServico |
| `cancelada` | BooleanField | — |

#### operacao.Compra — tabela `operacao_compra`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `status` | CharField | — |
| `criado_por` | ForeignKey | contas.Usuario |
| `criado_em` | DateTimeField | — |
| `observacoes` | TextField | — |
| `relatorio_estoque` | ForeignKey | operacao.RelatorioEstoque |
| `pedido_relatorio_id` | UUIDField | — |
| `selecao_relatorio` | JSONField | — |
| `fornecedor` | ForeignKey | gestao.Fornecedor |
| `deposito` | ForeignKey | operacao.Deposito |
| `necessidade` | TextField | — |
| `vencimento` | DateField | — |
| `conta` | OneToOneField | gestao.Lancamento |

#### operacao.ItemCompra — tabela `operacao_itemcompra`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `lote` | CharField | — |
| `fabricacao` | DateField | — |
| `validade` | DateField | — |
| `documento_entrada` | CharField | — |
| `relatorio_item` | ForeignKey | operacao.ItemRelatorioEstoque |
| `compra` | ForeignKey | operacao.Compra |
| `peca` | ForeignKey | gestao.Peca |
| `quantidade` | DecimalField | — |
| `custo_unitario` | DecimalField | — |

#### operacao.CotacaoCompra — tabela `operacao_cotacaocompra`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `compra` | ForeignKey | operacao.Compra |
| `fornecedor` | ForeignKey | gestao.Fornecedor |
| `valor` | DecimalField | — |
| `validade` | DateField | — |
| `prazo` | CharField | — |
| `observacoes` | TextField | — |

#### operacao.Venda — tabela `operacao_venda`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `status` | CharField | — |
| `criado_por` | ForeignKey | contas.Usuario |
| `criado_em` | DateTimeField | — |
| `observacoes` | TextField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `vendedor` | ForeignKey | contas.Usuario |
| `deposito` | ForeignKey | operacao.Deposito |
| `vencimento` | DateField | — |
| `conta` | OneToOneField | gestao.Lancamento |

#### operacao.ItemVenda — tabela `operacao_itemvenda`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `venda` | ForeignKey | operacao.Venda |
| `peca` | ForeignKey | gestao.Peca |
| `quantidade` | DecimalField | — |
| `valor_unitario` | DecimalField | — |
| `desconto` | DecimalField | — |
| `custo_unitario` | DecimalField | — |

#### operacao.ContaBancaria — tabela `operacao_contabancaria`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `nome` | CharField | — |
| `ativo` | BooleanField | — |
| `banco` | CharField | — |
| `agencia` | CharField | — |
| `numero` | CharField | — |
| `tipo` | CharField | — |
| `saldo_inicial` | DecimalField | — |
| `permite_saldo_negativo` | BooleanField | — |

#### operacao.MovimentoCaixa — tabela `operacao_movimentocaixa`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `conta` | ForeignKey | operacao.ContaBancaria |
| `tipo` | CharField | — |
| `valor` | DecimalField | — |
| `data` | DateField | — |
| `descricao` | CharField | — |
| `referencia` | UUIDField | — |
| `usuario` | ForeignKey | contas.Usuario |

#### operacao.Pagamento — tabela `operacao_pagamento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `lancamento` | ForeignKey | gestao.Lancamento |
| `valor` | DecimalField | — |
| `data` | DateField | — |
| `conta` | ForeignKey | operacao.ContaBancaria |
| `usuario` | ForeignKey | contas.Usuario |
| `observacoes` | TextField | — |
| `request_id` | UUIDField | — |

#### operacao.Parcela — tabela `operacao_parcela`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `origem` | ForeignKey | gestao.Lancamento |
| `lancamento` | OneToOneField | gestao.Lancamento |
| `numero` | PositiveIntegerField | — |

#### operacao.ExtratoBancario — tabela `operacao_extratobancario`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `conta` | ForeignKey | operacao.ContaBancaria |
| `identificador` | CharField | — |
| `data` | DateField | — |
| `valor` | DecimalField | — |
| `descricao` | CharField | — |
| `movimento` | OneToOneField | operacao.MovimentoCaixa |

#### operacao.DocumentoFiscal — tabela `operacao_documentofiscal`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `tipo` | CharField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `lancamento` | ForeignKey | gestao.Lancamento |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `venda` | ForeignKey | operacao.Venda |
| `numero` | CharField | — |
| `serie` | CharField | — |
| `status` | CharField | — |
| `protocolo` | CharField | — |
| `ambiente` | CharField | — |
| `municipio` | CharField | — |
| `codigo_servico` | CharField | — |
| `impostos` | JSONField | — |
| `retencoes` | JSONField | — |
| `descricao` | TextField | — |
| `valor` | DecimalField | — |
| `criado_por` | ForeignKey | contas.Usuario |
| `criado_em` | DateTimeField | — |

#### operacao.Documento — tabela `operacao_documento`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `titulo` | CharField | — |
| `tipo` | CharField | — |
| `arquivo` | FileField | — |
| `cliente` | ForeignKey | clientes.Cliente |
| `equipamento` | ForeignKey | equipamentos.Equipamento |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `contrato` | ForeignKey | gestao.Contrato |
| `orcamento` | ForeignKey | gestao.Orcamento |
| `fiscal` | ForeignKey | operacao.DocumentoFiscal |
| `disponivel_portal` | BooleanField | — |
| `sha256` | CharField | — |
| `enviado_por` | ForeignKey | contas.Usuario |
| `criado_em` | DateTimeField | — |

#### operacao.PortalCliente — tabela `operacao_portalcliente`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `usuario` | ForeignKey | contas.Usuario |
| `cliente` | ForeignKey | clientes.Cliente |
| `ativo` | BooleanField | — |

#### operacao.Notificacao — tabela `operacao_notificacao`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `ocorrencia_estoque` | ForeignKey | operacao.OcorrenciaEstoque |
| `resolvida_em` | DateTimeField | — |
| `titulo` | CharField | — |
| `mensagem` | TextField | — |
| `usuario` | ForeignKey | contas.Usuario |
| `chave` | CharField | — |
| `link` | CharField | — |
| `lida_em` | DateTimeField | — |
| `criado_em` | DateTimeField | — |

#### operacao.SaidaNotificacao — tabela `operacao_saidanotificacao`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `notificacao` | OneToOneField | operacao.Notificacao |
| `canal` | CharField | — |
| `status` | CharField | — |
| `criado_em` | DateTimeField | — |

#### operacao.LoteEstoque — tabela `operacao_loteestoque`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `peca` | ForeignKey | gestao.Peca |
| `deposito` | ForeignKey | operacao.Deposito |
| `grupo` | UUIDField | — |
| `numero` | CharField | — |
| `fabricacao` | DateField | — |
| `validade` | DateField | — |
| `quantidade` | DecimalField | — |
| `fornecedor` | ForeignKey | gestao.Fornecedor |
| `custo_unitario` | DecimalField | — |
| `entrada_em` | DateTimeField | — |
| `localizacao` | CharField | — |
| `documento_entrada` | CharField | — |
| `item_compra` | ForeignKey | operacao.ItemCompra |
| `legado` | BooleanField | — |

#### operacao.MovimentacaoLote — tabela `operacao_movimentacaolote`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `movimentacao` | ForeignKey | gestao.Movimentacao |
| `lote` | ForeignKey | operacao.LoteEstoque |
| `quantidade_anterior` | DecimalField | — |
| `variacao` | DecimalField | — |
| `quantidade_posterior` | DecimalField | — |

#### operacao.ReservaEstoque — tabela `operacao_reservaestoque`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `peca` | ForeignKey | gestao.Peca |
| `deposito` | ForeignKey | operacao.Deposito |
| `ordem` | ForeignKey | ordens.OrdemServico |
| `venda` | ForeignKey | operacao.Venda |
| `quantidade` | DecimalField | — |
| `status` | CharField | — |
| `motivo` | CharField | — |
| `usuario` | ForeignKey | contas.Usuario |
| `criado_em` | DateTimeField | — |

#### operacao.OcorrenciaEstoque — tabela `operacao_ocorrenciaestoque`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `peca` | ForeignKey | gestao.Peca |
| `lote` | ForeignKey | operacao.LoteEstoque |
| `chave` | CharField | — |
| `tipo` | CharField | — |
| `situacao` | CharField | — |
| `dados` | JSONField | — |
| `aberta_em` | DateTimeField | — |
| `atualizada_em` | DateTimeField | — |
| `resolvida_em` | DateTimeField | — |

#### operacao.RelatorioEstoque — tabela `operacao_relatorioestoque`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `semana` | DateField | — |
| `gerado_em` | DateTimeField | — |
| `automatico` | BooleanField | — |
| `usuario` | ForeignKey | contas.Usuario |
| `parametros` | JSONField | — |

#### operacao.ItemRelatorioEstoque — tabela `operacao_itemrelatorioestoque`

| Campo | Tipo | Relacionamento |
|---|---|---|
| `id` | BigAutoField | — |
| `organization` | ForeignKey | platform_core.Organization |
| `relatorio` | ForeignKey | operacao.RelatorioEstoque |
| `peca` | ForeignKey | gestao.Peca |
| `dados` | JSONField | — |

## URLs registradas

Padrões com `<int:pk>`/`<str:action>` são resolvidos dinamicamente.
A presença da rota não concede permissão; decorators, serviços, middleware
e contexto da organização aplicam as regras do módulo.

| Rota | Nome |
|---|---|
| `/health/` | `health` |
| `/admin/` | `admin:index` |
| `/admin/login/` | `admin:login` |
| `/admin/logout/` | `admin:logout` |
| `/admin/password_change/` | `admin:password_change` |
| `/admin/password_change/done/` | `admin:password_change_done` |
| `/admin/autocomplete/` | `admin:autocomplete` |
| `/admin/jsi18n/` | `admin:jsi18n` |
| `/admin/r/<int:content_type_id>/<path:object_id>/` | `admin:view_on_site` |
| `/admin/auth/group/` | `admin:auth_group_changelist` |
| `/admin/auth/group/add/` | `admin:auth_group_add` |
| `/admin/auth/group/<path:object_id>/history/` | `admin:auth_group_history` |
| `/admin/auth/group/<path:object_id>/delete/` | `admin:auth_group_delete` |
| `/admin/auth/group/<path:object_id>/change/` | `admin:auth_group_change` |
| `/admin/auth/group/<path:object_id>/` | `—` |
| `/admin/contas/usuario/<id>/password/` | `admin:auth_user_password_change` |
| `/admin/contas/usuario/` | `admin:contas_usuario_changelist` |
| `/admin/contas/usuario/add/` | `admin:contas_usuario_add` |
| `/admin/contas/usuario/<path:object_id>/history/` | `admin:contas_usuario_history` |
| `/admin/contas/usuario/<path:object_id>/delete/` | `admin:contas_usuario_delete` |
| `/admin/contas/usuario/<path:object_id>/change/` | `admin:contas_usuario_change` |
| `/admin/contas/usuario/<path:object_id>/` | `—` |
| `/admin/contas/tecnico/` | `admin:contas_tecnico_changelist` |
| `/admin/contas/tecnico/add/` | `admin:contas_tecnico_add` |
| `/admin/contas/tecnico/<path:object_id>/history/` | `admin:contas_tecnico_history` |
| `/admin/contas/tecnico/<path:object_id>/delete/` | `admin:contas_tecnico_delete` |
| `/admin/contas/tecnico/<path:object_id>/change/` | `admin:contas_tecnico_change` |
| `/admin/contas/tecnico/<path:object_id>/` | `—` |
| `/admin/clientes/cliente/` | `admin:clientes_cliente_changelist` |
| `/admin/clientes/cliente/add/` | `admin:clientes_cliente_add` |
| `/admin/clientes/cliente/<path:object_id>/history/` | `admin:clientes_cliente_history` |
| `/admin/clientes/cliente/<path:object_id>/delete/` | `admin:clientes_cliente_delete` |
| `/admin/clientes/cliente/<path:object_id>/change/` | `admin:clientes_cliente_change` |
| `/admin/clientes/cliente/<path:object_id>/` | `—` |
| `/admin/clientes/unidade/` | `admin:clientes_unidade_changelist` |
| `/admin/clientes/unidade/add/` | `admin:clientes_unidade_add` |
| `/admin/clientes/unidade/<path:object_id>/history/` | `admin:clientes_unidade_history` |
| `/admin/clientes/unidade/<path:object_id>/delete/` | `admin:clientes_unidade_delete` |
| `/admin/clientes/unidade/<path:object_id>/change/` | `admin:clientes_unidade_change` |
| `/admin/clientes/unidade/<path:object_id>/` | `—` |
| `/admin/equipamentos/categoriaequipamento/` | `admin:equipamentos_categoriaequipamento_changelist` |
| `/admin/equipamentos/categoriaequipamento/add/` | `admin:equipamentos_categoriaequipamento_add` |
| `/admin/equipamentos/categoriaequipamento/<path:object_id>/history/` | `admin:equipamentos_categoriaequipamento_history` |
| `/admin/equipamentos/categoriaequipamento/<path:object_id>/delete/` | `admin:equipamentos_categoriaequipamento_delete` |
| `/admin/equipamentos/categoriaequipamento/<path:object_id>/change/` | `admin:equipamentos_categoriaequipamento_change` |
| `/admin/equipamentos/categoriaequipamento/<path:object_id>/` | `—` |
| `/admin/equipamentos/equipamento/` | `admin:equipamentos_equipamento_changelist` |
| `/admin/equipamentos/equipamento/add/` | `admin:equipamentos_equipamento_add` |
| `/admin/equipamentos/equipamento/<path:object_id>/history/` | `admin:equipamentos_equipamento_history` |
| `/admin/equipamentos/equipamento/<path:object_id>/delete/` | `admin:equipamentos_equipamento_delete` |
| `/admin/equipamentos/equipamento/<path:object_id>/change/` | `admin:equipamentos_equipamento_change` |
| `/admin/equipamentos/equipamento/<path:object_id>/` | `—` |
| `/admin/ordens/ordemservico/` | `admin:ordens_ordemservico_changelist` |
| `/admin/ordens/ordemservico/add/` | `admin:ordens_ordemservico_add` |
| `/admin/ordens/ordemservico/<path:object_id>/history/` | `admin:ordens_ordemservico_history` |
| `/admin/ordens/ordemservico/<path:object_id>/delete/` | `admin:ordens_ordemservico_delete` |
| `/admin/ordens/ordemservico/<path:object_id>/change/` | `admin:ordens_ordemservico_change` |
| `/admin/ordens/ordemservico/<path:object_id>/` | `—` |
| `/admin/ordens/localizacao/` | `admin:ordens_localizacao_changelist` |
| `/admin/ordens/localizacao/add/` | `admin:ordens_localizacao_add` |
| `/admin/ordens/localizacao/<path:object_id>/history/` | `admin:ordens_localizacao_history` |
| `/admin/ordens/localizacao/<path:object_id>/delete/` | `admin:ordens_localizacao_delete` |
| `/admin/ordens/localizacao/<path:object_id>/change/` | `admin:ordens_localizacao_change` |
| `/admin/ordens/localizacao/<path:object_id>/` | `—` |
| `/admin/ordens/foto/` | `admin:ordens_foto_changelist` |
| `/admin/ordens/foto/add/` | `admin:ordens_foto_add` |
| `/admin/ordens/foto/<path:object_id>/history/` | `admin:ordens_foto_history` |
| `/admin/ordens/foto/<path:object_id>/delete/` | `admin:ordens_foto_delete` |
| `/admin/ordens/foto/<path:object_id>/change/` | `admin:ordens_foto_change` |
| `/admin/ordens/foto/<path:object_id>/` | `—` |
| `/admin/ordens/conferencia/` | `admin:ordens_conferencia_changelist` |
| `/admin/ordens/conferencia/add/` | `admin:ordens_conferencia_add` |
| `/admin/ordens/conferencia/<path:object_id>/history/` | `admin:ordens_conferencia_history` |
| `/admin/ordens/conferencia/<path:object_id>/delete/` | `admin:ordens_conferencia_delete` |
| `/admin/ordens/conferencia/<path:object_id>/change/` | `admin:ordens_conferencia_change` |
| `/admin/ordens/conferencia/<path:object_id>/` | `—` |
| `/admin/ordens/assinatura/` | `admin:ordens_assinatura_changelist` |
| `/admin/ordens/assinatura/add/` | `admin:ordens_assinatura_add` |
| `/admin/ordens/assinatura/<path:object_id>/history/` | `admin:ordens_assinatura_history` |
| `/admin/ordens/assinatura/<path:object_id>/delete/` | `admin:ordens_assinatura_delete` |
| `/admin/ordens/assinatura/<path:object_id>/change/` | `admin:ordens_assinatura_change` |
| `/admin/ordens/assinatura/<path:object_id>/` | `—` |
| `/admin/ordens/auditoria/` | `admin:ordens_auditoria_changelist` |
| `/admin/ordens/auditoria/add/` | `admin:ordens_auditoria_add` |
| `/admin/ordens/auditoria/<path:object_id>/history/` | `admin:ordens_auditoria_history` |
| `/admin/ordens/auditoria/<path:object_id>/delete/` | `admin:ordens_auditoria_delete` |
| `/admin/ordens/auditoria/<path:object_id>/change/` | `admin:ordens_auditoria_change` |
| `/admin/ordens/auditoria/<path:object_id>/` | `—` |
| `/admin/platform_core/organization/` | `admin:platform_core_organization_changelist` |
| `/admin/platform_core/organization/add/` | `admin:platform_core_organization_add` |
| `/admin/platform_core/organization/<path:object_id>/history/` | `admin:platform_core_organization_history` |
| `/admin/platform_core/organization/<path:object_id>/delete/` | `admin:platform_core_organization_delete` |
| `/admin/platform_core/organization/<path:object_id>/change/` | `admin:platform_core_organization_change` |
| `/admin/platform_core/organization/<path:object_id>/` | `—` |
| `/admin/platform_core/erpcatalog/` | `admin:platform_core_erpcatalog_changelist` |
| `/admin/platform_core/erpcatalog/add/` | `admin:platform_core_erpcatalog_add` |
| `/admin/platform_core/erpcatalog/<path:object_id>/history/` | `admin:platform_core_erpcatalog_history` |
| `/admin/platform_core/erpcatalog/<path:object_id>/delete/` | `admin:platform_core_erpcatalog_delete` |
| `/admin/platform_core/erpcatalog/<path:object_id>/change/` | `admin:platform_core_erpcatalog_change` |
| `/admin/platform_core/erpcatalog/<path:object_id>/` | `—` |
| `/admin/platform_core/organizationerp/` | `admin:platform_core_organizationerp_changelist` |
| `/admin/platform_core/organizationerp/add/` | `admin:platform_core_organizationerp_add` |
| `/admin/platform_core/organizationerp/<path:object_id>/history/` | `admin:platform_core_organizationerp_history` |
| `/admin/platform_core/organizationerp/<path:object_id>/delete/` | `admin:platform_core_organizationerp_delete` |
| `/admin/platform_core/organizationerp/<path:object_id>/change/` | `admin:platform_core_organizationerp_change` |
| `/admin/platform_core/organizationerp/<path:object_id>/` | `—` |
| `/admin/platform_core/organizationmembership/` | `admin:platform_core_organizationmembership_changelist` |
| `/admin/platform_core/organizationmembership/add/` | `admin:platform_core_organizationmembership_add` |
| `/admin/platform_core/organizationmembership/<path:object_id>/history/` | `admin:platform_core_organizationmembership_history` |
| `/admin/platform_core/organizationmembership/<path:object_id>/delete/` | `admin:platform_core_organizationmembership_delete` |
| `/admin/platform_core/organizationmembership/<path:object_id>/change/` | `admin:platform_core_organizationmembership_change` |
| `/admin/platform_core/organizationmembership/<path:object_id>/` | `—` |
| `/admin/platform_core/membershiperp/` | `admin:platform_core_membershiperp_changelist` |
| `/admin/platform_core/membershiperp/add/` | `admin:platform_core_membershiperp_add` |
| `/admin/platform_core/membershiperp/<path:object_id>/history/` | `admin:platform_core_membershiperp_history` |
| `/admin/platform_core/membershiperp/<path:object_id>/delete/` | `admin:platform_core_membershiperp_delete` |
| `/admin/platform_core/membershiperp/<path:object_id>/change/` | `admin:platform_core_membershiperp_change` |
| `/admin/platform_core/membershiperp/<path:object_id>/` | `—` |
| `/admin/platform_core/platformaudit/` | `admin:platform_core_platformaudit_changelist` |
| `/admin/platform_core/platformaudit/add/` | `admin:platform_core_platformaudit_add` |
| `/admin/platform_core/platformaudit/<path:object_id>/history/` | `admin:platform_core_platformaudit_history` |
| `/admin/platform_core/platformaudit/<path:object_id>/delete/` | `admin:platform_core_platformaudit_delete` |
| `/admin/platform_core/platformaudit/<path:object_id>/change/` | `admin:platform_core_platformaudit_change` |
| `/admin/platform_core/platformaudit/<path:object_id>/` | `—` |
| `/admin/gestao/peca/` | `admin:gestao_peca_changelist` |
| `/admin/gestao/peca/add/` | `admin:gestao_peca_add` |
| `/admin/gestao/peca/<path:object_id>/history/` | `admin:gestao_peca_history` |
| `/admin/gestao/peca/<path:object_id>/delete/` | `admin:gestao_peca_delete` |
| `/admin/gestao/peca/<path:object_id>/change/` | `admin:gestao_peca_change` |
| `/admin/gestao/peca/<path:object_id>/` | `—` |
| `/admin/gestao/fornecedor/` | `admin:gestao_fornecedor_changelist` |
| `/admin/gestao/fornecedor/add/` | `admin:gestao_fornecedor_add` |
| `/admin/gestao/fornecedor/<path:object_id>/history/` | `admin:gestao_fornecedor_history` |
| `/admin/gestao/fornecedor/<path:object_id>/delete/` | `admin:gestao_fornecedor_delete` |
| `/admin/gestao/fornecedor/<path:object_id>/change/` | `admin:gestao_fornecedor_change` |
| `/admin/gestao/fornecedor/<path:object_id>/` | `—` |
| `/admin/gestao/movimentacao/` | `admin:gestao_movimentacao_changelist` |
| `/admin/gestao/movimentacao/add/` | `admin:gestao_movimentacao_add` |
| `/admin/gestao/movimentacao/<path:object_id>/history/` | `admin:gestao_movimentacao_history` |
| `/admin/gestao/movimentacao/<path:object_id>/delete/` | `admin:gestao_movimentacao_delete` |
| `/admin/gestao/movimentacao/<path:object_id>/change/` | `admin:gestao_movimentacao_change` |
| `/admin/gestao/movimentacao/<path:object_id>/` | `—` |
| `/admin/gestao/orcamento/` | `admin:gestao_orcamento_changelist` |
| `/admin/gestao/orcamento/add/` | `admin:gestao_orcamento_add` |
| `/admin/gestao/orcamento/<path:object_id>/history/` | `admin:gestao_orcamento_history` |
| `/admin/gestao/orcamento/<path:object_id>/delete/` | `admin:gestao_orcamento_delete` |
| `/admin/gestao/orcamento/<path:object_id>/change/` | `admin:gestao_orcamento_change` |
| `/admin/gestao/orcamento/<path:object_id>/` | `—` |
| `/admin/gestao/itemorcamento/` | `admin:gestao_itemorcamento_changelist` |
| `/admin/gestao/itemorcamento/add/` | `admin:gestao_itemorcamento_add` |
| `/admin/gestao/itemorcamento/<path:object_id>/history/` | `admin:gestao_itemorcamento_history` |
| `/admin/gestao/itemorcamento/<path:object_id>/delete/` | `admin:gestao_itemorcamento_delete` |
| `/admin/gestao/itemorcamento/<path:object_id>/change/` | `admin:gestao_itemorcamento_change` |
| `/admin/gestao/itemorcamento/<path:object_id>/` | `—` |
| `/admin/gestao/contrato/` | `admin:gestao_contrato_changelist` |
| `/admin/gestao/contrato/add/` | `admin:gestao_contrato_add` |
| `/admin/gestao/contrato/<path:object_id>/history/` | `admin:gestao_contrato_history` |
| `/admin/gestao/contrato/<path:object_id>/delete/` | `admin:gestao_contrato_delete` |
| `/admin/gestao/contrato/<path:object_id>/change/` | `admin:gestao_contrato_change` |
| `/admin/gestao/contrato/<path:object_id>/` | `—` |
| `/admin/gestao/agendapreventiva/` | `admin:gestao_agendapreventiva_changelist` |
| `/admin/gestao/agendapreventiva/add/` | `admin:gestao_agendapreventiva_add` |
| `/admin/gestao/agendapreventiva/<path:object_id>/history/` | `admin:gestao_agendapreventiva_history` |
| `/admin/gestao/agendapreventiva/<path:object_id>/delete/` | `admin:gestao_agendapreventiva_delete` |
| `/admin/gestao/agendapreventiva/<path:object_id>/change/` | `admin:gestao_agendapreventiva_change` |
| `/admin/gestao/agendapreventiva/<path:object_id>/` | `—` |
| `/admin/gestao/categoriafinanceira/` | `admin:gestao_categoriafinanceira_changelist` |
| `/admin/gestao/categoriafinanceira/add/` | `admin:gestao_categoriafinanceira_add` |
| `/admin/gestao/categoriafinanceira/<path:object_id>/history/` | `admin:gestao_categoriafinanceira_history` |
| `/admin/gestao/categoriafinanceira/<path:object_id>/delete/` | `admin:gestao_categoriafinanceira_delete` |
| `/admin/gestao/categoriafinanceira/<path:object_id>/change/` | `admin:gestao_categoriafinanceira_change` |
| `/admin/gestao/categoriafinanceira/<path:object_id>/` | `—` |
| `/admin/gestao/centrocusto/` | `admin:gestao_centrocusto_changelist` |
| `/admin/gestao/centrocusto/add/` | `admin:gestao_centrocusto_add` |
| `/admin/gestao/centrocusto/<path:object_id>/history/` | `admin:gestao_centrocusto_history` |
| `/admin/gestao/centrocusto/<path:object_id>/delete/` | `admin:gestao_centrocusto_delete` |
| `/admin/gestao/centrocusto/<path:object_id>/change/` | `admin:gestao_centrocusto_change` |
| `/admin/gestao/centrocusto/<path:object_id>/` | `—` |
| `/admin/gestao/formapagamento/` | `admin:gestao_formapagamento_changelist` |
| `/admin/gestao/formapagamento/add/` | `admin:gestao_formapagamento_add` |
| `/admin/gestao/formapagamento/<path:object_id>/history/` | `admin:gestao_formapagamento_history` |
| `/admin/gestao/formapagamento/<path:object_id>/delete/` | `admin:gestao_formapagamento_delete` |
| `/admin/gestao/formapagamento/<path:object_id>/change/` | `admin:gestao_formapagamento_change` |
| `/admin/gestao/formapagamento/<path:object_id>/` | `—` |
| `/admin/gestao/lancamento/` | `admin:gestao_lancamento_changelist` |
| `/admin/gestao/lancamento/add/` | `admin:gestao_lancamento_add` |
| `/admin/gestao/lancamento/<path:object_id>/history/` | `admin:gestao_lancamento_history` |
| `/admin/gestao/lancamento/<path:object_id>/delete/` | `admin:gestao_lancamento_delete` |
| `/admin/gestao/lancamento/<path:object_id>/change/` | `admin:gestao_lancamento_change` |
| `/admin/gestao/lancamento/<path:object_id>/` | `—` |
| `/admin/gestao/eventofinanceiro/` | `admin:gestao_eventofinanceiro_changelist` |
| `/admin/gestao/eventofinanceiro/add/` | `admin:gestao_eventofinanceiro_add` |
| `/admin/gestao/eventofinanceiro/<path:object_id>/history/` | `admin:gestao_eventofinanceiro_history` |
| `/admin/gestao/eventofinanceiro/<path:object_id>/delete/` | `admin:gestao_eventofinanceiro_delete` |
| `/admin/gestao/eventofinanceiro/<path:object_id>/change/` | `admin:gestao_eventofinanceiro_change` |
| `/admin/gestao/eventofinanceiro/<path:object_id>/` | `—` |
| `/admin/^(?P<app_label>auth|contas|clientes|equipamentos|ordens|platform_core|gestao)/$` | `admin:app_list` |
| `/admin/(?P<url>.*)$` | `—` |
| `/` | `—` |
| `/vertyx/` | `platform_core:home` |
| `/vertyx/organizacao/` | `platform_core:select_organization` |
| `/assistencia/` | `core:painel` |
| `/contas/login/` | `contas:login` |
| `/contas/logout/` | `contas:logout` |
| `/contas/usuarios/` | `contas:usuario_list` |
| `/contas/usuarios/novo/` | `contas:usuario_create` |
| `/contas/usuarios/<int:pk>/editar/` | `contas:usuario_update` |
| `/contas/tecnicos/` | `contas:tecnico_list` |
| `/contas/tecnicos/novo/` | `contas:tecnico_create` |
| `/contas/tecnicos/<int:pk>/editar/` | `contas:tecnico_update` |
| `/clientes/` | `clientes:cliente_list` |
| `/clientes/novo/` | `clientes:cliente_create` |
| `/clientes/<int:pk>/` | `clientes:cliente_detail` |
| `/clientes/<int:pk>/editar/` | `clientes:cliente_update` |
| `/clientes/unidades/nova/` | `clientes:unidade_create` |
| `/clientes/unidades/<int:pk>/editar/` | `clientes:unidade_update` |
| `/equipamentos/categorias/nova/` | `equipamentos:categoria_create` |
| `/equipamentos/categorias/<int:pk>/editar/` | `equipamentos:categoria_update` |
| `/equipamentos/` | `equipamentos:equipamento_list` |
| `/equipamentos/novo/` | `equipamentos:equipamento_create` |
| `/equipamentos/<int:pk>/` | `equipamentos:equipamento_detail` |
| `/equipamentos/<int:pk>/editar/` | `equipamentos:equipamento_update` |
| `/equipamentos/qr/<uuid:codigo_publico>/` | `equipamentos:equipamento_qr` |
| `/equipamentos/ajax/unidades/` | `equipamentos:unidades_por_cliente` |
| `/ordens/` | `ordens:lista` |
| `/ordens/nova/` | `ordens:criar` |
| `/ordens/<int:pk>/` | `ordens:detalhe` |
| `/ordens/<int:pk>/editar/` | `ordens:editar` |
| `/ordens/<int:pk>/iniciar/` | `ordens:iniciar` |
| `/ordens/<int:pk>/fotos/adicionar/` | `ordens:foto_adicionar` |
| `/ordens/<int:pk>/fotos/<int:foto_id>/` | `ordens:foto` |
| `/ordens/<int:pk>/preparar/` | `ordens:preparar` |
| `/ordens/<int:pk>/conferencia/<str:token>/` | `ordens:conferencia` |
| `/ordens/<int:pk>/finalizar/` | `ordens:finalizar` |
| `/ordens/<int:pk>/reabrir/` | `ordens:reabrir` |
| `/ordens/<int:pk>/assinaturas/<int:assinatura_id>/imagem/` | `ordens:assinatura_imagem` |
| `/ordens/<int:pk>/assinaturas/<int:assinatura_id>/pdf/` | `ordens:pdf` |
| `/estoque/movimentar/` | `gestao:movimentar` |
| `/orcamentos/<int:pk>/itens/novo/` | `gestao:item_novo` |
| `/orcamentos/<int:pk>/itens/<int:item_id>/editar/` | `gestao:item_editar` |
| `/orcamentos/<int:pk>/itens/<int:item_id>/remover/` | `gestao:item_remover` |
| `/orcamentos/<int:pk>/status/<str:action>/` | `gestao:orcamento_status` |
| `/orcamentos/<int:pk>/converter/` | `gestao:converter` |
| `/orcamentos/<int:pk>/pdf/` | `gestao:orcamento_pdf` |
| `/contratos/<int:pk>/gerar/<str:action>/` | `gestao:contrato_gerar` |
| `/contratos/planejamento/` | `gestao:planejamento` |
| `/contratos/planejamento/<int:pk>/gerar-os/` | `gestao:agenda_os` |
| `/financeiro/` | `gestao:financeiro` |
| `/financeiro/lancamentos/<int:pk>/operacao/<str:action>/` | `gestao:financeiro_operacao` |
| `/relatorios/` | `gestao:relatorios` |
| `/relatorios/<slug:key>/` | `gestao:relatorio` |
| `/estoque/` | `gestao:peca_lista` |
| `/estoque/novo/` | `gestao:peca_novo` |
| `/estoque/<int:pk>/` | `gestao:peca_detalhe` |
| `/estoque/<int:pk>/editar/` | `gestao:peca_editar` |
| `/estoque/fornecedores/` | `gestao:fornecedor_lista` |
| `/estoque/fornecedores/novo/` | `gestao:fornecedor_novo` |
| `/estoque/fornecedores/<int:pk>/` | `gestao:fornecedor_detalhe` |
| `/estoque/fornecedores/<int:pk>/editar/` | `gestao:fornecedor_editar` |
| `/orcamentos/` | `gestao:orcamento_lista` |
| `/orcamentos/novo/` | `gestao:orcamento_novo` |
| `/orcamentos/<int:pk>/` | `gestao:orcamento_detalhe` |
| `/orcamentos/<int:pk>/editar/` | `gestao:orcamento_editar` |
| `/contratos/` | `gestao:contrato_lista` |
| `/contratos/novo/` | `gestao:contrato_novo` |
| `/contratos/<int:pk>/` | `gestao:contrato_detalhe` |
| `/contratos/<int:pk>/editar/` | `gestao:contrato_editar` |
| `/financeiro/lancamentos/` | `gestao:lancamento_lista` |
| `/financeiro/lancamentos/novo/` | `gestao:lancamento_novo` |
| `/financeiro/lancamentos/<int:pk>/` | `gestao:lancamento_detalhe` |
| `/financeiro/lancamentos/<int:pk>/editar/` | `gestao:lancamento_editar` |
| `/financeiro/categorias/` | `gestao:categoria_financeira_lista` |
| `/financeiro/categorias/novo/` | `gestao:categoria_financeira_novo` |
| `/financeiro/categorias/<int:pk>/` | `gestao:categoria_financeira_detalhe` |
| `/financeiro/categorias/<int:pk>/editar/` | `gestao:categoria_financeira_editar` |
| `/financeiro/centros-custo/` | `gestao:centro_custo_lista` |
| `/financeiro/centros-custo/novo/` | `gestao:centro_custo_novo` |
| `/financeiro/centros-custo/<int:pk>/` | `gestao:centro_custo_detalhe` |
| `/financeiro/centros-custo/<int:pk>/editar/` | `gestao:centro_custo_editar` |
| `/financeiro/formas-pagamento/` | `gestao:forma_pagamento_lista` |
| `/financeiro/formas-pagamento/novo/` | `gestao:forma_pagamento_novo` |
| `/financeiro/formas-pagamento/<int:pk>/` | `gestao:forma_pagamento_detalhe` |
| `/financeiro/formas-pagamento/<int:pk>/editar/` | `gestao:forma_pagamento_editar` |
| `/estoque/lotes/` | `operacao:stock_lots` |
| `/estoque/lotes/entrada/` | `operacao:stock_entry` |
| `/estoque/reservas/` | `operacao:stock_reservations` |
| `/estoque/reservas/<int:pk>/liberar/` | `operacao:stock_release` |
| `/estoque/ocorrencias/` | `operacao:stock_occurrences` |
| `/estoque/relatorios/` | `operacao:stock_reports` |
| `/estoque/relatorios/<int:pk>/` | `operacao:stock_report` |
| `/configuracoes/estoque-compras/` | `operacao:stock_config` |
| `/compras/<int:pk>/itens/<int:item_id>/lote/` | `operacao:stock_receipt` |
| `/planejamento/` | `operacao:calendario` |
| `/planejamento/nova-os/` | `operacao:planning_quick` |
| `/planejamento/ordens/<int:pk>/` | `operacao:planning_detail` |
| `/planejamento/ordens/<int:pk>/agendar/` | `operacao:planning_schedule` |
| `/painel-operacional/` | `operacao:operational_panel` |
| `/painel-operacional/dados/` | `operacao:panel_data` |
| `/configuracoes/painel-operacional/` | `operacao:panel_config` |
| `/tecnico/` | `operacao:tecnico` |
| `/manifest.webmanifest` | `operacao:manifest` |
| `/sw.js` | `operacao:worker` |
| `/configuracoes/` | `operacao:configuracao` |
| `/notificacoes/` | `operacao:notificacoes` |
| `/notificacoes/<int:pk>/lida/` | `operacao:notificacao_lida` |
| `/portal/` | `operacao:portal` |
| `/portal/chamados/novo/` | `operacao:portal_chamado` |
| `/portal/ordens/<int:pk>/` | `operacao:portal_os` |
| `/portal/ordens/<int:pk>/pdf/<int:item_id>/` | `operacao:portal_os_pdf` |
| `/portal/ordens/<int:pk>/foto/<int:item_id>/` | `operacao:portal_os_foto` |
| `/portal/orcamentos/<int:pk>/pdf/` | `operacao:portal_orcamento_pdf` |
| `/portal/orcamentos/<int:pk>/<str:action>/` | `operacao:portal_aprovar` |
| `/portal/documentos/<int:pk>/arquivo/` | `operacao:portal_documento` |
| `/portal/relatorio/` | `operacao:portal_relatorio` |
| `/compras/sugestoes/` | `operacao:sugestoes` |
| `/documentos/<int:pk>/arquivo/` | `operacao:documento_arquivo` |
| `/preventivas/ocorrencias/<int:pk>/gerar-os/` | `operacao:preventiva_gerar` |
| `/ordens/<int:pk>/operacao/<str:action>/` | `operacao:os_acao` |
| `/bancos/caixa/` | `operacao:caixa` |
| `/bancos/transferir/` | `operacao:transferir` |
| `/financeiro/<int:pk>/pagar/` | `operacao:pagar` |
| `/financeiro/<int:pk>/parcelar/` | `operacao:parcelar` |
| `/bancos/extrato/<int:pk>/conciliar/` | `operacao:conciliar` |
| `/depositos/` | `operacao:deposito_lista` |
| `/depositos/novo/` | `operacao:deposito_novo` |
| `/depositos/<int:pk>/` | `operacao:deposito_detalhe` |
| `/depositos/<int:pk>/editar/` | `operacao:deposito_editar` |
| `/depositos/<int:pk>/acao/<str:action>/` | `operacao:deposito_acao` |
| `/categorias-pecas/` | `operacao:categoria_lista` |
| `/categorias-pecas/novo/` | `operacao:categoria_novo` |
| `/categorias-pecas/<int:pk>/` | `operacao:categoria_detalhe` |
| `/categorias-pecas/<int:pk>/editar/` | `operacao:categoria_editar` |
| `/categorias-pecas/<int:pk>/acao/<str:action>/` | `operacao:categoria_acao` |
| `/chamados/` | `operacao:chamado_lista` |
| `/chamados/novo/` | `operacao:chamado_novo` |
| `/chamados/<int:pk>/` | `operacao:chamado_detalhe` |
| `/chamados/<int:pk>/editar/` | `operacao:chamado_editar` |
| `/chamados/<int:pk>/acao/<str:action>/` | `operacao:chamado_acao` |
| `/checklists/` | `operacao:checklist_lista` |
| `/checklists/novo/` | `operacao:checklist_novo` |
| `/checklists/<int:pk>/` | `operacao:checklist_detalhe` |
| `/checklists/<int:pk>/editar/` | `operacao:checklist_editar` |
| `/checklists/<int:pk>/acao/<str:action>/` | `operacao:checklist_acao` |
| `/preventivas/` | `operacao:plano_lista` |
| `/preventivas/novo/` | `operacao:plano_novo` |
| `/preventivas/<int:pk>/` | `operacao:plano_detalhe` |
| `/preventivas/<int:pk>/editar/` | `operacao:plano_editar` |
| `/preventivas/<int:pk>/acao/<str:action>/` | `operacao:plano_acao` |
| `/compras/` | `operacao:compra_lista` |
| `/compras/novo/` | `operacao:compra_novo` |
| `/compras/<int:pk>/` | `operacao:compra_detalhe` |
| `/compras/<int:pk>/editar/` | `operacao:compra_editar` |
| `/compras/<int:pk>/acao/<str:action>/` | `operacao:compra_acao` |
| `/vendas/` | `operacao:venda_lista` |
| `/vendas/novo/` | `operacao:venda_novo` |
| `/vendas/<int:pk>/` | `operacao:venda_detalhe` |
| `/vendas/<int:pk>/editar/` | `operacao:venda_editar` |
| `/vendas/<int:pk>/acao/<str:action>/` | `operacao:venda_acao` |
| `/bancos/` | `operacao:banco_lista` |
| `/bancos/novo/` | `operacao:banco_novo` |
| `/bancos/<int:pk>/` | `operacao:banco_detalhe` |
| `/bancos/<int:pk>/editar/` | `operacao:banco_editar` |
| `/bancos/<int:pk>/acao/<str:action>/` | `operacao:banco_acao` |
| `/bancos/extrato/` | `operacao:extrato_lista` |
| `/bancos/extrato/novo/` | `operacao:extrato_novo` |
| `/bancos/extrato/<int:pk>/` | `operacao:extrato_detalhe` |
| `/bancos/extrato/<int:pk>/editar/` | `operacao:extrato_editar` |
| `/bancos/extrato/<int:pk>/acao/<str:action>/` | `operacao:extrato_acao` |
| `/fiscal/` | `operacao:fiscal_lista` |
| `/fiscal/novo/` | `operacao:fiscal_novo` |
| `/fiscal/<int:pk>/` | `operacao:fiscal_detalhe` |
| `/fiscal/<int:pk>/editar/` | `operacao:fiscal_editar` |
| `/fiscal/<int:pk>/acao/<str:action>/` | `operacao:fiscal_acao` |
| `/documentos/` | `operacao:documento_lista` |
| `/documentos/novo/` | `operacao:documento_novo` |
| `/documentos/<int:pk>/` | `operacao:documento_detalhe` |
| `/documentos/<int:pk>/editar/` | `operacao:documento_editar` |
| `/documentos/<int:pk>/acao/<str:action>/` | `operacao:documento_acao` |
| `/portal-acessos/` | `operacao:portal_acesso_lista` |
| `/portal-acessos/novo/` | `operacao:portal_acesso_novo` |
| `/portal-acessos/<int:pk>/` | `operacao:portal_acesso_detalhe` |
| `/portal-acessos/<int:pk>/editar/` | `operacao:portal_acesso_editar` |
| `/portal-acessos/<int:pk>/acao/<str:action>/` | `operacao:portal_acesso_acao` |
| `/compras/<int:pk>/itens/novo/` | `operacao:compra_item_novo` |
| `/compras/<int:pk>/itens/<int:item_id>/` | `operacao:compra_item_editar` |
| `/compras/<int:pk>/itens/<int:item_id>/remover/` | `operacao:compra_item_remover` |
| `/vendas/<int:pk>/itens/novo/` | `operacao:venda_item_novo` |
| `/vendas/<int:pk>/itens/<int:item_id>/` | `operacao:venda_item_editar` |
| `/vendas/<int:pk>/itens/<int:item_id>/remover/` | `operacao:venda_item_remover` |
| `/compras/<int:pk>/cotacoes/novo/` | `operacao:cotacao_novo` |
| `/compras/<int:pk>/cotacoes/<int:item_id>/` | `operacao:cotacao_editar` |
| `/compras/<int:pk>/cotacoes/<int:item_id>/remover/` | `operacao:cotacao_remover` |
| `/media/<path:name>` | `legacy_media` |

Totais: 68 modelos concretos; 393 padrões de URL.

## Estoque e automação

LoteEstoque e MovimentacaoLote detalham Peca/Movimentacao/SaldoDeposito existentes.
ReservaEstoque compromete disponibilidade; OcorrenciaEstoque preserva ciclos e resolução.
RelatorioEstoque/ItemRelatorioEstoque guardam snapshots e geram Compra/ItemCompra atuais.
Comando: `processar_estoque [--organization SLUG] [--loop] [--poll-seconds 30]`.
Comando anterior `atualizar_alertas --organization SLUG` preservado.
Scheduler: operacao/stock_scheduler.py; serviços: operacao/stock.py.
Runner local: serviço estoque_runner no Docker Compose; Render: AUTOMACAO_ESTOQUE.md.
Gestão: operacao/executive.py/navigation.py; Assistência técnica preservada.

## Central de operações e TV

Planejamento reutiliza OrdemServico, PreventivaProgramada e AgendaPreventiva.
Views/forms/serviços: operacao/planning.py, planning_forms.py, planning_services.py.
TV: operacao/operational_panel.py; polling GET autenticado e grant explícito.
Configuracao guarda blocos/tema/intervalo; MembershipERP guarda permissão de TV.
Sem modelo de atividade paralelo; 68 modelos concretos preservados.
Detalhes de uso, migrations e limites: CENTRAL_OPERACOES.md.
Validação atual e histórico: VALIDACAO_FINAL.json.
