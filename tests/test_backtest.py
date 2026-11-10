"""Backtester tests on a tiny synthetic dataset with stub strategy / broker / risk (no network)."""
from __future__ import annotations

import csv
import math

import pytest

from ewbot.backtest import HTF_WARMUP, BacktestResult, compute_metrics, run_backtest
from ewbot.config import BotCfg, MarketCfg
from ewbot.models import (Bias, Candle, Fill, HtfContext, PatternType, Position, SetupType, Side, Signal,
                          TradeRecord, WaveCount)

M15, H1, H4 = 15 * 60_000, 3_600_000, 4 * 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)


def synthetic_15m(n: int) -> list[Candle]:
    out = []
    for i in range(n):
        mid = 100.0 + 5.0 * math.sin(i / 12.0) + i * 0.01
        o = mid - 0.1
        c = mid + 0.1 * (1 if i % 3 else -1)
        out.append(Candle(T0 + i * M15, o, max(o, c) + 0.6, min(o, c) - 0.6, c, 1.0))
    return out


def resample(candles: list[Candle], tf_ms: int) -> list[Candle]:
    groups: dict[int, list[Candle]] = {}
    for c in candles:
        groups.setdefault(c.ts - c.ts % tf_ms, []).append(c)
    return [Candle(ts, g[0].open, max(x.high for x in g), min(x.low for x in g), g[-1].close, sum(x.volume for x in g))
            for ts, g in sorted(groups.items())]


class SimPaperBroker:
    """Minimal paper broker: full exit at stop (checked first) or tp1, no fees."""

    def __init__(self, equity: float):
        self.cash_ = equity
        self.pos: list[Position] = []
        self.closed: list[TradeRecord] = []
        self.last: dict[str, float] = {}
        self.n = 0

    def equity(self):
        return self.cash_ + sum((self.last.get(p.symbol, p.entry) - p.entry) * p.qty_open * p.side.sign
                                for p in self.pos)

    def cash(self):
        return self.cash_

    def positions(self):
        return list(self.pos)

    def open(self, signal, qty, ts):
        self.n += 1
        p = Position(f"p{self.n}", signal.symbol, signal.side, qty, signal.entry, signal.stop, signal.tp1,
                     signal.tp2, ts, signal.setup, signal.timeframe)
        p.fees = 0.01
        self.cash_ -= p.fees
        self.pos.append(p)
        return p

    def close(self, position, qty, price_hint, ts, reason):
        pnl = (price_hint - position.entry) * position.qty_open * position.side.sign - position.fees
        self.cash_ += pnl + position.fees
        position.qty_open = 0.0
        self.pos.remove(position)
        self.closed.append(TradeRecord(position, ts, price_hint, pnl, 0.0, reason))
        return Fill(ts, position.symbol, position.side.opposite, qty, price_hint, 0.0, reason)

    def update_stop(self, position, new_stop):
        position.stop = new_stop

    def on_candle(self, symbol, candle):
        self.last[symbol] = candle.close
        out = []
        for p in [p for p in self.pos if p.symbol == symbol]:
            if candle.low <= p.stop:
                self.close(p, p.qty_open, p.stop, candle.ts + M15, "stop")
                out.append(self.closed[-1])
            elif candle.high >= p.tp1:
                self.close(p, p.qty_open, p.tp1, candle.ts + M15, "tp1")
                out.append(self.closed[-1])
        return out

    def trades(self):
        return list(self.closed)

    def last_price(self, symbol):
        return self.last.get(symbol, 0.0)


class EveryNStrategy:
    """Long signal every n-th evaluated bar; records what it was shown (look-ahead checks)."""

    def __init__(self, n: int = 7):
        self.n = n
        self.calls = 0
        self.views: list[tuple[int, int, dict[str, int]]] = []   # (exec close, n exec, {tf: last htf close})
        self._htf_last: dict[str, int] = {}

    def analyse_htf(self, timeframe, candles):
        self._htf_last[timeframe] = candles[-1].ts + (H1 if timeframe == "1h" else H4)
        self._htf_len = getattr(self, "_htf_len", {})
        self._htf_len[timeframe] = len(candles)
        return HtfContext(timeframe, Bias.BULL, None, None, 0.0, 0.0, 1.0)

    def evaluate(self, symbol, candles, htf):
        self.calls += 1
        self.views.append((candles[-1].ts + M15, len(candles), dict(self._htf_last), dict(self._htf_len)))
        if self.calls % self.n:
            return None
        c = candles[-1].close
        count = WaveCount(PatternType.IMPULSE, Side.LONG, [], [c - 2, c, c - 1], False, 0.8)
        setup = SetupType.WAVE3 if self.calls % 2 else SetupType.WAVE5
        return Signal(symbol, "15m", Side.LONG, setup, c, c - 1.0, c + 1.5, c + 3.0, candles[-1].ts, 0.8, count,
                      htf, ["test"])


class SimpleRisk:
    def __init__(self, risk_pct=5.0):
        self.risk_pct = risk_pct

    def position_size(self, equity, signal, market, min_notional):
        return equity * self.risk_pct / 100.0 / signal.risk_per_unit

    def can_open(self, now_ts, equity, open_positions, trades, symbol):
        if any(p.symbol == symbol for p in open_positions):
            return False, "one per symbol"
        return True, "ok"

    def set_day_start(self, equity, ts):
        pass

    def manage(self, position, candle, atr):
        return []


def make_cfg(lookback: int = 30) -> BotCfg:
    cfg = BotCfg()
    cfg.name = "bt-test"
    cfg.swing.lookback = lookback
    cfg.markets = [MarketCfg("BTC/USD")]
    return cfg


def dataset(n: int = 2000) -> dict:
    m15 = synthetic_15m(n)
    return {"BTC/USD": {"15m": m15, "1h": resample(m15, H1), "4h": resample(m15, H4)}}


def test_run_backtest_produces_metrics_and_equity_curve(tmp_path):
    data = dataset()
    strat = EveryNStrategy()
    res = run_backtest(make_cfg(), data, 20.0, strategy=strat, broker=SimPaperBroker(20.0), risk=SimpleRisk())
    assert isinstance(res, BacktestResult)
    assert len(res.equity_curve) == len(data["BTC/USD"]["15m"])
    assert all(b[0] > a[0] for a, b in zip(res.equity_curve, res.equity_curve[1:]))
    m = res.metrics
    for key in ("net_pnl", "return_pct", "win_rate", "profit_factor", "max_drawdown_pct", "avg_rr",
                "trades_per_setup", "trades", "fees_paid"):
        assert key in m
    assert m["trades"] == len(res.trades) > 5
    assert m["net_pnl"] == pytest.approx(res.final_equity - 20.0)
    assert m["fees_paid"] == pytest.approx(0.01 * m["trades"])
    assert set(m["trades_per_setup"]) <= {"wave3", "wave5"}
    assert 0.0 <= m["win_rate"] <= 100.0 and m["max_drawdown_pct"] >= 0.0
    # sized at 5 % risk: a full stop-out loses ~1 R, a tp1 hit wins ~1.5 R
    assert -1.2 < m["avg_rr"] < 1.6

    md = res.to_markdown()
    assert "Profit-Faktor" in md and "wave3" in md
    eq_path, tr_path = res.save_csv(tmp_path / "rep")
    rows = list(csv.reader(eq_path.open()))
    assert rows[0] == ["ts", "time_utc", "equity"] and len(rows) == len(res.equity_curve) + 1
    assert len(list(csv.reader(tr_path.open()))) == len(res.trades) + 1


def test_backtest_has_no_lookahead_and_respects_warmup():
    strat = EveryNStrategy(n=10_000)                     # never trades, just records views
    run_backtest(make_cfg(lookback=30), dataset(1500), 20.0, strategy=strat, broker=SimPaperBroker(20.0),
                 risk=SimpleRisk())
    assert strat.views
    first_close, first_len, _, first_htf_len = strat.views[0]
    assert first_len == 30
    assert min(first_htf_len.values()) >= HTF_WARMUP
    for exec_close, n_exec, htf_last, _ in strat.views:
        assert n_exec <= 30
        for tf, htf_close in htf_last.items():
            assert htf_close <= exec_close, f"{tf} candle closing {htf_close} seen at {exec_close}"
    # 4h warm-up (60 * 16 bars of 15m) dominates the 30-bar exec warm-up
    assert first_close == T0 + (HTF_WARMUP * 16) * M15


def test_compute_metrics_values():
    def tr(pnl, setup=SetupType.WAVE3):
        p = Position("x", "BTC/USD", Side.LONG, 1.0, 100.0, 99.0, 102.0, 104.0, T0, setup, "15m")
        p.tags["risk_quote"] = "1.0"
        return TradeRecord(p, T0, 100.0 + pnl, pnl, 0.0, "x")

    trades = [tr(2.0), tr(-1.0), tr(1.0, SetupType.WAVEC), tr(-1.0)]
    curve = [(1, 10.0), (2, 12.0), (3, 9.0), (4, 11.0)]
    m = compute_metrics(10.0, 11.0, trades, curve)
    assert m["win_rate"] == pytest.approx(50.0)
    assert m["profit_factor"] == pytest.approx(1.5)
    assert m["max_drawdown_pct"] == pytest.approx(25.0)
    assert m["avg_rr"] == pytest.approx(0.25)
    assert m["return_pct"] == pytest.approx(10.0)
    assert m["trades_per_setup"]["waveC"]["trades"] == 1
    assert compute_metrics(10.0, 10.0, [], [])["profit_factor"] == 0.0
