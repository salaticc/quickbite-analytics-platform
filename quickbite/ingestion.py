"""Load the generated source and publish one verified ClickHouse snapshot."""

from contextlib import closing, suppress
import csv
from datetime import datetime, timezone
from hashlib import sha256
from itertools import batched
import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

import clickhouse_connect
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

from .artifacts import validate_manifest
from .contracts import EVENTS, PG_TABLES, TABLES
from .warehouse import identifier, pg_money, postgres_totals, verify_snapshot

LOG = logging.getLogger(__name__)
BATCH_ROWS = 20_000
STATE = "public.quickbite_batch_state"


def connect():
    load_dotenv(override=False)
    env = os.environ.get
    pg = psycopg.connect(
        host=env("POSTGRES_HOST", "127.0.0.1"), port=env("POSTGRES_PORT", "55432"),
        dbname=env("POSTGRES_DB", "quickbite"), user=env("POSTGRES_USER", "quickbite"),
        password=env("POSTGRES_PASSWORD", "quickbite-dev-postgres"), connect_timeout=10,
        options="-c timezone=UTC", autocommit=True,
    )
    try:
        ch = clickhouse_connect.get_client(
            host=env("CLICKHOUSE_HOST", "127.0.0.1"), port=int(env("CLICKHOUSE_HTTP_PORT", "58123")),
            username=env("CLICKHOUSE_USER", "quickbite"), password=env("CLICKHOUSE_PASSWORD", "quickbite-dev-clickhouse"),
            database=env("CLICKHOUSE_DB", "quickbite"), autogenerate_session_id=False,
        )
    except Exception:
        pg.close()
        raise
    return pg, ch


def ingest(path: Path) -> dict:
    manifest, dataset = validate_manifest(path)
    pg, ch = connect()
    with pg, closing(ch):
        return publish(pg, ch, path, manifest, dataset)


def snapshot_state(pg):
    if pg.execute("SELECT to_regclass(%s)", (STATE,)).fetchone()[0] is None:
        return None
    return pg.execute(f"SELECT dataset, warehouse, report FROM {STATE} WHERE singleton").fetchone()


def verify() -> dict:
    pg, ch = connect()
    with pg, closing(ch), pg.transaction():
        pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        current = snapshot_state(pg)
        if current is None:
            raise ValueError("No QuickBite batch has been published")
        _, warehouse, report = current
        counts = postgres_totals(pg)
        counts[EVENTS.name] = report["rows"][EVENTS.name]
        money = pg_money(pg)
        if report["rows"] != counts or report["payments"] != money:
            raise ValueError("Source counts or payments changed since publication; rerun ingestion")
        verify_snapshot(ch, warehouse, counts, money)
        return report


def publish(pg, ch, path: Path, manifest: dict, dataset: str) -> dict:
    if not pg.execute("SELECT pg_try_advisory_lock(40936, 3)").fetchone()[0]:
        raise RuntimeError("Another QuickBite loader is running in this PostgreSQL database")

    candidate = f"qb_stage3_{uuid4().hex}"
    created = False
    committing = False
    try:
        with pg.transaction():
            pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            pg.execute(f"""CREATE TABLE IF NOT EXISTS {STATE} (
                singleton boolean PRIMARY KEY CHECK (singleton),
                dataset text NOT NULL,
                warehouse text NOT NULL,
                report jsonb NOT NULL
            )""")
            current = snapshot_state(pg)
            if current is None:
                for table in PG_TABLES:
                    load_postgres(pg, table, path)
            elif current[0] != dataset:
                raise ValueError("This PostgreSQL database already owns another dataset. "
                                 "Use a fresh Compose project to load a different manifest.")

            schema = identifier(candidate)
            ch.command(f"CREATE DATABASE {schema} ENGINE = Atomic")
            created = True
            base = identifier(ch.database)
            for table in TABLES:
                ch.command(f"CREATE TABLE {schema}.{table.landing} AS {base}.{table.landing}")

            counts, fingerprints = {}, {}
            for table in PG_TABLES:
                counts[table.name], fingerprints[table.name] = copy_snapshot(pg, ch, candidate, table)
                LOG.info("Staged %s: %s rows", table.landing, counts[table.name])
            if counts != postgres_totals(pg):
                raise ValueError("PostgreSQL snapshot counts changed while staging")
            seed_count, seed_fingerprint = copy_events(ch, candidate, path, manifest)
            counts[EVENTS.name] = seed_count + manifest["tables"][EVENTS.name]["rows"]
            LOG.info("Staged product_events: %s rows", counts[EVENTS.name])
            money = pg_money(pg)
            verify_snapshot(ch, candidate, counts, money)

            signature = {"tables": fingerprints, "events": manifest["tables"][EVENTS.name]["sha256"],
                         "seed_events": seed_fingerprint}
            if current is not None and current[2]["signature"] == signature:
                verify_snapshot(ch, current[1], counts, money)
                ch.command(f"DROP DATABASE {schema} SYNC")
                created = False
                return dict(current[2], reused=True)

            report = {"database": candidate, "rows": counts, "payments": money, "signature": signature}
            pg.execute(f"""INSERT INTO {STATE} (singleton, dataset, warehouse, report) VALUES (true, %s, %s, %s)
                ON CONFLICT (singleton) DO UPDATE SET dataset = EXCLUDED.dataset,
                    warehouse = EXCLUDED.warehouse, report = EXCLUDED.report""",
                       (dataset, candidate, Jsonb(report)))
            committing = True
        LOG.info("Published %s", candidate)
        return dict(report, reused=False)
    except Exception:
        if created and not committing:
            # Publication was never attempted. Preserve the active database on a partial failure.
            try:
                ch.command(f"DROP DATABASE {identifier(candidate)} SYNC")
            except Exception:
                LOG.warning("Could not remove unpublished database %s", candidate, exc_info=True)
        elif committing:
            LOG.warning("Commit result uncertain. Check the active pointer before removing %s", candidate)
        raise
    finally:
        with suppress(psycopg.Error):
            pg.execute("SELECT pg_advisory_unlock(40936, 3)")


def load_postgres(pg, table, path: Path):
    columns = ", ".join(table.columns)
    sql = f"COPY public.{table.name} ({columns}) FROM STDIN (FORMAT CSV, HEADER)"
    try:
        with (path / f"{table.name}.csv").open("rb") as source, pg.cursor() as cursor, cursor.copy(sql) as copy:
            while block := source.read(1024 * 1024):
                copy.write(block)
    except psycopg.Error as error:
        raise ValueError(f"PostgreSQL rejected {table.name}: {error.diag.message_primary}") from error


def copy_snapshot(pg, ch, database, table):
    digest = sha256()
    count = 0
    with pg.cursor(f"export_{table.name}") as cursor:
        cursor.execute(f"SELECT {', '.join(table.columns)} FROM public.{table.name} ORDER BY {', '.join(table.key)}")
        while rows := cursor.fetchmany(BATCH_ROWS):
            ch.insert(table.landing, rows, column_names=table.columns, database=database)
            digest.update(repr(rows).encode("utf-8"))
            count += len(rows)
    return count, digest.hexdigest()


def copy_events(ch, database, path, manifest):
    columns = ", ".join(EVENTS.columns)
    source = f"{identifier(ch.database)}.{EVENTS.name}"
    seed_count = 0
    digest = sha256()
    with ch.query_rows_stream(f"SELECT {columns} FROM {source} ORDER BY event_id") as rows:
        for batch in batched(rows, BATCH_ROWS):
            normalized = [(r[0], r[1], r[2], utc(r[3]), utc(r[4]), *r[5:]) for r in batch]
            ch.insert(EVENTS.name, normalized, column_names=EVENTS.columns, database=database)
            digest.update(repr(normalized).encode("utf-8"))
            seed_count += len(batch)

    loaded = 0
    with (path / "product_events.csv").open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        next(reader)
        for batch in batched(map(event_row, reader), BATCH_ROWS):
            ch.insert(EVENTS.name, batch, column_names=EVENTS.columns, database=database)
            loaded += len(batch)
    if loaded != manifest["tables"][EVENTS.name]["rows"]:
        raise ValueError("Event CSV changed while loading")
    return seed_count, digest.hexdigest()


def event_row(row):
    event, session, name, occurred, ingested, user, restaurant, cart, order, experiment, variant = row
    return (UUID(event), UUID(session), name, utc(datetime.fromisoformat(occurred)),
            utc(datetime.fromisoformat(ingested)), int(user) if user else None,
            int(restaurant) if restaurant else None, UUID(cart) if cart else None,
            int(order) if order else None, experiment or None, variant or None)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
