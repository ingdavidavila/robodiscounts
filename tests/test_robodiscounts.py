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
