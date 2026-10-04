# Plano de atualização — Bloco 1

Data: 02/10/2026. Base: Django 5.0.9, Python 3.12 no Docker, PostgreSQL 16, django-storages/boto3 para R2, ReportLab/Pillow para PDFs e PWA com assets locais.

## Escolha e limites

A linha escolhida para avaliação é **Django 5.2 LTS**, que suporta Python 3.12 e PostgreSQL 16 e recebe atualizações de segurança até abril de 2028. Usar o patch publicado dessa linha, confirmando sua disponibilidade no índice oficial. Não saltar para Django 6 nem substituir os componentes de storage/PDF/PWA.

Fontes: [versões suportadas](https://www.djangoproject.com/download/), [notas de 5.2](https://docs.djangoproject.com/en/5.2/releases/5.2/), [guia de atualização](https://docs.djangoproject.com/en/5.2/howto/upgrade-version/).

## Execução e critérios

1. Preservar o ambiente anterior e testar em virtualenv separado, sem copiar o projeto.
2. Resolver as dependências pelo PyPI oficial e verificar `pip check`. Manter os pins das bibliotecas existentes se forem compatíveis; registrar qualquer alteração transitiva.
3. Adaptar somente incompatibilidades comprovadas; não alterar migrations antigas. Mudanças de models do Bloco 1 usam migrations aditivas.
4. Executar os testes atuais e os novos testes PostgreSQL: isolamento, concorrência, dinheiro Decimal, FEFO, pagamentos, snapshots/PDF, uploads/storage S3 simulado, PWA e planejamento.
5. Executar `check`, `makemigrations --check --dry-run`, ensaio de migrations incremental local com dados sintéticos e `collectstatic` em diretório de validação local.
6. Aceitar o pin novo somente com os critérios aprovados. Em caso de incompatibilidade não resolvida, preservar o pin anterior e documentar o impedimento; não publicar uma atualização não validada.

Não alterar Render, banco publicado, R2 real ou credenciais. Não fazer commit, push ou deploy. Compatibilidade validada em testes locais não substitui homologação futura no ambiente publicado. A revisão desta etapa avalia resolução/compatibilidade; não afirma auditoria completa de CVEs de todas as bibliotecas.

## Ambiente avaliado

O patch disponível confirmado no PyPI oficial foi **5.2.17**. O único pin direto modificado em `requirements.txt` é `Django==5.2.17`, anteriormente `5.0.9`. Python 3.12.14 e PostgreSQL 16.15 locais são utilizados para a validação. O ambiente anterior permanece preservado.

Mantidos: psycopg2-binary 2.9.9, django-storages 1.14.6, boto3 1.40.54, botocore 1.40.76, s3transfer 0.14.0, ReportLab 4.2.5, Pillow 10.4.0, WhiteNoise 6.7.0, Gunicorn 22.0.0, openpyxl 3.1.5, django-htmx 1.19.0 e demais pins existentes. `requirements-test.txt` não mudou: Moto continua 5.1.13.

A comparação dos pacotes comuns aos dois ambientes encontrou asgiref 3.12.1 e sqlparse 0.6.0 inalterados. Além do Django, somente **python-dotenv 1.2.3 → 1.2.4** mudou na resolução do ambiente de testes; é uma dependência transitiva de pydantic-settings/Moto server e não foi adicionada aos requisitos de produção. Inventário completo e relatório pip ficam em `tmp/validation/`, ignorado pelo Git.

Resultado da resolução: `pip check` aprovado. A aceitação final, testes e limitações estão registrados em `BLOCO1_ESTABILIZACAO.md` e `VALIDACAO_BLOCO1.json`.
