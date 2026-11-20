CREATE TABLE IF NOT EXISTS pg_users (
    user_id Int64,
    registered_at DateTime64(6, 'UTC'),
    acquisition_channel Nullable(String)
) ENGINE = MergeTree ORDER BY user_id;

CREATE TABLE IF NOT EXISTS pg_restaurants (
    restaurant_id Int64,
    city_code String,
    time_zone String,
    opened_at DateTime64(6, 'UTC'),
    closed_at Nullable(DateTime64(6, 'UTC'))
) ENGINE = MergeTree ORDER BY restaurant_id;

CREATE TABLE IF NOT EXISTS pg_couriers (
    courier_id Int64,
    onboarded_at DateTime64(6, 'UTC')
) ENGINE = MergeTree ORDER BY courier_id;

CREATE TABLE IF NOT EXISTS pg_orders (
    order_id Int64,
    user_id Int64,
    restaurant_id Int64,
    placed_at DateTime64(6, 'UTC'),
    promised_delivery_at Nullable(DateTime64(6, 'UTC')),
    city_code_at_order String,
    time_zone_at_order String,
    delivery_distance_m Nullable(Int32),
    currency_code String,
    items_gross_minor Int64
) ENGINE = MergeTree ORDER BY order_id;

CREATE TABLE IF NOT EXISTS pg_payments (
    payment_id Int64,
    order_id Int64,
    provider String,
    provider_operation_id String,
    operation_type String,
    parent_capture_id Nullable(Int64),
    posted_at DateTime64(6, 'UTC'),
    currency_code String,
    amount_minor Int64,
    platform_revenue_minor Int64
) ENGINE = MergeTree ORDER BY payment_id;

CREATE TABLE IF NOT EXISTS pg_order_status_history (
    status_event_id Int64,
    order_id Int64,
    sequence_no Int32,
    status String,
    occurred_at DateTime64(6, 'UTC'),
    recorded_at DateTime64(6, 'UTC'),
    courier_id Nullable(Int64),
    transport_mode_at_pickup Nullable(String)
) ENGINE = MergeTree ORDER BY status_event_id;

CREATE TABLE IF NOT EXISTS pg_experiment_assignments (
    experiment_code String,
    user_id Int64,
    variant String,
    assigned_at DateTime64(6, 'UTC'),
    qualifying_order_id Int64
) ENGINE = MergeTree ORDER BY (experiment_code, user_id);

CREATE TABLE IF NOT EXISTS pg_restaurant_interventions (
    study_code String,
    restaurant_id Int64,
    study_group String,
    enrolled_at DateTime64(6, 'UTC'),
    comparison_start_on Date,
    study_time_zone String,
    actual_started_at Nullable(DateTime64(6, 'UTC'))
) ENGINE = MergeTree ORDER BY (study_code, restaurant_id);

CREATE TABLE IF NOT EXISTS product_events (
    event_id UUID,
    session_id UUID,
    event_name LowCardinality(String),
    occurred_at DateTime64(6, 'UTC'),
    ingested_at DateTime64(6, 'UTC'),
    user_id Nullable(Int64),
    restaurant_id Nullable(Int64),
    cart_id Nullable(UUID),
    order_id Nullable(Int64),
    experiment_code Nullable(String),
    variant_seen Nullable(String),
    CONSTRAINT known_event CHECK event_name IN (
        'search', 'restaurant_view', 'add_to_cart', 'checkout', 'order_completed', 'experiment_exposed'
    ),
    CONSTRAINT event_time_order CHECK ingested_at >= occurred_at,
    CONSTRAINT restaurant_present CHECK event_name NOT IN (
        'restaurant_view', 'add_to_cart', 'checkout', 'order_completed'
    ) OR isNotNull(restaurant_id),
    CONSTRAINT cart_present CHECK event_name NOT IN (
        'add_to_cart', 'checkout', 'order_completed'
    ) OR isNotNull(cart_id),
    CONSTRAINT completed_order_present CHECK event_name != 'order_completed'
        OR (isNotNull(order_id) AND isNotNull(user_id)),
    CONSTRAINT exposure_attrs CHECK (
        event_name = 'experiment_exposed'
        AND isNotNull(user_id)
        AND notEmpty(ifNull(experiment_code, ''))
        AND ifNull(variant_seen, '') IN ('control', 'treatment')
    ) OR (
        event_name != 'experiment_exposed' AND isNull(experiment_code) AND isNull(variant_seen)
    )
) ENGINE = MergeTree ORDER BY event_id;
