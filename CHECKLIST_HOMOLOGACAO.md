# Checklist em infraestrutura real

Executar após DEPLOY_RENDER.md. Registrar data, build, aparelho, sistema,
navegador e resultado. Chromium mobile com GPS simulado não substitui celular
físico, câmera, permissões do sistema ou coordenadas reais.

## Celular físico: 21 etapas

1. Login por HTTPS com conta comum e membership ativo.
2. Conferir Home VERTYX e organização selecionada.
3. Entrar no ERP Assistência habilitado para empresa e usuário.
4. Abrir OS atribuída ao técnico, com cliente/unidade/equipamento corretos.
5. Iniciar atendimento uma vez; conferir bloqueio do segundo início.
6. Autorizar GPS no navegador/sistema.
7. Conferir coordenadas, precisão e horário do evento inicial.
8. Tirar/selecionar foto pelo campo, enviar e visualizar autenticado.
9. Preencher diagnóstico.
10. Preencher serviço e peças, salvar e conferir valores.
11. Abrir conferência, revisar conteúdo, preencher nome/cargo do responsável.
12. Assinar com dedo, observando ajuste do canvas e rolagem da tela.
13. Limpar; conferir canvas branco e bloqueio de assinatura vazia.
14. Assinar novamente com dedo e marcar confirmação.
15. Finalizar; conferir bloqueio de edição e histórico preservado.
16. Conferir GPS final do fluxo, resultado/precisão/horário.
17. Abrir PDF: empresa, OS, cliente, unidade, equipamento, serviço, técnico,
    GPS, foto, responsável, assinatura e evidências de integridade.
18. Abrir localização no mapa, conferir ponto e retorno ao ERP.
19. Sair pelo logout.
20. Entrar novamente e selecionar a mesma empresa.
21. Conferir persistência de OS, foto, assinatura e geração do PDF.

## GPS negado

Em outra OS, negar GPS inicial/final. Conferir mensagem/ação para continuar com
localização não obtida, evento NEGADA e ausência de coordenadas inventadas.
Reautorizar no navegador/sistema e testar em nova OS. Não há rastreamento
contínuo.

## Duas empresas e permissões

Criar organização B identificada como teste, dados próprios, Assistência
habilitada, membership e usuário separados da TECNOLMED. Concluir OS em cada
empresa. PDF B deve conter dados B. Guardar URLs de OS/foto/assinatura/PDF B e
abrir autenticado como A: todas devem bloquear (404). Repetir B contra A e
tentar também cliente, equipamento, manual/QR e formulário com FK de B.

Testar separadamente usuário inativo, membership inativo, organização suspensa,
OrganizationERP e MembershipERP desabilitados. A próxima requisição bloqueia
ERP/arquivos. Reativar só no contexto correto. Técnico não atribuído não atende
nem baixa evidências. Superuser sem membership não acessa ERP. Não usar uma
conta superuser para representar todos os perfis.

## Restart, redeploy e recuperação

- Guardar IDs e conferir hashes/snapshot antes do restart.
- Reiniciar Web Service no Render e conferir OS, foto, assinatura e PDF.
- Fazer redeploy do mesmo código e repetir a conferência/login.
- Conferir R2 privado, sem r2.dev ou domínio público.
- Em ambiente isolado, testar storage indisponível: resposta genérica, sem
  secrets na tela/log e sem foto registrada sem upload.
- Conferir health 200 em operação e 503 em falha controlada de banco.
- Fazer backup e restauração conjunta em outro ambiente, repetindo amostras.

Não alterar snapshots/recalcular hashes antigos para acomodar erro. Marcar
APROVADA, FALHOU ou PENDENTE com evidências. Infraestrutura externa e celular
físico estão PENDENTES nesta entrega.
