# RH — cadastro central de funcionários e jornadas

Data: 06/10/2026. Entrega local, aguardando homologação do usuário.

## Fluxo concluído

RH → Funcionários → Novo funcionário → dados, trabalho, acesso, jornada e informações técnicas → Salvar.

A mesma ficha cria ou vincula uma conta e Membership, seleciona um perfil existente e, para TÉCNICO, cria/reaproveita a ficha operacional. Cargo e perfil são independentes. Duplicidade de pessoa, conta e matrícula é rejeitada. O salvamento é atômico e auditado. Na edição, a identidade da conta permanece vinculada, preservando histórico.

A jornada pode ser selecionada ou criada na ficha, por grade de segunda a domingo. O botão aplica horário aos dias úteis; fim de semana inicia como Folga e pode ser configurado. O armazenamento reutiliza JornadaTrabalho.semana; nenhum editor JSON é exibido. A tela RH → Jornadas também utiliza a grade. Meu Ponto utiliza a mesma jornada.

Somente ADMIN concede/altera perfil e acesso, conforme a autorização anterior de usuários. GESTOR/RH continuam com o cadastro RH autorizado; não recebem poderes de concessão. ADMIN/GESTOR mantêm ERP, VENDEDOR/PDV mantêm o fluxo exclusivo, FINANCEIRO suas permissões, TÉCNICO a navegação operacional. CPF não foi incluído porque os modelos atuais não o suportam.

Telefone/e-mail são locais à organização no Funcionario; edições não alteram os contatos globais de uma conta compartilhada. Campos e históricos profissionais do Técnico existente são preservados/reaproveitados.

## Validação

551/551 testes PostgreSQL aprovados (581.030 s), incluindo os 511 anteriores e 40 novos. Direcionados: 86/86 (128.848 s). `check`, `makemigrations --check --dry-run`, sintaxe JavaScript e `git diff --check` aprovados.

18 testes novos de cadastro: criação completa, login, vínculos, edição, duplicidade, validação de jornadas, virada de dia, isolamento, permissões, rollback transacional, concorrência PostgreSQL e migration com dados anteriores. O cadastro com nova senha foi validado automaticamente com credencial sintética; o navegador validou vínculo de conta existente, sem criar/alterar credencial.

Pela interface local: funcionário criado com técnico existente, nova jornada 07:30–12:00 / 13:00–17:00, edição de cargo persistida, um único Funcionario e Tecnico, 510 minutos previstos e fim de semana de folga. Meu Ponto/PWA Técnico funcionaram com esses vínculos.

Capturas: desktop 1365 × 768, celular 390 × 844 e verificação de 320 px. Sem overflow horizontal da ficha. As capturas finais da grade mostram uma prévia não salva de segunda jornada; a primeira jornada foi efetivamente criada e validada.

## Migration e arquivos

`operacao.0015_funcionario_contato`: adiciona somente telefone/e-mail e copia os contatos disponíveis para os campos novos. Validada/aplicada apenas em bancos PostgreSQL sintéticos de teste. Não aplicada em produção. Migrations anteriores não foram alteradas.

Arquivos de cadastro: employee_forms.py, employee_services.py, workforce_models.py, workforce_views.py, test_employee_central.py, migration 0015; templates employee_form.html, employee_field.html, schedule_grid.html e rh.html; static/css/employee.css e static/js/employee.js. Lista completa e hashes em VALIDACAO_RH_PONTO.json.

## Evidências e pendências

- [Ficha desktop](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/employee-central-evidence/ficha-desktop-1365x768.jpg)
- [Ficha mobile](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/employee-central-evidence/ficha-mobile-390x844.jpg)
- [Grade mobile](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/employee-central-evidence/jornada-mobile-390x844.jpg)
- [Ficha completa desktop](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/employee-central-evidence/ficha-desktop-full.jpg)
- [Ficha completa mobile](C:/Users/StartReparos/Documents/ChatGPT/saas vertyx/tecnolmed_erp/tmp/validation/employee-central-evidence/ficha-mobile-full.jpg)

Corrigidos durante a validação: formulário com conta inválida/duplicada tentava validar FK ausente; campo obrigatório de nova jornada oculta bloqueava edição no navegador. Sem falhas pendentes nos testes finais.

VALIDADO AUTOMATICAMENTE / VALIDADO PELA INTERFACE / VALIDADO EM BANCO SINTÉTICO. NÃO VALIDADO EM PRODUÇÃO nem iPhone físico. Homologação visual e física do usuário pendentes. Nenhum commit, push, deploy, acesso à produção ou alteração de Render/R2/credenciais.
