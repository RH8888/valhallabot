#!/usr/bin/env sh
set -eu

CERTBOT_DOMAIN="${SSL_DOMAIN:-}"
WEBROOT_PATH="${CERTBOT_WEBROOT_PATH:-/var/www/certbot}"
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

  if [ -d "${WEBROOT_PATH}" ]; then
    echo "[certbot-renew] Using webroot challenge at ${WEBROOT_PATH}"
    certbot certonly \
      --webroot \
      -w "${WEBROOT_PATH}" \
      --non-interactive \
      --agree-tos \
      ${EMAIL_FLAG} \
      -d "${CERTBOT_DOMAIN}" \
      --keep-until-expiring
  else
    echo "[certbot-renew] Webroot path ${WEBROOT_PATH} not found; running standard certbot renew"
    certbot renew \
      --non-interactive \
      --no-random-sleep-on-renew
  fi

  sleep "${CERTBOT_RENEW_INTERVAL_SECONDS:-43200}"
done
