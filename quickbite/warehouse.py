"""Check a ClickHouse snapshot against PostgreSQL and product-event totals."""

import re

from .contracts import PG_TABLES, TABLES

# PostgreSQL also enforces the composite references in its transactional DDL.
REFERENCES = (
    ("pg_orders", "pg_users", "user_id"),
    ("pg_orders", "pg_restaurants", "restaurant_id"),
    ("pg_payments", "pg_orders", "order_id currency_code"),
    ("pg_payments", "pg_payments", "parent_capture_id:payment_id order_id currency_code provider"),
    ("pg_order_status_history", "pg_orders", "order_id"),
    ("pg_order_status_history", "pg_couriers", "courier_id"),
    ("pg_experiment_assignments", "pg_users", "user_id"),
    ("pg_experiment_assignments", "pg_orders", "qualifying_order_id:order_id user_id"),
    ("pg_restaurant_interventions", "pg_restaurants", "restaurant_id"),
    ("product_events", "pg_users", "user_id"),
    ("product_events", "pg_restaurants", "restaurant_id"),
    ("product_events", "pg_orders", "order_id user_id restaurant_id"),
    ("product_events", "pg_experiment_assignments", "experiment_code user_id variant_seen:variant"),
)


def identifier(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise ValueError(f"Unsupported database identifier: {name!r}")
    return f"`{name}`"


def postgres_totals(pg) -> dict:
    return {t.name: pg.execute(f"SELECT count(*) FROM public.{t.name}").fetchone()[0]
            for t in PG_TABLES}


def pg_money(pg) -> dict:
    rows = pg.execute("""
        SELECT operation_type, count(*), sum(amount_minor), sum(platform_revenue_minor)
        FROM public.payments GROUP BY operation_type
    """).fetchall()
    return {kind: [int(value) for value in values] for kind, *values in rows}


def verify_snapshot(ch, database: str, expected: dict, money: dict) -> None:
    schema = identifier(database)
    for table in TABLES:
        key = ", ".join(table.key)
        rows, unique = ch.query(f"SELECT count(), uniqExact(tuple({key})) "
                                f"FROM {schema}.{table.landing}").first_row
        if rows != expected[table.name] or unique != rows:
            raise ValueError(f"{table.landing}: expected {expected[table.name]} rows, "
                             f"found {rows} rows / {unique} unique keys")

    financial = ch.query(f"""
        SELECT operation_type, count(), sum(toInt128(amount_minor)), sum(toInt128(platform_revenue_minor))
        FROM {schema}.pg_payments GROUP BY operation_type
    """).result_rows
    if {kind: list(values) for kind, *values in financial} != money:
        raise ValueError("ClickHouse payment totals differ from PostgreSQL by operation type")

    for child, parent, fields in REFERENCES:
        pairs = [(value, value) if ":" not in value else value.split(":") for value in fields.split()]
        join = " AND ".join(f"c.{left} = p.{right}" for left, right in pairs)
        nonnull = " AND ".join(f"isNotNull(c.{left})" for left, _ in pairs)
        bad = ch.query(f"SELECT 1 FROM {schema}.{child} AS c LEFT ANTI JOIN {schema}.{parent} AS p "
                       f"ON {join} WHERE {nonnull} LIMIT 1").result_rows
        if bad:
            raise ValueError(f"{child}: broken reference to {parent} on {fields}")

    # Nullable event references need an explicit validity check before the anti-join can skip nulls.
    invalid = ch.query(f"""
        SELECT 1 FROM {schema}.product_events AS e
        LEFT ANTI JOIN {schema}.pg_order_status_history AS s
            ON e.order_id = s.order_id AND e.occurred_at = s.occurred_at AND s.status = 'delivered'
        WHERE e.event_name = 'order_completed' LIMIT 1
    """).result_rows
    if invalid:
        raise ValueError("product_events: completion does not match a delivered status and timestamp")
