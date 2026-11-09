"""Download and cache long candle history from the public Crypto.com Exchange API (no key needed).

Cache files: data/hist/<COIN>_<tf>.json, rows [t,o,h,l,c,v], ascending, only CLOSED candles.
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.parse
from typing import List

BASE = "https://api.crypto.com/exchange/v1/public/get-candlestick"
TF_MS = {"5m": 300_000, "30m": 1_800_000, "4h": 14_400_000, "1D": 86_400_000}
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _get(instrument: str, tf: str, count: int, end_ts: int | None, retries: int = 4):
    q = {"instrument_name": instrument, "timeframe": tf, "count": count}
    if end_ts is not None:
        q["end_ts"] = end_ts
    url = BASE + "?" + urllib.parse.urlencode(q)
    for k in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                j = json.load(r)
            if j.get("code") == 0:
                return j["result"]["data"]
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    return []


def fetch_history(instrument: str, tf: str, max_candles: int = 30000, pause: float = 0.15) -> List[list]:
    """Page backwards until the API returns nothing new. Drops the still-open candle."""
    step = TF_MS[tf]
    rows = {}
    end = None
    while len(rows) < max_candles:
        data = _get(instrument, tf, 300, end)
        if not data:
            break
        new = 0
        for d in data:
            t = int(d["t"])
            if t not in rows:
                rows[t] = [t, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
                new += 1
        if new == 0:
            break
        end = min(rows) - 1
        time.sleep(pause)
    out = [rows[t] for t in sorted(rows)]
    now = int(time.time() * 1000)
    return [r for r in out if r[0] + step <= now]  # closed only


def cache_path(coin: str, tf: str) -> str:
    return os.path.join(DATA_DIR, "hist", f"{coin}_{tf}.json")


def load_history(coin: str, tf: str) -> List[list]:
    with open(cache_path(coin, tf)) as f:
        return json.load(f)


def download_all(coins=("BTC", "ETH", "SOL"), tfs=("30m", "4h")):
    os.makedirs(os.path.join(DATA_DIR, "hist"), exist_ok=True)
    for c in coins:
        for tf in tfs:
            rows = fetch_history(f"{c}_USD", tf)
            with open(cache_path(c, tf), "w") as f:
                json.dump(rows, f)
            if rows:
                a = time.strftime("%Y-%m-%d", time.gmtime(rows[0][0] / 1000))
                b = time.strftime("%Y-%m-%d", time.gmtime(rows[-1][0] / 1000))
                print(f"{c} {tf}: {len(rows)} candles {a} .. {b}")
            else:
                print(f"{c} {tf}: nothing downloaded")


if __name__ == "__main__":
    download_all()
