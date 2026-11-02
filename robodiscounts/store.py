import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Tuple


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """Per-URL state (last price, stock, alerts, failures) plus a price history log."""

    # Columns added after the first release; older databases get them via ALTER TABLE.
    _EXTRA_COLUMNS = {
        "in_stock": "INTEGER",
        "fail_streak": "INTEGER DEFAULT 0",
        "last_error": "TEXT",
        "last_checked": "TEXT",
    }

    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS prices ("
            "url TEXT PRIMARY KEY, last_price REAL, last_notified_price REAL)"
        )
        have = {r[1] for r in self.db.execute("PRAGMA table_info(prices)")}
        for col, decl in self._EXTRA_COLUMNS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE prices ADD COLUMN {col} {decl}")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            "url TEXT NOT NULL, ts TEXT NOT NULL, price REAL, in_stock INTEGER, "
            "ok INTEGER NOT NULL, error TEXT)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS history_url_ts ON history(url, ts)")
        self.db.commit()

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

    def fail_streak(self, url: str) -> int:
        return self._get("fail_streak", url) or 0

    def save(self, url: str, price: float, notified_price: Optional[float], in_stock: Optional[bool]):
        """notified_price: the price we last alerted at, or None once it no longer qualifies.
        A successful read also clears the failure streak."""
        self.db.execute(
            "INSERT INTO prices(url,last_price,last_notified_price,in_stock,fail_streak,last_error,last_checked) "
            "VALUES(?,?,?,?,0,NULL,?) "
            "ON CONFLICT(url) DO UPDATE SET last_price=excluded.last_price, "
            "last_notified_price=excluded.last_notified_price, in_stock=excluded.in_stock, "
            "fail_streak=0, last_error=NULL, last_checked=excluded.last_checked",
            (url, price, notified_price, None if in_stock is None else int(in_stock), _now()),
        )
        self.db.commit()

    def record_failure(self, url: str, error: str) -> int:
        """Count one more failed read for this URL and return the consecutive-failure streak."""
        self.db.execute(
            "INSERT INTO prices(url,fail_streak,last_error,last_checked) VALUES(?,1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET fail_streak=COALESCE(fail_streak,0)+1, "
            "last_error=excluded.last_error, last_checked=excluded.last_checked",
            (url, error, _now()),
        )
        self.db.commit()
        return self.fail_streak(url)

    def add_history(self, url: str, price: Optional[float], in_stock: Optional[bool],
                    ok: bool, error: Optional[str] = None):
        self.db.execute(
            "INSERT INTO history(url,ts,price,in_stock,ok,error) VALUES(?,?,?,?,?,?)",
            (url, _now(), price, None if in_stock is None else int(in_stock), int(ok), error),
        )
        self.db.commit()

    def price_history(self, url: str, limit: int = 500) -> List[Tuple[str, float]]:
        """Successful reads, oldest first: [(timestamp, price), ...] (the latest `limit`)."""
        rows = self.db.execute(
            "SELECT ts, price FROM (SELECT rowid AS id, ts, price FROM history "
            "WHERE url=? AND ok=1 ORDER BY ts DESC, id DESC LIMIT ?) ORDER BY ts, id",
            (url, limit),
        ).fetchall()
        return rows

    def info(self, url: str) -> dict:
        r = self.db.execute(
            "SELECT last_price,last_notified_price,in_stock,fail_streak,last_error,last_checked "
            "FROM prices WHERE url=?",
            (url,),
        ).fetchone()
        if not r:
            return {}
        return {
            "last_price": r[0], "last_notified": r[1],
            "in_stock": None if r[2] is None else bool(r[2]),
            "fail_streak": r[3] or 0, "last_error": r[4], "last_checked": r[5],
        }
