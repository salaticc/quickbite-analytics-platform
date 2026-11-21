"""Validated generation profiles and domain assumptions."""

from dataclasses import dataclass, replace
from datetime import date
import json
from pathlib import Path


@dataclass(frozen=True)
class Config:
    users: int
    restaurants: int
    couriers: int
    orders: int
    events: int
    seed: int = 42
    start_date: str = "2026-03-01"
    days: int = 84
    intervention_day: int = 42
    repeat_uplift: float = 0.055
    prep_reduction_minutes: float = 7.0

    def validate(self) -> None:
        for field in ("users", "restaurants", "couriers", "orders", "events", "seed", "days", "intervention_day"):
            if type(getattr(self, field)) is not int:
                raise ValueError(f"{field} must be an integer")
        if not (2 <= self.users <= 150_000 and 1 <= self.orders <= 500_000
                and 2 <= self.restaurants <= 2_000 and self.restaurants % 2 == 0
                and 1 <= self.couriers <= 20_000 and 6 <= self.events <= 5_000_000):
            raise ValueError("Volumes outside supported bounds or restaurant count is not even")
        if not 0 <= self.seed < 2**64:
            raise ValueError("seed must be an unsigned 64-bit integer")
        if not (42 <= self.days <= 365 and 14 <= self.intervention_day <= self.days - 14):
            raise ValueError("Require at least 14 days on each side of the intervention")
        if not (0 <= self.repeat_uplift <= 0.25 and 0 <= self.prep_reduction_minutes <= 15):
            raise ValueError("Generation effect parameters outside supported bounds")
        if not 2020 <= date.fromisoformat(self.start_date).year <= 2099:
            raise ValueError("start_date must be between 2020 and 2099")


PROFILES = {
    "smoke": Config(60, 8, 12, 96, 720, days=56, intervention_day=28),
    "small": Config(5_000, 40, 350, 25_000, 160_000),
    "full": Config(150_000, 240, 2_500, 500_000, 3_000_000),
}


def configuration(profile: str, overrides: Path | None, seed: int | None) -> Config:
    values = json.loads(overrides.read_text(encoding="utf-8")) if overrides else {}
    if seed is not None:
        values["seed"] = seed
    config = replace(PROFILES[profile], **values)
    config.validate()
    return config
