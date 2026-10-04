# VERTYX — planejamento do Bloco 4, sem execução autorizada

Documento de planejamento. Nenhuma funcionalidade do Bloco 4 foi iniciada; não autoriza commit, push, deploy, acesso ao PostgreSQL publicado ou alteração de Render/R2/secrets.

## Condição de entrada

O Bloco 3 tem código integrado localmente e evidência automatizada registrada em `VALIDACAO_BLOCO3.json`, mas ainda possui jornadas de interface pendentes. Antes de declarar seu encerramento, recuperar a interação do navegador e concluir:

1. Compra: necessidade/cotação/aprovação/pedido, parcial/final, lotes/estoque e conta a pagar somente no final.
2. PDV: abertura, código de barras/busca, quantidade/desconto, cliente quando necessário, pagamentos mistos/troco, snapshot/comprovante, estoque/financeiro, devolução e fechamento/conferência.
3. Técnico: agenda, QR autorizado/fallback, OS, checklist/medições, foto/upload, necessidade/peça do mesmo estoque, conferência/assinatura, finalização e relatório.
4. Ponto: cadastro/jornada, quatro marcações, ajuste aprovado/rejeitado preservando original, espelho/PDF/Excel e histórico/fechamento, sem confundir com tempo da OS.
5. Gestor: filtros e navegação dashboard → venda → estoque → financeiro → OS → ponto, sem apresentar dados sem base como resultados reais.

Inspecionar 1440×900, 768×1024 e 390×844, com captura por tela crítica; teclado intensivo no PDV, foco/labels/contraste e mensagens. Acrescentar teste/reexecutar suíte apenas se houver correção de código; congelar hashes dos arquivos efetivamente validados. Encerrar pendências de módulos/permissões também nos agregados legados.

## Homologação real dos Blocos 2 e 3

Depende de autorização específica e ambiente escolhido pelo usuário. Não criar serviço/banco/storage, inventar endpoints ou reaproveitar credencial de outro ambiente.

- Identificar repositório/branch/commit e serviços existentes, conferir configuração sem exibir secrets. Verificar backup disponível e testar restauração isolada autorizada antes de migração real.
- Confirmar banco correto e lista de migrations pendentes; executar apenas incrementais aprovadas. Conferir preservação de dados/relacionamentos e verificar build/collectstatic/Gunicorn/logs.
- Validar usuários/memberships reais e configurações de filial, centro, contas, pagamentos, depósitos/trânsito, jornadas e dados fiscais informativos.
- Testar uploads/arquivos privados no R2 existente, acesso autorizado e negado, URLs de arquivo protegidas, PDFs e política de cache PWA.
- Testar celular físico/touch/câmera/QR, leitor como teclado, GPS autorizado/negado/indisponível e TV real. Registrar dispositivo, navegador, resolução e resultado separado da validação sintética.
- Medir carga e latência com volume representativo: PDV, relatórios, dashboard, lotes/reservas, PDF e mobile. Investigar N+1 com evidência antes de otimização.

## Decisões necessárias para o próximo escopo

Definir e aprovar antes de implementação:

- política financeira de devolução sobre recebível parcelado e troca/crédito;
- governança de diferença de caixa, revisão por supervisor e justificativa de encerramento;
- alterações/correções de ponto em mês fechado, regras de jornada/banco de horas e estudo jurídico/técnico antes de qualquer alegação REP;
- distribuição de OS/depósitos por filial própria/centro e indicadores com base suficiente;
- catálogo de planos, enforcement de limites, administração de múltiplas PJs e cobrança SaaS;
- integração fiscal real, abrangência produto/serviço/mista, provedor, regras fiscais e homologação, se o usuário autorizar esse módulo futuramente;
- prioridades comerciais/comissões, integrações externas e módulos futuros separadamente, sem ativação antecipada.

Os recursos explicitamente excluídos no Bloco 3 não passam a estar autorizados pela existência deste plano. Não implementar NF-e/NFS-e/NFC-e, A1, gateways, mensagens, IA/OCR, folha/eSocial ou módulos públicos sem novo escopo e autorização.

## Critérios de entrega futura

Plano aprovado, baseline preservada, migrations aditivas, testes automatizados e PostgreSQL/concorrência, jornadas reais completas, responsividade e segurança documentadas, matriz de aderência com fonte verificável. Publicação somente mediante autorização posterior. Nenhuma conformidade com edital ou legislação será afirmada sem evidência específica.
