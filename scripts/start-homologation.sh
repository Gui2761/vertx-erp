#!/bin/sh
set -eu
# Explicit homologation entry point. Never calls migrate or seeds data.
if [ "${DJANGO_SETTINGS_MODULE:-}" != "tecnolmed.homologation_settings" ]; then
    echo "Startup recusado: selecione as settings de homologacao." >&2
    exit 1
fi
exec gunicorn tecnolmed.wsgi:application --config gunicorn.conf.py
