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


def fetch_range(instrument: str, tf: str, start_ts: int, end_ts: int | None = None, pause: float = 0.15) -> List[list]:
    """Page backwards from end_ts (default: now) until start_ts or until the API returns nothing. Closed candles only."""
    step = TF_MS[tf]
    rows = {}
    end = end_ts if end_ts is not None else int(time.time() * 1000)
    while end > start_ts:
        data = _get(instrument, tf, 300, end, retries=8)
        if not data:
            # the exchange has holes (e.g. June 2021) and coins that were not listed yet: skip one page back
            end -= 20 * step      # small step: the API returns nothing if its short look-back window holds no candle
            time.sleep(pause)
            continue
        new = 0
        for d in data:
            t = int(d["t"])
            if t not in rows:
                rows[t] = [t, float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]), float(d["v"])]
                new += 1
        if min(rows) <= start_ts:
            break
        end = min(end, min(rows)) - 1 if new else end - 20 * step
        time.sleep(pause)
    now = int(time.time() * 1000)
    return [rows[t] for t in sorted(rows) if t >= start_ts and t + step <= now]


def merge_rows(*lists: List[list]) -> List[list]:
    """Merge candle lists, dedupe by open time (later list wins), ascending."""
    m = {}
    for lst in lists:
        for r in lst:
            m[int(r[0])] = r
    return [m[t] for t in sorted(m)]


def gap_report(rows: List[list], tf: str) -> dict:
    """Missing candles inside the series: number of gaps, missing candles, longest gap (in candles)."""
    step = TF_MS[tf]
    gaps, missing, longest = 0, 0, 0
    for a, b in zip(rows, rows[1:]):
        n = int((b[0] - a[0]) // step) - 1
        if n > 0:
            gaps += 1; missing += n; longest = max(longest, n)
    return dict(gaps=gaps, missing=missing, longest=longest)


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


def extend_history(coins=("BTC", "ETH", "SOL"), tfs=("30m", "4h"), start_ts: int = 1609459200000, threads: int = 3):
    """Extend the cache back to start_ts (default 2021-01-01) and forward to now. Existing cache is kept and merged."""
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(os.path.join(DATA_DIR, "hist"), exist_ok=True)

    def job(c):
        for tf in tfs:
            try:
                old = load_history(c, tf)
            except Exception:
                old = []
            new = fetch_range(f"{c}_USD", tf, start_ts)
            rows = merge_rows(old, new)
            with open(cache_path(c, tf), "w") as f:
                json.dump(rows, f)
            g = gap_report(rows, tf)
            print(f"{c} {tf}: {len(rows)} candles {time.strftime('%Y-%m-%d', time.gmtime(rows[0][0]/1000))} .. "
                  f"{time.strftime('%Y-%m-%d', time.gmtime(rows[-1][0]/1000))} gaps={g}", flush=True)

    with ThreadPoolExecutor(max_workers=threads) as ex:
        list(ex.map(job, coins))


if __name__ == "__main__":
    import sys
    if "--extend" in sys.argv:
        extend_history()
    else:
        download_all()
