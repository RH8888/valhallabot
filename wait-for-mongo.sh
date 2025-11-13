#!/usr/bin/env bash
set -e

: "${MONGODB_HOST:=mongodb}"
: "${MONGODB_PORT:=27017}"

echo "⏳ Waiting for MongoDB at $MONGODB_HOST:$MONGODB_PORT ..."
for i in {1..60}; do
  if nc -z "$MONGODB_HOST" "$MONGODB_PORT" 2>/dev/null; then
    echo "✅ MongoDB is up."
    exit 0
  fi
  sleep 1
done

echo "❌ MongoDB did not become ready in time."
exit 1
