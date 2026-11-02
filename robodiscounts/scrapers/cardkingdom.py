import json

from bs4 import BeautifulSoup

from ..models import PriceResult
from .util import parse_money

# Tried in order. Card Kingdom lists conditions best-first (NM, EX, VG, G),
# so the first match is the near-mint / sealed-product price.
PRICE_SELECTORS = [
    '[itemprop="price"]',          # schema.org microdata (value in content= or text)
    ".stylePrice",                 # price element used on Card Kingdom item pages
    'meta[property="product:price:amount"]',
    'meta[property="og:price:amount"]',
]


def _value(el):
    if el is None:
        return None
    return parse_money(el.get("content") or el.get_text())


def _from_json_ld(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            offers = node.get("offers") if isinstance(node, dict) else None
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = parse_money(str(offers.get("price") or offers.get("lowPrice")))
                if price:
                    return price
    return None


def parse_cardkingdom(html: str) -> PriceResult:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else "Card Kingdom item"

    price = _from_json_ld(soup)
    if price is None:
        for sel in PRICE_SELECTORS:
            for el in soup.select(sel):
                price = _value(el)
                if price:
                    break
            if price:
                break
    if price is None:
        raise ValueError(
            "Could not find price (out of stock, layout changed, or bot check)"
        )
    return PriceResult(title=title, price=price)
