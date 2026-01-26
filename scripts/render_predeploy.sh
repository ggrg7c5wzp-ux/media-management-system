#!/usr/bin/env sh
set -eu

cd /app/src
python manage.py migrate --noinput
python manage.py collectstatic --noinput
