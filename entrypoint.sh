#!/bin/sh
set -e

python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --worker-class gthread --threads 8 \
    --timeout 120 --access-logfile - --error-logfile -
