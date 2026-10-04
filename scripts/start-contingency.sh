#!/bin/sh
set -eu
# Mesmo pacote, models e migrations. Nenhuma reversão do schema.
export DJANGO_SETTINGS_MODULE=tecnolmed.contingency_settings
exec /bin/sh /app/scripts/start.sh
