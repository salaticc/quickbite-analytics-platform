BEGIN;

CREATE TABLE IF NOT EXISTS users (
    user_id bigint PRIMARY KEY CHECK (user_id > 0),
    registered_at timestamptz NOT NULL,
    acquisition_channel text CHECK (btrim(acquisition_channel) <> '')
);

CREATE TABLE IF NOT EXISTS restaurants (
    restaurant_id bigint PRIMARY KEY CHECK (restaurant_id > 0),
    city_code text NOT NULL CHECK (btrim(city_code) <> ''),
    time_zone text NOT NULL CHECK (btrim(time_zone) <> ''),
    opened_at timestamptz NOT NULL,
    closed_at timestamptz CHECK (closed_at > opened_at)
);

CREATE TABLE IF NOT EXISTS couriers (
    courier_id bigint PRIMARY KEY CHECK (courier_id > 0),
    onboarded_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id bigint PRIMARY KEY CHECK (order_id > 0),
    user_id bigint NOT NULL REFERENCES users (user_id),
    restaurant_id bigint NOT NULL REFERENCES restaurants (restaurant_id),
    placed_at timestamptz NOT NULL,
    promised_delivery_at timestamptz CHECK (promised_delivery_at >= placed_at),
    city_code_at_order text NOT NULL CHECK (btrim(city_code_at_order) <> ''),
    time_zone_at_order text NOT NULL CHECK (btrim(time_zone_at_order) <> ''),
    delivery_distance_m integer CHECK (delivery_distance_m >= 0),
    currency_code text NOT NULL CHECK (currency_code = 'RUB'),
    items_gross_minor bigint NOT NULL CHECK (items_gross_minor >= 0),
    UNIQUE (order_id, currency_code),
    UNIQUE (order_id, user_id)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id bigint PRIMARY KEY CHECK (payment_id > 0),
    order_id bigint NOT NULL,
    provider text NOT NULL CHECK (btrim(provider) <> ''),
    provider_operation_id text NOT NULL CHECK (btrim(provider_operation_id) <> ''),
    operation_type text NOT NULL CHECK (operation_type IN ('capture', 'refund')),
    parent_capture_id bigint,
    -- Include the expected parent type in the FK so a refund cannot reference another refund.
    parent_operation_type text GENERATED ALWAYS AS (
        CASE WHEN parent_capture_id IS NOT NULL THEN 'capture'::text END
    ) STORED,
    posted_at timestamptz NOT NULL,
    currency_code text NOT NULL,
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    platform_revenue_minor bigint NOT NULL CHECK (platform_revenue_minor BETWEEN 0 AND amount_minor),
    CHECK (
        (operation_type = 'capture' AND parent_capture_id IS NULL)
        OR (operation_type = 'refund' AND parent_capture_id IS NOT NULL AND parent_capture_id <> payment_id)
    ),
    UNIQUE (provider, provider_operation_id),
    UNIQUE (payment_id, order_id, provider, currency_code, operation_type),
    FOREIGN KEY (order_id, currency_code) REFERENCES orders (order_id, currency_code),
    FOREIGN KEY (parent_capture_id, order_id, provider, currency_code, parent_operation_type)
        REFERENCES payments (payment_id, order_id, provider, currency_code, operation_type)
);

CREATE TABLE IF NOT EXISTS order_status_history (
    status_event_id bigint PRIMARY KEY CHECK (status_event_id > 0),
    order_id bigint NOT NULL REFERENCES orders (order_id),
    sequence_no integer NOT NULL CHECK (sequence_no > 0),
    status text NOT NULL CHECK (
        status IN ('accepted', 'courier_assigned', 'ready', 'picked_up', 'delivered', 'cancelled')
    ),
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL CHECK (recorded_at >= occurred_at),
    courier_id bigint REFERENCES couriers (courier_id),
    transport_mode_at_pickup text CHECK (
        transport_mode_at_pickup IS NULL OR (
            status = 'picked_up' AND transport_mode_at_pickup IN ('foot', 'bicycle', 'scooter', 'car')
        )
    ),
    CHECK ((status IN ('courier_assigned', 'picked_up')) = (courier_id IS NOT NULL)),
    UNIQUE (order_id, sequence_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_order_status_once
    ON order_status_history (order_id, status)
    WHERE status <> 'courier_assigned';

CREATE UNIQUE INDEX IF NOT EXISTS uq_order_terminal_status
    ON order_status_history (order_id)
    WHERE status IN ('delivered', 'cancelled');

CREATE TABLE IF NOT EXISTS experiment_assignments (
    experiment_code text NOT NULL CHECK (btrim(experiment_code) <> ''),
    user_id bigint NOT NULL REFERENCES users (user_id),
    variant text NOT NULL CHECK (variant IN ('control', 'treatment')),
    assigned_at timestamptz NOT NULL,
    qualifying_order_id bigint NOT NULL,
    PRIMARY KEY (experiment_code, user_id),
    FOREIGN KEY (qualifying_order_id, user_id) REFERENCES orders (order_id, user_id)
);

CREATE TABLE IF NOT EXISTS restaurant_interventions (
    study_code text NOT NULL CHECK (btrim(study_code) <> ''),
    restaurant_id bigint NOT NULL REFERENCES restaurants (restaurant_id),
    study_group text NOT NULL CHECK (study_group IN ('control', 'treatment')),
    enrolled_at timestamptz NOT NULL,
    comparison_start_on date NOT NULL,
    study_time_zone text NOT NULL CHECK (btrim(study_time_zone) <> ''),
    actual_started_at timestamptz CHECK (
        actual_started_at IS NULL OR (study_group = 'treatment' AND actual_started_at >= enrolled_at)
    ),
    PRIMARY KEY (study_code, restaurant_id)
);

COMMIT;
