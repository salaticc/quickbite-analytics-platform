"""Build a reproducible QuickBite dataset without holding event rows in memory."""

from contextlib import ExitStack
from datetime import date, datetime, time, timedelta, timezone
from hashlib import blake2b
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np

from .artifacts import ArtifactWriter, write_manifest
from .config import Config
from .contracts import BUSINESS_ZONE, EXPERIMENT, ID_BASE, STUDY
from .orders import OrderWriter

DAY = 86_400
CHANNELS = ("organic", "paid_search", "referral", "partner", None)
CITIES = ("MOW", "SPB", "KZN", "NNV", "EKB")
STEPS = ("search", "restaurant_view", "add_to_cart", "checkout")
HOUR_WEIGHTS = np.array([3, 2, 1, 1, 1, 2, 3, 5, 6, 8, 11, 16, 20, 17, 12, 10, 12, 16, 23, 24, 21, 14, 8, 5])
DAY_WEIGHTS = np.array([0.85, 0.86, 0.93, 1.0, 1.22, 1.3, 1.09])


def variant_for(user_id: int) -> str:
    sample = blake2b(f"{EXPERIMENT}:{user_id}".encode(), digest_size=1).digest()[0]
    return "treatment" if sample < 128 else "control"


def demo_uuid(namespace: int, index: int) -> str:
    return str(UUID(int=(namespace << 120) | index))


class EventWriter:
    def __init__(self, sink, clock, rng, config):
        self.sink, self.clock, self.rng, self.config = sink, clock, rng, config
        self.limit = min(config.orders, config.events // 6)
        self.index = 0

    def log_order(self, order) -> bool:
        ordinal = order.id - ID_BASE
        sampled = (ordinal + 1) * self.limit // self.config.orders > ordinal * self.limit // self.config.orders
        if not sampled:
            return False
        session = demo_uuid(0xAB, ordinal + 1)
        cart = demo_uuid(0xAC, ordinal + 1)
        self.prefix(session, cart, order.user, order.restaurant, order.placed - 300, 4)
        if order.delivered:
            self.event(session, "order_completed", order.terminal, order.user, order.restaurant, cart, order.id)
        return True

    def prefix(self, session, cart, user, restaurant, start, steps):
        for i in range(steps):
            self.event(session, STEPS[i], start + i * 52, user if i >= 2 else None,
                       restaurant if i >= 1 else None, cart if i >= 2 else None)

    def exposure(self, order, assigned, variant):
        if self.rng.random() < 0.82:
            session = demo_uuid(0xAB, order.id - ID_BASE + 1)
            self.event(session, "experiment_exposed", assigned + 20, order.user,
                       experiment=EXPERIMENT, variant=variant)

    def complete_volume(self, registration):
        session_num = self.config.orders + 1
        while self.index < self.config.events:
            steps = min(self.config.events - self.index, int(self.rng.integers(1, 5)))
            user_offset = int(self.rng.integers(self.config.users))
            user = ID_BASE + user_offset if self.rng.random() < 0.5 else None
            first_second = max(0, int(registration[user_offset])) if user is not None else 0
            second = int(self.rng.integers(first_second, self.config.days * DAY - 240))
            restaurant = ID_BASE + int(self.rng.integers(self.config.restaurants))
            self.prefix(demo_uuid(0xAB, session_num), demo_uuid(0xAC, session_num),
                        user, restaurant, second, steps)
            session_num += 1

    def event(self, session, name, second, user=None, restaurant=None, cart=None, order=None,
              experiment=None, variant=None):
        self.index += 1
        delay = int(self.rng.integers(1, 45))
        self.sink.row("product_events", demo_uuid(0xAA, self.index), session, name,
                      self.clock(second), self.clock(second + delay), user, restaurant, cart,
                      order, experiment, variant)


def generate(config: Config, output: Path) -> dict:
    config.validate()
    output.mkdir(parents=True, exist_ok=False)
    start_day = date.fromisoformat(config.start_date)
    local_start = datetime.combine(start_day, time(), ZoneInfo(BUSINESS_ZONE))
    start = local_start.astimezone(timezone.utc)
    dims, plan, orders_rng, events_rng = (np.random.default_rng(s) for s in np.random.SeedSequence(config.seed).spawn(4))

    with ExitStack() as stack:
        sink = ArtifactWriter(output, stack)
        registration = dims.integers(-45 * DAY, (config.days - 19) * DAY, config.users)
        segment = dims.choice(3, size=config.users, p=(0.45, 0.40, 0.15))
        cities = [CITIES[(i // 2) % len(CITIES)] for i in range(config.restaurants)]
        treatment = np.empty(config.restaurants, dtype=bool)
        treatment[::2] = dims.integers(0, 2, config.restaurants // 2)
        treatment[1::2] = ~treatment[::2]
        order_writer = OrderWriter(sink, config, start, orders_rng, cities,
                                   dims.normal(16.5, 2.8, config.restaurants // 2),
                                   treatment, dims.normal(0, 1.6, config.days))
        event_writer = EventWriter(sink, order_writer.instant, events_rng, config)
        write_dimensions(sink, config, start_day, order_writer.instant, dims, registration, cities, treatment)
        plan_orders(config, plan, segment, registration, order_writer, event_writer)
        event_writer.complete_volume(registration)
    return write_manifest(output, config, sink.counts)


def write_dimensions(sink, config, start_day, instant, rng, registration, cities, treatment):
    channels = rng.choice(len(CHANNELS), size=config.users, p=(0.39, 0.26, 0.18, 0.12, 0.05))
    for i, (at, channel) in enumerate(zip(registration, channels, strict=True)):
        sink.row("users", ID_BASE + i, instant(at), CHANNELS[channel])
    for i, city in enumerate(cities):
        id_ = ID_BASE + i
        sink.row("restaurants", id_, city, BUSINESS_ZONE, instant(-90 * DAY), None)
        sink.row("restaurant_interventions", STUDY, id_, "treatment" if treatment[i] else "control",
                 instant(-DAY), start_day + timedelta(days=config.intervention_day), BUSINESS_ZONE,
                 instant(config.intervention_day * DAY) if treatment[i] else None)
    for i in range(config.couriers):
        sink.row("couriers", ID_BASE + i, instant(-int(rng.integers(1, 70)) * DAY))


def plan_orders(config, rng, segments, registration, writer, events):
    active_count = min(max(1, int(config.users * 0.72)), max(1, config.orders // 2))
    propensity = np.array([0.75, 1.03, 1.45])[segments]
    active = rng.choice(config.users, size=active_count, replace=False, p=propensity / propensity.sum())
    weights = DAY_WEIGHTS[(np.arange(config.days) + date.fromisoformat(config.start_date).weekday()) % 7]
    uniform_hours = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()
    hours = iter(rng.choice(24, size=config.orders, p=uniform_hours))
    minute_seconds = iter(rng.integers(0, 3600, config.orders))
    background_starts = []

    for user_offset in active:
        user_offset = int(user_offset)
        start_day = max(0, (int(registration[user_offset]) + 300) // DAY)
        day = int(rng.integers(start_day, config.days - 17))
        second = place_at(day, hours, minute_seconds, max(300, int(registration[user_offset]) + 301))
        order = writer.write(ID_BASE + user_offset, int(rng.integers(config.restaurants)), second)
        sampled = events.log_order(order)
        window_anchor = order.terminal + 90
        if order.delivered:
            variant = variant_for(order.user)
            writer.sink.row("experiment_assignments", EXPERIMENT, order.user, variant,
                            writer.instant(window_anchor), order.id)
            if sampled:
                events.exposure(order, window_anchor, variant)
            # Treatment enters only the forward-looking repeat propensity.
            probability = (0.18, 0.30, 0.47)[segments[user_offset]]
            if variant == "treatment":
                probability += config.repeat_uplift
            if rng.random() < probability and writer.next_order < ID_BASE + config.orders:
                repeat_day = window_anchor // DAY + int(rng.integers(1, 13))
                repeat = writer.write(order.user, int(rng.integers(config.restaurants)),
                                      place_at(repeat_day, hours, minute_seconds, window_anchor + 301))
                events.log_order(repeat)
        background_starts.append(min(config.days - 1, (window_anchor + 14 * DAY) // DAY + 1))

    remaining = config.orders - (writer.next_order - ID_BASE)
    if remaining:
        active_weights = propensity[active]
        followups = rng.choice(len(active), size=remaining, p=active_weights / active_weights.sum())
        # Inverse CDF samples demand by weekday within each user's available interval.
        cumulative = np.cumsum(weights)
        for index in followups:
            earliest = background_starts[index]
            lower = cumulative[earliest - 1] if earliest else 0
            day = int(np.searchsorted(cumulative, rng.uniform(lower, cumulative[-1]), side="right"))
            order = writer.write(ID_BASE + int(active[index]), int(rng.integers(config.restaurants)),
                                 place_at(day, hours, minute_seconds, 300))
            events.log_order(order)


def place_at(day, hours, minute_seconds, earliest):
    return max(earliest, day * DAY + int(next(hours)) * 3600 + int(next(minute_seconds)))
