#!/usr/bin/env bash
set -euo pipefail

python /app/src/manage.py migrate --noinput
python /app/src/manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-10000}
