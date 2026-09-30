#!/bin/sh
set -eu
# Nunca gera migrations. O lock PostgreSQL serializa processos concorrentes.
python manage.py migrate_locked --noinput
exec gunicorn tecnolmed.wsgi:application --config gunicorn.conf.py
