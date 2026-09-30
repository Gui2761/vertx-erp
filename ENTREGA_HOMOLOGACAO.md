# ENTREGA — preparação de homologação VERTYX Assistência

Data: 30/09/2026. Escopo: infraestrutura e validação da arquitetura existente.
Nenhum novo módulo de negócio foi implementado. Código preparado; homologação
externa no Render/R2 e celular físico aguardam os recursos que o usuário ainda
não possui. Não houve contratação, criação de serviços externos, push ou deploy.

## 1. Estado inicial e auditoria

Referência desta fase: `vertyx_assistencia.zip`. Python local 3.12.14, Django
5.0.9; Docker Python 3.12. Requirements fixados, PostgreSQL por padrão, SQLite
explicitamente separado em test_settings. Os 71 testes anteriores passaram
antes das alterações (34 de OS e 37 da fundação).

Foram lidos settings, requirements, storages, views, models/migrations, JS de
GPS/assinatura, PDF, Docker/Compose, render.yaml, env e testes. Não havia banco
PostgreSQL disponível inicialmente, nem app Render, bucket ou credenciais
externas. A configuração permitia chave local padrão e faltava validação forte
de produção; storage privado era local com fachada configurável, ainda sem S3
por ambiente. Static usava o alias anterior de Django, health não tinha rota
dedicada e logging não tinha proteção específica contra payloads/secrets.
Quatro arquivos locais encontrados (21.712 bytes) foram preservados.

## 2. Alterações realizadas

Validação explícita de produção, conexão PostgreSQL, S3 privado por Django
Storage, tratamento seguro de falhas, namespaces UUID para novos uploads,
health, logging, static STORAGES, start com lock de migration e configuração
Render. Adicionados comandos de cópia verificável de arquivos e testes de
infraestrutura/concorrência. README, guia, checklist e env atualizados.

Não foram alterados snapshots/hashes antigos, banco existente, migrations
anteriores ou regras de atendimento. Dois testes antigos passaram a consumir
streaming_content para não fechar conexão dentro do TestCase PostgreSQL;
cobertura foi mantida e a existência dos bytes passou a ser verificada.

## 3. Dependências adicionadas

Produção: django-storages[s3] 1.14.6, boto3 1.40.54, botocore 1.40.76 e
s3transfer 0.14.0, fixados em requirements.txt. Django 5.0.9 e dependências
anteriores foram preservados. Testes: moto[s3,server] 5.1.13 em arquivo separado
requirements-test.txt; não é instalado na imagem de produção.

## 4. PostgreSQL

DEBUG=False exige DATABASE_URL PostgreSQL válida; ausência, SQLite, MySQL ou
URL inválida falham explicitamente, sem fallback e sem exibir seu valor.
CONN_MAX_AGE padrão 60, CONN_HEALTH_CHECKS=True, connect_timeout 5 segundos.
DATABASE_SSL_REQUIRE padrão True em produção (`sslmode=require`).
POSTGRES_* só é fallback de desenvolvimento DEBUG=True, ainda PostgreSQL.

Provisionado PostgreSQL **16.15** portátil, somente localhost, em diretório
ignorado, com banco novo isolado e senha aleatória local. Nenhuma base anterior
foi apagada. Esse banco de bancada usou transporte PostgreSQL local sem TLS;
TLS obrigatório está configurado para o Render, cuja conexão real permanece
pendente. O ensaio web e o simulador S3 utilizaram HTTPS com certificado local.

## 5. Resultado dos testes PostgreSQL

Suíte completa: **89 testes, todos aprovados**, em 187,190 segundos. Inclui os
71 anteriores, constraints/FKs, tenant, transações, histórico, reabertura,
assinatura, snapshots/hashes e teste forward-only de upgrade de dados legados.
Dois novos testes com conexões independentes e threads concorrentes confirmam
apenas um início e uma finalização da mesma OS, com uma assinatura e auditoria
coerentes. O teste legado cria e remove somente sua base temporária, nunca
reverte migrations do banco utilizado pela aplicação.

## 6. Storage

UPLOAD_STORAGE=s3 configura backend Django com bucket/endpoint/região/chaves
por ambiente, assinatura S3 v4, sem ACL pública, sem custom domain, sem
sobrescrever objetos e com cache privado. Conexão 5s, leitura 20s, até duas
tentativas. Endpoint HTTPS obrigatório com DEBUG=False. Provedor recomendado:
R2, cuja configuração manual está em DEPLOY_RENDER.md. Nenhuma configuração
externa foi inventada/preenchida.

## 7. Arquivos privados

Rotas existentes conferem usuário, organização, membership, habilitações de
ERP e permissão antes de abrir o objeto. Fotos e arquivos de equipamento são
entregues por FileResponse autorizado; o bucket deve permanecer privado.
Assinatura (imagem base64), snapshot e hashes continuam no PostgreSQL, sem
remodelagem. PDF lê arquivo por Storage.open, não por caminho local.

Novas fotos: `private/organizations/<organization_uuid>/assistencia/ordens/
<os_uuid>/fotos/<uuid>.jpg`. Equipamentos: prefixo `media/organizations/` com
UUID de organização/equipamento e nome aleatório. UUID/CNPJ não são autorização;
CNPJ e nome original do arquivo não são usados no namespace novo. Chaves antigas
continuam iguais. migrate_uploads faz dry-run/cópia/SHA-256 sem apagar origem
nem alterar referências/hashes. Conflitos falham, cópias iguais são verificadas.

## 8. URLs temporárias

Não são entregues presigned URLs ao navegador. `storage.url` de equipamento
retorna a rota Django autenticada; a fachada privada não publica URL de bucket.
Cada requisição passa pela autorização atual, inclusive após revogação de
membership. As opções de assinatura do SDK não mudam essa estratégia. Não
configure proxy/CDN para servir /media/ ou bucket diretamente.

## 9. Render

Blueprint original preservado e ajustado com variáveis S3 e health /health/.
Nomes técnicos preservados e plan: free confirmado pelo usuário para Web
Service e PostgreSQL. Ambos constam da referência Blueprint Render consultada
em 30/09/2026. Guia ajustado para operação sem Shell/pre-deploy pago, com
criação do operador localmente pela conexão externa do banco. Docker usa
PostgreSQL externo e R2; não depende de disco persistente web para uploads.

## 10. Build

Dockerfile: instala requirements.txt, copia código e executa
`python manage.py collectstatic --noinput`. Nenhuma migration, conexão de banco
ou bucket no build. .dockerignore exclui env real, mídia, banco, tmp, caches e
ambientes virtuais. Não há credenciais em Dockerfile ou build args.

## 11. Start

`/bin/sh /app/scripts/start.sh`, depois Gunicorn para tecnolmed.wsgi:application.
Porta PORT do Render (8000 local), dois workers por padrão, duas threads,
timeout 60s e graceful_timeout 30s. WEB_CONCURRENCY configurável. Não usa
runserver em produção. Servidor WSGI HTTPS portátil dos testes é apenas bancada.

## 12. Migrations no deploy

Start executa `migrate_locked --noinput` antes do Gunicorn. Advisory lock
PostgreSQL serializa migrations de starts concorrentes; espera até 120s e
falha explicitamente se não conseguir lock. Não gera migration no deploy.
Build e Pre-deploy Command não precisam aplicar schema nesta configuração.
Backup/janela de manutenção continuam necessários para atualizar dados reais.

## 13. Health

GET/HEAD /health/ público, sem login, responde 200 com status ok após SELECT 1;
falha de banco responde 503 genérico, sem credenciais/traceback, cache no-store.
Exceção de redirect HTTPS somente nessa rota para compatibilidade de health
do proxy. Não verifica S3 a cada probe; upload autorizado valida o storage.

## 14. HTTPS

DEBUG=False: SECURE_PROXY_SSL_HEADER reconhece X-Forwarded-Proto=https do
Render, redirect HTTPS, SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, nosniff,
sessão HttpOnly e SameSite Lax. HSTS 3600s. Include-subdomains/preload são
opções False por padrão; precisam de decisão sobre domínio definitivo.
Ensaio DEBUG=False, hosts restritos, PostgreSQL, HTTPS web e HTTPS S3 passou.
Certificado self-signed foi aceito no Chromium somente para localhost.

## 15. CSRF

CSRF_TRUSTED_ORIGINS usa CSV de origens HTTPS explícitas; wildcard, credenciais
e origens HTTP em produção são rejeitados. Hostname automático Render é
acrescentado com HTTPS. Login, upload e assinatura reais via navegador passaram
com cookies/CSRF; domínio externo não foi testado.

## 16. ALLOWED_HOSTS

Hosts explícitos por ambiente; wildcard, esquema e caminho rejeitados em
produção. RENDER_EXTERNAL_HOSTNAME é acrescentado automaticamente quando o
Render o fornecer. Nenhum domínio futuro ou hostname de serviço foi inventado.

## 17. Logging

Console com nível INFO padrão. Eventos fixos para upload, download/storage,
banco/health e PDF incluem classe de erro; logs de framework são resumidos
por status, classe e módulo/linha. Não registram mensagem crua de exceção,
traceback com valores, URL/token de conferência, base64 ou credenciais.
Access log de Gunicorn desabilitado por conter URLs privadas. Diagnóstico é
mais restrito deliberadamente; consultas de dados sensíveis não devem ser
introduzidas no logging durante manutenção.

## 18. Collectstatic

Executado com sucesso: 133 arquivos existentes conferidos, 371 resultados
pós-processados, sem arquivos privados em static. Backend
CompressedManifestStaticFilesStorage por STORAGES; WhiteNoise serve CSS/JS.
Chromium DEBUG=False confirmou Bootstrap carregado e nenhum erro JavaScript.

## 19. Resultado de migrations

Migrations aplicadas no PostgreSQL novo e nos bancos de teste. Checks finais:
`check`: sem problemas; `makemigrations --check --dry-run`: No changes detected;
`migrate --noinput`: No migrations to apply. Incrementais desta fase:
equipamentos/0004_organization_upload_paths.py e
ordens/0006_private_object_key_length.py (FileFields até 500 caracteres para
namespaces UUID). Nenhuma migration anterior alterada; comparação byte a byte
com ZIP de referência registrada na auditoria de arquivos.

## 20. Quantidade total de testes

89 PostgreSQL aprovados; SQLite explícito: 89 executados, 87 aprovados e dois
concorrentes exclusivos de PostgreSQL ignorados, em 169,953s. Novos: oito de
configuração/logging, três health/HTTPS, cinco storage remoto e dois concorrentes.
Testes anteriores preservados. Não se usa SQLite como prova de PostgreSQL.

## 21. Multiempresa

Testes automatizados de tenants/permissões anteriores passaram no PostgreSQL.
Ensaio HTTPS próximo do real: TECNOLMED e [TESTE] Empresa B, contas comuns
separadas e OS concluídas. Oito requisições cruzadas (OS, foto, assinatura e
PDF, nos dois sentidos) retornaram 404. Storage/PDF/equipamentos também têm
testes remotos de autorização. Nenhum bypass de superuser foi introduzido.

## 22. Upload

Upload do navegador para simulador S3 em HTTPS passou, com chave UUID e leitura
autorizada sem `.path`. Testes verificaram ACL privada no simulador, cliente
novo do storage, download, PDF, falha AccessDenied com resposta 503 genérica e
ausência de registro parcial. Migração testada em dry-run, cópia, reexecução
idempotente e recusa de conteúdo divergente. A privacidade R2 real depende
das configurações do bucket que você ainda criará.

## 23. Assinatura

Mouse, limpar, bloqueio de assinatura vazia, redesenho por eventos touch reais
do Chromium/CDP e finalização passaram nas duas empresas. Imagem, SHA-256 e
digest do snapshot conferidos após restart. Assinaturas antigas não foram
convertidas para S3 nem tiveram hashes recalculados. Dedo/caneta em aparelho
físico ainda exige checklist.

## 24. PDF

Download autorizado passou em DEBUG=False/HTTPS/PostgreSQL/S3. PDFs das duas
empresas renderizados e revisados visualmente (duas páginas cada): branding,
OS, cliente/unidade/equipamento, serviço/peças/técnico, GPS, foto sintética,
responsável, assinatura e hashes legíveis, sem cortes/sobreposição. Empresa B
usa identificação própria. Poppler emitiu avisos de fontes de fallback, mas
texto português e páginas renderizadas foram conferidos. Nenhuma dependência
de caminho local de mídia foi introduzida.

## 25. Restart/redeploy

Processo web HTTPS local foi encerrado/reiniciado, mantendo PostgreSQL e o
processo S3 separado. OS, foto e assinatura continuaram acessíveis; SHA-256 e
digest iguais ao banco e PDF gerável. Ambas as empresas verificadas após
reinício. Isso comprova independência do processo web no ensaio; redeploy e
restart no Render, R2 real e backup/restauração continuam PENDENTES.

## 26. Navegador

Chromium real headless, viewport mobile 390x844/touch e desktop 1365x900.
Login, Home, empresa, entrada/retorno Assistência, início com GPS simulado,
edição, foto, GPS final negado com continuação prevista, conferência, assinatura,
limpeza/validação, touch, finalização/PDF. Sem overflow horizontal mobile e sem
pageerror JavaScript. Segredos/sessões/certificados do ensaio ficaram só em tmp
ignorado, fora do pacote. GPS/câmera não foram declarados testes físicos.

## 27. Celular físico

CHECKLIST_HOMOLOGACAO.md contém as 21 etapas solicitadas, GPS negado/reativado,
foto/câmera, assinatura por dedo, mapa, logout/login, duas empresas, revogações,
restart/redeploy e restauração. Todos os testes físicos estão PENDENTES.

## 28. Variáveis a configurar

Obrigatórias: DEBUG=False, SECRET_KEY forte, DATABASE_URL, UPLOAD_STORAGE=s3,
S3_BUCKET_NAME, S3_REGION_NAME, AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY.
Para R2: S3_ENDPOINT_URL real, região auto e addressing path. Hosts/origens
reais ou hostname automático fornecido pelo Render. SSL do banco True, idade
de conexão 60, logging INFO, workers 2 e timezone preservado. PORT/hostname
são injetados pelo Render; token de sessão só com provedor temporário que o
exija. Tabela completa e fontes de cada valor: DEPLOY_RENDER.md, etapa 5.
.env.example contém campos vazios e padrões seguros, nenhuma credencial real.

## 29. Pendências e ponto de parada

Usuário ainda precisa criar um PostgreSQL e um Web Service Docker no Render,
bucket privado e token S3 no R2, preencher ambiente e executar deploy. Ordem e
configuração detalhadas no guia. Conectividade/provider/backup/domínio externo,
reinício/redeploy Render e celular físico não podem ser aprovados sem isso.
Trabalho encerrado nessa dependência, sem criar outro módulo ou recurso.

## 30. Riscos e limitações

Docker/Compose e Gunicorn Linux não foram executados neste Windows sem Docker;
comandos/checks de Django e o fluxo foram executados diretamente. S3 de bancada
é Moto, não valida particularidades de R2/quotas/latência. PostgreSQL local sem
TLS não comprova conexão TLS Render. `check --deploy --fail-level ERROR` não
teve erros, com W005/W021 mantidos e explicados no guia. Health não verifica
bucket; downloads transitam pelo web, com custo de recursos a medir no plano.
Lock serializa migrations, mas não substitui backup/janela de schema. Migração
de uploads exige janela sem escrita concorrente e origem completa. Versões de
framework existentes foram preservadas por escopo; manutenção de versões é
uma atividade futura separada. Arquivos de teste locais não são dados reais.

O PostgreSQL Free escolhido expira após 30 dias e não tem backup gerenciado;
exportação antes da expiração é necessária para preservar os dados do teste.
O serviço web gratuito dorme após inatividade. Planos e documentação foram
conferidos; nenhuma outra configuração da arquitetura foi alterada por isso.

Código completo em vertyx_homologacao.zip, sem env real, bancos, uploads,
certificados/chaves de bancada, binários PostgreSQL, caches ou ambiente virtual.
AUDITORIA_HOMOLOGACAO_ARQUIVOS.json registra preservação e mudanças; relatórios
anteriores permanecem como registros históricos daquelas fases.
