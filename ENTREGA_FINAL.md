# VERTYX ERP Assistência — entrega local para homologação final

01/10/2026. Base preservada: `vertyx_modulos.zip`. Entrega: `vertyx_final.zip`.
O ambiente Render informado pelo usuário não foi acessado ou alterado. Não
houve commit, push, deploy, alteração de credenciais, reset de banco, remoção
de migrations ou uso de dados reais nos ensaios. Código e documentos anteriores
permanecem disponíveis; os relatórios anteriores descrevem suas próprias fases.

## Auditoria e arquitetura

`AUDITORIA_FINAL.md` registra a análise anterior à implementação. Reutilizados:
Organization/membership/ERP/grants, TenantManager/TenantModelForm, decorators,
serviços de OS/estoque/financeiro, snapshots assinados e storage privado.
`operacao` concentra complementos integrados; `fiscal/providers` define a
camada substituível do provedor fiscal. Produtos da loja reutilizam `Peca`;
contas de compras/vendas reutilizam `Lancamento`; preventivas/chamados geram
`OrdemServico` existente. Não foram criadas identidades ou estoques paralelos.

## Funcionalidades preservadas e ampliadas

| Área | Resultado |
|---|---|
| Plataforma | Login, Home VERTYX, seleção de empresa, memberships, habilitação do ERP por empresa/usuário e administração preservados |
| Visual | Tokens, tipografia, cards, tabelas, formulários, badges, alertas, breadcrumbs, navegação lateral/colapsável, indicadores, estados vazios e atalhos mobile |
| Dashboard | OS abertas/agendadas, em atendimento/espera, concluídas no mês, atrasadas, preventivas, contratos, mínimo de estoque, contas, receitas/despesas realizadas e produtividade; gráficos de barras por estado/técnico |
| Clientes/unidades | Inscrições estadual/municipal, responsável, e-mail/observações da unidade e histórico de OS, equipamentos, contratos, orçamentos, contas, fiscal e documentos conforme perfil |
| Equipamentos | Patrimônio, aquisição, localização e criticidade; campos anteriores, garantia, QR, foto/manual e histórico preservados; certificados/documentos na central privada |
| OS | Nove tipos, contrato, prioridade, agenda, prazo, horas, deslocamento, checklist; estados aberta/agendada/em atendimento/espera de peça/espera de cliente/finalizada/aprovada/faturada/cancelada |
| Atendimento | GPS de chegada/saída, permissões negadas registradas sem coordenadas falsas, foto, vídeo/documento privado, diagnóstico, peças, checklist obrigatório, conferência, assinatura, PDF e reabertura versionada |
| PWA | Tela do técnico com hoje/atrasadas/próximas/sem agenda, prioridades, rota em mapa externo e atalhos; manifest, ícones e service worker com cache exclusivamente de recursos públicos |
| Preventivas | Plano/equipamentos/contrato/técnico/checklist, diário/semanal/quinzenal/mensal/bimestral/trimestral/semestral/anual/personalizado; geração persistida sem duplicação; OS e última/próxima execução |
| Calendário | Visões dia/semana/mês, filtros de cliente/unidade/técnico/equipamento/prioridade/estado, OS, planos, visitas contratuais e vencimentos; ocorrência convertida aparece pela OS |
| Estoque | Cadastro anterior ampliado com categoria/máximo/NCM/CFOP/CST, depósitos, saldo por depósito, transferência, utilização/devolução em OS e alertas de mínimo/validade/90 dias sem movimento |
| Compras | Solicitação, itens, cotações de fornecedores, seleção/aprovação, pedido, recebimento, entrada no depósito e conta a pagar; sugestão de reposição até mínimo/máximo |
| Orçamentos | Itens, desconto, deslocamento, impostos informados, margem estimada em relatório, estados/cancelamento, PDF, aprovação autenticada pelo cliente e conversão em OS |
| Contratos | Cobertura de unidades/equipamentos, peças/serviços, SLA, reajuste informado, periodicidade/visitas, agenda, OS, cobrança e alertas; suspensão/encerramento preservados |
| Financeiro | Contas por origem, pagamentos/recebimentos parciais, saldo pendente, parcelas mensais com centavos exatos, bancos/caixa/cartão, saldo inicial, entradas/saídas, transferências e conciliação manual de extrato |
| Vendas/loja | Pedido, cliente/vendedor/depósito, itens/quantidade/preço/desconto/custo/margem; confirmação baixa o mesmo estoque e gera recebível; nota fiscal preparada a partir da venda |
| Fiscal | Cadastros conceituais NFS-e/NF-e/NFC-e, ambiente, série/número/estado/protocolo, município/serviço, impostos/retenções e produtos; contrato de emissão/consulta/cancelamento, XML/PDF privados e provedor substituível |
| Documentos | PDF/imagem/XML/MP4/WebM até 25 MB, vínculo a cliente/equipamento/OS/contrato/orçamento/fiscal, SHA-256, storage privado e download autorizado; compartilhamento explícito ao portal |
| Portal | Papel CLIENTE e vínculos explícitos; chamado, acompanhamento de OS, comprovante/fotos, equipamentos, contratos, orçamento/PDF/decisão, documentos/notas, contas e relatório financeiro CSV/PDF/Excel |
| Relatórios | 31 relatórios operacionais, estoque, financeiro e comercial, filtros por organização, CSV, PDF e Excel; entradas de texto não viram fórmulas em planilhas |
| Auditoria | Ator, organização, instante, ação, objeto e antes/depois de cadastros/transições; históricos financeiros/caixa/estoque e comprovantes preservados |
| Notificações | Internas por eventos e varredura de prazos/estoque/fiscal; leitura por destinatário; estrutura de saída preparada, sem envio de e-mail/WhatsApp |
| Configurações | Empresa, logo privada, contato/endereço, prefixos, dígitos, prazo financeiro, juros/multa informados e parâmetros fiscais; usuários/grants reutilizados |

As rotas para mapas são calculadas a partir do endereço cadastrado; não existe
otimizador de múltiplas paradas nem rastreamento contínuo. Quando não houver
endereço, complete o cadastro antes de usar a rota.

PWA exige conexão para dados e gravações. Não há armazenamento offline de
dados empresariais nem sincronização posterior de GPS/foto/assinatura. O botão
de instalar aparece quando o navegador disponibiliza a instalação.

## Integrações e regras que dependem de configuração

- **Fiscal:** nenhum provedor real foi inventado/contratado. Sem adaptador
  aprovado, o serviço recusa emitir/consultar/cancelar e mantém o documento.
  Não gera XML, PDF fiscal, número ou protocolo fictícios. Impostos/ISS,
  retenções, NCM/CFOP/CST/CSOSN/ICMS/IPI/PIS/COFINS devem ser fornecidos pelo
  contador e validados pelo futuro adaptador; não há cálculo tributário presumido.
  `fiscal/README.md` detalha o contrato e os dados necessários à próxima etapa.
- **Bancos:** conciliação por registro manual de extrato e movimentos internos.
  PIX/TED/cartão podem ser classificados com formas de pagamento existentes;
  não há emissão de PIX, cobrança de cartão, liquidação bancária ou Open Finance
  via API. Tarifas/despesas são lançamentos/movimentos registrados pelo usuário.
- **Parâmetros:** juros/multa e reajuste são informações cadastráveis; aplicação
  automática depende de regras financeiras/contratuais explicitamente definidas.
  Prefixos de OS/orçamento são congelados em novos registros; contratos recebem
  sugestão de número conforme parâmetros, sujeita à unicidade e confirmação.
- **Avisos:** eventos criam notificações internas. Alertas de prazo/estoque
  podem ser atualizados na tela ou por `atualizar_alertas --organization SLUG`.
  Execução agendada, e-mail e WhatsApp exigem configuração posterior. Não há
  disparo real ou worker novo. Loja tem operação interna; checkout público e
  cobrança da assinatura SaaS permanecem fora desta entrega.
- **Storage e Render reais:** reaproveitar recursos existentes. Ensaios Moto
  validam compatibilidade S3 local; não certificam quotas, latência, região ou
  políticas do bucket publicado. Homologar essas particularidades depois.

## Modelos e migrations

24 modelos empresariais novos no app `operacao`:
Configuracao, Deposito, SaldoDeposito, CategoriaPeca, Chamado, ModeloChecklist,
PlanoPreventivo, PlanoEquipamento, PreventivaProgramada, Compra, ItemCompra,
CotacaoCompra, Venda, ItemVenda, ContaBancaria, MovimentoCaixa, Pagamento,
Parcela, ExtratoBancario, DocumentoFiscal, Documento, PortalCliente,
Notificacao e SaidaNotificacao. Todos têm organização. Nomeado/Fluxo são
abstratos e não geram tabelas.

Novas migrations (as anteriores permanecem byte a byte):

- clientes: `0004_cliente_inscricao_estadual_and_more`.
- equipamentos: `0005_equipamento_criticidade_equipamento_data_aquisicao_and_more`, `0006_alter_equipamento_criticidade`.
- contas: `0005_alter_usuario_perfil`.
- platform_core: `0003_alter_organizationmembership_role`.
- ordens: `0008_ordemservico_agendada_para_ordemservico_checklist_and_more`.
- gestao: `0002_contrato_cobertura_pecas_contrato_cobertura_servicos_and_more`, `0003_movimentacao_destino_movimentacao_origem_and_more`, `0004_orcamento_numero_personalizado`.
- operacao: `0001_initial`.

Dependências resolvem FKs entre apps em sequência aditiva. Nenhuma migration
destrutiva/retroativa foi usada. Saldo de estoque legado é alocado em Principal
na primeira movimentação, sem criar entrada/consumo fictício. Extratos,
pagamentos, documentos e fluxos novos não alteram registros antigos.

## Rotas e permissões

| Área | Rotas principais | Perfis |
|---|---|---|
| Calendário/técnico | `/planejamento/`, `/tecnico/` | ADMIN/GESTOR/TECNICO; técnico vê suas OS/plano/visitas |
| Chamados | `/chamados/` | ADMIN/GESTOR criam/convertem; técnico consulta os ligados a suas OS |
| Preventivas/checklist | `/preventivas/`, `/checklists/` | ADMIN/GESTOR gerenciam; técnico consulta planos atribuídos |
| Depósitos/compras | `/depositos/`, `/categorias-pecas/`, `/compras/`, `/compras/sugestoes/` | ADMIN/GESTOR/ESTOQUE |
| Venda | `/vendas/` | ADMIN/GESTOR |
| Bancos/extrato | `/bancos/`, `/bancos/extrato/` | ADMIN/GESTOR/FINANCEIRO escrevem; CONTABILIDADE consulta |
| Pagamento/parcelas | `/financeiro/ID/pagar/`, `/financeiro/ID/parcelar/` | ADMIN/GESTOR/FINANCEIRO |
| Fiscal | `/fiscal/` | ADMIN/GESTOR/FINANCEIRO escrevem; CONTABILIDADE consulta |
| Documentos | `/documentos/`, `/documentos/ID/arquivo/` | Conforme natureza/vínculo/OS atribuída; financeiro consulta anexos fiscais |
| Portal | `/portal/`, `/portal/chamados/novo/`, `/portal/ordens/ID/`, `/portal/relatorio/` | CLIENTE com grant ERP e vínculo explícito; nunca usa rotas internas |
| Gestão do portal | `/portal-acessos/` | ADMIN/GESTOR |
| Organização | `/configuracoes/` | ADMIN |
| Avisos | `/notificacoes/` | Perfis internos, somente destinatário |

URLs antigas de OS/cliente/equipamento/planejamento contratual/gestão foram
preservadas. `INVENTARIO_FINAL.md` apresenta inventário completo de modelos e
URLs, gerado da aplicação. `AUDITORIA_FINAL_ARQUIVOS.json` lista todos os
arquivos preservados/modificados/criados e hashes das migrations de referência.

## Validação final

Resultados completos em `VALIDACAO_FINAL.json`, sem credenciais/cookies:

- **165 testes aprovados em PostgreSQL 16.15: 136 anteriores e 29 novos**; controles
  de concorrência reais para estoque, faturamento, vendas e pagamento parcial.
- SQLite: **157 aprovados e oito ignorados** por exigirem bloqueios PostgreSQL;
  total de 165 testes descobertos e executados pela suíte.
- `check`, `makemigrations --check --dry-run`, `migrate --plan` e `collectstatic`.
- Upgrade da base local anterior: **357 linhas em 41 tabelas preservadas**, com
  todas as colunas anteriores idênticas; nenhuma remoção de dados.
- `check --deploy` em DEBUG=False: sem erros; W005/W021 mantidos porque
  HSTS em subdomínios/preload depende do domínio real e não foi habilitado.
- HTTPS local, PostgreSQL, storage Moto S3 com TLS, upload/download privado,
  digest de foto/snapshot/assinatura, PDF e oito tentativas de acesso cruzado
  a OS/foto/assinatura/PDF retornando 404.
- Navegador Chromium: fluxo original completo de GPS/foto/assinatura/PDF;
  15 telas anteriores em 390/1365; 27 telas finais em **320/390/768/1365**,
  compras/recebimento/venda/pagamento/banco/plano/checklist/OS/documento/portal.
  Sem overflow horizontal de página ou erros JavaScript. Tabelas largas têm
  rolagem contida, mantendo a página responsiva.
- PDFs de OS (duas páginas), orçamento e relatórios conferidos; navegação,
  dashboard, calendário e portal revisados visualmente. Fotografia/GPS/
  assinatura dos ensaios são explicitamente sintéticos.

Durante os ensaios foram corrigidos manifesto de estáticos desatualizado,
fechamento manual de download no teste PostgreSQL, quebra de texto do SHA-256
em 320 px, seletor padrão do calendário, campo CST/CSOSN no payload de produtos
e contagem de estado aprovado/faturado nas agendas existentes. Os
resultados finais substituem as tentativas intermediárias.

## Homologação local em ordem

1. Extraia o ZIP em diretório separado. Preserve o projeto/base anteriores.
2. Crie uma `.env` exclusivamente de desenvolvimento com valores próprios de
   teste, fora do Git. Não copie credenciais, URL de banco ou SECRET_KEY do Render.
   Use PostgreSQL separado e storage local (`DEBUG=True`, `UPLOAD_STORAGE=local`)
   ou bucket de teste dedicado quando for validar S3 real.
3. Instale requirements, aplique migrations pendentes e colete estáticos. Compose
   existente pode ser usado; não remova volumes/bancos de outra instalação.
4. Crie administrador de plataforma e organização/memberships/grants de teste.
   Depois use o administrador da organização para usuários e cadastros.
5. Cadastre cliente/unidade/equipamento/técnico; preencha parâmetros da empresa.
   Cadastre fornecedores, peças/depósitos, categorias financeiras/centros de
   custo/formas de pagamento e contas bancárias com saldos de abertura reais
   **do cenário sintético**, antes de movimentar.
6. Teste chamado → OS e contrato/plano/checklist → calendário → OS. Execute
   GPS/foto/vídeo/checklist/diagnóstico/peça/conferência/assinatura/PDF, depois
   aprovação/faturamento/reabertura. Conferir versão anterior assinada.
7. Teste cotação/aprovação/pedido/recebimento da compra; conferir estoque e
   pagável. Teste venda/consumo/devolução/transferência e saldo por depósito.
8. Teste recebível parcial/quitado, parcelas, caixa, transferências e conciliação;
   conferir valores e relatórios CSV/PDF/Excel sem duplicações.
9. Crie membership CLIENTE com acesso Assistência e vínculo em `/portal-acessos/`.
   Teste chamado, orçamento enviado/decisão, OS, documentos compartilhados e
   contas; confirmar bloqueio de outros clientes da mesma empresa e de outra.
10. Validar fiscal sem provedor: deve recusar emissão. Validar instalação PWA,
    GPS/câmera/upload e assinatura em aparelho físico com HTTPS antes de
    homologação externa. Executar checklist de papéis e isolamento.
11. Revisar relatório/diff/ZIP. **Somente depois decidir GitHub/Render.**

Comandos em ambiente exclusivamente local, a partir da pasta do projeto:

```powershell
python -m pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate_locked --noinput
python manage.py collectstatic --noinput
python manage.py test --noinput
```

O protocolo adicional de bancada em `tests/final_upgrade.py` e os fixtures/
scripts de navegador dependem de configuração sintética em `tmp/provision`;
essa configuração, binários, bancos, chaves e cookies **não integram o ZIP**.
Use-os somente com a bancada localhost indicada nos asserts dos scripts.

## Limites da entrega e próximos dados necessários

Homologação **local** concluída; ambiente publicado e aparelho físico não foram
certificados nesta etapa. A emissão fiscal real exige provedor, adapter,
credenciais/certificados externos e cadastro tributário validado pelo contador.
Envio real de mensagens, integração bancária e checkout externo exigem seus
respectivos provedores. Não foi criada infraestrutura ou presumida credencial.
Orientações para atualização futura estão em `DEPLOY_RENDER.md`.
