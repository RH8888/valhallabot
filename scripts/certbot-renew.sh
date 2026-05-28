#!/usr/bin/env sh
set -eu

CERTBOT_DOMAIN="${SSL_DOMAIN:-}"
if [ ! -S /var/run/docker.sock ]; then
  echo "[certbot-renew] /var/run/docker.sock is missing; cannot manage valhalla-app container."
  exit 1
fi

APP_CONTAINER="${APP_CONTAINER_NAME:-valhalla-app}"
EMAIL_FLAG="--register-unsafely-without-email"
if [ -n "${LETSENCRYPT_EMAIL:-}" ]; then
  EMAIL_FLAG="--email ${LETSENCRYPT_EMAIL}"
fi

while true; do
  CERTBOT_DOMAIN="${SSL_DOMAIN:-}"
  if [ -z "${CERTBOT_DOMAIN}" ]; then
    echo "[certbot-renew] SSL_DOMAIN is not set; sleeping before next check."
    sleep "${CERTBOT_RENEW_INTERVAL_SECONDS:-43200}"
    continue
  fi

  echo "[certbot-renew] Running renewal check for ${CERTBOT_DOMAIN} at $(date -u +'%Y-%m-%dT%H:%M:%SZ')"

  certbot certonly \
    --non-interactive \
    --agree-tos \
    ${EMAIL_FLAG} \
    --standalone \
    -d "${CERTBOT_DOMAIN}" \
    --keep-until-expiring \
    --pre-hook "docker stop ${APP_CONTAINER}" \
    --post-hook "docker start ${APP_CONTAINER}" \
    --deploy-hook "docker restart ${APP_CONTAINER}"

  sleep "${CERTBOT_RENEW_INTERVAL_SECONDS:-43200}"
done
