#!/bin/sh
set -eu
# Aceita tanto tecnolmed.homologation_settings quanto tecnolmed.settings
if [ "${DJANGO_SETTINGS_MODULE:-}" != "tecnolmed.homologation_settings" ] && [ "${DJANGO_SETTINGS_MODULE:-}" != "tecnolmed.settings" ]; then
    echo "Startup recusado: selecione tecnolmed.settings ou tecnolmed.homologation_settings." >&2
    exit 1
fi
exec gunicorn tecnolmed.wsgi:application --config gunicorn.conf.py
