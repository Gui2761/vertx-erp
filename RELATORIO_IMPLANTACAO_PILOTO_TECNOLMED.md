# VERTYX — Relatório técnico da preparação do piloto TECNOLMED

Data: 03/10/2026. Trabalho realizado na pasta original, sem extrair ZIP, copiar projeto ou repetir o Bloco 3H. Somente dados sintéticos no PostgreSQL 16.15 de loopback. Python 3.12.14 / Django 5.2.17, dependências preservadas.

## Resultado

Conferência de encerramento: a suíte completa já havia terminado com sucesso. O resultado final foi reconfirmado pelos logs e pelo manifesto de execução existentes. Nenhum teste ou homologação foi repetido nesta conferência; as evidências locais anteriores foram mantidas.

**441/441 testes PostgreSQL PASS, zero skips: 404 anteriores preservados e 37 novos.** Tempo da regressão final: 434.894 s. A fonte permaneceu idêntica durante a rodada e foi reconferida depois. Testes novos isolados: 37 PASS. `check`, `makemigrations --check --dry-run`, `collectstatic` e `git diff --check` PASS. Não houve relaxamento ou remoção de testes existentes.

| Item pedido | Estado |
|---|---|
| JORNADA CONTRATUAL | Pronta localmente |
| BLOQUEIO DE OS | Pronto no backend e interface |
| PDF NOVO | Pronto localmente |
| PWA | Pronta para homologação física |
| DISPOSITIVO FÍSICO | Pendente |
| PRODUÇÃO | Não pronta: auditoria publicada, backup/restore e homologação física pendentes |
| DEPLOY EXECUTADO | NÃO |

Plano de cadastro, publicação, rollback, critérios de aceite e roteiro físico: `PLANO_IMPLANTACAO_PILOTO_TECNOLMED.md`. Evidências estruturadas e hashes: `VALIDACAO_IMPLANTACAO_PILOTO_TECNOLMED.json`.

## Preservação e arquitetura

Baseline: `RELATORIO_BLOCO3.md`, `VALIDACAO_BLOCO3.json`, `HOMOLOGACAO_BLOCO3.md`. Os 328 arquivos da versão homologada foram inventariados antes dos ajustes. Todos os arquivos de teste anteriores permanecem byte a byte iguais aos da baseline do piloto; 404 métodos anteriores conservados. Os 69 arquivos históricos dos diretórios de migrations, incluindo oito inicializadores, preservam seus hashes. Sintaxe Python conferida e nenhum arquivo parcialmente escrito identificado ao finalizar.

Branch `main`, HEAD `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261`, origem `tecnolmedengclinica-spec/vertx-erp`. As alterações locais acumuladas continuam no working tree; esse commit não contém a implementação local. Nenhum commit, push, deploy, reset, flush, alteração de segredo ou acesso ao banco publicado. Render, R2 e PostgreSQL publicado não foram consultados nem modificados. Não foi iniciado Bloco 4.

Reutilizados `Contrato`, `OrdemServico`, técnico/auxiliares, agenda, conferência/assinatura, auditoria, contextos de tenant, estoque e compras. Jornada integrada à aplicação `operacao`; documento emitido integrado à aplicação `ordens`. Não foram criados ponto, estoque, compras, financeiro ou aplicação móvel paralelos.

`PONTO ≠ JORNADA CONTRATUAL ≠ TEMPO DA OS`. O início da jornada não marca ponto nem inicia OS. A correção da jornada não altera os horários da OS. O valor da medição não cria conta financeira automaticamente.

## Implementado

- Configuração opt-in por contrato, com ida/retorno, BASE/DESTINO, intervalos, limite diário, faixa permitida, categorias/tarifas Decimal e arredondamento/fração. Regras copiadas e preservadas por jornada.
- Destino disponível antes do início, sem expor detalhes operacionais. Gate nos services, consultas e GET/POST da OS, planejamento, peças e transições. Administrador pode planejar antes do início, mas não executar uma OS sujeita ao gate sem jornada do técnico.
- Início oficial, chegada, pausa, retomada, retorno e fim com relógio do servidor, estado de GPS e auditoria. Vínculos por OS/ciclo, múltiplas OS, prevenção de dupla abertura e locks PostgreSQL para concorrência.
- Limites originais imutáveis; solicitação de correção e aprovação/rejeição única por administrador diferente do solicitante. Tenant e autorizações também validados no service, não só no template.
- Área administrativa de medição por período/contrato, eventos, OS, ajustes, divergências e PDF separado. Jornadas abertas são provisórias e não compõem o total. Minutos fora da faixa e intervalos fora da janela faturável não entram indevidamente no cálculo.
- Condição final explícita e pendências técnicas na OS. Assinatura gráfica do técnico, além da assinatura do cliente; exigida para contratos que exigem jornada, sem romper contratos comuns anteriores.
- Novo snapshot técnico sem custos de materiais/lotes e sem medição/tarifas contratuais. Projeção da jornada técnica sem dados financeiros; auditoria detalhada com custos históricos restrita à administração.
- Novo PDF com identidade do tenant, cliente/unidade/contrato/setor, equipamento, tempos técnicos, relatório, checklist/medições, materiais/lotes, fotos categorizadas e duas assinaturas com hashes. Histórico legado mantém renderer anterior. Novo documento emitido armazenado em media privada com SHA-256; futuras consultas devolvem os mesmos bytes e detectam adulteração.
- Jornada online-first integrada à PWA existente. Sem fila offline de operações, aplicativo nativo ou acesso público novo de validação da OS.

## Evidência automática e sintética

Ensaio forward-only em banco sintético isolado no cluster local existente: aplicar somente as três migrations novas sobre o schema anterior e comparar todas as colunas/valores anteriores. **PASS: 2.451 registros preservados**, 69 hashes históricos e 404 testes conservados. Não foi feito rollback de migrations no banco existente nem reset do banco da interface. Bancos temporários de teste são locais; não são infraestrutura de produção.

Concorrência executada com duas conexões/threads PostgreSQL: dupla abertura cria uma jornada; início de OS concorrendo com encerramento não deixa execução sem jornada. Valores financeiros calculados com Decimal; tarifas inválidas, faixa de horário, limites, intervalos e regras congeladas cobertos.

Os testes anteriores continuam cobrindo estoque/FEFO/custo/compra/recebimento e os demais domínios. Esta etapa acrescenta testes da integração do gate a esses fluxos; não atribui aos novos testes uma jornada de compras repetida pela interface.

## Evidência pela interface

Navegador Codex In-app Browser; servidor local isolado e tenant sintético `VERTYX Piloto local`. Autenticação do cenário feita por helper de teste restrito a loopback e ignorado pelo Git; não representa teste de senha real, login público ou configuração de sessão em produção.

Jornada nova validada: destino sem detalhes → acesso direto à OS bloqueado com 403 amigável → início às 19:26:21 do servidor → chegada → liberação da OS → início próprio da OS às 19:27:42 → checklist Sim e medição 121,5 °C → diagnóstico/serviço/recomendação → upload pelo seletor do navegador → condição final OK/pendências → duas assinaturas sintéticas desenhadas com mouse → finalização → download do PDF → retorno → encerramento às 19:37:53 → solicitação de correção → aprovação administrativa.

OS sintética **OS-000052**, snapshot padrão 2, duas assinaturas, uma foto e documento privado. Upload real pelo navegador de `static/pwa/icon-512.png`, normalizado pelo fluxo existente, categoria DEPOIS. **Não foi foto de câmera física.** A jornada registrou GPS NEGADA sem consentimento; ações da OS registraram TIMEOUT. Não se obteve GPS real nesta execução.

Correção aprovada: limites efetivos 19:26:00–19:38:00; originais 19:26:21–19:37:53 preservados. Regras sintéticas de 15 minutos e tarifa 137,43 produziram 0,2500 h e valor 34,36, somente na medição administrativa. Tempos da OS permaneceram independentes. ADMIN abriu a medição/PDF e salvou a configuração; técnico recebeu 403 ao tentar abrir a área administrativa e sua tela não mostrou tarifas/valores.

As telas novas de atividade, configuração e medição foram conferidas em **390×844, 768×1024 e 1440×900**: nove combinações, sem overflow horizontal da página. A tabela de medição usa rolagem interna. Isso é validação de viewport desktop, não de aparelho físico. Pausas/rejeição/múltiplas OS e variantes adicionais são automáticas, não jornadas novas repetidas pela UI.

## PDF gerado e inspecionado

`tmp/validation/pilot-pdf/OS-piloto-v1.pdf`: três páginas, SHA-256 registrado no JSON. Todas as páginas renderizadas com Poppler e inspecionadas. Dados, checklist, medição e foto legíveis; duas assinaturas e hashes juntos na terceira página, sem página isolada apenas para nota de rodapé. Essa página ainda tem espaço livre abaixo das assinaturas, sem corte ou perda de conteúdo.

`tmp/validation/pilot-pdf/Medicao-contrato-administrativo.pdf`: uma página paisagem, inspecionada, com valor/hora e total administrativos. O PDF técnico não contém tarifa 137,43, valor 34,36, custos internos ou cálculo contratual. Texto extraído com pypdf do runtime de ferramentas, sem acrescentar dependência à aplicação. Warnings de fontes auxiliares do Poppler não impediram renderização nem causaram cortes observados.

O PDF da OS baixado pelo navegador corresponde exatamente ao arquivo emitido e armazenado. Testes verificam preservação após reabertura/mudança de emissor e detecção de adulteração de snapshot/assinaturas. PDFs antigos já baixados não foram reescritos. Como versões antigas não tinham cache do documento emitido, **não foi comprovada igualdade byte a byte de downloads históricos anteriores**; o renderer/snapshot legado foi preservado. A imutabilidade dos bytes armazenados vale a partir da primeira emissão persistida pelo novo mecanismo.

Identidade empresarial e logo reais ainda não estão configurados no tenant sintético; o PDF mostra os dados disponíveis, sem inventar CNPJ/contatos. Não foi criado QR público de validação de OS; hash e download autorizado são os mecanismos disponíveis. QR de equipamento permanece no fluxo existente.

## Migrations

Três migrations novas, aditivas, aplicadas e ensaiadas somente localmente:

| Arquivo | Operações |
|---|---|
| `ordens/migrations/0011_piloto_jornada_contratual.py` | Acrescentar imagem/hash da assinatura técnica e tabela de documento emitido |
| `operacao/migrations/0014_piloto_jornada_contratual.py` | Configuração, jornada, evento, vínculo OS, correção e decisão, com constraints |
| `ordens/migrations/0012_piloto_jornada_contratual.py` | Acrescentar condição final e pendências técnicas na OS |

Total local: **64 migrations do projeto**, excluindo oito `__init__.py`; 72 arquivos nos diretórios de migrations. Nenhuma migration histórica foi editada. **Nenhuma migration aplicada em produção nesta etapa.** As três novas devem ser consideradas pendentes de publicação; a lista completa publicada precisa de auditoria futura, inclusive as migrations dos blocos anteriores ainda não publicadas. Não inferir essa lista apenas pelo número local.

## Arquivos desta etapa

29 arquivos de fonte/template/JS/migrations novos ou alterados em relação à baseline do piloto:

- `gestao/services.py`
- `operacao/contract_workday.py`
- `operacao/contract_workday_models.py`
- `operacao/contract_workday_views.py`
- `operacao/history.py`
- `operacao/migrations/0014_piloto_jornada_contratual.py`
- `operacao/models.py`
- `operacao/planning.py`
- `operacao/planning_services.py`
- `operacao/services.py`
- `operacao/test_pilot_contract.py`
- `operacao/urls.py`
- `ordens/forms.py`
- `ordens/migrations/0011_piloto_jornada_contratual.py`
- `ordens/migrations/0012_piloto_jornada_contratual.py`
- `ordens/models.py`
- `ordens/pilot_report.py`
- `ordens/reports.py`
- `ordens/services.py`
- `static/js/contract-workday.js`
- `static/ordens/assinatura.js`
- `templates/403.html`
- `templates/gestao/detalhe.html`
- `templates/operacao/contract_activity.html`
- `templates/operacao/contract_measurement.html`
- `templates/operacao/tecnico.html`
- `templates/ordens/conferencia.html`
- `templates/ordens/detalhe.html`
- `templates/ordens/resumo.html`

Documentos novos: `PLANO_IMPLANTACAO_PILOTO_TECNOLMED.md`, este relatório e `VALIDACAO_IMPLANTACAO_PILOTO_TECNOLMED.json`. Helpers, logs, PDFs e screenshots locais ficam sob `tmp/validation`, ignorado pelo Git; não fazem parte do pacote de aplicação nem devem ser publicados. Arquivos previamente alterados dos Blocos 1/2/3/3H foram preservados. `requirements.txt`, Dockerfile, start script, Render YAML e configuração de credenciais não foram alterados neste piloto.

## Testes novos

- `test_common_contract_keeps_existing_operation`
- `test_admin_can_plan_before_technician_starts_workday`
- `test_required_contract_blocks_service_and_direct_get_post`
- `test_destination_is_only_projection_before_start`
- `test_start_unlocks_and_links_order_without_changing_os_clock`
- `test_server_time_ignores_injected_payload`
- `test_immutable_original_cannot_be_directly_edited_or_deleted`
- `test_double_start_and_end_are_idempotent`
- `test_open_order_prevents_pause_return_and_end`
- `test_finalized_order_allows_end_and_originals_preserved`
- `test_multiple_orders_share_workday`
- `test_approved_correction_preserves_original_events`
- `test_rejected_correction_does_not_affect_measurement`
- `test_correction_requires_admin_separate_actor_and_unique_decision`
- `test_correction_rejects_future_or_wrong_day`
- `test_snapshot_rules_preserved_when_contract_reconfigured`
- `test_decimal_travel_pause_return_rounding_and_daily_limit`
- `test_destination_start_excludes_outward_even_if_marked_billable`
- `test_measurement_excludes_outside_allowed_hours_and_overlapping_break_only`
- `test_allowed_hours_and_invalid_tariffs_rejected`
- `test_gps_variants_and_invalid_obtained_coordinate`
- `test_paused_or_returning_journey_blocks_execution`
- `test_administrative_start_cannot_bypass_required_journey`
- `test_stock_need_and_transition_cannot_bypass_gate`
- `test_technician_cannot_view_admin_config_or_measurement`
- `test_technician_activity_projection_omits_financial_data`
- `test_tenant_isolation_and_idor`
- `test_measurement_screen_and_pdf_administrative_only`
- `test_pdf_has_tenant_and_no_internal_cost_or_contract_measurement`
- `test_emitted_pdf_is_immutable_after_reopen_and_issuer_change`
- `test_pdf_detects_signature_and_snapshot_tampering`
- `test_invalid_technical_signature_rejected`
- `test_required_workday_requires_technical_signature`
- `test_client_portal_never_receives_workday_financial_data`
- `test_technical_audit_does_not_expose_prior_internal_cost`
- `test_concurrent_start_creates_one_workday`
- `test_concurrent_order_start_and_workday_end_cannot_leave_orphan_execution`

## Problemas encontrados e limites

- Na validação inicial da UI, a submissão assíncrona do formulário de jornada após GPS não prosseguia. Corrigida com o mecanismo de submissão já usado no fluxo da OS; início e encerramento repetidos com sucesso pela interface.
- Um probe inicial de preservação incluiu alterações legítimas de `auth_permission` produzidas por `post_migrate` e foi descartado como evidência de igualdade total. O ensaio isolado de avanço do schema anterior passou com as três migrations e 2.451 linhas, preservando colunas anteriores.
- Uma rodada intermediária executada enquanto a fonte mudava produziu resultados inconsistentes e erro do runner paralelo ao serializar traceback. Não foi usada para certificar o código. As rodadas finais estáveis, direcionada e completa, passaram sem mudar dependências/testes anteriores. Os dois logs 503 da suíte completa pertencem a testes intencionais de indisponibilidade de storage, não a falha do piloto publicado.
- Um acesso exploratório a ID de contrato diferente retornou 404; o link correto da interface foi usado em seguida. Não houve erro 500 identificado na jornada local nova. Isso não representa auditoria dos logs de produção.
- A regra de OS aberta bloqueia inclusive pausa e retorno; aceitação para atendimentos com espera/mais de um dia é pendente. Não encerrar OS artificiosamente para contorná-la.
- Uma categoria por jornada; correção só de limites; faixa no mesmo dia. Sem segmentação de tarifas nem turnos noturnos. Medição exige revisão administrativa e não é faturamento automático.
- Duração técnica pode conter segundos/microssegundos na apresentação. Refinamento visual futuro, sem alterar a medição original.
- Dados estruturados internos estão removidos das novas projeções técnicas; operador ainda deve revisar texto livre/legendas para não escrever conteúdo financeiro interno no relatório do cliente.
- Cache imutável novo depende de media privado funcional. R2 real, limites de upload, backups e documentos históricos publicados não foram validados nesta etapa.
- Assinaturas/GPS/imagens são evidências do fluxo; não se afirma certificação jurídica/biométrica, jornada trabalhista ou REP.
- Não homologados: aparelho físico, câmera/QR real, dedo, instalação/standalone, GPS obtido e redes reais. Não validados: produção, carga, dados reais e schema publicado.

## Encerramento e próximos passos autorizáveis

Trabalho local concluído com plano e evidências. Antes de uso real: aceitar políticas da jornada, cadastrar identidade/dados mínimos com autorização, executar roteiro físico e auditar ambiente publicado/backup/restore/schema. O YAML local nomeia serviço legado `tecnolmed-erp`, enquanto o usuário informou `vertyx-erp`; confirmar o serviço existente antes de publicar. O start script aplica migrations com trava antes do Gunicorn; autorização deve vir antes de qualquer restart/deploy que execute essa etapa.

**PARAR: aguardar autorização expressa. Sem commit, push, deploy ou migrations em produção. Sem Bloco 4.**
