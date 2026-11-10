import pytest

from ewbot.config import MarketCfg, RiskCfg
from ewbot.models import (Candle, PatternType, Position, SetupType, Side, Signal, Swing, SwingKind,
                          TradeRecord, WaveCount)
from ewbot.risk import RiskManager

DAY = 86_400_000
T0 = 1_700_006_400_000 - (1_700_006_400_000 % DAY)   # a UTC midnight
MIN = 60_000


def make_signal(entry=100.0, stop=98.0, symbol="BTC/USD"):
    swings = [Swing(0, 0, 90.0, SwingKind.LOW)]
    count = WaveCount(PatternType.IMPULSE, Side.LONG, swings, [90.0, 100.0, 95.0], False, 0.8)
    return Signal(symbol, "15m", Side.LONG, SetupType.WAVE3, entry, stop, 104.0, 108.0, 0, 0.8, count, [])


def make_pos(symbol="BTC/USD", side=Side.LONG, opened_ts=T0, **kw):
    base = dict(id=f"{symbol}-{opened_ts}-1", symbol=symbol, side=side, qty=1.0, entry=100.0,
                stop=98.0 if side is Side.LONG else 102.0, tp1=104.0 if side is Side.LONG else 96.0,
                tp2=108.0 if side is Side.LONG else 92.0, opened_ts=opened_ts,
                setup=SetupType.WAVE3, timeframe="15m")
    base.update(kw)
    return Position(**base)


def trade(pnl, closed_ts):
    return TradeRecord(make_pos(), closed_ts, 100.0, pnl, pnl, "stop" if pnl < 0 else "tp2")


def test_position_size_20usd_5pct():
    rm = RiskManager(RiskCfg(risk_pct=5.0, fee_pct=0.075))
    qty = rm.position_size(20.0, make_signal(), MarketCfg("BTC/USD"), min_notional=1.0)
    expected = 1.0 / (2.0 + 0.00075 * (100 + 98))
    assert qty == pytest.approx(expected)
    assert 0.45 < qty < 0.5
    # loss at stop incl. both fees equals the risk amount
    loss = qty * 2.0 + qty * 100 * 0.00075 + qty * 98 * 0.00075
    assert loss == pytest.approx(1.0)
    # weight scales the risk; min notional gate
    assert rm.position_size(20.0, make_signal(), MarketCfg("BTC/USD", weight=0.5), 1.0) == pytest.approx(expected / 2)
    assert rm.position_size(20.0, make_signal(), MarketCfg("BTC/USD"), min_notional=100.0) == 0.0
    assert rm.position_size(20.0, make_signal(stop=100.0), MarketCfg("BTC/USD"), 1.0) == 0.0


def test_can_open_position_limits():
    rm = RiskManager(RiskCfg(max_positions=2, max_positions_per_symbol=1))
    rm.set_day_start(20.0, T0)
    ok, _ = rm.can_open(T0 + MIN, 20.0, [], [], "BTC/USD")
    assert ok
    ok, why = rm.can_open(T0 + MIN, 20.0, [make_pos("BTC/USD")], [], "BTC/USD")
    assert not ok and "BTC/USD" in why
    ok, why = rm.can_open(T0 + MIN, 20.0, [make_pos("BTC/USD"), make_pos("ETH/USD")], [], "SOL/USD")
    assert not ok and "max positions" in why


def test_daily_loss_cap_halts_until_next_day():
    rm = RiskManager(RiskCfg(daily_loss_cap_pct=15.0))
    rm.set_day_start(20.0, T0)
    assert rm.can_open(T0 + 60 * MIN, 17.5, [], [], "BTC/USD")[0]          # -12.5 %
    ok, why = rm.can_open(T0 + 61 * MIN, 16.9, [], [], "BTC/USD")          # -15.5 %
    assert not ok and "daily loss cap" in why
    # next UTC day: fallback rollover resets the reference equity
    assert rm.can_open(T0 + DAY + MIN, 16.9, [], [], "BTC/USD")[0]
    assert rm.day_start_equity == pytest.approx(16.9)


def test_consecutive_loss_pause():
    rm = RiskManager(RiskCfg(max_consecutive_losses=3, pause_minutes_after_losses=120))
    rm.set_day_start(1000.0, T0)
    trades = [trade(-1, T0 + 1 * MIN), trade(-1, T0 + 2 * MIN)]
    assert rm.can_open(T0 + 3 * MIN, 1000.0, [], trades, "BTC/USD")[0]
    trades.append(trade(-1, T0 + 3 * MIN))
    ok, why = rm.can_open(T0 + 4 * MIN, 1000.0, [], trades, "BTC/USD")
    assert not ok and "paused" in why
    assert rm.can_open(T0 + 3 * MIN + 120 * MIN, 1000.0, [], trades, "BTC/USD")[0]
    # a win breaks the streak
    trades2 = trades[:2] + [trade(+2, T0 + 2 * MIN + 30_000)] + trades[2:]
    assert rm.can_open(T0 + 4 * MIN, 1000.0, [], trades2, "BTC/USD")[0]


def test_manage_tp1_be_trailing_and_time_stop():
    rm = RiskManager(RiskCfg(tp1_fraction=0.5, move_to_be_after_tp1=True, trail_after_tp1_atr=1.0,
                             max_hold_bars=4))
    pos = make_pos()
    c = Candle(T0 + 15 * MIN, 101, 104.5, 100.5, 104.2, 1)
    acts = rm.manage(pos, c, atr=1.0)
    assert acts[0] == ("tp1", 0.5)
    assert acts[1] == ("stop", 100.0)
    assert acts[2][0] == "stop" and acts[2][1] == pytest.approx(103.2)
    # after broker did TP1 + BE: only trailing remains
    pos.tp1_done, pos.be_moved, pos.stop, pos.qty_open = True, True, 100.0, 0.5
    acts = rm.manage(pos, Candle(T0 + 30 * MIN, 104, 106, 103.8, 105.5, 1), atr=1.0)
    assert acts == [("stop", pytest.approx(104.5))]
    # time stop after 4 bars of 15m
    pos2 = make_pos()
    assert rm.manage(pos2, Candle(T0 + 3 * 15 * MIN, 100, 101, 99, 100, 1), 1.0) == []
    assert rm.manage(pos2, Candle(T0 + 4 * 15 * MIN, 100, 101, 99, 100, 1), 1.0) == [("close", 1.0)]


def test_manage_short_mirror():
    rm = RiskManager(RiskCfg(tp1_fraction=0.5, max_hold_bars=0))
    pos = make_pos(side=Side.SHORT)
    acts = rm.manage(pos, Candle(T0 + 15 * MIN, 99, 99.5, 95.5, 96, 1), atr=1.0)
    assert acts == [("tp1", 0.5), ("stop", 100.0)]
