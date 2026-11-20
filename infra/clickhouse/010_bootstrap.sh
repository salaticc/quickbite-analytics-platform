#!/usr/bin/env bash
# The official image sources non-executable init scripts during temporary startup.
(
  set -euo pipefail
  clickhouse-client --host 127.0.0.1 --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
    --database "$CLICKHOUSE_DB" --multiquery < /quickbite-init/010_landing.sql
  clickhouse-client --host 127.0.0.1 --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
    --database "$CLICKHOUSE_DB" --multiquery < /quickbite-init/020_seed.sql
)
