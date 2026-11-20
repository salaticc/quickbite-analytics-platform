BEGIN;

SELECT version() AS postgres_version;

DO $$
BEGIN
    IF (SELECT count(*) FROM orders WHERE order_id BETWEEN 101 AND 104) <> 4
       OR (SELECT count(*) FROM payments WHERE payment_id BETWEEN 201 AND 204) <> 4
       OR (SELECT count(*) FROM order_status_history WHERE status_event_id BETWEEN 301 AND 318) <> 18
       OR (SELECT count(*) FROM experiment_assignments WHERE experiment_code = 'repeat-v1') <> 2
       OR (SELECT count(*) FROM restaurant_interventions WHERE study_code = 'capacity-v1') <> 2
    THEN
        RAISE EXCEPTION 'Missing or duplicated seed data';
    END IF;

    IF (SELECT sum(items_gross_minor) FROM orders AS o
        WHERE o.order_id BETWEEN 101 AND 104 AND EXISTS (
            SELECT FROM order_status_history AS s WHERE s.order_id = o.order_id AND s.status = 'delivered'
        )) IS DISTINCT FROM 310000::numeric
    THEN
        RAISE EXCEPTION 'Seed gross GMV must be 310000 minor units';
    END IF;

    IF (SELECT sum(CASE operation_type WHEN 'capture' THEN platform_revenue_minor ELSE -platform_revenue_minor END)
        FROM payments WHERE payment_id BETWEEN 201 AND 204) IS DISTINCT FROM 53000::numeric
    THEN
        RAISE EXCEPTION 'Seed net platform revenue must be 53000 minor units';
    END IF;

    IF (SELECT amount_minor FROM payments
        WHERE payment_id = 204 AND operation_type = 'refund'
          AND date_trunc('month', posted_at AT TIME ZONE 'Europe/Moscow') = TIMESTAMP '2026-02-01'
    ) IS DISTINCT FROM 20000::bigint THEN
        RAISE EXCEPTION 'Seed late refund is missing from February';
    END IF;

    INSERT INTO users (user_id, registered_at, acquisition_channel)
    VALUES (900001, '2026-01-01 09:00:00+00', 'smoke');

    IF (SELECT acquisition_channel FROM users WHERE user_id = 900001) IS DISTINCT FROM 'smoke'
    THEN
        RAISE EXCEPTION 'Insert/read-back failed';
    END IF;

    BEGIN
        INSERT INTO users (user_id, registered_at) VALUES (900001, now());
        RAISE EXCEPTION 'Duplicate primary key accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO orders (order_id, user_id, restaurant_id, placed_at, city_code_at_order,
                            time_zone_at_order, currency_code, items_gross_minor)
        VALUES (900002, 900099, 1, now(), 'MOW', 'Europe/Moscow', 'RUB', 0);
        RAISE EXCEPTION 'Order with missing user accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO experiment_assignments (
            experiment_code, user_id, variant, assigned_at, qualifying_order_id
        ) VALUES ('smoke', 2, 'control', now(), 101);
        RAISE EXCEPTION 'Assignment with another user''s order accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO payments (payment_id, order_id, provider, provider_operation_id, operation_type,
                              parent_capture_id, posted_at, currency_code, amount_minor, platform_revenue_minor)
        VALUES (900003, 103, 'demo', 'invalid-refund-parent', 'refund', 204, now(), 'RUB', 100, 0);
        RAISE EXCEPTION 'Refund referencing another refund accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO order_status_history (status_event_id, order_id, sequence_no, status, occurred_at, recorded_at)
        VALUES (900004, 101, 100, 'cancelled', now(), now());
        RAISE EXCEPTION 'Second terminal status accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO restaurant_interventions (
            study_code, restaurant_id, study_group, enrolled_at, comparison_start_on, study_time_zone, actual_started_at
        ) VALUES ('smoke', 1, 'control', now(), CURRENT_DATE, 'Europe/Moscow', now());
        RAISE EXCEPTION 'Control intervention with actual start accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;

ROLLBACK;
SELECT 'PostgreSQL smoke passed';
