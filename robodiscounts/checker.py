import logging
import time
from dataclasses import dataclass
from typing import Optional

from .models import Item, PriceResult
from .scrapers import get_price

log = logging.getLogger("robodiscounts")


def evaluate(item: Item, res: PriceResult, last_price: Optional[float]) -> Optional[str]:
    """Return a human-readable reason if the item qualifies as a deal, else None."""
    reasons = []
    if item.msrp:
        limit = 100 if item.max_percent_of_msrp is None else item.max_percent_of_msrp
        pct = res.price / item.msrp * 100
        if pct <= limit:
            reasons.append(f"{pct:.0f}% of MSRP ${item.msrp:.2f}")
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


def format_message(item: Item, res: PriceResult, reason: str, restock: bool = False) -> str:
    head = "📦 *Back in stock*" if restock else "🔥 *Deal alert*"
    return (
        f"{head}: {item.name}\n"
        f"{res.title[:100]}\n"
        f"Price: *${res.price:.2f}* ({reason})\n"
        f"{item.url}"
    )


@dataclass
class RunSummary:
    checked: int = 0
    failed: int = 0
    sent: int = 0

    @property
    def all_failed(self) -> bool:
        return self.checked > 0 and self.failed == self.checked


def _short(err: Exception, n: int = 80) -> str:
    return " ".join(str(err).split())[:n] or err.__class__.__name__


def run_once(config, store, notifier, fetch=get_price) -> RunSummary:
    summary = RunSummary(checked=len(config.items))
    threshold = getattr(config, "fail_alert_after", 3)
    newly_broken, recovered = [], []
    for item in config.items:
        try:
            res = fetch(item.url)
        except Exception as e:  # keep going if one page fails
            log.warning("Failed %s: %s", item.url, e)
            summary.failed += 1
            reason_txt = _short(e)
            store.add_history(item.url, None, None, ok=False, error=reason_txt)
            streak = store.record_failure(item.url, reason_txt)
            if threshold and streak == threshold:
                newly_broken.append(f"{item.name} ({reason_txt})")
            continue
        last = store.last_price(item.url)
        prev_notified = store.last_notified(item.url)
        was_in_stock = store.was_in_stock(item.url)
        if threshold and store.fail_streak(item.url) >= threshold:
            recovered.append(item.name)

        sold_out = res.in_stock is False
        # A sold-out item can't be bought, so its price never counts as a deal.
        deal = None if sold_out else evaluate(item, res, last)
        restock = bool(item.alert_on_restock and res.in_stock and was_in_stock is False)

        reasons = (["back in stock"] if restock else []) + ([deal] if deal else [])
        reason = "; ".join(reasons)
        notify = restock or (bool(deal) and prev_notified != res.price)
        if notify:
            notifier.send(
                format_message(item, res, reason, restock),
                params=[item.name, f"${res.price:.2f}", reason, item.url],
            )
            summary.sent += 1

        # Remember the alerted price only while it still qualifies, so the same deal
        # price can alert again after the price has gone back up in between.
        if not deal:
            new_notified = None
        elif notify:
            new_notified = res.price
        else:
            new_notified = prev_notified
        store.save(item.url, res.price, new_notified, res.in_stock)
        store.add_history(item.url, res.price, res.in_stock, ok=True)

        state = " (sold out)" if sold_out else ""
        log.info("%s: $%.2f%s %s", item.name, res.price, state, "-> notified" if notify else "")
        time.sleep(config.request_delay_seconds)

    # Bot-health messages: one per run, only when something just broke or recovered.
    send_status = getattr(notifier, "send_status", notifier.send)
    if newly_broken:
        send_status(
            f"⚠️ robodiscounts can't read {len(newly_broken)} item(s) after {threshold} checks "
            f"in a row: " + "; ".join(newly_broken) + ". Check the dashboard or Actions log."
        )
        summary.sent += 1
    if recovered:
        send_status("✅ robodiscounts is reading these items again: " + ", ".join(recovered) + ".")
        summary.sent += 1
    return summary
