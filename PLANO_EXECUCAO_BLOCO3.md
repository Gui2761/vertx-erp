# VERTYX — plano de execução do Bloco 3

02/10/2026. Registrado antes das alterações de arquitetura/models/migrations. Pasta original, base `fe6c554` + alterações locais dos Blocos 1 e 2. Solicitação autorizadora: Bloco 3, seções 1–75. Documentos do Bloco 2 e estabilização lidos; base anterior registra 335 testes PostgreSQL aprovados. Resultados anteriores não certificam antecipadamente este bloco.

## Auditoria e reutilização

| Domínio | Situação encontrada | Decisão incremental |
|---|---|---|
| Tenant/empresa | Organization já possui UUID, identidade jurídica, CNPJ, memberships e acesso ao ERP. | Preservar identidade; configuração fiscal/comercial e filiais da própria organização, distintas de Cliente/Unidade. Não renomear tenant real, não criar cliente TECNOLMED presumido. |
| Permissões | Papel efetivo vem de membership ativo, não do grupo/global perfil. Middleware isola portal e painel. | Acrescentar capacidades e módulos centralizados, configuráveis por membership/organização. Negação no backend e serviços. Manter papéis anteriores. |
| Produtos | Peca possui SKU, categoria, fabricante/marca, unidade, custos/preços, fiscal básico e saldo protegido. | Acrescentar metadados comerciais, códigos alternativos, fornecedores e conversões no mesmo produto. Não criar outro estoque. |
| Venda/financeiro | Venda/ItemVenda em rascunho/CONFIRMADA; confirmação consome FEFO e gera Lancamento. Pagamento/evento/caixa oficial com origem raiz. | Ampliar estados compatíveis, snapshot, carrinho/PDV, sessão de caixa, pagamentos mistos e devolução formal usando essas mesmas entidades. Preservar CONFIRMADA e vendas antigas. |
| Orçamento | Orcamento/ItemOrcamento oficiais aprovados podem gerar recebível e OS. | Nova conversão para Venda com vínculo único, sem duplicar recebível nem converter orçamento com serviço não representado em produto. |
| Estoque/compras | Lotes, saldo por depósito, reservas alocadas, transferências diretas, custos/devoluções e recebimento parcial já funcionam. | Reutilizar motor; inventário com contagem/recontagem, aprovação e movimentos. Transferência por fases usa os mesmos movimentos/lotes e depósito de trânsito explicitamente configurado. |
| Assistência/mobile | Agenda técnica, QR autorizado, execução/checklist/foto/assinatura e PWA seguro existem. | Home/atalhos móveis e leitura QR com fallback, etapas curtas e salvamento pelos serviços atuais; sem cache empresarial/offline complexo. |
| Ponto/RH | Tecnico e Usuario existem; jornada técnica é texto, OS não equivale a ponto trabalhista. | Ficha Funcionario vinculada a usuário/técnico, jornada configurável, marcações imutáveis e ajustes por eventos; espelho/exportação. Não criar outra conta de usuário/técnico. |
| TV | Perfil PAINEL, permissão explícita e DTO limitado já existem. | Preservar, compatibilizar PAINEL_TV e aperfeiçoar apresentação; nenhum privilégio administrativo. |
| GED/pesquisa/relatórios | Documentos privados e exportadores estão implementados. | Acrescentar vínculos produto/funcionário/compra/venda e autorização específica; ampliar busca/indicadores por domínios existentes. |
| Fiscal | DocumentoFiscal e adaptador já existem sem emissão autorizada. | Dados/configuração e snapshots internos; nenhuma chamada externa nem regra tributária presumida. |

## Políticas de integração

- Toda regra é por Organization. Organization identifica tenant e pessoa jurídica principal nesta fundação; filiais próprias não são unidades de clientes. Outras pessoas jurídicas do mesmo grupo não serão presumidas a partir do cadastro de cliente.
- Módulos ausentes na configuração mantêm compatibilidade de acesso legado; desabilitação explícita bloqueia rota e serviço. Novos papéis não recebem acesso administrativo implícito. Exceções de capacidade são configuradas/auditadas por administrador.
- Venda usa Venda/ItemVenda, Peca, depósitos, Movimentacao/MovimentacaoLote, Lancamento, Pagamento, EventoFinanceiro e MovimentoCaixa. Sessão de caixa só organiza esses movimentos, não mantém ledger financeiro paralelo.
- Caixa exige conta CAIXA já configurada e operador. Abertura registra conferência do numerário existente; não fabrica receita pelo saldo inicial. Suprimento/sangria/ajuste exigem origem/motivo e movimentos reais; fechamento registra esperado, contado e diferença sem baixa fictícia. Pagamento não bancarizado continua rastreável.
- Valores monetários em Decimal/centavos, conversões com quantidade base exata ou validação explícita; custos reais por lote. A precisão necessária às conversões será validada antes de ampliar campos e nunca arredondará saldo silenciosamente.
- Descontos por item/global respeitam limite configurável, autorização e motivo. Finalização congela dados e pagamentos, é idempotente e bloqueia edição. Venda a prazo exige cliente e crédito permitido; dinheiro pode conter troco, sem receber mais que o valor devido.
- Reserva de orçamento/venda é política explícita; finalização consome e cancelamento libera. Devolução identifica item, lote/custo originais e valor financeiro, sem apagar venda. Troca associa devolução e nova venda sem editar a original.
- Compras APROVADA/PEDIDO descontam somente pendência; RASCUNHO/CANCELADA não cobrem reposição. A conta a pagar permanece gerada no recebimento final, política expressamente preservada pela seção 26.
- Inventário detecta movimentos ocorridos desde a contagem e exige recontagem; ajuste por lote auditado, incluindo vencidos, sem sobrescrever saldo. Divergência e autorização ficam registradas.
- Ponto é independente de início/fim de OS. Marcações usam hora do servidor/timezone e token, sequência validada; correções preservam original. Tolerâncias/escala/banco de horas parametrizados. Não declarar conformidade trabalhista/REP nem aplicar regras legais não aprovadas. Localização não obrigatória nem coletada sem autorização específica.
- Identificadores públicos novos usam UUID; PKs legadas protegidas por isolamento/permissão permanecem. Metadados de planos SaaS não ativam cobrança nem impõem limites retroativos aos dados existentes.

## Execução e validação por etapa

1. **3.0:** preservar hashes de arquivos/migrations e inventário dos 335 métodos; check/migrations seco; registrar plano e roteiro real do Bloco 2.
2. **3.1:** filiais, configuração fiscal/SaaS, módulos/capacidades e novos papéis; testes de tenant/IDOR, flags e compatibilidade.
3. **3.2:** cadastro comercial/conversões/códigos/fornecedores, sem saldo paralelo; testes Decimal e isolamento.
4. **3.3:** PDV, sessão de caixa, snapshot/pagamentos/recebível/orçamento/devolução; testes transacionais, idempotência e corridas.
5. **3.4:** compras compatíveis, inventário e transferências; testes de lote/custo, divergência, concorrência e preservação.
6. **3.5:** indicadores/financeiro com dados reais e filtros por filial/centro; regressões de origem raiz/parcelas/pagamentos.
7. **3.6:** home técnica e jornada móvel/QR, serviços atuais e PWA sem dados privados em cache.
8. **3.7:** RH/ponto, jornada/escala, marcações/ajustes/espelho e banco configurável; testes de sequência/duplicação/permissão/exportação.
9. **3.8–3.9:** TV, GED, pesquisa, dashboards e fundação fiscal; testes de DTO privado, novos vínculos e exportações.
10. **3.10:** 335 anteriores + novos, PostgreSQL real local, concorrência, check/migrations seco/pip/collectstatic/PWA, banco limpo e incremental anterior, jornadas/browser/teclado e 1440×900/768×1024/390×844; evidência e documentos finais.

Migrations serão novas; hashes anteriores devem permanecer iguais. Banco de teste somente no cluster sintético de loopback já existente. O ensaio incremental usa banco temporário isolado com schema anterior/dados sintéticos e compara colunas/linhas/relações. Scripts de QA nunca serão usados no banco publicado.

## Homologação real do Bloco 2 — roteiro pendente de autorização

Conferir usuários/memberships reais, cadastros/depósitos/lotes, celulares físicos, touch, QR, GPS negado e indisponível, uploads/documentos/PDF, R2 privado e expiração de acesso. Em ambiente autorizado: testar backup e restauração isolada, sequência de migrations, conexão PostgreSQL, collectstatic/Gunicorn/logs no Render. Registrar tempos/volume e responsabilidades. Nada disso será executado em produção neste desenvolvimento.

## Fora de escopo e entrega

Sem integrações fiscais/bancárias/mensagens/IA/OCR/fabricante/ANVISA reais, folha/eSocial, aplicativo nativo, offline empresarial complexo ou módulos públicos do roadmap. Nenhum commit, push, deploy, alteração de secrets/infraestrutura nem Bloco 4.

Entregar `RELATORIO_BLOCO3.md`, `VALIDACAO_BLOCO3.json`, `MATRIZ_ADERENCIA_VERTYX.md` e `PLANO_BLOCO4.md`. Separar validado automaticamente/interface/banco sintético/dispositivo real/produção; não declarar editais conformes sem fonte/evidência. Qualquer lacuna deve ser registrada como pendência, sem simular integração.
