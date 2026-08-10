#!/bin/sh

set -eu

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Ensuring core market catalogue..."
python manage.py seed_market_catalog

case "${RUN_STARTUP_SEEDS:-false}" in
  true|TRUE|1|yes|YES)
    echo "Running initial staging seed commands..."
    python manage.py seed_roles
    python manage.py seed_lookups
    python manage.py seed_sports
    python manage.py seed_dashboard_data
    python manage.py seed_notification_data
    ;;
  *)
    echo "Initial seed commands disabled."
    ;;
esac

echo "Starting Gunicorn on port ${PORT:-8000}..."

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}"
