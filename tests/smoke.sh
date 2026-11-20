#!/usr/bin/env bash
set -euo pipefail
export MSYS2_ARG_CONV_EXCL='*'

case "${1:-}" in
  '') replay=false ;;
  --replay) replay=true ;;
  *) printf 'Usage: bash tests/smoke.sh [--replay]\n' >&2; exit 2 ;;
esac

postgres() {
  docker compose exec -T postgres sh -ec '
    export PGPASSWORD="$POSTGRES_PASSWORD"
    exec psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -v ON_ERROR_STOP=1 "$@"
  ' sh "$@"
}

clickhouse() {
  docker compose exec -T clickhouse sh -ec '
    exec clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
      --database "$CLICKHOUSE_DB" --multiquery "$@"
  ' sh "$@"
}

smoke() {
  postgres -f /quickbite-tests/smoke.sql
  clickhouse --queries-file /quickbite-tests/smoke.sql
}

smoke
if "$replay"; then
  postgres -f /docker-entrypoint-initdb.d/010_schema.sql -f /docker-entrypoint-initdb.d/020_seed.sql
  clickhouse --queries-file /quickbite-init/010_landing.sql
  clickhouse --queries-file /quickbite-init/020_seed.sql
  smoke
fi
