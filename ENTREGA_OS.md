# Entrega da base operacional de OS — 30/09/2026

O projeto original foi extraído de `tecnolmed_erp_etapa1.zip` para esta pasta.
A pasta de trabalho continha somente `.git`, sem arquivos de aplicação rastreados.
O ZIP foi a referência para a auditoria; não houve recriação do Django, exclusão
de migrations, reset de banco, push, deploy ou desenvolvimento de VERTYX.

## 1. Estado encontrado antes das alterações

| Área | Implementação real no pacote |
|---|---|
| Apps | `contas`, `clientes`, `equipamentos`, `core` |
| Usuários | `Usuario`, baseado em `AbstractUser`, perfis ADMIN/GESTOR/TECNICO/ESTOQUE/FINANCEIRO |
| Técnicos | `Tecnico`, ficha profissional com vínculo opcional a usuário, registro profissional e custo/hora |
| Clientes | `Cliente`, `ContatoCliente`, `Unidade` |
| Equipamentos | `Equipamento`, `CategoriaEquipamento`, cliente/unidade, patrimônio, série, manutenção e QR Code |
| Views/forms | Listagem, detalhe, criação e edição de clientes, unidades e equipamentos; gestão de usuários/técnicos; login/logout; painel |
| URLs | `/`, `/contas/`, `/clientes/`, `/equipamentos/`, `/admin/` |
| Templates | `base.html`, paginação, login, painel e cadastros existentes |
| Migrations | `0001_initial.py` de contas/clientes/equipamentos; core sem tabelas |
| Autenticação | Sessões Django, usuário customizado, login obrigatório nas telas; middleware CSRF |
| Permissões | Usuários para ADMIN; técnicos para ADMIN/GESTOR; cadastros de cliente/equipamento permitem edição a qualquer autenticado no código original |
| Estáticos | CSS próprio; Bootstrap/ícones/HTMX externos |
| PostgreSQL | `DATABASE_URL` ou variáveis POSTGRES; host padrão `db` do Docker |
| Render | Blueprint Docker + PostgreSQL; migrate/collectstatic/Gunicorn no Dockerfile; proxy HTTPS e cookies seguros com DEBUG=False |
| Testes | Nenhum teste automatizado existente |

## 2–3. Existente e ausente

Os cadastros e relações acima já existiam e foram preservados. Não havia app,
model, view, form, URL, template ou implementação parcial de OS. Também não havia
início/finalização, geolocalização, assinatura, fotos de OS, PDF de OS ou auditoria.
As fotos existentes pertenciam somente ao cadastro de equipamento. Não havia
estoque/peças; peças de OS foram implementadas como descrição e quantidades em
texto, sem inventar integração financeira ou movimentação de estoque.
Nenhum banco, imagem de logomarca ou arquivo de mídia real estava no ZIP.

## 4. Arquivos criados

- `ordens/__init__.py`, `apps.py`, `models.py`, `forms.py`, `services.py`.
- `ordens/views.py`, `urls.py`, `admin.py`, `storage.py`, `reports.py`, `tests.py`.
- `ordens/migrations/__init__.py`, `0001_initial.py`, `0002_localizacao_geo_resultado_coerente_and_more.py`.
- `ordens/templatetags/__init__.py`, `ordens_format.py`.
- `templates/ordens/lista.html`, `form.html`, `detalhe.html`, `resumo.html`, `localizacao.html`, `geo_form.html`, `conferencia.html`.
- `static/ordens/atendimento.js`, `assinatura.js`.
- `static/vendor/bootstrap.min.css`, `bootstrap.bundle.min.js`, `README.md`.
- `tecnolmed/test_settings.py`.
- `tests/prepare_browser.py`, `browser_flow.cjs`, `photo_sample.png`, `verify_source.py`.
- Este relatório e `AUDITORIA_ARQUIVOS.json`, contendo comparação por SHA-256 com o ZIP.
- `.gitignore` na raiz da pasta de trabalho, para ignorar o ambiente virtual e artefatos de validação.

Os caminhos listados sem prefixo são relativos a esta pasta `tecnolmed_erp`.
Ambiente virtual, bancos de validação, fotos de teste e arquivos gerados não entram
no pacote de código.

## 5. Arquivos existentes modificados

| Arquivo | Alteração |
|---|---|
| `tecnolmed/settings.py` | App ordens, diretório privado e configuração de logomarca |
| `tecnolmed/urls.py` | Inclusão de `/ordens/` |
| `requirements.txt` | ReportLab 4.2.5 para PDF |
| `equipamentos/views.py` | Login no endpoint de unidades; entrada inválida retorna lista vazia |
| `templates/base.html` | Menu de OS ativo; Bootstrap da mesma versão servido localmente |
| `templates/core/painel.html` | Link para o módulo disponível |
| `static/css/estilo.css` | Formulários, cartões, fotos, assinatura e áreas de toque responsivas |
| `docker-compose.yml` | Volume privado persistente para fotos de OS |
| `.env.example` | Configurações opcionais de arquivos privados e logomarca |
| `.gitignore` | Arquivos privados e artefatos de validação |
| `README.md` | Aviso com o estado atualizado e referência a esta entrega |
| `DEPLOY_RENDER.md` | Persistência privada, homologação e configuração da OS |

## 6–7. Models

Criados: `OrdemServico`, `Localizacao`, `Foto`, `Conferencia`, `Assinatura`,
`Auditoria`. `Imutavel` é uma base abstrata, sem tabela.

Nenhum model anterior foi modificado. As novas FKs usam os cadastros existentes e
`PROTECT`, preservando referências históricas. Número de OS usa a chave primária
gerada pelo banco; há também código UUID único. Uma OS tem revisão e ciclo para
controlar edição concorrente e reaberturas.

## 8. Migrations

`ordens/0001_initial` cria somente as seis novas tabelas e a unicidade da assinatura
por OS/ciclo. `ordens/0002` acrescenta restrições para coordenadas coerentes,
precisão não negativa e um único início por OS/ciclo. As três migrations originais
foram preservadas byte a byte. Não há operações de exclusão ou reset.

## 9. URLs

Novo namespace `ordens`: lista, criar, detalhe, editar, iniciar, foto_adicionar,
foto, preparar, conferencia, finalizar, reabrir, assinatura_imagem e pdf.
Todas sob `/ordens/`; ações que alteram estado exigem POST. PDF e assinatura
incluem a identificação da versão assinada, preservando comprovantes antigos.
URLs anteriores foram mantidas.

## 10. Templates

Sete templates novos de OS listados acima. Apenas base e painel anteriores
foram ajustados. O formulário de atendimento do técnico expõe diagnóstico,
serviço, peças e observações; relações cadastrais são administradas por
administrador/gestor. A lista do técnico mostra somente suas OS.

## 11. Funcionalidades

- OS integrada a cliente, unidade opcional, equipamento e ficha de técnico.
- Criação, listagem, detalhe, edição, início, fotos, conferência e finalização.
- GPS solicitado uma vez no início e novamente ao preparar a finalização;
  `maximumAge: 0`, sem rastreamento contínuo.
- Latitude, longitude, precisão, usuário e horário do servidor; falhas distintas
  para recusa, indisponibilidade, timeout e falta de suporte.
- Falha de localização permite continuar mediante botão explícito, sem coordenadas.
- Início e final ficam em eventos separados; todas as tentativas são preservadas.
- Links HTTPS de mapa na OS e na consulta administrativa.
- Fotos novas com identificadores próprios, descrição, autor e horário; câmera
  sugerida por `capture="environment"`. Fotos são normalizadas para JPEG, sem EXIF,
  com limite de entrada de 10 MB, 25 milhões de pixels e dimensão final de 2000 px.
- Conferência mostra os dados cadastrais, serviço, peças, fotos, técnico, datas e GPS.
- Canvas com Pointer Events, área de toque, limpeza e nova assinatura antes de confirmar.
- Nome, cargo, confirmação de recebimento, imagem e data da assinatura vinculados
  à cópia imutável conferida. O horário de conclusão do serviço é o da preparação
  da conferência; a confirmação/assinatura tem horário próprio.
- PDF paginado com dados conferidos, fotos, assinatura, localizações, identificação
  profissional e hashes de integridade. O PDF foi renderizado e inspecionado.
- Reabertura com justificativa cria novo ciclo, mantém assinaturas/PDFs anteriores
  e exige novo atendimento/conferência/assinatura.

## 12. Segurança e integridade

Administrador/gestor podem gerenciar as OS; técnico acessa e opera apenas OS
vinculadas à sua ficha. Estoque/financeiro não acessam OS. As verificações ocorrem
no backend, também nas URLs de imagem/PDF. Login, CSRF e restrições de método
estão ativos. O admin de OS/históricos é somente leitura; reabertura ocorre pelo
fluxo auditado.

Transações e `select_for_update` serializam as operações de uma OS no PostgreSQL.
A revisão evita sobrescrever uma edição feita em outra sessão. O token de
conferência é assinado, vinculado a usuário/OS e expira em 30 minutos. Ao finalizar,
o backend compara revisão, ciclo e SHA-256 de todo o conteúdo conferido, incluindo
os dados dos cadastros relacionados e a relação de fotos. Alterações exigem nova
conferência. Assinatura vazia, arquivo inválido e dupla finalização são rejeitados.

Registros históricos não têm edição/exclusão nas interfaces; `save`, `delete`,
`update` e `bulk_update` também bloqueiam alterações comuns pelo ORM. Não existe
proteção contra um operador que altere diretamente o banco/arquivos fora da
aplicação. O PDF verifica hashes do snapshot, assinatura e fotografias e recusa
arquivo ausente ou corrompido. A assinatura é eletrônica desenhada, sem certificado
digital ou validação externa de identidade.

Fotos ficam fora de MEDIA_ROOT público; assinatura e snapshot ficam no banco.
Auditoria registra usuário, horário, ação e diferenças anterior/posterior. Não
registra senhas, cookies ou segredos. Cadastro original de clientes/equipamentos
mantém a política de edição por qualquer autenticado; mudar essa política geral
não foi incluído nesta etapa. Alterar esses cadastros não muda uma versão assinada.

## 13–15. Testes, comandos e resultados

Ambiente local: Python 3.12 do runtime, venv nesta pasta de trabalho e versões
originais de requirements. O alias `python` do Windows não executava; foi usado
o executável real da venv. Instalação de dependências foi autorizada após bloqueio
de rede no sandbox.

Antes das alterações:

| Comando | Resultado |
|---|---|
| `manage.py check` | Sem problemas |
| `manage.py makemigrations --check --dry-run` com configuração original | Falhou ao conectar ao PostgreSQL `db`; driver apresentou UnicodeDecodeError na mensagem localizada |
| Mesmo comando com `DATABASE_URL=sqlite:///audit_baseline.sqlite3` | No changes detected |
| `manage.py test` | 0 testes existentes |

Depois das alterações:

```powershell
# Na pasta do projeto, usando o Python da venv do workspace:
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=tecnolmed.test_settings
..\.venv\Scripts\python.exe manage.py migrate --settings=tecnolmed.test_settings --noinput
..\.venv\Scripts\python.exe manage.py test --settings=tecnolmed.test_settings
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Resultados: check sem problemas; nenhuma migration pendente de geração;
migrations aplicadas no SQLite isolado; **34 testes aprovados**; collectstatic
com WhiteNoise/manifest de produção aprovado. Uma falha durante a implementação
por referências de sourcemap do Bootstrap foi corrigida removendo somente esses
comentários dos arquivos vendorizados. O aviso inicial de ausência de staticfiles
foi resolvido executando collectstatic.

Os testes abrangem criação, leitura, início, GPS permitido/recusado/indisponível,
coordenadas inválidas, fotos, diagnóstico/serviço, conferência, assinatura vazia,
confirmação obrigatória, finalização, dupla submissão, bloqueio de alteração,
reabertura, versões antigas, PDF, integridade, auditoria, clientes/equipamentos
existentes, OS sem GPS/assinatura, CSRF, login, permissões por URL, admin e ORM.

Também foram executados `makemigrations ordens`, um fluxo real em Chromium
headless com Playwright e viewport 390×844, screenshots de mobile/desktop e
renderização do PDF com Poppler. O navegador validou início com GPS simulado,
upload de foto, edição, GPS final recusado, conferência, assinatura, limpar,
bloquear assinatura vazia, refazer, finalizar e download do PDF. Não houve erros
JavaScript ou overflow horizontal. Screenshots/PDF de teste ficam em
`tmp/validation/`, fora do pacote. Os avisos de fontes auxiliares do Poppler não
afetaram a legibilidade das páginas, conferidas visualmente.

Para repetir o navegador, primeiro aplique as migrations de test_settings e execute
`tests/prepare_browser.py`; inicie `runserver 127.0.0.1:8765` com test_settings.
Execute `node tests/browser_flow.cjs` com Playwright instalado. Opcionalmente
configure PLAYWRIGHT_MODULE e BROWSER_EXECUTABLE. Isso cria somente dados de teste
no banco isolado. Nunca use test_settings em produção.

## 16. Limitações e implantação

- PostgreSQL/Docker não estão disponíveis neste ambiente. Os testes e migrate
  ocorreram em SQLite; a concorrência por lock de linha e o deploy devem ser
  validados com PostgreSQL em homologação. Nenhum banco real foi modificado.
- O ZIP não contém a logomarca oficial. O PDF usa marca textual TECNOLMED;
  `TECNOLMED_LOGO_PATH` permite configurar PNG/JPEG da marca verdadeira.
- O blueprint Render original não possui disco persistente. Configure armazenamento
  privado persistente e backups antes de guardar fotos reais; detalhes em
  DEPLOY_RENDER.md. Não foi contratado plano nem publicado o projeto.
- Peças são registro textual, pois estoque ainda não existe. Não há anexos genéricos
  de documentos neste módulo, apenas fotos.
- JavaScript e conexão são necessários para o fluxo de GPS/canvas; não há operação
  offline. Ícones e HTMX anteriores ainda usam CDN; os componentes de layout
  Bootstrap e o JavaScript operacional da OS são locais.
- Celular físico, GPS real, câmera, caneta e toque não foram usados. O navegador
  automatizado valida lógica/UI, sem comprovar a integração do hardware.

## 17. Checklist manual no celular

1. Em homologação HTTPS, entre como técnico vinculado à ficha e abra Minhas OS.
2. Inicie uma OS permitindo GPS; confira coordenadas, precisão, usuário, horário e mapa.
3. Em outra OS, recuse GPS e pressione continuar; confirme ausência de coordenadas.
   Repita com GPS indisponível/timeout quando possível.
4. Registre diagnóstico, serviço e peças; abra a câmera, capture duas fotos e
   confirme que ambas aparecem e nenhuma anterior desaparece.
5. Prepare a finalização e permita/recuse GPS novamente; confira que a localização
   inicial foi preservada e que todas as informações/fotos estão corretas.
6. Preencha responsável/cargo. Assine com o dedo, limpe, refaça, gire o aparelho
   e teste mouse/caneta se disponíveis. Tente confirmar uma área vazia.
7. Confirme recebimento e finalize; baixe/abra o PDF e confira marca, textos,
   fotos, assinatura, horários, localizações e paginação.
8. Tente voltar/repetir o envio, editar e trocar a assinatura; deve ser bloqueado.
9. Entre como outro técnico e tente as URLs de detalhe, edição, foto, assinatura
   e PDF daquela OS; o backend deve negar acesso.
10. Como administrador/gestor, reabra com justificativa, altere o atendimento e
    finalize novamente. Verifique auditoria e os dois comprovantes preservados.
11. No PostgreSQL, teste duas sessões iniciando/finalizando/editando a mesma OS
    para validar os locks reais e mensagens de edição concorrente.
12. Reinicie o serviço de homologação e confirme que fotos/PDF continuam acessíveis
    no armazenamento persistente configurado.

## 18. Encerramento

Etapa operacional implementada no projeto e entregue para validação. VERTYX,
multi-tenant, planos, financeiro, IA e integrações futuras não foram iniciados.
