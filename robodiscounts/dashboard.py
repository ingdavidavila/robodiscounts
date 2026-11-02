"""Static HTML dashboard built from the price history. No JavaScript, no external assets."""
from datetime import datetime, timezone
from html import escape
from typing import Optional
from urllib.parse import urlparse

from .scrapers import site_for

STATUS_ORDER = {"deal": 0, "failing": 1, "sold out": 2, "watching": 3, "no data": 4}


def _money(v: Optional[float]) -> str:
    return "—" if v is None else f"${v:,.2f}"


def _when(ts: Optional[str]) -> str:
    return "never" if not ts else ts.replace("T", " ").replace("Z", " UTC")


def _site(url: str) -> str:
    try:
        return site_for(url)
    except ValueError:
        return urlparse(url).netloc or "site"


def _sparkline(points, w=120, h=32) -> str:
    prices = [p for _, p in points]
    if len(prices) < 2:
        return '<span class="muted">—</span>'
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    step = w / (len(prices) - 1)
    pts = " ".join(
        f"{i * step:.1f},{h - 3 - (p - lo) / span * (h - 6):.1f}" for i, p in enumerate(prices)
    )
    label = f"Price trend, {len(prices)} checks, from {_money(prices[0])} to {_money(prices[-1])}"
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
        f'aria-label="{escape(label)}"><polyline fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linejoin="round" points="{pts}"/></svg>'
    )


def _status(info: dict) -> str:
    if not info:
        return "no data"
    if info.get("fail_streak"):
        return "failing"
    if info.get("in_stock") is False:
        return "sold out"
    if info.get("last_notified") is not None:  # only set while the price still qualifies
        return "deal"
    if info.get("last_price") is None:
        return "no data"
    return "watching"


def render(config, store, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    rows = []
    for item in config.items:
        info = store.info(item.url)
        hist = store.price_history(item.url)
        prices = [p for _, p in hist]
        rows.append({
            "item": item, "info": info, "status": _status(info), "hist": hist,
            "low": min(prices) if prices else None, "high": max(prices) if prices else None,
        })
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], r["item"].name.lower()))

    count = lambda s: sum(1 for r in rows if r["status"] == s)
    last_checked = max((r["info"].get("last_checked") or "" for r in rows), default="") or None
    cards = [
        ("Tracked", len(rows)), ("Deals now", count("deal")),
        ("Sold out", count("sold out")), ("Failing", count("failing")),
    ]

    body_rows = []
    for r in rows:
        it, info = r["item"], r["info"]
        err = ""
        if r["status"] == "failing":
            err = (f'<div class="muted small">{info["fail_streak"]} failed check(s) in a row: '
                   f'{escape(info.get("last_error") or "unknown error")}</div>')
        target = _money(it.target_price) if it.target_price is not None else "—"
        body_rows.append(
            "<tr>"
            f'<td><a href="{escape(it.url, quote=True)}" rel="noopener noreferrer">{escape(it.name)}</a>'
            f'<div class="muted small">{escape(_site(it.url))}</div>{err}</td>'
            f'<td><span class="badge {r["status"].replace(" ", "-")}">{r["status"]}</span></td>'
            f'<td class="num">{_money(info.get("last_price"))}</td>'
            f'<td class="num hs">{_money(r["low"])}</td>'
            f'<td class="num hs">{target}</td>'
            f'<td>{_sparkline(r["hist"])}</td>'
            f'<td class="small hs">{escape(_when(info.get("last_checked")))}</td>'
            "</tr>"
        )
    table = (
        '<div class="scroll"><table><thead><tr><th>Product</th><th>Status</th>'
        '<th class="num">Price</th><th class="num hs">Lowest seen</th><th class="num hs">Target</th>'
        '<th>Trend</th><th class="hs">Last checked</th></tr></thead><tbody>'
        + "".join(body_rows) + "</tbody></table></div>"
        if rows else '<p class="muted">No items in the watchlist yet.</p>'
    )
    card_html = "".join(
        f'<div class="card"><div class="muted small">{escape(k)}</div><div class="big">{v}</div></div>'
        for k, v in cards
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Discount Watch</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1c1c1a;--muted:#6b6b66;--card:#fff;--line:#e3e3de;
--deal:#0a7a3d;--fail:#b3261e;--sold:#8a5a00;--watch:#44508a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ececea;--muted:#9a9a94;--card:#1f1f1d;
--line:#33332f;--deal:#4cc287;--fail:#ff8a80;--sold:#e8b04a;--watch:#9fb0ff}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:22px;margin:0 0 4px}} a{{color:inherit}}
.muted{{color:var(--muted)}} .small{{font-size:12.5px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:18px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.big{{font-size:26px;font-weight:650}}
.scroll{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}}
table{{border-collapse:collapse;width:100%;min-width:680px}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
tr:last-child td{{border-bottom:0}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.badge{{display:inline-block;white-space:nowrap;padding:2px 9px;border-radius:99px;font-size:12.5px;font-weight:600;border:1px solid currentColor}}
.deal{{color:var(--deal)}} .failing{{color:var(--fail)}} .sold-out{{color:var(--sold)}}
.watching,.no-data{{color:var(--watch)}}
.spark{{color:var(--watch);display:block}}
@media (max-width:600px){{.hs{{display:none}} table{{min-width:0}} .spark{{width:64px;height:auto}} th,td{{padding:10px 8px}}}}
</style></head><body><main>
<h1>Discount Watch</h1>
<div class="muted small">Updated {escape(now.strftime("%Y-%m-%d %H:%M UTC"))} · last price check {escape(_when(last_checked))}</div>
<div class="cards">{card_html}</div>
{table}
<p class="muted small">Status: <b>deal</b> = meets your rules right now · <b>failing</b> = the page could not be read ·
<b>sold out</b> = reported unavailable (Best Buy only) · <b>watching</b> = no deal at the moment.</p>
</main></body></html>
"""
