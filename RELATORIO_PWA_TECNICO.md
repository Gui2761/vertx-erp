# PWA operacional do TÉCNICO — VERTYX

Entrega local em 06/10/2026. Mesmo ERP e PWA, sem publicação. ADMIN/GESTOR continuam com o ERP completo; TÉCNICO utiliza a Home operacional `/tecnico/` conforme a membership da organização selecionada.

## Comportamento entregue

- Home com minhas OS, meus chamados, atendimentos de hoje, em andamento, atrasados e próximos; botões para atendimento, diagnóstico, fotos, peças, QR e agenda.
- Reutilização dos serviços, modelos e auditoria existentes. OS atribuídas ao técnico principal ou auxiliar ativo; chamados atribuídos e vínculos com OS autorizadas. Não foi criado fluxo novo para assumir chamados sem atribuição.
- Preservação da Jornada Contratual: antes de iniciar a atividade, permanece a projeção de destino e o bloqueio dos detalhes da OS.
- Clientes, unidades, equipamentos, documentos e mídia privada limitados aos vínculos operacionais permitidos. Nenhuma consulta ampliada para outra organização.
- Backend bloqueia URLs administrativas de estoque geral, compras, vendas/PDV, financeiro, bancos, relatórios financeiros, usuários, configurações e administração. Override de capacidade ou perfil global/superusuário não amplia o acesso de uma membership técnica.
- Utilização/devolução de peças exige OS autorizada, usa o fluxo existente de FEFO/auditoria e volta à OS. Sem acesso ao cadastro administrativo de estoque.
- Exportações operacionais existentes das próprias OS foram preservadas; central de relatórios administrativos e exportações financeiras continuam bloqueadas.
- Login, entrada pelo PWA, `/vertyx/`, painel antigo e troca de organização respeitam o perfil atual. A identidade instalada `/tecnico/` foi preservada; novos launches usam `/vertyx/`. Instalações com entrada antiga também respeitam o redirecionamento do servidor.
- Interface com navegação inferior, botões de no mínimo 48 px e CSS exclusivo do técnico. Câmera, GPS, checklist, assinaturas e PDF reutilizam os componentes atuais.
- HTML autenticado e logout usam `private, no-store`; retorno de página pelo histórico revalida no servidor. Service worker armazena somente assets públicos. Aviso de conexão e bloqueio de envio offline não representam uma fila de sincronização.

## Validação automatizada — APROVADA

PostgreSQL sintético local, sem acesso remoto: **471 testes aprovados** em 434.233 s, incluindo **19 testes novos** específicos do técnico. A suíte completa inclui as validações anteriores de concorrência e isolamento.

`python manage.py check`: sem problemas. `python manage.py makemigrations --check --dry-run`: `No changes detected`. JavaScript: `node --check` nos dois scripts alterados. `git diff --check`: aprovado.

Execuções específicas finais também aprovadas: 19 testes do PWA técnico (23,490 s) e 5 testes dos cenários de menu, redirecionamento e health check (3,329 s). Esses testes já integram o total único da suíte completa; as reexecuções não são somadas ao total.

Categorias verificadas:

- Login real e redirecionamento pela membership; perfil global não concede acesso
- Home operacional, chamados e OS atribuídos; técnico auxiliar autorizado
- URLs administrativas GET/POST negadas, inclusive overrides e superusuário com membership técnica
- ADMIN e GESTOR conservam ERP completo
- Troca de conta e organização recalcula perfil; HTML autenticado não armazenado em cache
- Isolamento entre organizações, técnicos, clientes, unidades e equipamentos; QR e mídia privada
- Documentos e campos de upload respeitam os vínculos autorizados
- Peças limitadas à OS autorizada, FEFO e bloqueio de entrada administrativa
- Jornada Contratual mantém bloqueio até o início da atividade
- Fluxo de OS com tentativa de GPS, diagnóstico, serviços, fotos antes/depois, assinaturas e PDF
- Identidade única do PWA e entrada conforme perfil
- Exportação operacional das próprias OS mantida; exportações administrativas negadas

O primeiro ensaio paralelo no Windows não conseguiu transportar o traceback de uma asserção antiga; a execução sequencial identificou os cenários restantes. Expectativas anteriores incompatíveis com a nova navegação técnica foram ajustadas explicitamente, sem eliminar testes e sem relaxar a autorização. O cabeçalho original `no-store` de `/health/` foi preservado após a regressão detectá-lo. Logs esperados de HTTP 503 pertencem a testes que simulam indisponibilidade do health check.

Evidências: `tmp/validation/technician_final_results.json` e os logs `technician_final_0_check.log`, `technician_final_1_makemigrations.log`, `technician_final_2_test.log`. O runner confirma que os arquivos da aplicação permaneceram iguais durante a execução final.

## Validação pela interface — ambiente local sintético

- Home em **320 × 740** e **390 × 844**, sem overflow horizontal (larguras de conteúdo 305 e 375 px, considerando a barra de rolagem).
- OS em ambas as resoluções, navegação operacional e controles de câmera.
- Checklist preenchido e salvo pela interface em 320 px; valor persistido conferido posteriormente em 390 px.
- URLs diretas de Financeiro e Usuários negadas. Troca de ADMIN para TÉCNICO refletida na Home; Dashboard administrativo continua completo.
- Nenhum erro de console observado nas páginas inspecionadas.

Imagens em `tmp/validation/technician-evidence/`: `home-320.png`, `home-390.png`, `os-320.png`, `os-390.png` e `checklist-390.png`.

## Limites e pendências

- Homologar no iPhone físico: abertura pelo ícone instalado, câmera, permissões GPS, assinatura por toque e troca de conta.
- Sem gravação ou fila automática offline: arquitetura atual mantém somente assets públicos e página offline. É necessário reconectar para salvar.
- R2 e ambiente publicado não foram acessados ou testados nesta etapa.

O teste automatizado do fluxo gera GPS com resultado de permissão negada, imagens e assinaturas sintéticas, finaliza a OS e recebe PDF válido. Isso não comprova sensor GPS, câmera ou assinatura por toque no iPhone real. Não foi realizada homologação em produção.

## Arquivos alterados/criados nesta tarefa

- `clientes/views.py`
- `contas/views.py`
- `core/views.py`
- `equipamentos/views.py`
- `gestao/forms.py`
- `gestao/services.py`
- `gestao/tests.py`
- `gestao/views.py`
- `operacao/navigation.py`
- `operacao/permissions.py`
- `operacao/planning.py`
- `operacao/pwa.py`
- `operacao/test_stock.py`
- `operacao/tests.py`
- `operacao/views.py`
- `platform_core/media_views.py`
- `platform_core/middleware.py`
- `platform_core/modules.py`
- `platform_core/views.py`
- `static/js/vertyx.js`
- `static/pwa/sw.js`
- `templates/base.html`
- `templates/operacao/tecnico.html`
- `templates/platform_core/home.html`
- `operacao/technician_access.py`
- `operacao/test_technician_pwa.py`
- `static/css/technician.css`
- `templates/operacao/technician_order.html`

Documentação criada: `RELATORIO_PWA_TECNICO.md` e `VALIDACAO_PWA_TECNICO.json`. Runners, fixtures e capturas locais ficam no diretório ignorado `tmp/validation`; não fazem parte do código publicado. A alteração pré-existente de `templates/operacao/executive.html` foi preservada e não pertence a esta implementação.

## Banco e publicação

**Nenhuma migration criada ou antiga alterada. Nenhuma dependência alterada.** Não houve commit, push, deploy, acesso a produção, alteração de credenciais, Render, PostgreSQL remoto ou R2. Não houve reset/flush manual ou recriação do banco da aplicação. Escritas de interface ocorreram exclusivamente na organização sintética local; a suíte usa bancos de teste Django isolados.

## Correção do menu técnico e links VERTYX — 06/10/2026

**VALIDADO LOCALMENTE; NÃO PUBLICADO.** Suíte completa PostgreSQL: **511/511 testes aprovados**, em 447.153 s. Foram adicionados oito testes e ampliado o teste existente de troca de organização/perfil. Execução direcionada: **63/63**, em 50.205 s; esse total é subconjunto da suíte completa e não deve ser somado a ela. `check` aprovado; `makemigrations --check --dry-run`: `No changes detected`.

- A membership TÉCNICO recebe um ramo exclusivo do template, sem fallback para menus administrativos. Não há itens administrativos renderizados, nem links cinzas/desabilitados. Não foi utilizado CSS/JavaScript para esconder módulos.
- Menu: Meu atendimento / Atender, Minha agenda, Minhas OS, Meus chamados, Ler QR / código, Meu ponto, Alertas / notificações, Conhecimento técnico e Sair. Capacidades e módulos existentes determinam quais links operacionais são renderizados; conhecimento e ponto não aparecem se não autorizados.
- Logo VERTYX e todos os breadcrumbs técnicos apontam diretamente para `/tecnico/`. Não é renderizado “Voltar para VERTYX” nem atalho para `/vertyx/` ou `/assistencia/` na navegação técnica.
- Na seleção de organização, a ação técnica é “Acessar meus atendimentos”. A seleção válida redireciona diretamente para `/tecnico/` quando o ERP está habilitado para a organização e membership; acesso desabilitado não é ampliado.
- Navegação inferior: ATENDER | AGENDA | OS | ALERTAS. ADMIN/GESTOR conservam seu menu completo e seus destinos; VENDEDOR continua destinado ao PDV.
- As regras de autorização do backend, serviços de escopo/OS, isolamento e permissões não foram alteradas. GET/POST administrativos continuam negados, inclusive com override de capacidades ou superusuário global vinculado como técnico.

**VALIDADO PELA INTERFACE EM BANCO SINTÉTICO:** hambúrguer aberto em 390 × 844 e 320 × 844, sem overflow horizontal; links com altura mínima de 48 px; oito opções operacionais e saída acessíveis. Clique no logo permaneceu em `/tecnico/`; entrada pela rota anterior `/vertyx/` voltou para `/tecnico/`; URL financeira direta exibiu acesso restrito. Os quatro atalhos inferiores foram abertos com sucesso. A fixture existente do piloto foi reutilizada em loopback, sem novo seed, migration, alteração de credenciais ou escrita em dados de negócio; autenticação utilizou somente sessões QA locais.

Evidências: `tmp/validation/technician-menu-evidence/menu-tecnico-390x844.jpg`, `menu-tecnico-320x844.jpg`, `interface.json`, `technician_menu_targeted_results.json`, `technician_menu_final_results.json` e respectivos logs.

Arquivos de código alterados nesta correção:

- `operacao/navigation.py`
- `templates/base.html`
- `static/css/technician.css`
- `platform_core/views.py`
- `templates/platform_core/home.html`
- `operacao/test_technician_pwa.py`

Documentação atualizada: `RELATORIO_PWA_TECNICO.md` e `VALIDACAO_PWA_TECNICO.json`. Helpers e evidências permanecem no diretório ignorado `tmp/validation`.

Na primeira rodada, a base descartável de testes previamente usada pela prévia comercial continha dados sintéticos incompatíveis com testes que pressupõem contagens vazias. Foi utilizado um banco de teste exclusivo para cada execução final, sem reset do banco da aplicação. Uma asserção excessivamente ampla sobre “hidden” também foi corrigida: atributos legítimos de acessibilidade/CSRF não representam itens administrativos escondidos. Os testes finais verificam os destinos exatos e a ausência literal dos itens proibidos no HTML. Não foram alterados recursos comerciais para resolver esses problemas de ensaio.

**Nenhuma migration nova; nenhuma migration antiga ou dependência alterada.** Migrations existentes foram aplicadas pelo Django somente na preparação dos bancos sintéticos exclusivos de testes; não houve migration no banco da interface ou produção. Hashes confirmaram preservação dos arquivos de permissões, middleware, serviços de OS, migrations, configurações, Render e service worker durante a validação.

**NÃO VALIDADO NO IPHONE FÍSICO OU EM PRODUÇÃO nesta correção.** Pendente apenas homologação da versão corrigida no aparelho após publicação autorizada. Sem commit, push, deploy, alteração/acesso à infraestrutura remota, R2, banco de produção ou credenciais.
