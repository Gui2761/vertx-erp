# Consolidação para publicação — VERTYX

Data: 06/10/2026. Publicação autorizada pelo usuário para o serviço existente `vertyx-erp`, repositório `tecnolmedengclinica-spec/vertx-erp`, branch `main`. Base remota preservada: `bb139538daf4bf79af14a22c1a8bea96625982ec`.

## Versão consolidada

Todo o ERP anterior permanece no projeto principal, incluindo assistência, Jornada Contratual, estoque/FEFO, compras, financeiro, PDV e fundação multiempresa. O pacote incorpora as etapas homologadas posteriores: PWA Técnico com navegação exclusivamente operacional e autorização no backend; página comercial pública e catálogo configurável; cadastro central de funcionários e contatos; jornadas visuais/5x2 e escalas; Meu Ponto; solicitação/aprovação/recusa de hora extra, referências históricas, notificações e indicadores. Não foi recriado o projeto ou criado um ERP paralelo.

Relatórios locais das etapas anteriores permanecem como registros históricos de sua validação antes da publicação. Este documento registra a verificação de consolidação posterior à autorização.

## Verificações antes do envio

- Suíte completa: **551/551 testes PostgreSQL aprovados**, 564.861 s.
- Suíte específica RH/jornadas/ponto/hora extra/PWA/segurança: **86/86 aprovados**, 144.599 s; integra o total de 551, sem somar reexecuções.
- `python manage.py check`: sem problemas.
- `python manage.py makemigrations --check --dry-run`: nenhuma alteração pendente.
- Nenhuma migration antiga alterada ou removida; testes de preservação e concorrência incluídos.
- Os 27 arquivos da etapa RH/Ponto coincidem com os hashes homologados.
- Varredura do pacote: sem credenciais reais, arquivos .env privados, chaves, certificados, bancos locais, backups ou diretórios temporários. `.env.example` contém somente configuração de exemplo já versionada.
- Histórico local/remoto alinhado antes do commit; sem reset, force-push ou reescrita de histórico.

A primeira tentativa com banco de testes reutilizado foi interrompida por ausência do tenant de seed exigido por teste antigo de OS; a suíte integral foi repetida em banco sintético novo, exclusivamente no PostgreSQL loopback, e aprovada. Nenhuma mudança de código da aplicação foi necessária. Logs 503 em cenários negativos de health fazem parte dos testes aprovados.

## Migrations do pacote

1. `commercial.0001_initial`: duas tabelas comerciais novas e quatro planos globais; sem criação automática de tenant/assinatura/pagamento.
2. `operacao.0015_funcionario_contato`: campos novos de telefone/e-mail e cópia do contato existente para esses campos.
3. `operacao.0016_hora_extra_aprovacao`: novas referências/solicitações/decisões e constraints; congela referências legadas disponíveis sem alterar marcações/fechamentos originais.

Dependências e ordem validadas no PostgreSQL local. Nenhuma migration nova criada nesta consolidação. Migrations em produção serão conferidas nos logs do deploy; este documento precede o push.

## Serviço e preservação

Render confirmado: `srv-dauq0560tbcc73c81nqg`, Docker Free, raiz do repositório, `./Dockerfile`, branch `main`, auto-deploy On Commit, Health Check Path `/health/`. URL: https://vertyx-erp.onrender.com.

O Dockerfile executa `collectstatic`; o comando existente `scripts/start.sh` executa `migrate_locked --noinput` com lock advisory PostgreSQL e inicia Gunicorn. Não sincronizar o Blueprint histórico `render.yaml`, que descreve o serviço antigo. Não ativar runner/Cron de estoque nesta publicação.

Usar as variáveis existentes, inclusive DATABASE_URL/SECRET_KEY/R2, sem modificá-las. Não recriar PostgreSQL, alterar plano, resetar schema, executar flush, remover registros ou modificar usuários/memberships. O PostgreSQL existente foi localizado no projeto como `vertyx-postgres-homologacao` e estava Available. `/health/` respondeu status ok antes do envio; esse endpoint testa conexão ao banco com SELECT 1.

Contingência já disponível no mesmo pacote: `scripts/start-contingency.sh`, compatível com os models/migrations atuais, sem reversão de schema. Não retornar diretamente ao código fe6c554 após as migrations.

## Validação publicada a seguir

Acompanhar build, collectstatic, migrations, Gunicorn e Live. Conferir health, sessão/login ADMIN, navegação, RH → Funcionários/Jornadas, Meu Ponto e Hora Extra; perfil TÉCNICO/PWA com conta técnica existente preenchida pelo usuário, sem criar usuários ou alterar memberships. Consultas de dados antes/depois limitadas à interface, sem operações de negócio para teste em produção. A evidência final do deploy será registrada localmente após a publicação.
