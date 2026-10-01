# VERTYX: atualização do ambiente Render existente

01/10/2026. Esta entrega é local. O usuário informou que já existe aplicação funcional no Render. Este guia substitui as orientações anteriores de criar um par Web Service/PostgreSQL; relatórios de fases anteriores são históricos.

Nenhum deploy, commit, push, alteração no Render ou acesso ao banco publicado foi realizado. Não criar outro PostgreSQL, Web Service ou bucket para aplicar esta atualização. Não trocar credenciais existentes.

## Configuração preparada

`render.yaml` mantém o serviço Docker original `tecnolmed-erp`, `plan: free`, health `/health/` e as opções anteriores de aplicação/storage. A declaração `databases` e a referência `fromDatabase` foram removidas. `DATABASE_URL` e `SECRET_KEY` usam `sync: false`, assim como os segredos de storage: nenhum valor real aparece no arquivo. O plano do PostgreSQL existente não é definido nem alterado por este YAML. Dockerfile, Compose, Gunicorn e start permanecem iguais.

O plano Free de Web Service continua listado na [referência oficial Blueprint](https://render.com/docs/blueprint-spec), consultada em 01/10/2026. O Render ignora variáveis `sync: false` ao atualizar serviços existentes. O nome técnico do serviço foi preservado da base local; antes de futura sincronização, confira se corresponde ao serviço existente. Caso não corresponda, interrompa a sincronização e ajuste a associação: não crie uma aplicação duplicada.

## Variáveis existentes a preservar

| Variável | Configuração |
|---|---|
| `DATABASE_URL` | Conexão PostgreSQL já usada pelo serviço, sem substituição |
| `SECRET_KEY` | Valor atual, sem rotação nesta entrega |
| `DATABASE_SSL_REQUIRE` | Configuração TLS atual do PostgreSQL externo |
| `UPLOAD_STORAGE` | `s3` no serviço publicado |
| `S3_BUCKET_NAME` | Bucket privado atual |
| `S3_ENDPOINT_URL` | Endpoint S3 real atual |
| `S3_REGION_NAME` | Região atual do provedor |
| `S3_ADDRESSING_STYLE` | Valor atual (`path` quando configurado para R2) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Credenciais atuais do storage |
| `AWS_SESSION_TOKEN` | Preservar se utilizado pelo provedor |
| `DEBUG` | `False` no ambiente publicado |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Hosts/origens reais atuais |
| `PORT`, `RENDER_EXTERNAL_HOSTNAME` | Gerenciados pelo Render |

Nenhuma variável fiscal nova é obrigatória para iniciar o ERP. Fiscal fica sem emissão até escolher, implementar e validar um adaptador real. Nome e ambiente do provedor são parâmetros por organização; segredos não pertencem ao cadastro nem ao Git. Não há integração de e-mail/WhatsApp/Open Finance ativada.

## Ordem para uma futura atualização, somente após autorização

1. Homologar o ZIP local seguindo `ENTREGA_FINAL.md`, com dados sintéticos e banco separado. Não apontar ensaios para o banco publicado.
2. Conferir os Web Service, PostgreSQL e bucket atuais da aplicação; guardar sua identificação em local privado. Nenhum recurso novo é necessário.
3. Fazer backup consistente do banco e arquivos privados, e testar restauração em ambiente isolado. Preservar migrations anteriores.
4. Revisar código/diff e novas migrations. Conferir nome do serviço do YAML e ausência de provisionamento de banco.
5. Somente após decisão do usuário, preparar commit/branch e atualizar o serviço existente. Esta etapa não foi executada.
6. Manter conexão PostgreSQL, chaves e parâmetros do storage atuais. Não colar `.env.example` sobre o ambiente e não gerar nova `SECRET_KEY`.
7. O build Docker instala requirements e executa `collectstatic`; o start executa `migrate_locked --noinput` com advisory lock antes de Gunicorn. Não executar `makemigrations`, `flush`, `--fake`, reset ou remoção de volumes no ambiente publicado.
8. Verificar health, login, organização/ERP, perfis, arquivos, assinatura/PDF, estoque, financeiro, portal e calendário. Conferir logs sem publicar segredos.
9. Homologar instalação PWA/GPS/câmera em celular físico com o domínio HTTPS real. Free tem limitações de disponibilidade; veja [limites oficiais](https://render.com/docs/free).

## Integrações pendentes

Fiscal: escolher provedor e adapter em `fiscal/providers/`, obter documentação, credenciais sandbox por organização, dados do emitente/contador, certificado quando exigido, municípios/serviços, tributação de produtos, consulta/cancelamento e idempotência. Validar primeiro em sandbox; habilitar produção só após autorização. Não fornecer tokens por chat.

Notificações: alertas internos funcionam por eventos e atualização manual/comando `atualizar_alertas`. Agendamento real e provedores de e-mail/WhatsApp dependem de configuração futura. Não foi criado worker nem presumido serviço pago.
