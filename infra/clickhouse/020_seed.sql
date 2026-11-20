-- The image runs this on initialization. Manual replay uses the same fixed IDs and one writer.
INSERT INTO product_events (
    event_id, session_id, event_name, occurred_at, ingested_at, user_id,
    restaurant_id, cart_id, order_id, experiment_code, variant_seen
)
SELECT event_id, session_id, event_name, occurred_at, occurred_at + INTERVAL 1 SECOND,
       user_id, restaurant_id, cart_id, order_id, experiment_code, variant_seen
FROM values(
    'event_id UUID, session_id UUID, event_name String, occurred_at DateTime64(6, \'UTC\'), user_id Nullable(Int64), restaurant_id Nullable(Int64), cart_id Nullable(UUID), order_id Nullable(Int64), experiment_code Nullable(String), variant_seen Nullable(String)',
    ('20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'search', '2026-01-03 09:54:00', NULL, NULL, NULL, NULL, NULL, NULL),
    ('20000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000001', 'restaurant_view', '2026-01-03 09:55:00', NULL, 1, NULL, NULL, NULL, NULL),
    ('20000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000001', 'add_to_cart', '2026-01-03 09:56:00', 1, 1, '40000000-0000-0000-0000-000000000001', NULL, NULL, NULL),
    ('20000000-0000-0000-0000-000000000004', '30000000-0000-0000-0000-000000000001', 'checkout', '2026-01-03 09:59:00', 1, 1, '40000000-0000-0000-0000-000000000001', NULL, NULL, NULL),
    ('20000000-0000-0000-0000-000000000005', '30000000-0000-0000-0000-000000000001', 'order_completed', '2026-01-03 10:30:00', 1, 1, '40000000-0000-0000-0000-000000000001', 101, NULL, NULL),
    ('20000000-0000-0000-0000-000000000006', '30000000-0000-0000-0000-000000000002', 'experiment_exposed', '2026-01-03 10:35:00', 1, NULL, NULL, NULL, 'repeat-v1', 'treatment')
)
WHERE event_id NOT IN (SELECT event_id FROM product_events);
