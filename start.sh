#!/usr/bin/env bash
set -e

db_backend="${DATABASE_BACKEND:-${DB_BACKEND:-mysql}}"

case "${db_backend,,}" in
  mongo|mongodb)
    if [ -x /app/wait-for-mongo.sh ]; then
      /app/wait-for-mongo.sh
    fi
    ;;
  mysql|*)
    /app/wait-for-mysql.sh
    ;;
esac

service="${SERVICE:-app}"

if [ "$service" = "app" ]; then
  cert_args=()
  worker_args=()

  if [ -n "$SSL_CERT_PATH" ] && [ -n "$SSL_KEY_PATH" ]; then
    cert_args=(--ssl-certfile "$SSL_CERT_PATH" --ssl-keyfile "$SSL_KEY_PATH")
  fi

  if [ -n "$WORKERS" ]; then
    worker_args=(--workers "$WORKERS")
  fi

  exec uvicorn api.main:app --host "${FLASK_HOST:-0.0.0.0}" --port "${FLASK_PORT:-5000}" \
    "${cert_args[@]}" "${worker_args[@]}"
else
  exec python -m "$service"
fi
