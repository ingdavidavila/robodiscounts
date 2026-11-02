from robodiscounts.checker import evaluate, run_once
from robodiscounts.config import Config
from robodiscounts.models import Item, PriceResult
from robodiscounts.scrapers import get_price, site_for
from robodiscounts.store import Store

AMAZON = """<span id="productTitle"> Cool Headphones </span>
<div id="corePrice_feature_div"><span class="a-price priceToPay"><span class="a-offscreen">$199.99</span></span>
<span class="basisPrice"><span class="a-offscreen">$349.99</span></span></div>"""
TCG = """<h1>Charizard ex</h1><span class="spotlight__price">$12.34</span>"""


def test_amazon_parse():
    r = get_price("https://www.amazon.com/dp/X", html=AMAZON)
    assert (r.title, r.price, r.list_price) == ("Cool Headphones", 199.99, 349.99)


def test_tcg_parse():
    r = get_price("https://www.tcgplayer.com/product/1", html=TCG)
    assert r.price == 12.34 and r.title == "Charizard ex"


def test_site_for():
    assert site_for("https://www.amazon.com.mx/dp/1") == "amazon"


def test_evaluate():
    res = PriceResult("t", 80, list_price=100)
    assert evaluate(Item("a", "u", min_discount_percent=20), res, None)
    assert not evaluate(Item("a", "u", min_discount_percent=30), res, None)
    assert evaluate(Item("a", "u", min_drop_percent=10), res, 100)
    assert evaluate(Item("a", "u", target_price=90), res, None)


def test_dedupe(tmp_path):
    class N:
        sent = []
        def send(self, b, params=None): self.sent.append(b)
    item = Item("a", "https://www.amazon.com/dp/1", target_price=90)
    cfg = Config(items=[item], request_delay_seconds=0)
    store, n = Store(str(tmp_path / "t.db")), N()
    fetch = lambda url: PriceResult("t", 80)
    run_once(cfg, store, n, fetch)
    run_once(cfg, store, n, fetch)
    assert len(n.sent) == 1


def test_meta_payloads(monkeypatch):
    from robodiscounts.notifier import WhatsAppNotifier
    calls = []
    class R: ok = True
    monkeypatch.setattr("requests.post", lambda url, **kw: calls.append((url, kw["json"])) or R())
    WhatsAppNotifier("tok", "123", "+5211", None).send("hi")
    assert calls[-1][1]["type"] == "text" and calls[-1][1]["to"] == "5211"
    WhatsAppNotifier("tok", "123", "+5211", "deal").send("hi", params=["a", "b", "c", "d"])
    assert calls[-1][1]["template"]["name"] == "deal"
    assert len(calls[-1][1]["template"]["components"][0]["parameters"]) == 4


def test_all_failed_summary(tmp_path):
    class N:
        def send(self, b, params=None): pass
    def boom(url): raise ValueError("blocked")
    cfg = Config(items=[Item("a", "u1"), Item("b", "u2")], request_delay_seconds=0)
    summary = run_once(cfg, Store(str(tmp_path / "t.db")), N(), boom)
    assert summary.all_failed and summary.failed == 2

    def half(url):
        if url == "u1": raise ValueError("blocked")
        return PriceResult("t", 5)
    summary = run_once(cfg, Store(str(tmp_path / "t2.db")), N(), half)
    assert summary.failed == 1 and not summary.all_failed


def test_debug_capture_on_parse_failure(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("ROBODISCOUNTS_DEBUG_DIR", str(tmp_path / "dbg"))
    with pytest.raises(ValueError):
        get_price("https://www.amazon.com/dp/X", html="<html>captcha</html>")
    files = list((tmp_path / "dbg").glob("*.html"))
    assert len(files) == 1 and "captcha" in files[0].read_text()


def test_cli_exits_nonzero_when_all_fail(tmp_path, monkeypatch):
    import pytest
    from robodiscounts import cli
    cfgfile = tmp_path / "c.yaml"
    cfgfile.write_text(f"db_path: {tmp_path}/x.db\nrequest_delay_seconds: 0\nitems:\n  - name: a\n    url: https://www.amazon.com/dp/1\n")
    monkeypatch.setattr("robodiscounts.checker.get_price", lambda u: (_ for _ in ()).throw(ValueError("x")))
    monkeypatch.setattr("robodiscounts.cli.run_once", lambda c, s, n: run_once(c, s, n, lambda u: (_ for _ in ()).throw(ValueError("x"))))
    monkeypatch.setattr("sys.argv", ["robodiscounts", "check", "-c", str(cfgfile), "--dry-run"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1


BESTBUY = '{"sku": 6578291, "name": "Pokemon Booster Bundle", "salePrice": 17.99, "regularPrice": 26.94, "onSale": true}'


def test_bestbuy_parse():
    r = get_price("https://www.bestbuy.com/site/x/6578291.p?skuId=6578291", html=BESTBUY)
    assert (r.title, r.price, r.list_price) == ("Pokemon Booster Bundle", 17.99, 26.94)
    no_sale = '{"name": "n", "salePrice": 10, "regularPrice": 10}'
    assert get_price("https://www.bestbuy.com/site/x/1234567.p", html=no_sale).list_price is None


def test_bestbuy_sku_and_fetch(monkeypatch):
    import pytest
    from robodiscounts.scrapers.bestbuy import fetch_bestbuy, sku_from_url
    assert sku_from_url("https://www.bestbuy.com/site/x/6578291.p?skuId=6578291") == "6578291"
    assert sku_from_url("https://www.bestbuy.com/site/some-name/6578291.p") == "6578291"
    with pytest.raises(ValueError):
        sku_from_url("https://www.bestbuy.com/site/searchpage.jsp")
    monkeypatch.setenv("BESTBUY_API_KEY", "k")
    seen = {}
    class R:
        ok = True; text = BESTBUY
    def fake_get(url, params, timeout):
        seen.update(url=url, params=params); return R()
    monkeypatch.setattr("requests.get", fake_get)
    assert get_price("https://www.bestbuy.com/site/x/6578291.p").price == 17.99
    assert seen["url"].endswith("/6578291.json") and seen["params"]["apiKey"] == "k"


CK_MICRODATA = (
    '<h1>Modern Horizons 3 Draft Booster Box</h1>'
    '<span itemprop="price" content="249.99">$249.99</span>'
)
CK_CLASS = '<h1>Lightning Bolt</h1><div class="stylePrice">$1,234.50</div><div class="stylePrice">$9.00</div>'
CK_LD = '<h1>X</h1><script type="application/ld+json">{"@type":"Product","offers":{"price":"42.10"}}</script>'


def test_cardkingdom_parse_variants():
    u = "https://www.cardkingdom.com/catalog/item/1"
    assert get_price(u, html=CK_MICRODATA).price == 249.99
    r = get_price(u, html=CK_CLASS)
    assert r.price == 1234.50 and r.title == "Lightning Bolt"
    assert get_price(u, html=CK_LD).price == 42.10


def test_cardkingdom_out_of_stock():
    import pytest
    with pytest.raises(ValueError):
        get_price("https://www.cardkingdom.com/catalog/item/1", html="<h1>Sold out</h1>")
    assert site_for("https://www.cardkingdom.com/mtg/x/y") == "cardkingdom"


def _run(tmp_path, item, results, store=None):
    class N:
        def __init__(self): self.sent = []
        def send(self, b, params=None): self.sent.append(b)
    n, store = N(), store or Store(str(tmp_path / "s.db"))
    cfg = Config(items=[item], request_delay_seconds=0)
    for res in results:
        run_once(cfg, store, n, lambda url, r=res: r)
    return n.sent, store


def test_realert_after_price_leaves_and_returns(tmp_path):
    item = Item("a", "https://www.bestbuy.com/site/x/1234567.p", target_price=90)
    sent, _ = _run(tmp_path, item, [PriceResult("t", 80), PriceResult("t", 80),
                                    PriceResult("t", 100), PriceResult("t", 80)])
    assert len(sent) == 2  # first deal, then again after it ended and returned


def test_restock_alert_and_sold_out_not_a_deal(tmp_path):
    item = Item("a", "https://www.bestbuy.com/site/x/1234567.p", target_price=90, alert_on_restock=True)
    sold = PriceResult("t", 50, in_stock=False)
    sent, store = _run(tmp_path, item, [PriceResult("t", 100, in_stock=True), sold, sold])
    assert sent == []  # sold-out price of 50 is not a deal
    sent, _ = _run(tmp_path, item, [PriceResult("t", 50, in_stock=True)], store)
    assert len(sent) == 1 and "Back in stock" in sent[0]


def test_no_restock_alert_when_not_enabled_or_first_seen(tmp_path):
    item = Item("a", "https://www.bestbuy.com/site/x/1234567.p", alert_on_restock=True)
    sent, _ = _run(tmp_path, item, [PriceResult("t", 100, in_stock=True)])
    assert sent == []  # never seen sold out, so not a restock


def test_store_migrates_old_schema(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE prices (url TEXT PRIMARY KEY, last_price REAL, last_notified_price REAL)")
    db.execute("INSERT INTO prices VALUES ('u', 5.0, NULL)")
    db.commit(); db.close()
    st = Store(path)
    assert st.last_price("u") == 5.0 and st.was_in_stock("u") is None


def test_bestbuy_stock_flag():
    sold = '{"name": "n", "salePrice": 10, "regularPrice": 10, "onlineAvailability": false}'
    assert get_price("https://www.bestbuy.com/site/x/1234567.p", html=sold).in_stock is False


class StatusN:
    def __init__(self): self.sent, self.status = [], []
    def send(self, b, params=None): self.sent.append(b)
    def send_status(self, t): self.status.append(t)


def test_failure_alert_once_at_threshold_then_recovery(tmp_path):
    item = Item("Box", "https://www.bestbuy.com/site/x/1234567.p")
    cfg = Config(items=[item], request_delay_seconds=0, fail_alert_after=3)
    store, n = Store(str(tmp_path / "f.db")), StatusN()
    def boom(url): raise ValueError("Could not find price")
    for _ in range(5):
        run_once(cfg, store, n, boom)
    assert len(n.status) == 1 and "Box" in n.status[0] and "3 checks" in n.status[0]
    assert store.fail_streak(item.url) == 5
    run_once(cfg, store, n, lambda u: PriceResult("t", 10))
    assert len(n.status) == 2 and "reading these items again" in n.status[1]
    assert store.fail_streak(item.url) == 0
    run_once(cfg, store, n, lambda u: PriceResult("t", 10))
    assert len(n.status) == 2  # no repeat recovery message


def test_failure_alert_can_be_disabled(tmp_path):
    cfg = Config(items=[Item("a", "u")], request_delay_seconds=0, fail_alert_after=0)
    n = StatusN()
    for _ in range(4):
        run_once(cfg, Store(str(tmp_path / "d.db")), n, lambda u: (_ for _ in ()).throw(ValueError("x")))
    assert n.status == []


def test_history_records_reads_and_failures(tmp_path):
    item = Item("a", "https://www.bestbuy.com/site/x/1234567.p")
    cfg = Config(items=[item], request_delay_seconds=0)
    store = Store(str(tmp_path / "h.db"))
    for p in (10, 9, 11):
        run_once(cfg, store, StatusN(), lambda u, p=p: PriceResult("t", p))
    run_once(cfg, store, StatusN(), lambda u: (_ for _ in ()).throw(ValueError("blocked")))
    assert [p for _, p in store.price_history(item.url)] == [10, 9, 11]
    assert store.info(item.url)["last_error"] == "blocked"


def test_notifier_status_template_is_single_line(monkeypatch):
    from robodiscounts.notifier import WhatsAppNotifier
    calls = []
    class R: ok = True
    monkeypatch.setattr("requests.post", lambda url, **kw: calls.append(kw["json"]) or R())
    monkeypatch.setenv("WHATSAPP_STATUS_TEMPLATE", "health")
    WhatsAppNotifier("t", "1", "+52", None).send_status("a\n\nb\t  c")
    param = calls[-1]["template"]["components"][0]["parameters"][0]["text"]
    assert calls[-1]["template"]["name"] == "health" and param == "a b c"
    monkeypatch.delenv("WHATSAPP_STATUS_TEMPLATE")
    WhatsAppNotifier("t", "1", "+52", None).send_status("plain")
    assert calls[-1]["type"] == "text"


def _populated(tmp_path):
    items = [
        Item('Evil <script>alert(1)</script> Box', "https://www.bestbuy.com/site/x/1111111.p", target_price=90),
        Item("Broken one", "https://www.cardkingdom.com/catalog/item/1"),
        Item("Gone", "https://www.bestbuy.com/site/x/2222222.p"),
        Item("Quiet", "https://www.tcgplayer.com/product/5", target_price=1),
    ]
    cfg = Config(items=items, request_delay_seconds=0, fail_alert_after=0)
    store = Store(str(tmp_path / "dash.db"))
    def fetch(url):
        if "cardkingdom" in url: raise ValueError("Could not find price <b>")
        if "2222222" in url: return PriceResult("t", 30, in_stock=False)
        if "1111111" in url: return PriceResult("t", 80, in_stock=True)
        return PriceResult("t", 25)
    for _ in range(3):
        run_once(cfg, store, StatusN(), fetch)
    return cfg, store


def test_dashboard_statuses_and_escaping(tmp_path):
    from robodiscounts.dashboard import render
    cfg, store = _populated(tmp_path)
    html = render(cfg, store)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "Could not find price &lt;b&gt;" in html
    for label in ("deal", "failing", "sold out", "watching"):
        assert f'badge {label.replace(" ", "-")}">{label}<' in html
    assert html.index("Evil") < html.index("Broken one") < html.index("Gone") < html.index("Quiet")
    assert "$80.00" in html and "viewport" in html


def test_dashboard_cli_needs_no_credentials(tmp_path, monkeypatch):
    from robodiscounts import cli
    for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TO"):
        monkeypatch.delenv(k, raising=False)
    cfgfile = tmp_path / "c.yaml"
    cfgfile.write_text(f"db_path: {tmp_path}/x.db\nitems:\n  - name: a\n    url: https://www.tcgplayer.com/product/1\n")
    out = tmp_path / "site" / "index.html"
    monkeypatch.setattr("sys.argv", ["robodiscounts", "dashboard", "-c", str(cfgfile), "-o", str(out)])
    cli.main()
    assert "Discount Watch" in out.read_text()


def test_msrp_rule_default_and_percentages():
    res = PriceResult("t", 47.50)
    assert "95% of MSRP $49.99" in evaluate(Item("a", "u", msrp=49.99), res, None)       # default 100%
    assert evaluate(Item("a", "u", msrp=49.99), PriceResult("t", 49.99), None)           # exactly MSRP
    assert not evaluate(Item("a", "u", msrp=49.99), PriceResult("t", 60), None)          # above MSRP
    assert not evaluate(Item("a", "u", msrp=49.99, max_percent_of_msrp=90), res, None)   # needs 10% off
    assert evaluate(Item("a", "u", msrp=49.99, max_percent_of_msrp=130), PriceResult("t", 60), None)


def test_msrp_alert_end_to_end_and_sold_out_ignored(tmp_path):
    item = Item("ETB", "https://www.bestbuy.com/site/x/1234567.p", msrp=50)
    sent, _ = _run(tmp_path, item, [PriceResult("t", 70), PriceResult("t", 48), PriceResult("t", 48)])
    assert len(sent) == 1 and "96% of MSRP $50.00" in sent[0]
    sent, _ = _run(tmp_path, item, [PriceResult("t", 30, in_stock=False)])
    assert sent == []


def test_config_msrp_validation(tmp_path):
    import pytest
    from robodiscounts.config import load_config
    def cfg(extra):
        f = tmp_path / "c.yaml"
        f.write_text("items:\n  - name: a\n    url: https://www.tcgplayer.com/product/1\n" + extra)
        return load_config(str(f))
    assert cfg("    msrp: 49.99\n    max_percent_of_msrp: 90\n").items[0].msrp == 49.99
    with pytest.raises(ValueError):
        cfg("    msrp: 0\n")
    with pytest.raises(ValueError):
        cfg("    max_percent_of_msrp: 90\n")


def test_dashboard_shows_percent_of_msrp(tmp_path):
    from robodiscounts.dashboard import render
    item = Item("ETB", "https://www.bestbuy.com/site/x/1234567.p", msrp=50)
    cfg = Config(items=[item], request_delay_seconds=0, fail_alert_after=0)
    store = Store(str(tmp_path / "m.db"))
    run_once(cfg, store, StatusN(), lambda u: PriceResult("t", 45))
    html = render(cfg, store)
    assert "90%" in html and "of $50.00" in html


def _history_item(**kw):
    return Item("ETB", "https://www.bestbuy.com/site/x/1234567.p", **kw)


def test_below_average_rule_needs_enough_history(tmp_path):
    item = _history_item(below_avg_percent=10)
    # 4 earlier reads is not enough history yet, even though 70 is far below the average
    sent, store = _run(tmp_path, item, [PriceResult("t", 100)] * 4 + [PriceResult("t", 70)])
    assert sent == []
    # 5 earlier reads (average 94): a drop to 80 is 15% below it and alerts once, not twice
    sent, store = _run(tmp_path, item, [PriceResult("t", 80), PriceResult("t", 80)], store)
    assert len(sent) == 1 and "15% below the 30-day average $94.00" in sent[0]


def test_below_average_threshold_not_met(tmp_path):
    item = _history_item(below_avg_percent=10)
    sent, _ = _run(tmp_path, item, [PriceResult("t", 100)] * 6 + [PriceResult("t", 95)])
    assert sent == []  # only 5% below average


def test_new_low_rule(tmp_path):
    item = _history_item(alert_on_new_low=True)
    prices = [100, 99, 101, 100, 98, 100, 97, 97, 96]
    sent, _ = _run(tmp_path, item, [PriceResult("t", p) for p in prices])
    # 97 (after 5 reads) and 96 are new lows; the repeated 97 is not a new low
    assert len(sent) == 2 and "new low, previous best $98.00" in sent[0]


def test_history_ignores_sold_out_reads_and_old_reads(tmp_path):
    from datetime import datetime, timedelta, timezone
    item = _history_item(below_avg_percent=10, alert_on_new_low=True)
    store = Store(str(tmp_path / "w.db"))
    # a stale price of 5 recorded while sold out must not become the "all-time low"
    for _ in range(5):
        store.add_history(item.url, 5.0, False, ok=True)
    assert store.price_stats(item.url, 30)["n_all"] == 0
    # reads older than the window count for the all-time low but not for the average
    old = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(5):
        store.db.execute("INSERT INTO history(url,ts,price,in_stock,ok) VALUES(?,?,?,1,1)", (item.url, old, 40.0))
    store.db.commit()
    st = store.price_stats(item.url, 30)
    assert st["n_all"] == 5 and st["low"] == 40.0 and st["n_window"] == 0 and st["avg"] is None


def test_history_rules_off_by_default(tmp_path):
    sent, _ = _run(tmp_path, _history_item(), [PriceResult("t", 100)] * 6 + [PriceResult("t", 1)])
    assert sent == []


def test_history_config_validation(tmp_path):
    import pytest
    from robodiscounts.config import load_config
    def cfg(extra):
        f = tmp_path / "c.yaml"
        f.write_text("items:\n  - name: a\n    url: https://www.tcgplayer.com/product/1\n" + extra)
        return load_config(str(f))
    it = cfg("    below_avg_percent: 10\n    alert_on_new_low: true\n    history_days: 14\n").items[0]
    assert (it.below_avg_percent, it.alert_on_new_low, it.history_days) == (10, True, 14)
    for bad in ("    below_avg_percent: 0\n", "    below_avg_percent: 100\n", "    history_days: 0\n"):
        with pytest.raises(ValueError):
            cfg(bad)


def test_dashboard_average_column(tmp_path):
    from robodiscounts.dashboard import render
    item = _history_item()
    cfg = Config(items=[item], request_delay_seconds=0, fail_alert_after=0)
    store = Store(str(tmp_path / "a.db"))
    for p in (10, 20):
        run_once(cfg, store, StatusN(), lambda u, p=p: PriceResult("t", p))
    html = render(cfg, store)
    assert "Average" in html and "$15.00" in html
