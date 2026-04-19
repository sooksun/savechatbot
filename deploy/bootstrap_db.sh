#!/usr/bin/env bash
# Create the savechatbot database in the existing MariaDB container, then create tables and seed.
# Usage: bash deploy/bootstrap_db.sh
set -euo pipefail

MARIADB_CONTAINER="${MARIADB_CONTAINER:-mariadb}"
DB_USER="${DB_USER:-root}"
DB_PASSWORD="${DB_PASSWORD:-l6-lyo9N}"
DB_NAME="${DB_NAME:-savechatbot}"

echo "==> Creating database '$DB_NAME' (if not exists) inside container '$MARIADB_CONTAINER'..."
docker exec -i "$MARIADB_CONTAINER" mariadb -u"$DB_USER" -p"$DB_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
SQL

echo "==> Creating tables via SQLAlchemy (inside the app container)..."
docker compose -f docker-compose.prod.yml run --rm app python -m app.init_db

echo "==> Seeding default categories..."
docker exec -i "$MARIADB_CONTAINER" mariadb -u"$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
  < migrations/001_init.sql || true

echo "==> Applying enrichment migration (ocr_text column)..."
docker exec -i "$MARIADB_CONTAINER" mariadb -u"$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
  < migrations/002_enrich.sql || true

echo "==> Done."
