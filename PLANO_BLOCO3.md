# VERTYX — recomendação para o Bloco 3

02/10/2026. Recomendação após o desenvolvimento local do Bloco 2. Este documento não autoriza nem executa implementação, publicação ou configuração externa.

## Primeiro: homologar os fluxos locais aprovados

1. Revisar `RELATORIO_BLOCO2.md` e `VALIDACAO_BLOCO2.json`, com atenção à política financeira do recebimento parcial, aos indicadores e às limitações.
2. Fazer homologação assistida com ADMIN/GESTOR, técnico principal/auxiliar, ESTOQUE, FINANCEIRO e CLIENTE. Usar ambiente autorizado separado e dados adequados; não executar os scripts sintéticos de `tmp/validation` em produção.
3. Conferir cadastros reais: vínculo usuário/cliente, unidades, critérios dos checklists, equipes, permissões, mínimos/ideais, depósitos, validade por lote, cobertura e calendário dos contratos. Campos históricos opcionais ficam vazios até preenchimento explícito e auditado.
4. Após autorização específica para publicação: revisar diff acumulado dos Blocos 1 e 2, backup/restauração, variáveis existentes, storage privado, commit e cinco migrations novas deste bloco mais as três do Bloco 1 se ainda não aplicadas. Não criar outro banco ou substituir infraestrutura.

## Próximo escopo recomendado

| Prioridade | Proposta | Critério de aceite antes de expansão |
|---|---|---|
| 1 | Homologação com celulares físicos e operação real | Assinatura mouse/touch, GPS negado/indisponível, anexos, QR, planejamento, reservas e recebimentos; confirmar acessibilidade e legibilidade. |
| 1 | Operação de notificações | Autorizar e configurar execução periódica existente, frequência, monitoramento e prevenção de sobreposição. Nenhum runner foi ativado neste bloco. Validar resolução/reabertura em execução contínua. |
| 1 | Recuperação e observabilidade | Ensaio de restauração em ambiente autorizado, monitoramento de storage/Gunicorn, alertas de falha e trilha operacional sem segredos. |
| 2 | Política financeira de entregas parciais | Decidir com gestão se a obrigação deve nascer por entrega/documento ou apenas no recebimento final, política atual preservada. Eventual mudança exige conciliação, idempotência e testes de regressão antes de implementação. |
| 2 | Governança das preventivas | Revisar planos e visitas contratuais sobrepostos. Hoje são fontes oficiais distintas, apresentadas em conjunto; não fundir nem apagar histórico automaticamente. |
| 2 | Importação assistida de metadados legados | Prévia, validação, aprovação, auditoria e reversão; nunca presumir classificação, lote, custo ou assinatura faltantes. |
| 2 | Usabilidade orientada à homologação | Melhorias pequenas comprovadas pelo uso, critérios de checklist e pesquisa técnica; evitar reescrita visual/framework. |

## Integrações somente após decisão específica

Fiscal real (NF-e/NFS-e/certificado A1), mensagens externas, pagamentos, Open Finance, fabricante/ANVISA e IA/OCR exigem escopo, fornecedor, credenciais fora do código, ambiente de teste, contrato de dados e autorização próprios. A base de conhecimento estruturada é fundamento para futuras buscas; não é IA externa funcionando.

Sincronização offline de dados empresariais, resolução de conflitos e assinatura offline exigem projeto próprio. O PWA atual mantém apenas assets públicos e tela de indisponibilidade; não armazenar documentos, sessão, GPS ou assinaturas em cache.

## Regras que continuam obrigatórias

Preservar origem raiz, centavos exatos, pagamentos parciais/idempotentes e não bancarizados, FEFO/custos reais por lote/devoluções, snapshots assinados, dados históricos e isolamento por organização. Usar somente migrations incrementais e serviços oficiais. Manter a suíte PostgreSQL e ampliar concorrência para cada novo fluxo. Nenhum item acima foi implementado como Bloco 3.
