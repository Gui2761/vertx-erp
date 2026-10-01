FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/staticfiles /app/media
# Build sem conexão com banco/bucket; static não contém uploads.
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Usado quando o container roda sozinho (ex.: Render), sem docker-compose.
# As migrations já vêm versionadas no repositório — não geramos migrations
# em produção, só aplicamos (migrate) as que já existem.
CMD ["sh","-c","python manage.py migrate && python manage.py createsuperuser --noinput || true; exec gunicorn tecnolmed.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
