from collections import Counter, defaultdict
from datetime import datetime
import csv
from dataclasses import replace
from zoneinfo import ZoneInfo
from uuid import UUID

import pytest

from quickbite.artifacts import validate_manifest
from quickbite.config import PROFILES
from quickbite.contracts import BUSINESS_ZONE, EXPERIMENT, ID_BASE, TABLES
from quickbite.generator import generate, variant_for


def read_tables(path):
    tables = {}
    for table in TABLES:
        with (path / f"{table.name}.csv").open(newline="", encoding="utf-8") as file:
            tables[table.name] = list(csv.DictReader(file))
    return tables


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "data"
    generate(PROFILES["smoke"], path)
    return path, read_tables(path)


def test_same_seed_reproduces_business_rows(demo, tmp_path):
    path, _ = demo
    same, different = tmp_path / "same", tmp_path / "different"
    generate(PROFILES["smoke"], same)
    generate(replace(PROFILES["smoke"], seed=43), different)
    original, digest = validate_manifest(path)
    assert validate_manifest(same)[1] == digest
    assert validate_manifest(different)[1] != digest
    assert original["tables"]["orders"]["rows"] == PROFILES["smoke"].orders
    assert original["tables"]["product_events"]["rows"] == PROFILES["smoke"].events


def test_manifest_rejects_modified_file(tmp_path):
    dataset = tmp_path / "broken"
    generate(PROFILES["smoke"], dataset)
    with (dataset / "users.csv").open("a", encoding="utf-8") as file:
        file.write("tampered\n")
    with pytest.raises(ValueError, match="users: CSV checksum"):
        validate_manifest(dataset)


def test_primary_keys_and_references(demo):
    _, tables = demo
    for table in TABLES:
        keys = [tuple(row[k] for k in table.key) for row in tables[table.name]]
        assert len(set(keys)) == len(keys), table.name
        if table.key[0].endswith("_id") and table.name != "product_events":
            assert all(int(key[0]) >= ID_BASE for key in keys)
    users = {u["user_id"]: u for u in tables["users"]}
    restaurants = {r["restaurant_id"]: r for r in tables["restaurants"]}
    orders = {o["order_id"]: o for o in tables["orders"]}
    statuses = {s["order_id"]: s for s in tables["order_status_history"] if s["status"] == "delivered"}
    assignments = {(a["experiment_code"], a["user_id"]): a for a in tables["experiment_assignments"]}
    for o in orders.values():
        assert users[o["user_id"]]["registered_at"] <= o["placed_at"]
        assert restaurants[o["restaurant_id"]]["opened_at"] <= o["placed_at"]
        assert o["currency_code"] == "RUB"
    for event in tables["product_events"]:
        assert UUID(event["event_id"]).int >> 120 == 0xAA
        assert event["occurred_at"] <= event["ingested_at"]
        if event["user_id"]:
            assert users[event["user_id"]]["registered_at"] <= event["occurred_at"]
        if event["restaurant_id"]:
            assert event["restaurant_id"] in restaurants
        if event["event_name"] == "order_completed":
            order = orders[event["order_id"]]
            assert event["occurred_at"] == statuses[event["order_id"]]["occurred_at"]
            assert (event["restaurant_id"], event["user_id"]) == (order["restaurant_id"], order["user_id"])
        if event["event_name"] == "experiment_exposed":
            a = assignments[(event["experiment_code"], event["user_id"])]
            assert a["variant"] == event["variant_seen"] and a["assigned_at"] <= event["occurred_at"]


def test_status_lifecycle_and_assignment(demo):
    _, tables = demo
    histories = defaultdict(list)
    couriers = {r["courier_id"]: r for r in tables["couriers"]}
    for status in tables["order_status_history"]:
        histories[status["order_id"]].append(status)
    terminal_states = Counter()
    for order in tables["orders"]:
        rows = histories[order["order_id"]]
        assert [int(r["sequence_no"]) for r in rows] == list(range(1, len(rows) + 1))
        times = [r["occurred_at"] for r in rows]
        assert times == sorted(times) and order["placed_at"] < times[0]
        assert all(r["occurred_at"] <= r["recorded_at"] for r in rows)
        stages = [r["status"] for r in rows if r["status"] != "courier_assigned"]
        assert stages in (["accepted", "cancelled"], ["accepted", "ready", "picked_up", "delivered"])
        terminal_states[stages[-1]] += 1
        assigned = None
        for row in rows:
            if row["courier_id"]:
                assert couriers[row["courier_id"]]["onboarded_at"] <= row["occurred_at"]
            if row["status"] == "courier_assigned":
                assigned = row["courier_id"]
            if row["status"] == "picked_up":
                assert row["courier_id"] == assigned
    assert terminal_states["delivered"] and terminal_states["cancelled"]


def test_partial_payments_and_refunds(demo):
    _, tables = demo
    charges = {r["payment_id"]: r for r in tables["payments"] if r["operation_type"] == "capture"}
    totals = defaultdict(lambda: [0, 0])
    charge_counts = Counter(c["order_id"] for c in charges.values())
    orders = {o["order_id"]: o for o in tables["orders"]}
    for operation in tables["payments"]:
        assert orders[operation["order_id"]]["placed_at"] <= operation["posted_at"]
        amount, revenue = map(int, (operation["amount_minor"], operation["platform_revenue_minor"]))
        assert 0 <= revenue <= amount and amount > 0 and operation["currency_code"] == "RUB"
        if operation["operation_type"] == "refund":
            charge = charges[operation["parent_capture_id"]]
            assert charge["order_id"] == operation["order_id"] and charge["posted_at"] < operation["posted_at"]
            totals[charge["payment_id"]][0] += amount
            totals[charge["payment_id"]][1] += revenue
    assert max(charge_counts.values()) > 1 and totals
    for key, (amount, revenue) in totals.items():
        assert amount <= int(charges[key]["amount_minor"])
        assert revenue <= int(charges[key]["platform_revenue_minor"])


def test_ab_assignments_are_stable_and_qualify_on_first_delivery(demo, tmp_path):
    _, tables = demo
    alternate = tmp_path / "different"
    generate(replace(PROFILES["smoke"], seed=73), alternate)
    runs = []
    for dataset in (tables, read_tables(alternate)):
        by_order = {o["order_id"]: o["user_id"] for o in dataset["orders"]}
        by_user = defaultdict(list)
        for row in dataset["order_status_history"]:
            if row["status"] == "delivered":
                by_user[by_order[row["order_id"]]].append((row["occurred_at"], row["order_id"]))
        variants = {}
        for a in dataset["experiment_assignments"]:
            user = a["user_id"]
            first_at, first_id = min(by_user[user])
            assert a["qualifying_order_id"] == first_id and a["assigned_at"] > first_at
            assert a["experiment_code"] == EXPERIMENT and a["variant"] == variant_for(int(user))
            variants[user] = a["variant"]
        assert set(variants.values()) == {"treatment", "control"}
        runs.append(variants)
    shared = runs[0].keys() & runs[1].keys()
    assert shared and all(runs[0][user] == runs[1][user] for user in shared)


def test_did_pre_post_boundary_and_matched_restaurants(demo):
    _, tables = demo
    zone = ZoneInfo(BUSINESS_ZONE)
    grouped = {r["restaurant_id"]: r for r in tables["restaurant_interventions"]}
    assert Counter(r["study_group"] for r in grouped.values()) == {"control": 4, "treatment": 4}
    date_cutoffs = {r["comparison_start_on"] for r in grouped.values()}
    assert len(date_cutoffs) == 1
    cutoff = next(iter(date_cutoffs))
    for restaurant in tables["restaurants"][::2]:
        key = restaurant["restaurant_id"]
        other = str(int(key) + 1)
        assert grouped[key]["study_group"] != grouped[other]["study_group"]
    for row in grouped.values():
        if row["study_group"] == "treatment":
            started = datetime.fromisoformat(row["actual_started_at"]).astimezone(zone)
            assert started.date().isoformat() == cutoff and started.hour == started.minute == 0
        else:
            assert not row["actual_started_at"]
    actual = Counter()
    for order in tables["orders"]:
        date = datetime.fromisoformat(order["placed_at"]).astimezone(zone).date().isoformat()
        actual[(grouped[order["restaurant_id"]]["study_group"], date >= cutoff)] += 1
    assert len(actual) == 4 and all(actual.values())
