import os
import re
from urllib.parse import urlparse

from .amazon import parse_amazon
from .bestbuy import fetch_bestbuy, parse_bestbuy
from .tcgplayer import parse_tcgplayer
from .fetch import fetch_html

PARSERS = {"amazon": parse_amazon, "tcgplayer": parse_tcgplayer, "bestbuy": parse_bestbuy}


def site_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "amazon." in host or "amzn." in host:
        return "amazon"
    if "tcgplayer.com" in host:
        return "tcgplayer"
    if "bestbuy.com" in host:
        return "bestbuy"
    raise ValueError(f"Unsupported site: {host}")


def _slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", url.split("://", 1)[-1]).strip("-")[:80]


def get_price(url: str, html: str = None):
    """Fetch (unless html is given) and parse a product page into a PriceResult.

    If ROBODISCOUNTS_DEBUG_DIR is set, a failed parse leaves <slug>.html and
    <slug>.png there so you can see what the site actually returned.
    """
    site = site_for(url)
    parser = PARSERS[site]
    debug_dir = os.environ.get("ROBODISCOUNTS_DEBUG_DIR")
    png = None
    if html is None and site == "bestbuy":
        html = fetch_bestbuy(url)  # official API: JSON, no browser needed
    elif html is None:
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            png = os.path.join(debug_dir, _slug(url) + ".png")
        html = fetch_html(url, screenshot_path=png)
    try:
        result = parser(html)
    except Exception:
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, _slug(url) + ".html"), "w") as f:
                f.write(html)
        raise
    if png and os.path.exists(png):
        os.remove(png)  # only keep screenshots of failures
    return result
