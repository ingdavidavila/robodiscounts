import json

from bs4 import BeautifulSoup

from ..models import PriceResult
from .util import parse_money

PRICE_SELECTORS = [
    ".spotlight__price",             # market price block
    ".price-points__upper__price",
    ".listing-item__listing-data__info__price",  # cheapest listing
]


def parse_tcgplayer(html: str) -> PriceResult:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    title = h1.get_text(strip=True) if h1 else "TCGplayer item"

    price = None
    for sel in PRICE_SELECTORS:
        el = soup.select_one(sel)
        price = parse_money(el.get_text()) if el else None
        if price is not None:
            break
    if price is None:
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(tag.string or "")
                offers = data.get("offers", {})
                price = parse_money(str(offers.get("lowPrice") or offers.get("price")))
                if price:
                    break
            except (ValueError, AttributeError):
                continue
    if price is None:
        raise ValueError("Could not find price (layout changed or bot check)")
    return PriceResult(title=title, price=price)
