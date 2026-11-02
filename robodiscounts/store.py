import sqlite3
from typing import Optional


class Store:
    """Remembers last seen / last notified price per URL to avoid duplicate alerts."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS prices ("
            "url TEXT PRIMARY KEY, last_price REAL, last_notified_price REAL)"
        )

    def last_price(self, url: str) -> Optional[float]:
        r = self.db.execute("SELECT last_price FROM prices WHERE url=?", (url,)).fetchone()
        return r[0] if r else None

    def last_notified(self, url: str) -> Optional[float]:
        r = self.db.execute(
            "SELECT last_notified_price FROM prices WHERE url=?", (url,)
        ).fetchone()
        return r[0] if r else None

    def save(self, url: str, price: float, notified: bool):
        self.db.execute(
            "INSERT INTO prices(url,last_price,last_notified_price) VALUES(?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET last_price=excluded.last_price, "
            "last_notified_price=CASE WHEN ? THEN excluded.last_price "
            "ELSE last_notified_price END",
            (url, price, price if notified else None, notified),
        )
        self.db.commit()
