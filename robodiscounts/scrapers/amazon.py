import json

from bs4 import BeautifulSoup

from ..models import PriceResult
from .util import parse_money

PRICE_SELECTORS = [
    "#corePrice_feature_div .priceToPay .a-offscreen",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#apex_desktop .priceToPay .a-offscreen",
    "span.a-price span.a-offscreen",
    "#priceblock_dealprice",
    "#priceblock_ourprice",
]
LIST_SELECTORS = [
    "#corePrice_feature_div .basisPrice .a-offscreen",
    "span.a-price.a-text-price span.a-offscreen",
    "#listPrice",
]


def _first_text(soup, selectors):
    for sel in selectors:
        el = soup.select_one(sel)
        if el and parse_money(el.get_text()) is not None:
            return el.get_text()
    return None


def parse_amazon(html: str) -> PriceResult:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("#productTitle")
    title = title_el.get_text(strip=True) if title_el else "Amazon item"

    price_txt = _first_text(soup, PRICE_SELECTORS)
    price = parse_money(price_txt)
    if price is None:  # JSON-LD fallback
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(tag.string or "")
                offers = (data[0] if isinstance(data, list) else data).get("offers", {})
                price = parse_money(str(offers.get("price")))
                if price:
                    break
            except (ValueError, AttributeError, KeyError, IndexError):
                continue
    if price is None:
        raise ValueError("Could not find price (page may be a CAPTCHA or layout changed)")

    list_price = parse_money(_first_text(soup, LIST_SELECTORS))
    if list_price is not None and list_price <= price:
        list_price = None
    return PriceResult(title=title, price=price, list_price=list_price)
