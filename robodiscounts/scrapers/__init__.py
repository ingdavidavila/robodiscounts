from urllib.parse import urlparse

from .amazon import parse_amazon
from .tcgplayer import parse_tcgplayer
from .fetch import fetch_html

PARSERS = {"amazon": parse_amazon, "tcgplayer": parse_tcgplayer}


def site_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "amazon." in host or "amzn." in host:
        return "amazon"
    if "tcgplayer.com" in host:
        return "tcgplayer"
    raise ValueError(f"Unsupported site: {host}")


def get_price(url: str, html: str = None):
    """Fetch (unless html is given) and parse a product page into a PriceResult."""
    parser = PARSERS[site_for(url)]
    return parser(html if html is not None else fetch_html(url))
