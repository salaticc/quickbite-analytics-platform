SELECT version() AS clickhouse_version;

SELECT throwIf(count() != 9, 'Landing schema is incomplete')
FROM system.tables
WHERE database = currentDatabase()
  AND name IN (
      'pg_users', 'pg_restaurants', 'pg_couriers', 'pg_orders', 'pg_payments',
      'pg_order_status_history', 'pg_experiment_assignments', 'pg_restaurant_interventions',
      'product_events'
  );

SELECT throwIf(count() != 6 OR uniqExact(event_id) != 6, 'Missing or duplicate product seed events')
FROM product_events
WHERE event_id IN (
    '20000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000005', '20000000-0000-0000-0000-000000000006'
);

SELECT throwIf(
    count() != 5
    OR argMin(event_name, occurred_at) != 'search'
    OR argMax(event_name, occurred_at) != 'order_completed'
    OR countIf(event_name = 'order_completed' AND order_id = 101 AND restaurant_id = 1) != 1
    OR uniqExactIf(cart_id, event_name IN ('add_to_cart', 'checkout', 'order_completed')) != 1,
    'Seed funnel does not lead to order 101 through one cart'
)
FROM product_events
WHERE session_id = '30000000-0000-0000-0000-000000000001';

CREATE TEMPORARY TABLE smoke_insert (id UInt8, label String) ENGINE = Memory;
INSERT INTO smoke_insert VALUES (1, 'quickbite');
SELECT throwIf(countIf(id = 1 AND label = 'quickbite') != 1, 'Insert/read-back failed')
FROM smoke_insert;
SELECT 'ClickHouse smoke passed';
