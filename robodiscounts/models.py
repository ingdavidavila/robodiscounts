from dataclasses import dataclass
from typing import Optional


@dataclass
class Item:
    name: str
    url: str
    target_price: Optional[float] = None
    min_discount_percent: Optional[float] = None  # vs. list/strike-through price
    min_drop_percent: Optional[float] = None      # vs. last seen price


@dataclass
class PriceResult:
    title: str
    price: float
    list_price: Optional[float] = None
    currency: str = "$"
