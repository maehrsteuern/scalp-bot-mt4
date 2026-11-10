"""Market data access via ccxt (public endpoints only) plus CSV helpers.

`MarketData.fetch` returns closed candles only and caches per (symbol, timeframe) so the
bot loop can call it every few seconds without hammering the exchange.
"""
from __future__ import annotations

import csv
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

import ccxt

from .config import ExchangeCfg
from .models import Candle

log = logging.getLogger("ewbot.data")

_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 7 * 86400,
    "M": 30 * 86400,   # ccxt convention
    "y": 365 * 86400,
}

RETRY_DELAYS = (1.0, 2.0, 4.0)   # backoff between attempts on ccxt.NetworkError


def timeframe_ms(timeframe: str) -> int:
    """'15m' -> 900000. Same unit convention as ccxt.parse_timeframe."""
    tf = timeframe.strip()
    if len(tf) < 2:
        raise ValueError(f"invalid timeframe '{timeframe}'")
    unit = tf[-1]
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"invalid timeframe unit in '{timeframe}'")
    try:
        amount = int(tf[:-1])
    except ValueError as exc:
        raise ValueError(f"invalid timeframe '{timeframe}'") from exc
    if amount <= 0:
        raise ValueError(f"invalid timeframe '{timeframe}'")
    return amount * _UNIT_SECONDS[unit] * 1000


def trust_proxy_env(exchange: Any) -> None:
    """ccxt disables requests' trust_env; re-enable so HTTPS_PROXY / REQUESTS_CA_BUNDLE apply."""
    session = getattr(exchange, "session", None)
    if session is not None:
        try:
            session.trust_env = True
        except Exception:  # pragma: no cover - exotic session objects
            pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_candle(row: Any) -> Optional[Candle]:
    try:
        ts, o, h, l, c, v = row[:6]
        if ts is None or o is None or h is None or l is None or c is None:
            return None
        return Candle(int(ts), float(o), float(h), float(l), float(c), float(v or 0.0))
    except (TypeError, ValueError, IndexError):
        return None


class MarketData:
    """ccxt-backed OHLCV source.

    exchange: optional pre-built ccxt-like object (tests inject a fake with `fetch_ohlcv`).
    clock:    optional callable returning "now" in epoch ms (tests).
    sleep:    optional sleep function used for retry backoff (tests pass a no-op).
    page_limit: max candles per request (Crypto.com caps candlesticks at 300).
    """

    def __init__(self, cfg: ExchangeCfg, exchange: Any = None,
                 clock: Callable[[], int] | None = None,
                 sleep: Callable[[float], None] | None = None,
                 page_limit: int = 300) -> None:
        if hasattr(cfg, "exchange") and not isinstance(cfg, ExchangeCfg):   # tolerate BotCfg
            cfg = cfg.exchange  # type: ignore[assignment]
        self.cfg: ExchangeCfg = cfg
        self.clock = clock or _now_ms
        self.sleep = sleep or time.sleep
        self.page_limit = max(1, int(page_limit))
        if exchange is None:
            klass = getattr(ccxt, cfg.id)
            exchange = klass({"enableRateLimit": bool(cfg.rate_limit)})
            trust_proxy_env(exchange)
        self.exchange = exchange
        # (symbol, timeframe) -> (closed candles, limit requested)
        self._cache: dict[tuple[str, str], tuple[list[Candle], int]] = {}

    # ------------------------------------------------------------------ helpers
    timeframe_ms = staticmethod(timeframe_ms)

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call `fn`, retrying on ccxt.NetworkError with 1s/2s/4s backoff."""
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except ccxt.NetworkError as exc:
                if attempt >= len(RETRY_DELAYS):
                    raise
                delay = RETRY_DELAYS[attempt]
                attempt += 1
                log.warning("network error (%s), retry %d/%d in %.0fs", exc, attempt,
                            len(RETRY_DELAYS), delay)
                self.sleep(delay)

    def _closed(self, rows: list[Any], tf_ms: int, now: int) -> list[Candle]:
        out: dict[int, Candle] = {}
        for row in rows or []:
            candle = _to_candle(row)
            if candle is None:
                continue
            if candle.ts + tf_ms > now:          # still forming
                continue
            out[candle.ts] = candle
        return [out[k] for k in sorted(out)]

    # --------------------------------------------------------------------- API
    def fetch(self, symbol: str, timeframe: str, limit: int | None = None) -> list[Candle]:
        """Closed candles (ascending). Served from cache until a new candle could have closed."""
        limit = int(limit or self.cfg.ohlcv_limit)
        tf = timeframe_ms(timeframe)
        now = self.clock()
        key = (symbol, timeframe)
        cached = self._cache.get(key)
        if cached is not None:
            candles, cached_limit = cached
            if candles and cached_limit >= limit:
                next_close = candles[-1].ts + 2 * tf   # close time of the candle after the last closed one
                if now < next_close:
                    return candles[-limit:]
        try:
            candles = self._fetch_recent(symbol, timeframe, limit, tf, now)
        except Exception:
            if cached is not None and cached[0]:
                log.exception("fetch %s %s failed, serving stale cache", symbol, timeframe)
                return cached[0][-limit:]
            raise
        self._cache[key] = (candles, limit)
        return candles[-limit:]

    def _fetch_recent(self, symbol: str, timeframe: str, limit: int, tf: int, now: int) -> list[Candle]:
        want = limit + 1                         # +1 because the forming candle is dropped
        if want <= self.page_limit:
            rows = self._call(self.exchange.fetch_ohlcv, symbol, timeframe, limit=want)
            return self._closed(rows, tf, now)[-limit:]
        since = (now // tf) * tf - limit * tf
        return self.fetch_history(symbol, timeframe, since, now)[-limit:]

    def fetch_history(self, symbol: str, timeframe: str, since_ms: int,
                      until_ms: int | None = None) -> list[Candle]:
        """All closed candles with since_ms <= ts < until_ms, paginating forward with `since`."""
        tf = timeframe_ms(timeframe)
        now = self.clock()
        until = min(until_ms if until_ms is not None else now, now)
        out: dict[int, Candle] = {}
        since = int(since_ms)
        while since < until:
            rows = self._call(self.exchange.fetch_ohlcv, symbol, timeframe, since=since,
                              limit=self.page_limit)
            page = [c for c in self._closed(rows, tf, now) if c.ts >= since_ms and c.ts < until]
            if not page:
                # Gap in the data (e.g. exchange outage)? Jump forward one page and try again.
                raw = [_to_candle(r) for r in rows or []]
                raw_ts = [c.ts for c in raw if c is not None]
                if raw_ts and max(raw_ts) >= since:
                    since = max(raw_ts) + tf
                    continue
                break
            for c in page:
                out[c.ts] = c
            next_since = page[-1].ts + tf
            if next_since <= since:
                break
            since = next_since
        return [out[k] for k in sorted(out)]

    def clear_cache(self) -> None:
        self._cache.clear()

    # --------------------------------------------------------------------- CSV
    @staticmethod
    def from_csv(path: str | os.PathLike[str]) -> list[Candle]:
        candles: dict[int, Candle] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                c = _to_candle([row.get("ts"), row.get("open"), row.get("high"), row.get("low"),
                                row.get("close"), row.get("volume")])
                if c is None:
                    # ts may be written as float string
                    try:
                        c = Candle(int(float(row["ts"])), float(row["open"]), float(row["high"]),
                                   float(row["low"]), float(row["close"]), float(row.get("volume") or 0))
                    except (KeyError, TypeError, ValueError):
                        continue
                candles[c.ts] = c
        return [candles[k] for k in sorted(candles)]

    @staticmethod
    def to_csv(candles: list[Candle], path: str | os.PathLike[str]) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ts", "open", "high", "low", "close", "volume"])
            for c in candles:
                writer.writerow([c.ts, repr(c.open), repr(c.high), repr(c.low), repr(c.close),
                                 repr(c.volume)])
        os.replace(tmp, p)
