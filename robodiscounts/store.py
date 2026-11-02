import sqlite3
from typing import Optional


class Store:
    """Remembers last seen price, stock state and last alerted price per URL."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS prices ("
            "url TEXT PRIMARY KEY, last_price REAL, last_notified_price REAL, in_stock INTEGER)"
        )
        try:  # databases created before stock tracking lack this column
            self.db.execute("ALTER TABLE prices ADD COLUMN in_stock INTEGER")
        except sqlite3.OperationalError:
            pass

    def _get(self, col: str, url: str):
        r = self.db.execute(f"SELECT {col} FROM prices WHERE url=?", (url,)).fetchone()
        return r[0] if r else None

    def last_price(self, url: str) -> Optional[float]:
        return self._get("last_price", url)

    def last_notified(self, url: str) -> Optional[float]:
        return self._get("last_notified_price", url)

    def was_in_stock(self, url: str) -> Optional[bool]:
        v = self._get("in_stock", url)
        return None if v is None else bool(v)

    def save(self, url: str, price: float, notified_price: Optional[float], in_stock: Optional[bool]):
        """notified_price: the price we last alerted at, or None once it no longer qualifies."""
        self.db.execute(
            "INSERT INTO prices(url,last_price,last_notified_price,in_stock) VALUES(?,?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET last_price=excluded.last_price, "
            "last_notified_price=excluded.last_notified_price, in_stock=excluded.in_stock",
            (url, price, notified_price, None if in_stock is None else int(in_stock)),
        )
        self.db.commit()
