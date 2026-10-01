# Automação de estoque e compras — VERTYX

## O que já está implementado

`python manage.py processar_estoque` executa uma rodada e encerra. Sem `--organization`, percorre todas as organizações ativas com Assistência habilitada; cada execução usa o contexto isolado da empresa. Com `--organization SLUG`, limita a uma empresa existente. Não há credenciais no comando.

O scheduler bloqueia a configuração da organização em uma transação PostgreSQL. O horário da última verificação fica no banco. No padrão, uma rodada efetiva verifica os alertas a cada 30 minutos; chamadas intermediárias não repetem a verificação. O relatório semanal usa dia/horário configurados e uma chave única por organização/semana. Execuções simultâneas não duplicam relatórios nem ocorrências abertas.

Em Configurações → Estoque e Compras, ADMIN configura intervalo (1–1440 minutos), faixas de validade, dia/horário e geração semanal. Padrão: 30 minutos, faixas 90/60/30/15/7 dias, segunda-feira às 08:00. O horário usa `TIME_ZONE` já configurado na aplicação. O valor existente no Blueprint é `America/Maceio`; a aplicação não muda esse fuso nem credenciais.

O relatório atrasado é gerado na próxima rodada da mesma semana. Sem scheduler ativo não há garantia de pontualidade. Após uma parada longa, não são inventados snapshots retroativos das semanas anteriores.

O executor identifica um usuário ativo ADMIN, GESTOR ou ESTOQUE com grant Assistência na empresa, nessa ordem de preferência. Essa identidade aparece na auditoria da rotina. Empresas sem operador autorizado são identificadas com `OPERADOR_ESTOQUE_ERP_ATIVO_AUSENTE` e não processadas. Erros retornam o nome da classe, sem conexão, senha ou traceback; outras empresas continuam a execução. Em rodada única, erros produzem código de saída não zero.

## Execução automática local

O serviço `estoque_runner` no `docker-compose.yml` inicia junto com o Compose, aguarda o PostgreSQL saudável, aplica migrations com o bloqueio já existente e executa `processar_estoque --loop`. Reutiliza a mesma imagem, configuração `.env` e banco do Web Service. Reinicia se parar. Não há Redis, Celery, novo estoque ou novo banco.

```sh
docker compose up -d --build
docker compose logs -f estoque_runner
```

O loop consulta o scheduler a cada 30 segundos. O intervalo efetivo de alertas continua controlado pelo banco. Pode funcionar independentemente de acessos ou do processo web. Para executar em uma máquina configurada sem Docker:

```sh
python manage.py processar_estoque --loop
```

Esse processo precisa ficar em execução e ser supervisionado pelo operador/serviço da máquina. A entrega não instala tarefa persistente no computador do usuário. O comando anterior `atualizar_alertas --organization SLUG` foi preservado para suporte e verificações pontuais.

## Ativação futura no Render — não realizada nesta entrega

Não iniciar o loop dentro do Gunicorn ou `AppConfig.ready()`: múltiplos workers e suspensão do plano Free não garantem a rotina. O `render.yaml` permanece com Web Service `plan: free`, usando o PostgreSQL e storage existentes. Não foi criado serviço, banco, bucket, URL ou segredo remoto.

O Render suporta Free para Web Service e PostgreSQL, mas não para Cron Jobs. O Web Free dorme após 15 minutos sem tráfego. Cron Jobs têm cobrança por tempo de execução e mínimo mensal de US$ 1 por serviço. Informação verificada em 01/10/2026: [Cron Jobs](https://render.com/docs/cronjobs), [Deploy for Free](https://render.com/docs/free). O valor final depende do plano e uso apresentados no painel. A ativação de um serviço pago depende da escolha do usuário; a entrega não altera o plano gratuito.

Quando houver autorização para publicar esta versão e ativar a rotina:

1. Fazer backup do banco existente por procedimento disponível na infraestrutura. Conferir migrations pendentes em homologação; não resetar ou criar outro banco.
2. Publicar a versão revisada no repositório/branch usados pelo serviço, somente com autorização. Aplicar migrations aditivas pelo mecanismo atual de deploy. Confirmar saúde do web e acesso à empresa.
3. Criar **New → Cron Job**, conectado ao mesmo repositório/branch e na mesma região do PostgreSQL existente. Selecionar Docker e conferir o preço do compute antes de criar.
4. Em **Advanced → Docker Command**, definir `python manage.py processar_estoque`. Não usar o CMD web padrão do Dockerfile e não passar `--loop` no Cron Job.
5. Definir o agendamento `* * * * *` (a cada minuto). O scheduler decide quando os alertas de 30 minutos e o relatório semanal estão devidos. Isso também permite alterar o intervalo nas configurações sem modificar a agenda externa. Cron do Render usa UTC; o horário semanal da aplicação usa `TIME_ZONE`.
6. Configurar com segurança os valores **existentes**, preferencialmente por Environment Group: `DATABASE_URL` interno do mesmo PostgreSQL, `SECRET_KEY`, `DEBUG=False`, `TIME_ZONE`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` e a configuração atual de uploads privados. Para S3: `UPLOAD_STORAGE=s3`, `S3_BUCKET_NAME`, `S3_REGION_NAME`, `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Preservar outras variáveis já usadas pela instalação. Não copiar valores para código, documentos, logs ou Git.
7. Na empresa, verificar membership ativo ADMIN/GESTOR/ESTOQUE com Assistência habilitada. Ajustar Configurações → Estoque e Compras e cadastrar mínimo/ideal por produto. Os padrões novos não sobrescrevem produtos existentes.
8. Em **Runs → Trigger Run**, executar uma vez. Conferir saída por empresa, ocorrências, horários e relatório. A primeira rodada poderá gerar o relatório da semana corrente se o horário já passou.
9. Aguardar a próxima rodada devida, confirmar atualização sem duplicação e acompanhar falhas no painel do Cron Job. Validar também a resolução após reposição e uma nova ocorrência quando o problema retornar.

Como alternativa ao Cron Job pago, um scheduler supervisionado em infraestrutura que o usuário já possua pode executar a rodada única a cada minuto, com acesso autorizado ao banco e a mesma configuração. Não foi criada essa infraestrutura. Sem um executor externo ativo, o Web Free sozinho não garante a execução automática.

## Ocorrências, validade e reposição

Uma ocorrência aberta tem identificação durável por produto/problema ou lote/validade. Mudança de faixa atualiza a mesma ocorrência. Ler a notificação não resolve o problema. Ao regularizar, a rodada seguinte resolve a ocorrência e seus avisos; se o problema retornar, abre um novo ciclo com histórico preservado.

FEFO consome primeiro lotes com validade mais próxima, considerando a validade no dia corrente como válida. Lotes vencidos não são consumidos por OS, venda ou saída automática. Descarte/transferência física de lote vencido exige seleção explícita e movimento auditado; não torna o lote utilizável. Devoluções recuperam a validade original, mesmo se já venceu.

Saldo físico é o mesmo `Peca.quantidade_atual`/`SaldoDeposito`. Lotes detalham esse saldo. Reservas não retiram saldo físico; comprometem quantidade válida por depósito para uma OS, uma venda ou outro motivo operacional. Cadastre o compromisso em Estoque → Reservas antes da separação. Rascunhos editáveis não são automaticamente tratados como compromisso firme. A confirmação da venda e o consumo da OS utilizam a própria reserva sem duplicar baixa; outras reservas são protegidas. Encerramento/cancelamento libera o restante na rodada seguinte e deixa de contar imediatamente na disponibilidade.

A recomendação desconta disponibilidade válida e solicitações/compras pendentes nos estados RASCUNHO/APROVADA/PEDIDO. Considera reposição estimada de lotes que vencerão e consumo médio quando há pelo menos 30 dias desde o primeiro consumo. A janela padrão é 90 dias e a cobertura de reposição é 30 dias. Sem histórico suficiente, usa mínimo/ideal cadastrados. Sugestão é recomendação editável; quantidade acima da necessidade atual exige justificativa. Cancelar uma compra retira seu saldo pendente; receber converte o pendente em estoque.

O relatório é um snapshot imutável com histórico independente por geração. PDF e Excel contêm as mesmas 15 informações gerenciais. Gerar solicitação revalida a necessidade atual, usa UUID para impedir duplo envio e cria os models existentes `Compra`/`ItemCompra`. Cotação, fornecedor, aprovação, pedido, recebimento e conta a pagar continuam pelo fluxo atual. Informe lote/validade dos produtos controlados antes do recebimento.

## Atualização segura dos dados existentes

Migrations novas: `gestao.0005`, `operacao.0002`, `0003` e `0004`. Nenhuma migration anterior foi editada. O detalhamento legado copia saldo, validade antiga quando conhecida, fornecedor, custo e localização para os lotes. Sem validade registrada, o lote é identificado como legado/sem validade; nenhuma data de fabricação ou vencimento é inventada. Quantidade antiga permanece no saldo original. Inconsistência entre depósitos e produto aborta o upgrade para análise, sem apagar registros.

A regularização deve ocorrer por movimentos auditados. Não editar saldo ou validade global de `Peca` diretamente: os campos globais antigos são históricos, e as novas entradas usam validade por lote. A ausência de validade continua permitida para peças não perecíveis; para perecíveis, habilite **Controla validade** no produto e informe validade por entrada.
