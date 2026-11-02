import logging
import time
from typing import Optional

from .models import Item, PriceResult
from .scrapers import get_price

log = logging.getLogger("robodiscounts")


def evaluate(item: Item, res: PriceResult, last_price: Optional[float]) -> Optional[str]:
    """Return a human-readable reason if the item qualifies as a deal, else None."""
    reasons = []
    if item.target_price is not None and res.price <= item.target_price:
        reasons.append(f"at/below your target of ${item.target_price:.2f}")
    if item.min_discount_percent and res.list_price:
        pct = (res.list_price - res.price) / res.list_price * 100
        if pct >= item.min_discount_percent:
            reasons.append(f"{pct:.0f}% off list price ${res.list_price:.2f}")
    if item.min_drop_percent and last_price and res.price < last_price:
        pct = (last_price - res.price) / last_price * 100
        if pct >= item.min_drop_percent:
            reasons.append(f"dropped {pct:.0f}% from ${last_price:.2f}")
    return "; ".join(reasons) or None


def format_message(item: Item, res: PriceResult, reason: str) -> str:
    return (
        f"🔥 *Deal alert*: {item.name}\n"
        f"{res.title[:100]}\n"
        f"Price: *${res.price:.2f}* ({reason})\n"
        f"{item.url}"
    )


def run_once(config, store, notifier, fetch=get_price) -> int:
    sent = 0
    for item in config.items:
        try:
            res = fetch(item.url)
        except Exception as e:  # keep going if one page fails
            log.warning("Failed %s: %s", item.url, e)
            continue
        last = store.last_price(item.url)
        reason = evaluate(item, res, last)
        notify = bool(reason) and store.last_notified(item.url) != res.price
        if notify:
            notifier.send(format_message(item, res, reason))
            sent += 1
        log.info("%s: $%.2f %s", item.name, res.price, "-> notified" if notify else "")
        store.save(item.url, res.price, notify)
        time.sleep(config.request_delay_seconds)
    return sent
