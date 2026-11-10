import ccxt
import pytest

from ewbot.config import ExchangeCfg
from ewbot.data import MarketData, timeframe_ms
from ewbot.models import Candle

TF = 15 * 60_000
BASE = 1_700_000_100_000 - (1_700_000_100_000 % TF)


class FakeExchange:
    """Serves synthetic 15m candles up to and including the one forming at `now`."""

    def __init__(self, clock, fail_times=0):
        self.clock = clock
        self.calls = []
        self.fail_times = fail_times

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None, params=None):
        self.calls.append((symbol, timeframe, since, limit))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ccxt.NetworkError("timeout")
        now = self.clock()
        last = (now // TF) * TF                     # forming candle
        start = since if since is not None else last - (limit - 1) * TF
        start = max(start, BASE)
        rows = []
        ts = start
        while ts <= last and (limit is None or len(rows) < limit):
            i = (ts - BASE) // TF
            rows.append([ts, 100 + i, 101 + i, 99 + i, 100.5 + i, 10.0])
            ts += TF
        return rows


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def test_timeframe_ms():
    assert timeframe_ms("15m") == 900_000
    assert timeframe_ms("4h") == 14_400_000
    assert timeframe_ms("1d") == 86_400_000
    assert MarketData.timeframe_ms("30m") == 1_800_000
    with pytest.raises(ValueError):
        timeframe_ms("abc")


def test_fetch_drops_unclosed_candle_and_caches():
    clock = Clock(BASE + 300 * TF + 5 * 60_000)        # 5 minutes into a forming candle
    ex = FakeExchange(clock)
    md = MarketData(ExchangeCfg(), exchange=ex, clock=clock, sleep=lambda s: None)
    candles = md.fetch("BTC/USD", "15m", limit=50)
    assert len(candles) == 50
    assert all(isinstance(c, Candle) for c in candles)
    assert candles[-1].ts == BASE + 299 * TF           # forming candle at 300 dropped
    assert all(b.ts - a.ts == TF for a, b in zip(candles, candles[1:]))
    assert len(ex.calls) == 1

    clock.now += 5 * 60_000                            # still inside the same candle
    assert md.fetch("BTC/USD", "15m", limit=50) == candles
    assert md.fetch("BTC/USD", "15m", limit=20) == candles[-20:]
    assert len(ex.calls) == 1

    clock.now = BASE + 301 * TF + 1                    # candle 300 has closed
    newer = md.fetch("BTC/USD", "15m", limit=50)
    assert len(ex.calls) == 2
    assert newer[-1].ts == BASE + 300 * TF

    md.fetch("ETH/USD", "15m", limit=50)               # cache is per symbol
    assert len(ex.calls) == 3


def test_fetch_retries_network_errors_with_backoff():
    clock = Clock(BASE + 300 * TF + 1)
    ex = FakeExchange(clock, fail_times=2)
    sleeps = []
    md = MarketData(ExchangeCfg(), exchange=ex, clock=clock, sleep=sleeps.append)
    assert len(md.fetch("BTC/USD", "15m", limit=10)) == 10
    assert sleeps == [1.0, 2.0]

    ex2 = FakeExchange(clock, fail_times=10)
    sleeps2 = []
    md2 = MarketData(ExchangeCfg(), exchange=ex2, clock=clock, sleep=sleeps2.append)
    with pytest.raises(ccxt.NetworkError):
        md2.fetch("BTC/USD", "15m", limit=10)
    assert sleeps2 == [1.0, 2.0, 4.0]


def test_fetch_large_limit_paginates():
    clock = Clock(BASE + 1000 * TF + 1)
    ex = FakeExchange(clock)
    md = MarketData(ExchangeCfg(), exchange=ex, clock=clock, sleep=lambda s: None, page_limit=300)
    candles = md.fetch("BTC/USD", "15m", limit=500)
    assert len(candles) == 500 and candles[-1].ts == BASE + 999 * TF
    assert len(ex.calls) >= 2


def test_fetch_history_paginates_with_since():
    clock = Clock(BASE + 1000 * TF + 1)
    ex = FakeExchange(clock)
    md = MarketData(ExchangeCfg(), exchange=ex, clock=clock, sleep=lambda s: None, page_limit=100)
    hist = md.fetch_history("BTC/USD", "15m", BASE + 10 * TF, BASE + 260 * TF)
    assert len(hist) == 250
    assert hist[0].ts == BASE + 10 * TF and hist[-1].ts == BASE + 259 * TF
    assert len(ex.calls) == 3
    assert all(call[2] is not None for call in ex.calls)
    # until defaults to now: forming candle excluded
    tail = md.fetch_history("BTC/USD", "15m", BASE + 990 * TF)
    assert tail[-1].ts == BASE + 999 * TF


def test_csv_roundtrip(tmp_path):
    candles = [Candle(BASE + i * TF, 1.5 + i, 2.25 + i, 1.0 + i, 2.0 + i, 0.1 * i) for i in range(5)]
    path = tmp_path / "d" / "btc.csv"
    MarketData.to_csv(candles, path)
    assert path.read_text().splitlines()[0] == "ts,open,high,low,close,volume"
    assert MarketData.from_csv(path) == candles
