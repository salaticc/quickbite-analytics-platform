"""Generate one order lifecycle and its payment ledger."""

from dataclasses import dataclass
from datetime import timedelta

from .contracts import BUSINESS_ZONE, ID_BASE


@dataclass(frozen=True)
class Order:
    id: int
    user: int
    restaurant: int
    placed: int
    terminal: int
    delivered: bool


class OrderWriter:
    def __init__(self, sink, config, start, rng, cities, pair_prep, treatment, demand):
        self.sink = sink
        self.config = config
        self.start = start
        self.rng = rng
        self.cities = cities
        self.pair_prep = pair_prep
        self.treatment = treatment
        self.demand = demand
        self.next_order = ID_BASE
        self.next_status = ID_BASE
        self.next_payment = ID_BASE

    def write(self, user: int, restaurant: int, placed: int) -> Order:
        rng = self.rng
        order_id = self.next_order
        self.next_order += 1
        day, second = divmod(placed, 86_400)
        hour = second // 3_600
        peak = int(11 <= hour <= 13 or 17 <= hour <= 20)
        distance = min(12_000, max(400, int(rng.lognormal(7.85, 0.48))))
        items = max(25_000, int(rng.lognormal(11.45, 0.48)) // 100 * 100)
        promised = placed + 60 * (31 + distance // 650 + 4 * peak)
        accepted = placed + int(rng.integers(30, 240))
        enroute = placed + int(rng.integers(240, 560)) + peak * 150
        courier = ID_BASE + int(rng.integers(self.config.couriers))

        self.sink.row("orders", order_id, user, ID_BASE + restaurant, self.instant(placed),
                      self.instant(promised) if rng.random() > 0.03 else None,
                      self.cities[restaurant], BUSINESS_ZONE, distance, "RUB", items)
        statuses = [("accepted", accepted, None, None)]
        delivered = rng.random() >= 0.07
        if delivered:
            post_effect = (self.config.prep_reduction_minutes
                           if self.treatment[restaurant] and day >= self.config.intervention_day else 0)
            minutes = max(4.0, self.pair_prep[restaurant // 2] + 4.8 * peak
                          + 0.035 * day + self.demand[day] - post_effect + rng.normal(0, 4))
            ready = accepted + int(minutes * 60)
            pickup = max(ready, enroute) + int(rng.integers(70, 400))
            mode, speed = (("bicycle", 4.0), ("scooter", 5.0), ("car", 7.0))[int(rng.integers(3))]
            terminal = pickup + int(distance / speed + rng.lognormal(5.1 + peak * 0.45, 0.45))
            statuses.append(("courier_assigned", enroute, courier, None))
            if self.config.couriers > 1 and rng.random() < 0.08:
                courier = ID_BASE + (courier - ID_BASE + 1) % self.config.couriers
                statuses.append(("courier_assigned", pickup - 15, courier, None))
            statuses.extend((("ready", ready, None, None), ("picked_up", pickup, courier, mode),
                             ("delivered", terminal, None, None)))
        else:
            terminal = accepted + int(rng.integers(110, 1_100))
            if enroute < terminal:
                statuses.append(("courier_assigned", enroute, courier, None))
            statuses.append(("cancelled", terminal, None, None))

        for sequence, (status, at, handler, transport) in enumerate(sorted(statuses, key=lambda x: x[1]), 1):
            self.sink.row("order_status_history", self.next_status, order_id, sequence, status,
                          self.instant(at), self.instant(at + int(rng.integers(1, 21))), handler, transport)
            self.next_status += 1
        if delivered or rng.random() < 0.42:
            self.pay(order_id, items, placed, terminal, delivered)
        return Order(order_id, user, ID_BASE + restaurant, placed, terminal, delivered)

    def pay(self, order_id: int, items: int, placed: int, terminal: int, delivered: bool) -> None:
        rng = self.rng
        charge = items - int(items * rng.uniform(0, 0.12)) + int(rng.integers(2_900, 12_001))
        split = charge // 3 if rng.random() < 0.18 else charge
        captures = (split, charge - split) if split < charge else (split,)
        for i, amount in enumerate(captures):
            revenue = amount * 18 // 100
            charge_id = self.payment(order_id, "capture", None, placed + 15 + i * 7, amount, revenue)
            if not delivered or rng.random() < 0.05:
                refunded = amount if not delivered else max(1, int(amount * rng.uniform(0.08, 0.70)))
                first = refunded // 2 if refunded > 1 and rng.random() < 0.22 else refunded
                parts = (first, refunded - first) if first < refunded else (first,)
                refund_at = terminal + int(rng.integers(1_800, 14 * 86_400))
                for j, part in enumerate(parts):
                    self.payment(order_id, "refund", charge_id, refund_at + j * 3_600, part,
                                 revenue * part // amount)

    def payment(self, order_id, kind, parent, at, amount, revenue):
        key = self.next_payment
        self.next_payment += 1
        self.sink.row("payments", key, order_id, "qb-demo", f"qb-{key}", kind, parent,
                      self.instant(at), "RUB", amount, revenue)
        return key

    def instant(self, second: int):
        return self.start + timedelta(seconds=int(second))
