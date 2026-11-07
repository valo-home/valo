#!/usr/bin/env bash
# Прогон тестов сервера. Поднимает временные PostgreSQL и Redis в контейнерах valo-test-*,
# база и Redis отдельные от сред demo и real, порты только на 127.0.0.1
set -euo pipefail
cd "$(dirname "$0")/.."

PG_PORT="${VALO_TEST_PG_PORT:-55439}"
REDIS_PORT="${VALO_TEST_REDIS_PORT:-56389}"

if ! docker ps --format '{{.Names}}' | grep -qx valo-test-postgres; then
  docker rm -f valo-test-postgres >/dev/null 2>&1 || true
  docker run -d --name valo-test-postgres -e POSTGRES_USER=valo -e POSTGRES_PASSWORD=valo -e POSTGRES_DB=valo_test \
    -p "127.0.0.1:${PG_PORT}:5432" --tmpfs /var/lib/postgresql/data postgres:17-alpine >/dev/null
fi
if ! docker ps --format '{{.Names}}' | grep -qx valo-test-redis; then
  docker rm -f valo-test-redis >/dev/null 2>&1 || true
  docker run -d --name valo-test-redis -p "127.0.0.1:${REDIS_PORT}:6379" redis:8-alpine >/dev/null
fi
until docker exec valo-test-postgres pg_isready -U valo -d valo_test >/dev/null 2>&1; do sleep 1; done

export DATABASE_URL="postgresql+asyncpg://valo:valo@127.0.0.1:${PG_PORT}/valo_test"
export REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/15"
uv run pytest "$@"
