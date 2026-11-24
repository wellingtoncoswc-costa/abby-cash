#!/usr/bin/env bash
# Aplica todas as migrações num banco novo e roda `alembic check` (modelos == migrações).
set -euo pipefail
cd "$(dirname "$0")/.."
DB="abby_scratch_$$"
PSQL=(docker compose -f ../infra/docker-compose.dev.yml exec -T postgres psql -U abby -d postgres -v ON_ERROR_STOP=1)
"${PSQL[@]}" -c "CREATE DATABASE $DB"
trap '"${PSQL[@]}" -c "DROP DATABASE IF EXISTS $DB"' EXIT
export DATABASE_URL="postgresql+asyncpg://abby:abby@localhost:5432/$DB"
uv run alembic upgrade head
uv run alembic check
