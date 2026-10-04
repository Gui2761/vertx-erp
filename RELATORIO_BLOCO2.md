# VERTYX — relatório do Bloco 2

02/10/2026. Desenvolvimento local encerrado, com limites e pendências de homologação explicitados abaixo. Base `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261`, branch `main`, repositório `tecnolmedengclinica-spec/vertx-erp`, preservando as alterações locais já aprovadas do Bloco 1. Nenhum commit, push, deploy ou início do Bloco 3.

## Resultado e níveis de evidência

- **VALIDADO AUTOMATICAMENTE:** 335/335 testes PostgreSQL, incluindo os 293 anteriores e 42 novos; nenhum skip. Suíte final: 363.355 s. Execução específica: 42/42 em 54.490 s. Sete novos testes de concorrência real PostgreSQL.
- **VALIDADO PELA INTERFACE:** jornadas locais de chamado/técnico, preventiva, reserva/consumo/devolução, necessidade/compra, gestão e portal; formulário real de foto e assinatura por traço; 24 verificações em desktop/tablet/celular.
- **VALIDADO EM BANCO SINTÉTICO:** migrations limpas pela suíte e ensaio incremental independente sobre schema anterior; 1505 linhas em 71 tabelas antigas preservadas, comparando todas as colunas anteriores.
- **NÃO VALIDADO EM PRODUÇÃO:** sem acesso a Render, PostgreSQL publicado, R2 real, credenciais ou usuários reais. Esta entrega não certifica configuração/deploy publicado nem substitui homologação operacional.

## Arquitetura e preservação

A auditoria e o plano `PLANO_BLOCO2.md` precederam a implementação. Foram reutilizados cadastros, Organization/TenantManager, serviços transacionais, auditorias existentes, OS/snapshots, Compra/ItemCompra/CotacaoCompra, lote/movimentação, contrato/agenda e financeiro do Bloco 1. As novas entidades guardam detalhes ausentes — recebimentos, alocações de reserva, necessidades de peças, equipe e artigos — dentro dos aplicativos atuais. Não há estoque, compras, documentos ou financeiro paralelos.

Origem raiz, parcelamento com centavos exatos, pagamentos parciais/idempotentes, rastreio não bancarizado, EventoFinanceiro/MovimentoCaixa, FEFO/custos/devoluções e comprovantes históricos continuam cobertos pela suíte anterior. Não foram inventados metadados ou movimentos legados. Nenhuma dependência foi alterada neste bloco; Django 5.2.17 do Bloco 1 e compatibilidade existente permanecem.

## Funcionalidades efetivamente concluídas no ambiente local

### Chamados e triagem

**Existia:** Cadastro básico e conversão oficial para OS.

**Alterado:** Contato, origem, tipo, agenda, técnico, prazo/SLA, prioridade solicitada separada da interna, anexos privados e estados sincronizados com a OS; abertura/conversão idempotentes.

**Arquivos:** `operacao/models.py`, `operacao/forms.py`, `operacao/services.py`, `operacao/views.py`, `operacao/portal.py`, `templates/operacao/block2_call.html`, `templates/operacao/portal_chamado.html`.

**Migrations:** operacao/0007. **Testes:** `test_call_*; test_portal_call_priority_*; test_contract_sla_*; test_call_attachments_*`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** SLA básico por prazo; nenhum motor avançado, mensagem externa ou confirmação de atendimento fora do sistema.

### OS, equipe e assinatura

**Existia:** Execução, fotos, assinatura eletrônica, conferência congelada e PDFs históricos.

**Alterado:** Auxiliares autorizados, deslocamento/aguardando aprovação, campos técnicos, categorias de foto, checklist tipado e sincronização do chamado; dados novos no snapshot/PDF, sem reescrever versões antigas.

**Arquivos:** `ordens/models.py`, `ordens/forms.py`, `ordens/services.py`, `ordens/views.py`, `ordens/reports.py`, `templates/ordens/detalhe.html`, `templates/ordens/resumo.html`, `templates/operacao/block2_os.html`.

**Migrations:** ordens/0010. **Testes:** `test_auxiliary_authorization_*; test_checklist_model_copy_*; test_complete_call_order_*`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Assinatura eletrônica com trilha e hashes; não é certificado A1/ICP-Brasil. Celular físico ainda requer homologação.

### Checklists

**Existia:** Modelo JSON com caixas obrigatórias e notas.

**Alterado:** Editor de perguntas com nove tipos, critérios de equipamento/serviço, respostas Boolean/Decimal/data/seleção/foto, cópia independente para a OS e validação antes da assinatura.

**Arquivos:** `operacao/forms.py`, `operacao/models.py`, `operacao/services.py`, `static/js/checklist-builder.js`, `templates/operacao/block2_checklist.html`.

**Migrations:** operacao/0007. **Testes:** `test_typed_checklist_*; test_photo_checklist_*; test_checklist_model_copy_*; test_auxiliary_planning_*`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Editor depende de JavaScript; fallback textual legado permanece. Não há editor offline com sincronização.

### Equipamentos, técnicos, fornecedores e histórico

**Existia:** Cadastros multiempresa, vínculos e QR interno.

**Alterado:** Metadados faltantes opcionais, classificação do ciclo de vida, campos profissionais/fornecedor, linha do tempo consolidada, etiqueta e QR autorizado para o cliente.

**Arquivos:** `equipamentos/models.py`, `equipamentos/forms.py`, `equipamentos/views.py`, `equipamentos/urls.py`, `contas/models.py`, `contas/forms.py`, `gestao/models.py`, `gestao/forms.py`, `operacao/history.py`, `templates/equipamentos/etiqueta.html`, `templates/equipamentos/equipamento_detail.html`, `templates/operacao/timeline.html`.

**Migrations:** contas/0007, equipamentos/0007, gestao/0008. **Testes:** `test_portal_qr_*; test_complete_call_order_*; test_all_new_pages_*`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Metadados antigos vazios não foram presumidos; registro ANVISA é cadastro, sem consulta externa.

### Preventivas e planejamento

**Existia:** PlanoPreventivo/PreventivaProgramada e contrato/AgendaPreventiva oficiais.

**Alterado:** Quadrimestral ancorada, unidade/tipo/equipe, agenda unificada, chamados e auxiliares em filtros/conflitos; geração/conversão/conclusão idempotentes e próxima data preservada.

**Arquivos:** `operacao/models.py`, `operacao/services.py`, `operacao/planning.py`, `operacao/planning_services.py`, `operacao/forms.py`, `operacao/views.py`.

**Migrations:** operacao/0007. **Testes:** `test_quadrimestral_generation_*; test_preventive_generation_*; test_auxiliary_planning_*; suíte anterior de planejamento`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Planos e visitas contratuais são fontes distintas. Não fundir históricos coincidentes automaticamente; evento sem fim não recebe duração fictícia.

### Estoque, FEFO, reserva e necessidade

**Existia:** Peça/depósito/saldo/lote/movimento oficiais; FEFO, custos e devoluções estabilizados no Bloco 1.

**Alterado:** Alocação de lotes dentro da reserva existente, proteção de compromissos de outras OS, liberação no consumo/cancelamento, necessidade ligada à OS, compra oficial e resolução auditada por motivo.

**Arquivos:** `operacao/stock_models.py`, `operacao/stock.py`, `operacao/stock_forms.py`, `operacao/stock_views.py`, `operacao/services.py`, `gestao/services.py`, `templates/operacao/necessidades.html`.

**Migrations:** operacao/0007. **Testes:** `test_reservation_*; test_reserved_*; test_new_earlier_lot_*; test_piece_need_*; regressões FEFO/validade/devolução anteriores`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Reservas agregadas legadas são respeitadas, sem fabricar detalhes passados. Resolver necessidade não baixa nem ajusta estoque.

### Compras e recebimentos

**Existia:** Compra, ItemCompra, CotacaoCompra, aprovação/pedido e conta a pagar oficiais.

**Alterado:** Previsão, cabeçalho idempotente e itens de recebimento imutáveis ligados ao movimento/lote, parcial/final, bloqueio de excesso/cancelamento após entrada; necessidade desconta cobertura real.

**Arquivos:** `operacao/models.py`, `operacao/forms.py`, `operacao/services.py`, `operacao/views.py`, `operacao/stock.py`, `templates/operacao/block2_purchase.html`.

**Migrations:** operacao/0007. **Testes:** `test_partial_receipt_*; test_receipt_same_*; test_over_receipt_*; test_received_history_*; test_expired_receipt_*; test_purchase_receipt_*; test_same_receipt_token_*`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Parcial entra no estoque imediatamente; a única conta a pagar do pedido nasce no recebimento final, política atual preservada. Recebidas legadas continuam recebidas sem inventar detalhes.

### Financeiro, contratos e centros de custo

**Existia:** Origem raiz, parcelas exatas, pagamentos parciais/idempotentes, eventos, caixa/banco e contratos do Bloco 1.

**Alterado:** Filtros de período/origem/banco e controle não bancarizado; integração mantida com OS/compras/contrato e indicadores sem simular saldo bancário.

**Arquivos:** `gestao/forms.py`, `gestao/views.py`, `gestao/reporting.py`, `operacao/dashboard.py`, `operacao/executive.py`, `operacao/reporting.py`, `templates/gestao/financeiro.html`.

**Migrations:** nenhuma adicional para esta área. **Testes:** `test_financial_filters_*; test_complete_call_order_*; todos os testes de estabilização`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Banco/controle filtram valores realizados; contas pendentes não têm banco presumido. Não há conciliação externa/Open Finance.

### Documentos e portal

**Existia:** Storage privado, uploads validados, vínculo explícito usuário/cliente e liberação individual.

**Alterado:** Categorias/vínculos/validade/observações, técnicos/fornecedores/chamados, documentos e histórico de equipamento no portal, abertura e acompanhamento de chamado sem revelar campos internos.

**Arquivos:** `operacao/models.py`, `operacao/forms.py`, `operacao/services.py`, `operacao/permissions.py`, `operacao/portal.py`, `platform_core/middleware.py`, `templates/operacao/portal.html`, `templates/operacao/portal_equipamento.html`.

**Migrations:** operacao/0007. **Testes:** `test_document_release_*; test_call_attachments_*; test_portal_qr_*; test_portal_call_*; testes anteriores de storage privado`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** R2 real e permissões com usuários reais não foram acessados; uploads externos cobertos por simulação e guardas existentes.

### Notificações e ocorrências

**Existia:** Notificacao/OcorrenciaEstoque, comandos e runner de estoque existentes.

**Alterado:** Chave estável, atualização, leitura independente da resolução/reabertura; alertas de prazos, contrato/visitas, preventiva/documento e necessidade de peças.

**Arquivos:** `operacao/notifications.py`, `operacao/stock.py`, `operacao/services.py`, `templates/operacao/notificacoes.html`.

**Migrations:** nenhuma adicional para esta área. **Testes:** `test_document_validity_alert_*; test_contract_sla_*; testes anteriores de não duplicação/resolução/reabertura de estoque`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Nenhum runner externo foi ativado. Notificações operacionais usam a atualização existente; não há envio real de email/WhatsApp. Alertas diários históricos são preservados.

### Dashboard, TV, pesquisa e conhecimento

**Existia:** Painéis, DTO restrito de TV e navegação oficiais.

**Alterado:** Novos estados/chamados/auxiliares, pendências e métricas reais; pesquisa autorizada e artigos técnicos estruturados vinculados a equipamento/OS/manual.

**Arquivos:** `operacao/dashboard.py`, `operacao/executive.py`, `operacao/operational_panel.py`, `operacao/navigation.py`, `operacao/views.py`, `operacao/models.py`, `templates/core/painel.html`, `templates/operacao/block2_dashboard.html`, `templates/operacao/pesquisa.html`, `templates/base.html`.

**Migrations:** operacao/0007. **Testes:** `test_real_dashboard_*; test_global_search_*; test_all_new_pages_*; regressões anteriores do painel TV`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Artigos não representam IA externa. TV conserva a lista permitida de campos; indicadores sem histórico suficiente ficam vazios, sem números demonstrativos.

### Relatórios, PDF e PWA

**Existia:** Exportadores CSV/Excel/PDF, manifesto e worker com cache público.

**Alterado:** OS/preventivas pendentes e executadas, custo líquido registrado de peças e compras pendentes, filtros e isolamento; PDF da OS com novos dados; editor local no collectstatic.

**Arquivos:** `gestao/reporting.py`, `operacao/reporting.py`, `ordens/reports.py`, `templates/operacao/block2_checklist.html`.

**Migrations:** nenhuma adicional para esta área. **Testes:** `test_reports_export_*; test_complete_call_order_*; teste PWA e relatórios anteriores`. Resultado: PASS na suíte PostgreSQL final; nomes completos e inventário em `VALIDACAO_BLOCO2.json`.

**Limites:** Custos de peças não incluem mão de obra/deslocamento presumidos. Instalação PWA em dispositivo físico e operação offline complexa não foram homologadas.

## Jornadas e resoluções verificadas

| Jornada | Evidência de interface local | Complemento automatizado |
|---|---|---|
| Chamado / técnico / cliente | Portal criou CH-7, gestão fez triagem/conversão/agendamento, técnico executou OS-48, mediu 4.80 °C, enviou foto, conferiu e assinou por traço; OS Finalizada e chamado Concluído no portal. | Conversão única, prioridade interna protegida, sincronização, autorização de auxiliares, snapshot/PDF/financeiro/histórico. |
| Preventiva | Plano quadrimestral gerado com datas 02/10/2026, 02/02/2027 e 02/06/2027; OS-49 gerada/agendada/executada/assinada; ocorrência CONCLUIDA e futuras PENDENTE preservadas. | Geração/conversão concorrentes e idempotentes, próxima execução ancorada. |
| Estoque | Reserva OS-47 de 1.000, consumo parcial 0.500, devolução 0.250; físico 7.750 e reservado 0.500 antes da nova compra. | FEFO, custo real por lote, devolução ao custo original, proteção de reserva alheia, insuficiência e corridas. |
| Necessidade / compras | Necessidade da OS-47 de 12.000 gerou COMP-15 de 4.250 após desconto da cobertura; Aprovação → Pedido → parcial 2.000 → final 2.250 → Recebida, zero pendente, dois lotes e conta vinculada. COMP-14 também teve saldo final recebido pela interface. | Repetição idempotente, excesso/entrada vencida bloqueados, rollback, isolamento, rascunho não cobre necessidade. |
| Resolução da necessidade | Motivo obrigatório; Resolver sem movimentar saldo deixou a lista sem necessidade aberta. | Auditoria/resolução, motivo vazio rejeitado, saldo sem alteração; consumo em outro depósito não resolve indevidamente. |
| Gestão | Dashboard, planejamento, contratos/cobertura/SLA/cobranças, plano, OS, editor e relatório de custo líquido: OS-47 = 1.83250 após devolução. | Métricas reais, coorte, ausência de dados, grupos por ID, exports e filtros. |
| Portal | Equipamento/histórico, abertura/acompanhamento do chamado e documentos liberados. | QR e IDOR entre clientes/organizações, arquivos privados e campos internos protegidos. |

Os ensaios usaram sessões locais sintéticas por perfil. O login normal é coberto pelos testes existentes; não houve login real em produção. A matriz de 24 verificações corresponde a oito telas (dashboard, agenda, OS, equipamento, compra, lotes, financeiro e editor), em 1440×900, 768×1024 e 390×844. Não houve overflow horizontal de página ou traceback. Outras telas/jornadas acima foram inspecionadas no celular; isso não significa cobertura visual de todas as combinações possíveis. A inspeção final do console retornou zero erros/avisos.

Resoluções/reaberturas automáticas de estoque e documentos são cobertas pelos testes: leitura não elimina ocorrência; regularização resolve; retorno do problema reabre; execução repetida não duplica. Na interface foi comprovada também resolução manual motivada da necessidade. Não se declara operação periódica contínua sem runner externo ativo.

## Upload e PDF

**Upload: PASS.** O seletor de arquivo do navegador demorou, mas a foto sintética foi enviada pelo formulário: foto 13 na OS-48 e evento FOTO_ADICIONADA confirmados. Nenhum contorno de segurança foi implementado. Os testes também cobrem upload/anexo válido, tipos proibidos, vínculos e acesso privado/isolado.

**PDF: PASS.** `tmp/validation/bloco2-os.pdf` foi gerado pelo exportador real da OS e suas três páginas foram renderizadas e inspecionadas: identificação/cadastro, campos técnicos, peças, checklist/medição, foto categorizada, assinatura, datas e hashes. Não foram encontrados cortes ou sobreposições que prejudiquem leitura. As OS assinadas pela interface também exibiram os links dos comprovantes oficiais. Não é validação de emissão fiscal nem de storage publicado.

## Migrations e preservação de schema/dados

- `contas/migrations/0007_operacao_bloco2.py`
- `equipamentos/migrations/0007_operacao_bloco2.py`
- `gestao/migrations/0008_operacao_bloco2.py`
- `operacao/migrations/0007_operacao_bloco2.py`
- `ordens/migrations/0010_operacao_bloco2.py`

Somente operações aditivas, novos detalhes e ampliação compatível de campos/estados; sem RemoveField, DeleteModel, RunSQL, RunPython ou recriação de tabela. Os hashes dos 50 arquivos de migrations anteriores foram conferidos. Os 293 métodos anteriores permanecem. O check seco final não identificou alteração de model sem migration.

O ensaio incremental criou um banco isolado de teste no cluster PostgreSQL local já existente, construiu o schema anterior, copiou somente colunas/dados sintéticos compatíveis, capturou snapshot e aplicou as cinco migrations forward. Comparou 1505 linhas em 71 tabelas: todas as colunas/linhas anteriores permaneceram iguais. Não houve reset, flush, truncate, reversão de migration ou substituição do banco existente. A suíte também validou criação limpa do banco temporário de testes.

A verificação posterior de repetição sem migrations pendentes comparou 1836 registros da base já migrada, incluindo fixtures visuais. Esse resultado é separado do ensaio verdadeiro do schema anterior e não é prova do banco de produção.

**Produção:** nenhuma das cinco migrations foi aplicada por esta tarefa no banco publicado. Não se consultou a tabela django_migrations de produção; portanto a situação publicada não foi verificada. As três migrations do Bloco 1 continuam pré-requisitos locais e deverão ser conferidas em uma futura publicação autorizada.

## Checks, integridade e falhas resolvidas

- `python manage.py check`: PASS, sem problemas.
- `python manage.py makemigrations --check --dry-run`: PASS, No changes detected.
- Suíte completa PostgreSQL e 42 testes específicos: PASS, sem skips.
- `pip check`: No broken requirements found.
- `collectstatic`: PASS. Manifesto/compressão de produção verificados separadamente; 146 assets presentes.
- PWA: manifesto/worker respondem e teste confirma cache só de assets públicos; documentos/sessão/GPS/assinaturas fora do cache.
- Retomada após interrupção: 203 arquivos Python analisados sintaticamente, nenhum marcador de conflito, `git diff --check` aprovado. Nenhum arquivo parcialmente escrito identificado nos arquivos de código/documentos verificados. Render/settings/arquivos de segredo/banco não aparecem entre as alterações.

Falhas encontradas e resolvidas: exibição da equipe vazia como objeto interno; fixture nova sem fim obrigatório; comparação inicial de metadata Django ajustada para distinguir permissões adicionais de perda histórica, seguida por ensaio independente completo. A fixture foi corrigida sem relaxar o model e os testes foram repetidos. Os dois logs 503 da suíte são intencionais nos cenários de storage indisponível. Nenhum erro 500 foi encontrado nas telas ensaiadas.

## Indicadores e políticas explícitas

Compras que descontam reposição: APROVADA e PEDIDO, apenas quantidade não recebida; RASCUNHO/CANCELADA não contam, RECEBIDA não gera pendência. Reservado reduz disponível válido; lote vencido não é consumido automaticamente. Necessidade por OS respeita depósito e cobertura atual, sem emitir nova compra se já coberta. Quantidade é recomendação editável no fluxo oficial.

Financeiro mantém valor total original e origem raiz. Valores realizados incluem controles não bancarizados com rastreabilidade e sem saldo bancário fictício. O recebimento parcial atualiza estoque imediatamente e mantém pedido aberto; a conta a pagar única nasce ao final.

Taxa de execução usa OS abertas na coorte do período e concluídas nessa base; preventivas usam datas planejadas das duas fontes oficiais; médias de tempo usam registros válidos e não inventam zero sem amostra. Agrupamentos de equipamento/cliente usam identidade, não apenas nome. Relatórios de custo somam custo líquido registrado de peças, descontando devolução; não representam custo total de mão de obra/deslocamento.

## Parcialmente concluído ou dependente de homologação real

- Execução contínua de notificações e relatórios automáticos em infraestrutura real: mecanismo existente preservado; runner não ativado.
- PWA: fundamento, manifesto, worker e cache público validados; instalação em celulares físicos e offline complexo não validados.
- Homologação operacional com equipes/clientes reais, permissões finais e cadastros legados opcionais: pendente.
- Ensaios visuais não repetem todas as combinações de filtros, permissões, redes, modelos de checklist e navegadores; a cobertura automatizada complementa o ensaio.

## Não implementado neste bloco

NF-e/NFS-e real, certificado A1/ICP-Brasil, email/WhatsApp real, gateway de pagamento, Open Finance/conciliação externa, IA/OCR externo, integração fabricante/ANVISA, roteirização avançada, aplicativo nativo, novo frontend/ERP Loja separado, sincronização offline complexa, deploy/Bloco 3. Os adaptadores e pontos de configuração existentes não são apresentados como integrações operacionais sem fornecedor/configuração. Não há funcionalidade pendente sendo substituída por dados demonstrativos.

## Riscos, pendências e débitos técnicos

- Recebimento parcial antecede a geração da conta a pagar final; política explicitada na interface e deve ser confirmada pela gestão.
- Dois calendários preventivos oficiais podem conter atividades semelhantes; preservam-se as fontes, sem fusão destrutiva.
- Reservas/históricos legados sem detalhes não recebem reconstrução presumida; precisam de revisão assistida quando necessário.
- Notificações antigas com chaves diárias permanecem e podem coexistir com a primeira ocorrência estável; nenhuma exclusão histórica.
- Módulos de serviços/views existentes cresceram; refatoração futura deve preservar contratos e não criar módulos paralelos.
- Disponibilidade de R2, configuração Render/Gunicorn, credenciais, backup e volume/carga reais não foram certificados por esta validação local.

Homologar em ambiente autorizado: usuários/perfis reais, dispositivos mouse/touch, GPS e rede, R2 privado, documentos grandes, concorrência/volume real, configurações e backup/restauração. Nenhum desses requisitos implica autorização para modificar produção neste bloco.

## Arquivos modificados e evidências

O working tree também contém mudanças anteriores do Bloco 1. `requirements.txt`, `gestao/financial_origin.py`, migrations de estabilização e seus documentos/testes são desse bloco anterior, preservados; não são novas alterações de dependência do Bloco 2. O inventário completo relativo ao commit-base está em `VALIDACAO_BLOCO2.json` (`integrity.modified_tracked_files` / `added_nonignored_files`). Os arquivos por área estão listados acima.

Arquivos rastreados modificados em relação ao commit-base:

- `contas/forms.py`
- `contas/models.py`
- `equipamentos/forms.py`
- `equipamentos/models.py`
- `equipamentos/urls.py`
- `equipamentos/views.py`
- `gestao/forms.py`
- `gestao/models.py`
- `gestao/reporting.py`
- `gestao/services.py`
- `gestao/views.py`
- `operacao/dashboard.py`
- `operacao/executive.py`
- `operacao/forms.py`
- `operacao/history.py`
- `operacao/models.py`
- `operacao/navigation.py`
- `operacao/notifications.py`
- `operacao/operational_panel.py`
- `operacao/permissions.py`
- `operacao/planning.py`
- `operacao/planning_services.py`
- `operacao/portal.py`
- `operacao/reporting.py`
- `operacao/services.py`
- `operacao/stock.py`
- `operacao/stock_forms.py`
- `operacao/stock_models.py`
- `operacao/stock_views.py`
- `operacao/test_planning.py`
- `operacao/test_stock.py`
- `operacao/urls.py`
- `operacao/views.py`
- `ordens/forms.py`
- `ordens/models.py`
- `ordens/reports.py`
- `ordens/services.py`
- `ordens/views.py`
- `platform_core/middleware.py`
- `requirements.txt`
- `templates/base.html`
- `templates/core/painel.html`
- `templates/equipamentos/equipamento_detail.html`
- `templates/gestao/detalhe.html`
- `templates/gestao/financeiro.html`
- `templates/gestao/lista.html`
- `templates/operacao/detalhe.html`
- `templates/operacao/notificacoes.html`
- `templates/operacao/os_extras.html`
- `templates/operacao/portal.html`
- `templates/ordens/detalhe.html`
- `templates/ordens/resumo.html`

Arquivos novos não ignorados em relação ao commit-base (incluindo entregas anteriores):

- `AUDITORIA_ERP_COMPLETO.json`
- `AUDITORIA_ERP_COMPLETO.md`
- `BLOCO1_ESTABILIZACAO.md`
- `PLANO_BLOCO2.md`
- `PLANO_BLOCO3.md`
- `PLANO_DEPENDENCIAS_BLOCO1.md`
- `RELATORIO_BLOCO2.md`
- `VALIDACAO_BLOCO1.json`
- `VALIDACAO_BLOCO2.json`
- `contas/migrations/0007_operacao_bloco2.py`
- `equipamentos/migrations/0007_operacao_bloco2.py`
- `gestao/financial_origin.py`
- `gestao/migrations/0006_estabilizacao_bloco1.py`
- `gestao/migrations/0007_origem_parcelas_existentes.py`
- `gestao/migrations/0008_operacao_bloco2.py`
- `operacao/migrations/0006_estabilizacao_bloco1.py`
- `operacao/migrations/0007_operacao_bloco2.py`
- `operacao/test_block2.py`
- `operacao/test_block2_interfaces.py`
- `operacao/test_stabilization.py`
- `ordens/migrations/0010_operacao_bloco2.py`
- `static/js/checklist-builder.js`
- `templates/equipamentos/etiqueta.html`
- `templates/operacao/block2_call.html`
- `templates/operacao/block2_checklist.html`
- `templates/operacao/block2_dashboard.html`
- `templates/operacao/block2_os.html`
- `templates/operacao/block2_purchase.html`
- `templates/operacao/necessidades.html`
- `templates/operacao/pesquisa.html`
- `templates/operacao/portal_chamado.html`
- `templates/operacao/portal_equipamento.html`
- `templates/operacao/timeline.html`

Evidências técnicas e screenshots ficam em `tmp/validation` ignorado pelo Git, com caminhos/hashes no JSON. Scripts de QA usam somente loopback e dados sintéticos; não executar em produção. Arquivos protegidos de ambiente de teste não entram no inventário de entrega. Não foi criado ZIP/cópia do projeto nem alterada a pasta original.

## Encerramento

Entregues `RELATORIO_BLOCO2.md`, `VALIDACAO_BLOCO2.json` e `PLANO_BLOCO3.md`. Bloco 2 encerrado no desenvolvimento local com a distinção dos quatro níveis de evidência; homologação real permanece necessária. Bloco 3 contém apenas recomendação. Aguardar autorização do usuário antes de qualquer próximo bloco, commit, push ou deploy.
