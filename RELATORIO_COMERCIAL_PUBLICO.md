# VERTYX — experiência comercial pública

Data: 06/10/2026. **VALIDADO LOCALMENTE — 503/503 testes PostgreSQL aprovados; não publicado.** Evidências detalhadas em `VALIDACAO_COMERCIAL_PUBLICO.json`.

## Entrega

Página comercial própria para visitantes anônimos em `/`, página dedicada em `/planos/`, formulário em `/demonstracao/` e `/contato/`, confirmação de envio, suporte, informações comerciais e privacidade. Header e footer responsivos, SEO básico, Open Graph, canonical, favicon e acesso ao login existente por `/login/`.

O visual usa azul/branco, gradientes discretos, espaço em branco, ícones, notebook e celular com capturas reais do produto usando exclusivamente dados sintéticos. Não foi utilizado conteúdo de produção. Os quatro cards destacam Profissional como “Mais escolhido”; os planos ficam empilhados no celular e em quatro colunas no desktop.

| Plano inicial | Preço mensal | Destaque |
| --- | --- | --- |
| Básico | R$ 149 | — |
| Profissional | R$ 249 | Mais escolhido |
| Empresarial | R$ 399 | — |
| Personalizado | Fale conosco | — |

Os preços iniciais foram definidos pelo usuário. Estão no catálogo persistido, não nos templates. Limites de usuários/técnicos são nulos; são exibidos como “A definir na proposta”. O escopo de módulos e suporte também permanece a definir. Não se presume recurso ilimitado nem inclusão de módulos em um plano sem definição comercial.

## Configuração e fluxo comercial

`PlanoComercial` é um catálogo global de marketing, separado dos dados de organizações e das configurações de acesso do ERP. Nome, preço, periodicidade, descrição, usuários, técnicos, recursos, destaque, ordem e ativo podem ser editados no Django Admin existente, exclusivamente por superusuário da plataforma. O administrador de uma organização não pode editar preços globais ou consultar leads de outras empresas.

Configuração: `/admin/commercial/planocomercial/`. Recursos conhecidos usam `INCLUIDO`, `CONSULTA` ou `FUTURO`. Fiscal, gateway e provisionamento/assinatura automática ficam internos como futuros e não são anunciados como implementados. Preço anual explícito e desconto percentual anual estão preparados, com cálculo em Decimal e arredondamento de centavos. Sem condição anual configurada, a página não inventa desconto e informa consulta comercial.

Cada CTA abre o formulário com o plano selecionado. O envio grava `InteresseComercial` com consentimento, versão das informações de privacidade e uma fotografia da oferta no momento do envio. O catálogo pode mudar depois sem modificar essa fotografia. O atendimento é humano, controlado pelo status NOVO/CONTATADO/ENCERRADO em `/admin/commercial/interessecomercial/`.

Há CSRF, token de formulário assinado e vinculado à sessão, validade de duas horas, identificação única para evitar duplicação, campo antispam e limite básico de cinco solicitações por e-mail/hora. Confirmação pública não revela os dados da solicitação. Não existe endpoint público para listar ou recuperar leads. O envio não cria usuário, organização, membership, assinatura, cobrança ou pagamento. Nenhuma mensagem externa é enviada automaticamente.

Essa separação permite uma futura integração comercial explícita sem conceder permissões a partir do catálogo. Não foram implementados contratação, gateway, pagamento, assinatura financeira, emissão fiscal ou provisionamento automático.

## ERP e PWA preservados

Login é o `LoginView` já existente, incluindo `/contas/login/`. Usuários autenticados que acessam `/` seguem para a Home interna. ADMIN/GESTOR mantêm acesso ao ERP; TÉCNICO mantém seu redirecionamento operacional; VENDEDOR/PDV seguem ao PDV pela Home da plataforma e pelo seletor de organização.

O middleware libera somente as rotas comerciais públicas exatas, sem liberar URLs administrativas ou dados internos. Os bloqueios existentes do técnico continuam aplicados às telas internas. A página comercial usa seus próprios templates/CSS/JS e não registra um novo PWA. Manifest, service worker, lógica técnica, autenticação, permissões técnicas, templates operacionais e CSS/JS do ERP não foram modificados nesta etapa; os hashes desses arquivos foram conferidos.

Render, R2, variáveis de ambiente, credenciais, dependências e infraestrutura não foram alterados. Nenhum serviço externo ou banco de produção foi consultado.

## Migration e banco

Nova migration: `commercial/0001_initial.py`. Somente duas tabelas novas (`PlanoComercial`, `InteresseComercial`) e cadastro inicial dos quatro planos globais. Não altera tabelas do ERP, não remove registros, não modifica migrations anteriores, nem provisiona organizações. A função histórica de seed está congelada na própria migration e usa a conexão do schema editor.

A execução foi informada antes de ocorrer e restrita aos bancos descartáveis de testes PostgreSQL em loopback: `test_vertyx_homologation`, `test_vertyx_homologation_1` e `test_vertyx_homologation_2`. Os clones foram preparados para a execução paralela mantendo a mesma migration. Fixtures básicas do catálogo ERP e tenant sintético foram repostas com `get_or_create`, pois testes transacionais anteriores haviam esvaziado essas dependências nos bancos de testes. Não houve flush manual, reset, alteração ou reversão de schema existente.

A base sintética de trabalho `vertyx_homologation` foi consultada apenas para conferência e captura do produto: nenhuma migration comercial aplicada e nenhuma tabela comercial criada nessa base. Os dados de negócio monitorados e todos os arquivos de migrations anteriores foram preservados. A migration continua não aplicada em produção.

## Validações

32 novos testes automatizados comerciais passaram na execução específica. Cobrem página anônima, quatro planos/preços/destaque, configuração e desativação, condições anuais/Decimal, links, login por perfil, isolamento de organizações, bloqueios administrativos, administração global, consentimento/CSRF, idempotência, sessão/token/expiração, antispam, preservação da oferta, escape HTML, ausência de provisionamento e SEO.

`manage.py check` e `manage.py makemigrations --check --dry-run` passaram. A regressão completa PostgreSQL aprovou **503/503 testes, zero falhas e zero erros, em 447,179 segundos**, incluindo os 471 testes anteriores e os 32 novos. O código da aplicação não mudou durante esses comandos. A execução específica aprovou 32/32 testes em 9,823 segundos; esses 32 estão incluídos no total de 503, não são somados novamente. Uma primeira execução específica encontrou cinco falhas de fixture por ausência do catálogo ERP na base de testes previamente esvaziada; a fixture comercial foi corrigida e a execução de 32 testes passou. Os cenários 503 produzidos propositalmente pela suíte de saúde/storage não são falhas da página comercial.

Validação de interface local: Home, planos e formulário em 320, 390, 768 e 1365 px, com largura de documento igual à largura útil em todas as medições (zero overflow horizontal). Foram inspecionadas capturas em cada resolução. Menu móvel abriu e navegou corretamente; seleção de Profissional preencheu plano/periodicidade; formulário foi enviado com dados sintéticos e mostrou confirmação real. Imagens do produto carregaram e não houve erro/warning capturado no console da aba.

Não houve teste físico de iPhone, teste em produção ou alteração da homologação PWA anterior. A homologação em navegador local não substitui aprovação visual/comercial pelo usuário.

Evidências: `tmp/validation/commercial-evidence/`, métricas em `tmp/validation/commercial_responsive.json`, logs e resultados em `tmp/validation/commercial_*`. Prévia local em `http://127.0.0.1:8870/`, exclusivamente no banco de testes. A prévia usa cookies QA próprios, sem misturar a sessão de demonstração com a sessão da aplicação local anterior.

## Pendências antes de divulgar

- Aprovar visualmente esta experiência.
- Definir o escopo e os quantitativos de cada plano, suporte e eventuais condições anuais. Campos indefinidos continuam “A definir”; não se aplicam cotas técnicas ou permissões automaticamente.
- Aprovar e completar os textos institucionais: identificação comercial/controlador, contato oficial, retenção de dados e termos contratuais. As páginas atuais declaram expressamente que são prévias locais para revisão, sem inventar CNPJ, e-mail ou endereço.
- Definir rotina humana para atendimento dos leads. Não há envio de e-mail, campanha ou CRM externo automático; proteção antispam é básica e não foi ensaiada sob tráfego real.
- A referência inicial em `/mnt/data/...` não estava acessível. A referência posteriormente anexada em Downloads foi inspecionada e orienta o ajuste visual descrito ao final deste relatório.

## Arquivos desta etapa

Integrações alteradas: `tecnolmed/settings.py` (somente registro do app), `tecnolmed/urls.py` (rotas públicas), `platform_core/middleware.py` (rotas públicas exatas), `platform_core/views.py` (entrada de vendedor/PDV), `templates/platform_core/home.html` (link do vendedor/PDV no seletor).

Novos arquivos: `commercial/__init__.py`, `apps.py`, `catalog.py`, `models.py`, `forms.py`, `services.py`, `views.py`, `urls.py`, `admin.py`, `tests.py`, `migrations/__init__.py`, `migrations/0001_initial.py`; `templates/commercial/{base,icons,home,plans,pricing,demo,thanks,information,faq,cta}.html`; `static/css/commercial.css`; `static/js/commercial.js`; `static/commercial/{brand.svg,erp-preview.jpg,technician-preview.jpg}`; este relatório e `VALIDACAO_COMERCIAL_PUBLICO.json`.

Ferramentas locais ignoradas pelo Git: `tmp/validation/commercial_run.py`, `commercial_prepare_tests.py`, `commercial_preview.py`, `commercial_inspect.py`, logs, métricas e capturas. Nenhuma credencial foi colocada no código novo ou na documentação; as ferramentas leem a configuração local privada já existente sem imprimir seus valores. Alterações anteriores do PWA e demais etapas foram preservadas, não atribuídas a este escopo.

Sem commit, push, deploy ou publicação. Aguardar autorização após a avaliação visual.

## Ajuste visual solicitado em 06/10/2026

A referência `C:/Users/StartReparos/Downloads/erp vendas de produtos 001TELA ERP.png` foi aberta e inspecionada. A página `/planos/` agora usa cabeçalho branco, hero azul escuro com título e texto próprios, botão verde e notebook do VERTYX. A seção de preços permanece logo abaixo, com o título “Escolha o plano ideal para sua empresa”, quatro cards configuráveis e Profissional destacado por borda/faixa azul e CTA verde. Seguem recursos com checkmarks, FAQ sobre planos/demonstração/contratação/suporte/implantação, CTA final e footer. Nenhum texto, marca, imagem de produto de terceiro, recurso fiscal ou condição comercial da referência foi copiado.

Arquivos deste ajuste: `templates/commercial/base.html` (blocos opcionais de estilo/classe), `templates/commercial/pricing.html`, `templates/commercial/plans.html` (conteúdo condicional somente nesta página) e `static/css/commercial-pricing.css` (novo CSS exclusivo de `/planos/`). A Home mantém a apresentação anterior. Models, services, preços do catálogo, autenticação, permissões, ERP, PWA, PDV e infraestrutura não mudaram. Nenhuma migration adicional. Nenhum commit, push ou deploy.

A suíte de 503 testes registrada acima precede este ajuste estritamente visual. Não foi reexecutada e não houve alteração ou migration de banco nesta etapa. A prévia local foi reiniciada somente para limpar os templates em memória, executando apenas consultas de leitura ao catálogo existente, sem seed ou cadastro.

Capturas finais: `tmp/validation/commercial-visual-homologacao/` — `/planos/` em 1365×768 e 390×844, página inicial em 1365×768 e capturas completas para avaliação de recursos, FAQ e rodapé. Após as capturas finais, nenhuma nova alteração de código. Aprovação visual/comercial e publicação continuam pendentes de autorização.
