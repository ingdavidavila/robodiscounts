import json
import os
import re
from urllib.parse import parse_qs, urlparse

import requests

from ..models import PriceResult

API = "https://api.bestbuy.com/v1/products/{sku}.json"
FIELDS = "sku,name,salePrice,regularPrice,onSale,onlineAvailability"


def sku_from_url(url: str) -> str:
    """Best Buy product URLs look like .../6578291.p?skuId=6578291"""
    parsed = urlparse(url)
    sku = parse_qs(parsed.query).get("skuId", [None])[0]
    if not sku:
        m = re.search(r"/(\d{6,8})\.p", parsed.path)
        sku = m.group(1) if m else None
    if not sku:
        raise ValueError(f"Could not find a SKU in Best Buy URL: {url}")
    return sku


def fetch_bestbuy(url: str) -> str:
    """Query the official Best Buy Products API; returns the raw JSON text."""
    key = os.environ.get("BESTBUY_API_KEY")
    if not key:
        raise RuntimeError("BESTBUY_API_KEY is not set")
    r = requests.get(
        API.format(sku=sku_from_url(url)),
        params={"apiKey": key, "format": "json", "show": FIELDS},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"Best Buy API error {r.status_code}: {r.text[:200]}")
    return r.text


def parse_bestbuy(text: str) -> PriceResult:
    data = json.loads(text)
    price = data.get("salePrice")
    if price is None:
        raise ValueError("Best Buy API returned no salePrice")
    regular = data.get("regularPrice")
    list_price = float(regular) if regular and float(regular) > float(price) else None
    in_stock = data.get("onlineAvailability")
    return PriceResult(
        title=data.get("name") or "Best Buy item",
        price=float(price),
        list_price=list_price,
        in_stock=bool(in_stock) if in_stock is not None else None,
    )
