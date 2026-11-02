from dataclasses import dataclass, field
from typing import List

import yaml

from .models import Item


@dataclass
class Config:
    items: List[Item] = field(default_factory=list)
    db_path: str = "robodiscounts.db"
    check_interval_minutes: int = 60
    request_delay_seconds: float = 5
    fail_alert_after: int = 3  # WhatsApp warning after this many failed checks in a row (0 = off)


def load_config(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    items = [Item(**i) for i in raw.get("items", [])]
    return Config(
        items=items,
        db_path=raw.get("db_path", "robodiscounts.db"),
        check_interval_minutes=raw.get("check_interval_minutes", 60),
        request_delay_seconds=raw.get("request_delay_seconds", 5),
        fail_alert_after=raw.get("fail_alert_after", 3),
    )
