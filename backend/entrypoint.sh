#!/bin/sh
set -eu
python manage.py migrate --noinput --database=default
if [ "${WMS_MODE:-mock}" = "mock" ] && [ -n "${DEMO_USERNAME:-}" ] && [ -n "${DEMO_PASSWORD:-}" ]; then
    python manage.py create_demo_user
fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 30 --access-logfile - --error-logfile -
