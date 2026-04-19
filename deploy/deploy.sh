#!/usr/bin/env bash
# Build & (re)start the savechatbot app container.
# Run from /DATA/AppData/www/savechatbot
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. cp .env.production.example .env and fill in values." >&2
  exit 1
fi

mkdir -p storage/media
chmod -R 775 storage

echo "==> Building image..."
docker compose -f docker-compose.prod.yml build

echo "==> Starting container..."
docker compose -f docker-compose.prod.yml up -d

echo "==> Status:"
docker compose -f docker-compose.prod.yml ps

echo
echo "Logs:    docker compose -f docker-compose.prod.yml logs -f app"
echo "Health:  curl http://127.0.0.1:9920/health"
