"""Exercise the real PostgreSQL and ClickHouse stack, including partial failure."""

from contextlib import closing
import json
import os
from time import perf_counter

import pytest

from quickbite.artifacts import validate_manifest
from quickbite.config import PROFILES
from quickbite.generator import generate
from quickbite import ingestion
from quickbite.warehouse import postgres_totals, verify_snapshot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("QUICKBITE_INTEGRATION") != "1", reason="requires fresh Compose databases"),
]


def test_atomic_ingestion_replay_and_reconciliation(tmp_path, monkeypatch):
    path = tmp_path / "smoke"
    start = perf_counter()
    generate(PROFILES["smoke"], path)
    generation_seconds = perf_counter() - start
    manifest, dataset = validate_manifest(path)

    pg, ch = ingestion.connect()
    with pg, closing(ch):
        source_before = postgres_totals(pg)
        assert ingestion.snapshot_state(pg) is None, "integration test requires a fresh Stage 2 stack"

        def staged_databases():
            return ch.query("SELECT name FROM system.databases WHERE startsWith(name, 'qb_stage3_')").result_rows

        before = staged_databases()
        real_copy = ingestion.copy_snapshot

        def fail_after_writing(pg, ch, database, table):
            result = real_copy(pg, ch, database, table)
            if table.name == "orders":
                raise RuntimeError("forced failure after four tables have been staged")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(ingestion, "copy_snapshot", fail_after_writing)
            with pytest.raises(RuntimeError, match="forced failure"):
                ingestion.publish(pg, ch, path, manifest, dataset)
        assert ingestion.snapshot_state(pg) is None
        assert postgres_totals(pg) == source_before and staged_databases() == before

        start = perf_counter()
        first = ingestion.ingest(path)
        ingest_seconds = perf_counter() - start
        start = perf_counter()
        second = ingestion.ingest(path)
        replay_seconds = perf_counter() - start
        assert not first["reused"] and second["reused"]
        assert first["database"] == second["database"]
        assert first["rows"] == second["rows"] and first["payments"] == second["payments"]

        for table, rows_before in source_before.items():
            assert first["rows"][table] == rows_before + manifest["tables"][table]["rows"]
        assert first["rows"]["product_events"] == 6 + manifest["tables"]["product_events"]["rows"]
        assert set(first["payments"]) == {"capture", "refund"}
        assert ingestion.verify()["database"] == first["database"]
        active_databases = staged_databases()
        assert len(active_databases) == len(before) + 1

        with monkeypatch.context() as patch:
            patch.setattr(ingestion, "copy_snapshot", fail_after_writing)
            with pytest.raises(RuntimeError, match="forced failure"):
                ingestion.publish(pg, ch, path, manifest, dataset)
        assert ingestion.snapshot_state(pg)[1] == first["database"]
        assert staged_databases() == active_databases
        verify_snapshot(ch, first["database"], first["rows"], first["payments"])

    print("STAGE3_SMOKE", json.dumps({
        "generated": {name: entry["rows"] for name, entry in manifest["tables"].items()},
        "published": first["rows"],
        "generation_seconds": round(generation_seconds, 3),
        "ingest_seconds": round(ingest_seconds, 3),
        "replay_seconds": round(replay_seconds, 3),
        "database_reused": second["reused"],
    }, sort_keys=True))
