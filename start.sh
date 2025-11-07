#!/usr/bin/env bash
set -e

/app/wait-for-mysql.sh

service="${SERVICE:-app}"

normalize_base_path() {
  local value="${1:-/}"
  if [[ "$value" != /* ]]; then
    value="/$value"
  fi
  if [[ "$value" != "/" ]]; then
    value="${value%/}"
  fi
  printf '%s' "$value"
}

if [ -z "$PUBLIC_BASE_URL" ]; then
  base_path="$(normalize_base_path "$DASHBOARD_BASE_URL")"
  host_port="${DASHBOARD_PORT:-4173}"
  public_url="http://localhost:${host_port}"
  if [ "$base_path" != "/" ]; then
    public_url="${public_url}${base_path}"
  fi
  export PUBLIC_BASE_URL="$public_url"
fi

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
