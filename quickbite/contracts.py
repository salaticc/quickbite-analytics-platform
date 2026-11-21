"""Column and key order shared by CSV, PostgreSQL and ClickHouse."""

from dataclasses import dataclass

ID_BASE = 10_000_000
EXPERIMENT = "qb-repeat-v1"
STUDY = "qb-capacity-v1"
BUSINESS_ZONE = "Europe/Moscow"


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]

    @property
    def landing(self) -> str:
        return self.name if self.name == "product_events" else f"pg_{self.name}"


def table(name: str, columns: str, key: str) -> Table:
    return Table(name, tuple(columns.split()), tuple(key.split()))


TABLES = (
    table("users", "user_id registered_at acquisition_channel", "user_id"),
    table("restaurants", "restaurant_id city_code time_zone opened_at closed_at", "restaurant_id"),
    table("couriers", "courier_id onboarded_at", "courier_id"),
    table("orders", "order_id user_id restaurant_id placed_at promised_delivery_at "
          "city_code_at_order time_zone_at_order delivery_distance_m currency_code items_gross_minor", "order_id"),
    table("payments", "payment_id order_id provider provider_operation_id operation_type "
          "parent_capture_id posted_at currency_code amount_minor platform_revenue_minor", "payment_id"),
    table("order_status_history", "status_event_id order_id sequence_no status occurred_at recorded_at "
          "courier_id transport_mode_at_pickup", "status_event_id"),
    table("experiment_assignments", "experiment_code user_id variant assigned_at qualifying_order_id",
          "experiment_code user_id"),
    table("restaurant_interventions", "study_code restaurant_id study_group enrolled_at comparison_start_on "
          "study_time_zone actual_started_at", "study_code restaurant_id"),
    table("product_events", "event_id session_id event_name occurred_at ingested_at user_id restaurant_id "
          "cart_id order_id experiment_code variant_seen", "event_id"),
)
PG_TABLES = TABLES[:-1]
EVENTS = TABLES[-1]
