"""Append-only CSV journal for German tax (Par. 23 EStG, private sales). One row per executed fill."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

HEADER = ["date", "coin", "side", "qty", "price", "fee", "quote", "order_id", "trade_id", "note"]


class Journal:
    def __init__(self, path: str):
        self.path = path
        self._keys: set[tuple[str, str]] = set()
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    self._keys.add((row.get("order_id", ""), row.get("side", "")))

    def has(self, order_id: str, side: str) -> bool:
        return (order_id, side) in self._keys

    def append(self, ts_ms: int, coin: str, side: str, qty: float, price: float, fee: float,
               order_id: str, trade_id: str, note: str = "") -> bool:
        """Append one fill. Returns False (and writes nothing) if this order_id/side is already logged."""
        key = (str(order_id), side)
        if key in self._keys:
            return False
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        new = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
        date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HEADER)
            w.writerow([date, coin, side, f"{qty:.8f}", f"{price:.8f}", f"{fee:.8f}",
                        f"{qty * price:.8f}", order_id, trade_id, note])
            f.flush()
            os.fsync(f.fileno())
        self._keys.add(key)
        return True
