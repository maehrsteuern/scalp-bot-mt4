"""Bot orchestration tests with stub collaborators (no dependency on modules A/B, no network)."""
from __future__ import annotations

import json
import logging

import pytest

from ewbot.bot import Bot, utc_date
from ewbot.config import BotCfg, MarketCfg
from ewbot.models import (Bias, Candle, Fill, HtfContext, PatternType, Position, SetupType, Side, Signal,
                          TradeRecord, WaveCount)

TF = 15 * 60_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)   # midnight UTC


def candles(n: int, start: int = T0, price: float = 100.0) -> list[Candle]:
    out = []
    for i in range(n):
        p = price + i * 0.1
        out.append(Candle(start + i * TF, p, p + 0.5, p - 0.5, p + 0.05, 10.0))
    return out


def make_signal(symbol: str, side: Side = Side.LONG, ts: int = T0, entry: float = 100.0) -> Signal:
    sign = side.sign
    count = WaveCount(PatternType.IMPULSE, side, [], [90, 100, 95], False, 0.8)
    return Signal(symbol=symbol, timeframe="15m", side=side, setup=SetupType.WAVE3, entry=entry,
                  stop=entry - sign * 2.0, tp1=entry + sign * 3.0, tp2=entry + sign * 5.0, ts=ts, score=0.8,
                  count=count, htf=[], reasons=["test"])


# ----------------------------------------------------------------------------------------- stubs

class StubBroker:
    def __init__(self, equity: float = 20.0):
        self._equity = equity
        self._positions: list[Position] = []
        self._trades: list[TradeRecord] = []
        self.opened: list[tuple[Signal, float, int]] = []
        self.stops: list[float] = []
        self.on_candle_calls: list[tuple[str, int]] = []
        self.n = 0

    def equity(self) -> float:
        return self._equity

    def cash(self) -> float:
        return self._equity

    def positions(self) -> list[Position]:
        return list(self._positions)

    def open(self, signal: Signal, qty: float, ts: int) -> Position | None:
        self.n += 1
        self.opened.append((signal, qty, ts))
        pos = Position(id=f"p{self.n}", symbol=signal.symbol, side=signal.side, qty=qty, entry=signal.entry,
                       stop=signal.stop, tp1=signal.tp1, tp2=signal.tp2, opened_ts=ts, setup=signal.setup,
                       timeframe=signal.timeframe)
        self._positions.append(pos)
        return pos

    def close(self, position: Position, qty: float, price_hint: float, ts: int, reason: str) -> Fill | None:
        qty = min(qty, position.qty_open)
        pnl = (price_hint - position.entry) * qty * position.side.sign
        position.qty_open -= qty
        position.realized_pnl += pnl
        self._equity += pnl
        if position.qty_open <= 1e-12:
            self._positions.remove(position)
            self._trades.append(TradeRecord(position, ts, price_hint, position.realized_pnl, 0.0, reason))
        return Fill(ts, position.symbol, position.side.opposite, qty, price_hint, 0.0, reason)

    def update_stop(self, position: Position, new_stop: float) -> None:
        position.stop = new_stop
        self.stops.append(new_stop)

    def on_candle(self, symbol: str, candle: Candle) -> list[TradeRecord]:
        self.on_candle_calls.append((symbol, candle.ts))
        return []

    def trades(self) -> list[TradeRecord]:
        return list(self._trades)

    def last_price(self, symbol: str) -> float:
        return 101.0

    # restore hook (optional broker capability used by Bot.restore)
    def restore(self, positions, trades=None):
        self._positions = list(positions)


class StubStrategy:
    def __init__(self, signal_side: Side | None = Side.LONG):
        self.signal_side = signal_side
        self.evaluate_calls = 0
        self.htf_seen: list[tuple[str, int]] = []

    def analyse_htf(self, timeframe: str, candles: list[Candle]) -> HtfContext:
        self.htf_seen.append((timeframe, len(candles)))
        return HtfContext(timeframe, Bias.BULL, None, None, 0.0, 0.0, 1.0)

    def evaluate(self, symbol: str, candles: list[Candle], htf: list[HtfContext]) -> Signal | None:
        self.evaluate_calls += 1
        if self.signal_side is None:
            return None
        return make_signal(symbol, self.signal_side, ts=candles[-1].ts, entry=candles[-1].close)


class StubRisk:
    def __init__(self, allow: bool = True, qty: float = 0.5):
        self.allow, self.qty = allow, qty
        self.day_starts: list[tuple[float, int]] = []
        self.actions: list[tuple[str, float]] = []

    def position_size(self, equity, signal, market, min_notional) -> float:
        return self.qty

    def can_open(self, now_ts, equity, open_positions, trades, symbol):
        return (True, "ok") if self.allow else (False, "blocked by test")

    def set_day_start(self, equity, ts) -> None:
        self.day_starts.append((equity, ts))

    def manage(self, position, candle, atr):
        return list(self.actions)


class StubNotifier:
    def __init__(self):
        self.sent: list[str] = []
        self.queue: list[tuple[str, str]] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        return True

    def poll_commands(self):
        q, self.queue = self.queue, []
        return q

    def format_signal(self, signal) -> str:
        return f"SIGNAL {signal.symbol}"

    def format_fill(self, fill, position) -> str:
        return f"FILL {fill.reason} {position.symbol}"

    def format_summary(self, equity, day_pnl, trades) -> str:
        return f"SUMMARY {equity:.2f}"


class StubData:
    def __init__(self, series: dict[tuple[str, str], list[Candle]]):
        self.series = series

    def fetch(self, symbol: str, timeframe: str, limit=None) -> list[Candle]:
        return list(self.series.get((symbol, timeframe), []))


# --------------------------------------------------------------------------------------- fixtures

def make_cfg(tmp_path, allow_short: bool = False) -> BotCfg:
    cfg = BotCfg()
    cfg.name = "test-bot"
    cfg.state_file = str(tmp_path / "state" / "test.json")
    cfg.log_file = str(tmp_path / "logs" / "test.log")
    cfg.markets = [MarketCfg("BTC/USD", allow_short=allow_short), MarketCfg("ETH/USD", allow_short=allow_short)]
    cfg.telegram.daily_summary_utc = "21:00"
    return cfg


def make_bot(tmp_path, side=Side.LONG, allow=True, allow_short=False, data=None):
    cfg = make_cfg(tmp_path, allow_short)
    broker, strat, risk, notif = StubBroker(), StubStrategy(side), StubRisk(allow), StubNotifier()
    bot = Bot(cfg, data, broker, strat, risk, notif, logging.getLogger("test"))
    return bot, broker, strat, risk, notif


HTF = {"1h": candles(80), "4h": candles(80)}


# ------------------------------------------------------------------------------------------ tests

def test_process_candle_opens_position_when_signal_and_risk_allow(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    exec_c = candles(50)
    now = exec_c[-1].ts + TF
    pos = bot.process_candle("BTC/USD", exec_c, HTF, now)
    assert pos is not None and pos.side is Side.LONG
    assert len(broker.opened) == 1
    sig, qty, ts = broker.opened[0]
    assert qty == pytest.approx(0.5) and ts == now
    assert broker.on_candle_calls == [("BTC/USD", exec_c[-1].ts)]
    assert {tf for tf, _ in strat.htf_seen} == {"1h", "4h"}
    assert any(m.startswith("SIGNAL") for m in notif.sent)
    assert any(m.startswith("FILL entry") for m in notif.sent)
    assert pos.tags["stop0"] and float(pos.tags["risk_quote"]) == pytest.approx(2.0 * 0.5)


def test_short_signal_filtered_when_allow_short_false(tmp_path):
    bot, broker, *_ = make_bot(tmp_path, side=Side.SHORT, allow_short=False)
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is None
    assert broker.opened == []


def test_short_signal_allowed_when_allow_short_true(tmp_path):
    bot, broker, *_ = make_bot(tmp_path, side=Side.SHORT, allow_short=True)
    pos = bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF)
    assert pos is not None and pos.side is Side.SHORT


def test_risk_block_prevents_entry(tmp_path):
    bot, broker, *_ = make_bot(tmp_path, allow=False)
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is None
    assert broker.opened == []


def test_zero_size_prevents_entry(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    risk.qty = 0.0
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is None
    assert broker.opened == []


def test_risk_manage_actions_are_executed(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path, side=None)
    sig = make_signal("BTC/USD")
    pos = broker.open(sig, 1.0, T0)
    risk.actions = [("stop", 100.0)]
    bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF)
    assert pos.stop == 100.0 and broker.stops == [100.0]
    risk.actions = [("close", 1.0)]
    bot.process_candle("BTC/USD", candles(51), HTF, T0 + 52 * TF)
    assert broker.positions() == [] and len(broker.trades()) == 1
    assert bot.trades_count == 1
    assert any("geschlossen" in m for m in notif.sent)


def test_step_persists_state_and_only_processes_new_candles(tmp_path):
    exec_c = candles(60)
    series = {}
    for sym in ("BTC/USD", "ETH/USD"):
        series[(sym, "15m")] = exec_c
        series[(sym, "1h")] = HTF["1h"]
        series[(sym, "4h")] = HTF["4h"]
    data = StubData(series)
    bot, broker, strat, risk, notif = make_bot(tmp_path, data=data)
    now = exec_c[-1].ts + TF + 5_000
    bot.step(now)
    assert strat.evaluate_calls == 2 and len(broker.opened) == 2
    assert risk.day_starts and risk.day_starts[0][1] == now

    state = json.loads(open(bot.cfg.state_file, encoding="utf-8").read())
    assert state["last_seen"] == {"BTC/USD": exec_c[-1].ts, "ETH/USD": exec_c[-1].ts}
    assert len(state["positions"]) == 2 and state["positions"][0]["side"] == "long"
    assert state["day_start"]["date"] == utc_date(now)
    assert state["paused"] is False

    bot.step(now + 10_000)                       # no new candle -> nothing happens
    assert strat.evaluate_calls == 2

    # restore into a fresh bot
    bot2, broker2, strat2, risk2, _ = make_bot(tmp_path, data=data)
    bot2.restore()
    assert bot2.last_seen == bot.last_seen
    assert len(broker2.positions()) == 2
    assert risk2.day_starts and risk2.day_starts[-1][0] == pytest.approx(20.0)
    bot2.step(now + 20_000)
    assert strat2.evaluate_calls == 0             # already seen before the restart


def test_missed_candles_are_passed_to_broker(tmp_path):
    exec_c = candles(60)
    data = StubData({("BTC/USD", "15m"): exec_c, ("BTC/USD", "1h"): HTF["1h"], ("BTC/USD", "4h"): HTF["4h"]})
    bot, broker, *_ = make_bot(tmp_path, side=None, data=data)
    bot.last_seen["BTC/USD"] = exec_c[-4].ts
    bot.step(exec_c[-1].ts + TF)
    assert [ts for s, ts in broker.on_candle_calls if s == "BTC/USD"] == [c.ts for c in exec_c[-3:]]


def test_telegram_pause_resume_and_close_all(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    notif.queue = [("/pause", "")]
    assert bot.handle_commands(T0) is True and bot.paused
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is None
    assert broker.opened == []
    bot.persist()
    assert json.loads(open(bot.cfg.state_file, encoding="utf-8").read())["paused"] is True

    notif.queue = [("/resume", ""), ("/status", ""), ("/equity", ""), ("/positions", "")]
    bot.handle_commands(T0)
    assert not bot.paused
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is not None
    notif.queue = [("/close_all@my_bot", "")]
    bot.handle_commands(T0 + 52 * TF)
    assert broker.positions() == [] and len(broker.trades()) == 1


def test_daily_summary_sent_once_per_day(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    bot.check_day_rollover(T0)
    assert bot.maybe_daily_summary(T0 + 20 * 3_600_000) is False         # 20:00 < 21:00
    assert bot.maybe_daily_summary(T0 + 21 * 3_600_000 + 60_000) is True
    assert bot.maybe_daily_summary(T0 + 22 * 3_600_000) is False         # once per day
    assert sum(1 for m in notif.sent if m.startswith("SUMMARY")) == 1
    bot.check_day_rollover(T0 + 86_400_000 + 1)
    assert len(risk.day_starts) == 2
    assert bot.maybe_daily_summary(T0 + 86_400_000 + 21 * 3_600_000 + 1) is True


# ------------------------------------------------------------------------------------ audit fixes

def test_last_seen_persisted_before_entry_and_position_right_after(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    exec_c = candles(50)
    seen_on_disk = []
    orig_open = broker.open

    def spy_open(signal, qty, ts):
        seen_on_disk.append(json.loads(open(bot.cfg.state_file, encoding="utf-8").read())["last_seen"])
        return orig_open(signal, qty, ts)

    broker.open = spy_open
    pos = bot.process_candle("BTC/USD", exec_c, HTF, exec_c[-1].ts + TF)
    assert pos is not None
    assert seen_on_disk == [{"BTC/USD": exec_c[-1].ts}]                # written before the order
    state = json.loads(open(bot.cfg.state_file, encoding="utf-8").read())
    assert [p["id"] for p in state["positions"]] == [pos.id]          # persisted without step()
    assert pos.tags["signal_ts"] == str(exec_c[-1].ts)


def test_close_all_and_management_close_persist_immediately(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path, side=None)
    broker.open(make_signal("BTC/USD"), 1.0, T0)
    broker.open(make_signal("ETH/USD"), 1.0, T0)
    risk.actions = [("close", 1.0)]
    bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF)
    state = json.loads(open(bot.cfg.state_file, encoding="utf-8").read())
    assert [p["symbol"] for p in state["positions"]] == ["ETH/USD"]
    risk.actions = []
    assert bot.close_all(T0 + 52 * TF) == 1
    assert json.loads(open(bot.cfg.state_file, encoding="utf-8").read())["positions"] == []


def test_unknown_equity_skips_day_reset_and_entries(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    broker._equity = None
    bot.check_day_rollover(T0)
    assert risk.day_starts == [] and bot.day_start == {}
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is None
    assert broker.opened == []
    broker._equity = 20.0
    bot.check_day_rollover(T0 + 1)
    assert risk.day_starts == [(20.0, T0 + 1)]


def test_spot_entry_skipped_without_free_cash(tmp_path):
    bot, broker, strat, risk, notif = make_bot(tmp_path)
    broker.cash = lambda: 0.0
    assert bot.process_candle("BTC/USD", candles(50), HTF, T0 + 51 * TF) is None
    assert broker.opened == []


def test_paper_stop_in_bar_after_entry_is_executed_through_bot(tmp_path):
    from ewbot.broker import PaperBroker

    cfg = make_cfg(tmp_path)
    cfg.markets = [MarketCfg("BTC/USD:USD")]
    broker, strat = PaperBroker(cfg, start_equity=1000.0), StubStrategy(Side.LONG)
    bot = Bot(cfg, None, broker, strat, StubRisk(qty=1.0), StubNotifier(), logging.getLogger("test"),
              persist_enabled=False)
    exec_c = candles(50)
    pos = bot.process_candle("BTC/USD:USD", exec_c, HTF, exec_c[-1].ts + TF)     # entry on bar N
    assert pos is not None
    strat.signal_side = None
    nxt = Candle(exec_c[-1].ts + TF, pos.entry, pos.entry + 0.1, pos.stop - 0.5, pos.stop - 0.2, 1.0)
    bot.process_candle("BTC/USD:USD", exec_c + [nxt], HTF, nxt.ts + TF)          # stop inside bar N+1
    assert broker.positions() == []
    tr = broker.trades()[0]
    assert tr.reason == "stop" and tr.closed_ts == nxt.ts + TF
