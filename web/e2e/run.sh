#!/usr/bin/env bash
# E2E contra backend local descartável: banco próprio, Redis DB 13, portas livres. Precisa de postgres/redis do dev.
set -euo pipefail
cd "$(dirname "$0")/../.."
DB=abby_e2e_$$
PSQL="docker exec abby-cash-dev-postgres-1 psql -U abby -d postgres -qc"
free() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])'; }
API_PORT=$(free); WEB_PORT=$(free)
export DATABASE_URL="postgresql+asyncpg://abby:abby@localhost:5432/$DB" REDIS_URL="redis://localhost:6379/13" ENV=dev JWT_SECRET=e2e-secret-not-for-prod-0123456789
docker exec abby-cash-dev-redis-1 redis-cli -n 13 flushdb >/dev/null
$PSQL "CREATE DATABASE $DB"
cleanup() { kill ${API_PID:-} ${WEB_PID:-} 2>/dev/null || true; $PSQL "DROP DATABASE IF EXISTS $DB WITH (FORCE)"; }
trap cleanup EXIT
(cd backend && uv run alembic upgrade head >/dev/null 2>&1)
mapfile -t CODES < <(cd backend && PYTHONPATH=. uv run python ../web/e2e/seed.py 3)
(cd backend && uv run uvicorn app.main:app --port "$API_PORT" >/tmp/e2e-api.log 2>&1) & API_PID=$!
(cd web && API_URL="http://localhost:$API_PORT" npx vite --port "$WEB_PORT" --strictPort >/tmp/e2e-web.log 2>&1) & WEB_PID=$!
for _ in $(seq 60); do curl -sf "http://localhost:$WEB_PORT/health" >/dev/null && break; sleep 1; done
cd web && E2E_BASE_URL="http://localhost:$WEB_PORT" E2E_INVITE_1="${CODES[0]}" E2E_INVITE_2="${CODES[1]}" E2E_INVITE_3="${CODES[2]}" npx playwright test "$@"
