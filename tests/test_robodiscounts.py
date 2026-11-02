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
        def send(self, b): self.sent.append(b)
    item = Item("a", "https://www.amazon.com/dp/1", target_price=90)
    cfg = Config(items=[item], request_delay_seconds=0)
    store, n = Store(str(tmp_path / "t.db")), N()
    fetch = lambda url: PriceResult("t", 80)
    run_once(cfg, store, n, fetch)
    run_once(cfg, store, n, fetch)
    assert len(n.sent) == 1
