from dataclasses import dataclass
from typing import Optional


@dataclass
class Item:
    name: str
    url: str
    target_price: Optional[float] = None
    min_discount_percent: Optional[float] = None  # vs. list/strike-through price
    min_drop_percent: Optional[float] = None      # vs. last seen price
    alert_on_restock: bool = False                # alert when it comes back in stock


@dataclass
class PriceResult:
    title: str
    price: float
    list_price: Optional[float] = None
    currency: str = "$"
    in_stock: Optional[bool] = None  # None = site/parser can't tell
