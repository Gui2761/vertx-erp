# VERTYX — Plano de implantação piloto TECNOLMED

Data: 03/10/2026. Etapa exclusivamente local, posterior ao Bloco 3H. Não autoriza publicação nem inicia o Bloco 4.

## Situação para decisão

| Recurso | Situação |
|---|---|
| JORNADA CONTRATUAL | Pronta localmente; regras operacionais dependem de aceitação no piloto |
| BLOQUEIO DE OS | Pronto no backend e na interface |
| PDF NOVO | Pronto localmente, com documento técnico separado da medição administrativa |
| PWA | Pronta para homologação física, com operação online-first |
| DISPOSITIVO FÍSICO | Pendente |
| PRODUÇÃO | Não pronta para autorização de publicação: auditoria do ambiente, backup, restore e testes físicos pendentes |
| DEPLOY EXECUTADO | NÃO |

O relatório técnico e o arquivo `VALIDACAO_IMPLANTACAO_PILOTO_TECNOLMED.json` discriminam as evidências. Prontidão local não significa homologação em produção ou no celular.

## Baseline e auditoria inicial

Fontes preservadas: `RELATORIO_BLOCO3.md`, `VALIDACAO_BLOCO3.json` e `HOMOLOGACAO_BLOCO3.md`. O encerramento 3H continua sendo 404 testes PostgreSQL, zero skips e 39 reconciliações. Essas jornadas não foram repetidas nem reclassificadas como testes desta etapa.

Branch `main`; HEAD `fe6c554eb1fce12f430d9e6a1f9da8ecf9eae261`; origem `tecnolmedengclinica-spec/vertx-erp`. O working tree acumulado dos Blocos 1/2/3/3H foi preservado. Esse HEAD identifica o último commit, não inclui as alterações locais do piloto. Não houve commit, push ou deploy.

| Domínio ou requisito novo | Encontrado antes da implementação | Encaminhamento nesta etapa |
|---|---|---|
| Clientes, unidades, equipamentos, contratos e preventivas | Existente | Reutilizar cadastros e relações atuais |
| Chamados, triagem, planejamento, agenda e OS | Existente | Integrar bloqueio contratual aos fluxos atuais |
| VERTYX Técnico, checklist, medições, fotos e auditoria | Existente | Reutilizar backend, armazenamento e permissões |
| Estoque, FEFO, peças, necessidades e compras | Existente | Preservar fluxos; adicionar gate nas entradas operacionais da OS |
| Ponto e tempo próprio da OS | Existente | Manter independentes da jornada contratual |
| Jornada externa por contrato e regras de cobrança | Não existia como registro independente | Implementar na aplicação `operacao`, vinculada ao `Contrato` existente |
| Destino visível com detalhes de OS bloqueados | Parcial: agenda e autorização existentes | Criar projeção explícita e bloqueio real de GET/POST/services |
| Eventos oficiais, múltiplas OS e correção da jornada | Não existia para jornada contratual | Registros imutáveis, correção solicitada e decisão separada |
| Medição administrativa contratual separada | Não existia para jornada contratual | Tela/PDF administrativos com tenant e permissões |
| PDF técnico da OS | Existente, parcialmente adequado | Novo layout para novas versões; renderer legado preservado |
| Assinatura do cliente e hashes | Existente | Acrescentar assinatura gráfica do técnico e documento emitido imutável |
| Separação dos dados financeiros em novas versões técnicas | Parcial | Projeção técnica sem custo, tarifas ou cálculo da jornada |
| PWA instalável/online-first | Fundação existente | Integrar jornada; não criar aplicativo nativo ou fila offline |
| Homologação física e auditoria do ambiente publicado | Não realizadas nesta etapa | Roteiros abaixo; não presumir equivalência com o banco local |

## Uso da jornada no piloto

1. Administrador autorizado abre o contrato e sua configuração de jornada. A configuração é opt-in; contratos comuns continuam no fluxo anterior.
2. Define exigência de início, contagem BASE/DESTINO, ida/retorno faturáveis, intervalos, limite diário, faixa horária, categorias/tarifas, fração e arredondamento. As tarifas são valores decimais, não números de ponto flutuante.
3. Técnico recebe somente município, contrato e destino antes de iniciar. Os detalhes operacionais da OS ficam bloqueados.
4. `INICIAR ATIVIDADE DO DIA` registra horário do servidor, técnico/usuário, contrato, organização, origem, agenda e resultado de GPS. Não há campo para escolher livremente o início.
5. Registra chegada, executa OS, checklist, medições, fotos, peças e assinaturas. Cada OS mantém seus horários próprios; várias OS podem compartilhar a jornada.
6. Finaliza as OS; registra retorno e encerra a atividade. Os eventos usam hora do servidor e auditoria.
7. Se necessário, solicita correção justificada dos limites de uma jornada encerrada. Administrador distinto aprova ou rejeita; o original permanece intacto. Só a medição administrativa usa a correção aprovada.
8. Administrador revisa jornadas, divergências e medição. O valor calculado é informativo: não cria cobrança, conta a receber ou faturamento automático.

### Regras que precisam de aceitação operacional

- OS aberta, inclusive aguardando peça/cliente, impede pausa, retorno ou encerramento da jornada vinculada. Finalizar ou cancelar pelo fluxo autorizado é a regra segura atual. Não encerrar artificialmente uma OS real apenas para contornar a regra; casos de atendimento que atravessa dias precisam de avaliação antes de habilitar esse contrato.
- Uma jornada por técnico/contrato/dia, sem duas jornadas abertas simultâneas. Uma categoria por jornada; não há tarifa diferente por segmento/OS dentro do mesmo dia.
- A configuração de horário permitido representa faixa no mesmo dia. Não configura turno atravessando meia-noite. Encerramento tardio fica auditado e marcado para revisão; minutos fora da faixa são excluídos da medição.
- Ida é computada quando início BASE e deslocamento faturável estão habilitados. Início DESTINO começa na chegada. Retorno depende de sua regra. Intervalos são descontados somente na interseção com o período computável. Fração aplica-se ao tempo positivo nas regras de arredondamento; EXATO preserva os minutos exatos. Limite diário restringe o total final.
- Regras/tarifas são copiadas para a jornada ao início: editar o contrato não reescreve medições anteriores. Jornadas abertas são provisórias e não entram no total do relatório.
- Correções abrangem início/fim; não editam os eventos intermediários. Exigem dia correto, horários não futuros, ausência de sobreposição e justificativa.
- GPS é opcional e depende de consentimento/disponibilidade. Falhas registram NEGADA, INDISPONIVEL ou TIMEOUT; não inventam coordenadas.

## Cadastro posterior dos dados reais

Ainda não foram importados dados reais da TECNOLMED. Preparar arquivo de conferência, identificar duplicidades e obter autorização para a carga. Fazer uma carga pequena primeiro, validar vínculos e contagens, e registrar usuário/origem. Não usar fixtures sintéticas de teste como dados iniciais de produção.

| Cadastro | Conferências antes de gravar |
|---|---|
| TECNOLMED / Organization / identidade ERP | Razão social, documento, endereço, contatos e logo verdadeiros; organização correta e isolamento |
| Filial TECNOLMED | Usar `FilialEmpresa`, entidade da organização; endereço e centro de custo quando existentes |
| Usuários / memberships / permissões | Cada usuário pertence à organização correta; ADMIN/GESTOR/TECNICO com menor acesso necessário; testar usuário de outro tenant |
| Técnicos e funcionários | Vínculo usuário-técnico e identificação profissional; funcionário/ponto separado; não confundir cadastro de funcionário com jornada do contrato |
| Clientes e unidades | Cliente/documento e `clientes.Unidade` para UBS/local do cliente; endereço, município, setor e responsável |
| Contratos | Cliente, vigência, unidades/equipamentos cobertos, permissões, categoria e regras de jornada aceitas pelo gestor |
| Equipamentos | Cliente/unidade/setor, fabricante, modelo, serial, patrimônio, identificação/QR existente e histórico |
| Peças e depósitos | SKU, unidade, mínimo/ideal, fornecedor/custo, depósitos reais, lotes/validade e saldo de abertura via movimentação auditada; nunca editar saldo silenciosamente |
| Contas/formas | Caixa/bancos/formas reais; não inserir credenciais bancárias; conferir origem e conciliação dos movimentos |
| Agenda e jornadas | Começar com um contrato, um técnico e poucas OS reais; hora oficial e fuso conferidos antes do início |

**Filial da TECNOLMED (`FilialEmpresa`) e unidade do cliente (`clientes.Unidade`) são entidades diferentes.** Não importar uma UBS como filial da empresa nem usar esse vínculo para inferir receitas/despesas ou permissões.

## Publicação futura: ordem e critérios

Esta seção é um plano. Nenhuma consulta a Render, PostgreSQL publicado ou R2 foi feita nesta passagem. Não criar serviços, bancos, storage, runners ou cron jobs.

1. **Identificar o ambiente existente.** Com autorização específica, conferir o serviço Render correto, repositório, branch e commit publicado; PostgreSQL original e storage privado vinculado. O usuário informou anteriormente `vertyx-erp`, enquanto `render.yaml` ainda nomeia `tecnolmed-erp`. Resolver essa diferença antes de executar qualquer publicação; não sincronizar um Blueprint para presumir identidade. Não imprimir valores de variáveis.
2. **Inventariar o estado publicado.** Conferir versão de Python/Django, configurações existentes, nomes das variáveis, hosts, HTTPS, CSRF, fuso, tenant/memberships e acessos. Identificar migrations realmente aplicadas e todas as pendentes, inclusive as acumuladas dos Blocos 1/2/3. Não inferir que o banco publicado possui as 64 migrations locais.
3. **Backup e restore comprováveis.** Exportar backup consistente do banco existente, armazená-lo de forma privada e registrar metadados sem senha. Confirmar cobertura dos arquivos R2 privados e testar restauração em ambiente isolado autorizado. Não restaurar sobre o banco publicado nesta etapa. Sem restore ensaiado, não liberar o piloto.
4. **Ensaio incremental com o schema real.** Comparar plano de migrations e operações, ensaiar avanço na cópia isolada, conferir registros, vínculos, saldos, PDFs e usuários. O ensaio sintético local é uma evidência adicional, não substitui este ensaio.
5. **Revisão do pacote Git.** Revisar todas as alterações acumuladas; excluir `.env`, bancos locais, arquivos privados, backups, evidências com dados reais, certificados/chaves/tokens e diretórios `tmp`. Verificar que testes e migrations históricas permanecem íntegros. Preparar diff e lista exata das migrations para aprovação.
6. **Obter autorização expressa.** Apresentar serviço, branch, commit a publicar, migrations pendentes, backup/restore e rollback. A autorização deve abranger commit, push, deploy e aplicação incremental. Nenhuma dessas ações está autorizada por este documento.
7. **Publicar somente no serviço existente.** Sem mudar plano, banco, bucket ou secrets. Acompanhar build e `collectstatic`; o `scripts/start.sh` atual executa `migrate_locked --noinput` antes do Gunicorn. Portanto o primeiro restart/deploy já aplica pendências: aprovar o plano antes de dispará-lo. Usar a trava existente, sem concorrência de executores manuais e sem `fake`, flush ou reset.
8. **Verificar inicialização.** Confirmar migrations autorizadas, Gunicorn, health `/health/`, HTTPS e status Live; verificar logs e erros 500. Confirmar identidade do PostgreSQL correto e conservação de dados por contagens/vínculos previamente registrados.
9. **Conferir storage e segurança.** Static acessível; media, fotos, assinaturas e PDFs privados no R2 existente; acesso autorizado funciona, acesso indevido falha. Tenant, memberships, hosts e CSRF corretos. Não abrir bucket publicamente para contornar falhas.
10. **Smoke test controlado.** Login ADMIN/GESTOR/TECNICO; cliente/unidade/equipamento/contrato; agenda/chamado/OS/preventiva; peças/compra/recebimento; financeiro/relatórios existentes. Testar contrato comum e contrato opt-in; repetir os bloqueios e a separação de medição/PDF. Usar registros claramente identificados e sem apagar dados históricos.
11. **Homologar celular e iniciar piloto pequeno.** Executar o roteiro físico abaixo e revisar todas as divergências com responsáveis. Liberar um contrato, um técnico e poucas OS; acompanhar diariamente GPS/fotos/assinaturas/medição/estoque. Expandir somente depois da aceitação registrada.

## Rollback futuro

Interromper novas operações e registrar a falha; preservar logs, arquivos e todos os eventos. Com autorização, voltar ao último código conhecido compatível com o schema aditivo, sem migration reversa, exclusão de tabelas ou restauração destrutiva. Validar previamente compatibilidade do código anterior: a existência de campos/tabelas adicionais não garante compatibilidade de todos os fluxos.

Se o problema estiver na adoção da jornada, administrador autorizado pode desabilitar o opt-in pelo formulário auditado depois de revisar as jornadas abertas; não apagar sua história. Isso não equivale a desfazer o banco. PDFs já emitidos e seus objetos privados permanecem preservados.

Restore do banco publicado é um procedimento separado, excepcional, com análise de perda de operações posteriores ao backup e autorização expressa. Não usar restore/flush/reset como rollback automático. Após rollback, conferir health, login, dados, OS antigas e privacidade dos documentos.

## Roteiro de homologação física

Registrar aparelho, sistema/browser/versão, usuário/tenant, data, contrato, OS e resultado de cada caso. Evidências não devem expor credenciais ou dados pessoais desnecessários. Aprovação exige aparelho real, HTTPS e ambiente identificado.

| Caso físico pendente | Procedimento e resultado esperado |
|---|---|
| Instalação PWA, ícone e standalone | Instalar pelo browser suportado, fechar/reabrir pelo ícone; conferir nome, ícone e navegação standalone |
| Login e expiração | Login com conta técnica real autorizada; logout/expiração exige nova autenticação, sem acesso a outro tenant |
| Touch e telas | Navegar agenda/formulários com dedo, teclado virtual, rotação e resolução real; ações e mensagens legíveis |
| Destino e bloqueio | Antes do início, ver somente destino/contrato; URL direta e tentativa de executar OS bloqueadas |
| Início/liberação | Iniciar uma vez e repetir toque: um registro, hora do servidor, auditoria; OS atribuídas liberadas |
| GPS permitido | Consentir; obter coordenadas reais/precisão ou registrar timeout; conferir estado sem assumir precisão absoluta |
| GPS negado | Negar no aparelho/browser; continuar com estado registrado, sem coordenadas inventadas |
| GPS indisponível/timeout | Desativar localização ou testar falha controlada; mensagem útil, registro de falha e ausência de travamento |
| Checklist e medições | Preencher itens, unidade/decimais e diagnóstico; conferir persistência e PDF |
| Câmera e fotos | Fotografar com aparelho; ANTES/DURANTE/DEPOIS e legendas; conferir orientação, normalização, privacidade e upload |
| QR físico | Ler QR real do equipamento com câmera e conferir equipamento/tenant; invalidar código estranho. Identificação manual é fallback, não aprovação da câmera |
| Peças/estoque | Consumir peça pelo fluxo existente; conferir lote FEFO, validade, custo interno, saldo e auditoria; sem custo no documento do cliente |
| Assinaturas pelo dedo | Cliente e técnico desenham no canvas; impedir assinatura vazia; conferir identificação e hashes |
| Finalização e PDF | Definir condição final/pendências, finalizar, abrir/baixar PDF no aparelho; todas as páginas, duas assinaturas, sem dados financeiros internos |
| Retorno/encerramento | Testar bloqueio com OS aberta; depois finalizar e encerrar com hora oficial |
| Correção | Solicitar limite justificado, aprovar/rejeitar com outro usuário; conferir originais, decisão e medição separada |
| Wi-Fi | Executar jornada curta online, confirmar gravações no servidor |
| Rede móvel | Repetir upload e conclusão com dados móveis; confirmar respostas e ausência de duplicações |
| Troca de rede | Alternar Wi-Fi/dados durante formulário/upload; reconferir servidor antes de repetir operação; nenhuma suposição de gravação offline |
| Sem rede | Deve informar indisponibilidade; jornada não é enfileirada offline. Reconectar e verificar estado antes de repetir |

Não homologados fisicamente: todos os casos desta tabela. A validação de viewport desktop e o upload de imagem sintética não homologam câmera, touch, dedo, GPS obtido, QR físico ou troca de rede.

## Regra de parada

Entregar o plano, relatório e evidências locais. Aguardar autorização expressa para o próximo passo. Não executar commit, push, deploy ou migrations em produção; não iniciar o Bloco 4.
