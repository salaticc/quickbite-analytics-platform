BEGIN;

INSERT INTO users (user_id, registered_at, acquisition_channel)
VALUES (1, '2026-01-01 09:00:00+00', 'organic'),
       (2, '2026-01-01 10:00:00+00', NULL)
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO restaurants (restaurant_id, city_code, time_zone, opened_at)
VALUES (1, 'MOW', 'Europe/Moscow', '2025-12-01 09:00:00+00'),
       (2, 'MOW', 'Europe/Moscow', '2025-12-01 09:00:00+00')
ON CONFLICT (restaurant_id) DO NOTHING;

INSERT INTO couriers (courier_id, onboarded_at)
VALUES (1, '2025-12-10 09:00:00+00'), (2, '2025-12-12 09:00:00+00')
ON CONFLICT (courier_id) DO NOTHING;

INSERT INTO orders (
    order_id, user_id, restaurant_id, placed_at, promised_delivery_at,
    city_code_at_order, time_zone_at_order, delivery_distance_m, currency_code, items_gross_minor
)
VALUES (101, 1, 1, '2026-01-03 10:00:00+00', '2026-01-03 10:35:00+00', 'MOW', 'Europe/Moscow', 2200, 'RUB', 100000),
       (102, 2, 2, '2026-01-03 11:00:00+00', '2026-01-03 11:40:00+00', 'MOW', 'Europe/Moscow', 2600, 'RUB', 90000),
       (103, 1, 1, '2026-01-08 10:00:00+00', '2026-01-08 10:45:00+00', 'MOW', 'Europe/Moscow', 3400, 'RUB', 120000),
       (104, 2, 2, '2026-01-08 11:00:00+00', NULL, 'MOW', 'Europe/Moscow', NULL, 'RUB', 70000)
ON CONFLICT (order_id) DO NOTHING;

INSERT INTO payments (
    payment_id, order_id, provider, provider_operation_id, operation_type,
    parent_capture_id, posted_at, currency_code, amount_minor, platform_revenue_minor
)
VALUES (201, 101, 'demo', 'capture-101', 'capture', NULL, '2026-01-03 10:01:00+00', 'RUB', 110000, 18000),
       (202, 102, 'demo', 'capture-102', 'capture', NULL, '2026-01-03 11:01:00+00', 'RUB', 99000, 16000),
       (203, 103, 'demo', 'capture-103', 'capture', NULL, '2026-01-08 10:01:00+00', 'RUB', 130000, 22000)
ON CONFLICT (payment_id) DO NOTHING;

INSERT INTO payments (
    payment_id, order_id, provider, provider_operation_id, operation_type,
    parent_capture_id, posted_at, currency_code, amount_minor, platform_revenue_minor
)
VALUES (204, 103, 'demo', 'refund-103', 'refund', 203, '2026-02-01 12:00:00+00', 'RUB', 20000, 3000)
ON CONFLICT (payment_id) DO NOTHING;

INSERT INTO order_status_history (
    status_event_id, order_id, sequence_no, status, occurred_at, recorded_at, courier_id, transport_mode_at_pickup
)
SELECT event_id, order_id, seq, status, occurred_at, occurred_at + interval '1 second', courier_id, mode
FROM (VALUES
    (301, 101, 1, 'accepted',         TIMESTAMPTZ '2026-01-03 10:02:00+00', NULL, NULL),
    (302, 101, 2, 'courier_assigned', TIMESTAMPTZ '2026-01-03 10:04:00+00', 1, NULL),
    (303, 101, 3, 'ready',            TIMESTAMPTZ '2026-01-03 10:12:00+00', NULL, NULL),
    (304, 101, 4, 'courier_assigned', TIMESTAMPTZ '2026-01-03 10:13:00+00', 2, NULL),
    (305, 101, 5, 'picked_up',        TIMESTAMPTZ '2026-01-03 10:15:00+00', 2, 'bicycle'),
    (306, 101, 6, 'delivered',        TIMESTAMPTZ '2026-01-03 10:30:00+00', NULL, NULL),
    (307, 102, 1, 'accepted',         TIMESTAMPTZ '2026-01-03 11:03:00+00', NULL, NULL),
    (308, 102, 2, 'courier_assigned', TIMESTAMPTZ '2026-01-03 11:07:00+00', 1, NULL),
    (309, 102, 3, 'ready',            TIMESTAMPTZ '2026-01-03 11:32:00+00', NULL, NULL),
    (310, 102, 4, 'picked_up',        TIMESTAMPTZ '2026-01-03 11:35:00+00', 1, 'car'),
    (311, 102, 5, 'delivered',        TIMESTAMPTZ '2026-01-03 11:46:00+00', NULL, NULL),
    (312, 103, 1, 'accepted',         TIMESTAMPTZ '2026-01-08 10:03:00+00', NULL, NULL),
    (313, 103, 2, 'courier_assigned', TIMESTAMPTZ '2026-01-08 10:04:00+00', 1, NULL),
    (314, 103, 3, 'ready',            TIMESTAMPTZ '2026-01-08 10:18:00+00', NULL, NULL),
    (315, 103, 4, 'picked_up',        TIMESTAMPTZ '2026-01-08 10:22:00+00', 1, 'car'),
    (316, 103, 5, 'delivered',        TIMESTAMPTZ '2026-01-08 10:39:00+00', NULL, NULL),
    (317, 104, 1, 'accepted',         TIMESTAMPTZ '2026-01-08 11:02:00+00', NULL, NULL),
    (318, 104, 2, 'cancelled',        TIMESTAMPTZ '2026-01-08 11:20:00+00', NULL, NULL)
) AS fixture(event_id, order_id, seq, status, occurred_at, courier_id, mode)
ON CONFLICT (status_event_id) DO NOTHING;

INSERT INTO experiment_assignments (experiment_code, user_id, variant, assigned_at, qualifying_order_id)
VALUES ('repeat-v1', 1, 'treatment', '2026-01-03 10:32:00+00', 101),
       ('repeat-v1', 2, 'control', '2026-01-03 11:49:00+00', 102)
ON CONFLICT (experiment_code, user_id) DO NOTHING;

INSERT INTO restaurant_interventions (
    study_code, restaurant_id, study_group, enrolled_at, comparison_start_on, study_time_zone, actual_started_at
)
VALUES ('capacity-v1', 1, 'treatment', '2026-01-01 08:00:00+00', '2026-01-05', 'Europe/Moscow', '2026-01-04 21:00:00+00'),
       ('capacity-v1', 2, 'control', '2026-01-01 08:00:00+00', '2026-01-05', 'Europe/Moscow', NULL)
ON CONFLICT (study_code, restaurant_id) DO NOTHING;

COMMIT;
