import logging
import time
from dataclasses import dataclass
from typing import Optional

from .models import Item, PriceResult
from .scrapers import get_price

log = logging.getLogger("robodiscounts")


# History rules stay quiet until there are at least this many earlier reads to compare with.
MIN_HISTORY_READS = 5


def evaluate(item: Item, res: PriceResult, last_price: Optional[float],
             stats: Optional[dict] = None) -> Optional[str]:
    """Return a human-readable reason if the item qualifies as a deal, else None.
    `stats` is Store.price_stats(): earlier in-stock reads, used by the history rules."""
    reasons = []
    if stats:
        if (item.below_avg_percent and stats["avg"] and stats["n_window"] >= MIN_HISTORY_READS
                and res.price <= stats["avg"] * (1 - item.below_avg_percent / 100)):
            pct = (stats["avg"] - res.price) / stats["avg"] * 100
            reasons.append(f"{pct:.0f}% below the {item.history_days}-day average ${stats['avg']:.2f}")
        if (item.alert_on_new_low and stats["low"] is not None
                and stats["n_all"] >= MIN_HISTORY_READS and res.price < stats["low"]):
            reasons.append(f"new low, previous best ${stats['low']:.2f}")
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
    send_failed: int = 0   # alerts that could not be delivered (will be retried next run)

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
        stats = store.price_stats(item.url, item.history_days)  # before this read is logged
        deal = None if sold_out else evaluate(item, res, last, stats)
        restock = bool(item.alert_on_restock and res.in_stock and was_in_stock is False)

        reasons = (["back in stock"] if restock else []) + ([deal] if deal else [])
        reason = "; ".join(reasons)
        notify = restock or (bool(deal) and prev_notified != res.price)
        delivered = False
        if notify:
            try:
                notifier.send(
                    format_message(item, res, reason, restock),
                    params=[item.name, f"${res.price:.2f}", reason, item.url],
                )
                delivered = True
                summary.sent += 1
            except Exception as e:  # a broken notifier must never stop price tracking
                summary.send_failed += 1
                log.error("Could not send alert for %s: %s", item.name, e)

        # Remember the alerted price only while it still qualifies, so the same deal
        # price can alert again after the price has gone back up in between. An alert
        # that failed to send is not remembered, so the next run tries again.
        if not deal:
            new_notified = None
        elif delivered:
            new_notified = res.price
        else:
            new_notified = prev_notified
        # Likewise keep the old stock state if a restock alert failed, so it is retried.
        saved_in_stock = was_in_stock if (restock and not delivered) else res.in_stock
        store.save(item.url, res.price, new_notified, saved_in_stock)
        store.add_history(item.url, res.price, res.in_stock, ok=True)

        state = " (sold out)" if sold_out else ""
        outcome = "-> notified" if delivered else ("-> SEND FAILED" if notify else "")
        log.info("%s: $%.2f%s %s", item.name, res.price, state, outcome)
        time.sleep(config.request_delay_seconds)

    # Bot-health messages: one per run, only when something just broke or recovered.
    send_status = getattr(notifier, "send_status", notifier.send)

    def status(text: str):
        try:
            send_status(text)
            summary.sent += 1
        except Exception as e:
            summary.send_failed += 1
            log.error("Could not send status message: %s", e)

    if newly_broken:
        status(
            f"⚠️ robodiscounts can't read {len(newly_broken)} item(s) after {threshold} checks "
            f"in a row: " + "; ".join(newly_broken) + ". Check the dashboard or logs."
        )
    if recovered:
        status("✅ robodiscounts is reading these items again: " + ", ".join(recovered) + ".")
    return summary
