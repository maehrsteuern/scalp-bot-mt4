import json, os, random
import pytest
from ewbot.models import Candle
from ewbot.zigzag import zigzag, confirmed, atr, atr_series, retracement_levels, abc_targets
from ewbot.strategy import StrategyParams, find_signals, M30, H4
from ewbot import backtest as bt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mk(prices, t0=0, step=M30):
    """prices: list of (o,h,l,c)"""
    return [Candle(t0 + i * step, *p) for i, p in enumerate(prices)]


def walk(seed=1, n=600, start=100.0, vol=0.01):
    rnd = random.Random(seed)
    out, px = [], start
    for i in range(n):
        o = px
        c = o * (1 + rnd.gauss(0, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 3)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, vol / 3)))
        out.append(Candle(i * M30, o, h, l, c, 1.0))
        px = c
    return out


def test_zigzag_basic_pct():
    # up to 110, down to 100, up to 112
    cs = mk([(100, 101, 99, 100), (100, 105, 100, 105), (105, 110, 104, 110), (110, 110, 100, 101),
             (101, 103, 100, 102), (102, 112, 102, 112)])
    p = zigzag(cs, pct=0.05)
    kinds = [(x.kind, x.price) for x in p]
    assert ("H", 110) in kinds and ("L", 100) in kinds   # 99 start low is replaced by order
    assert p[-1].confirm_idx is None                     # last pivot is open


def test_one_candle_never_makes_two_pivots():
    cs = walk(3, 800, vol=0.02)
    for mult in (1.5, 2.5):
        piv = zigzag(cs, mult=mult)
        idxs = [x.idx for x in piv]
        assert len(idxs) == len(set(idxs))               # a candle is the extreme of at most one pivot
        for a, b in zip(piv, piv[1:]):
            assert a.kind != b.kind and a.idx < b.idx    # strictly alternating and ordered
        for x in confirmed(piv):
            assert x.confirm_idx > x.idx            # confirmed strictly after the extreme candle


def test_huge_candle_does_not_confirm_both():
    # big outside candle after an up-move: must not produce H and L from the same candle
    cs = mk([(100, 100.5, 99.5, 100), (100, 103, 100, 103), (103, 103.2, 102.8, 103),
             (103, 110, 95, 100)])           # outside bar: new high AND deep low
    piv = zigzag(cs, pct=0.03)
    assert len({x.idx for x in piv}) == len(piv)
    # outside bar extends the high candidate; reversal is not confirmed on the same candle
    assert all(not (x.kind == "H" and x.confirm_idx == 3) for x in piv)


def test_zigzag_prefix_property_no_lookahead():
    cs = walk(7, 700, vol=0.015)
    full = confirmed(zigzag(cs, mult=2.0))
    for k in (150, 300, 450, 699):
        part = confirmed(zigzag(cs[:k], mult=2.0))
        expect = [x for x in full if x.confirm_idx < k]
        assert part == expect


def test_atr_causal():
    cs = walk(2, 100)
    s = atr_series(cs, 14)
    assert s[50] == atr_series(cs[:51], 14)[50]
    assert atr(cs[:51]) > 0


def test_retracement_math():
    lv = retracement_levels(100, 200)
    assert lv[0.5] == 150 and lv[0.618] == pytest.approx(138.2) and lv[0.786] == pytest.approx(121.4)


def test_abc_math():
    t = abc_targets(2807.53, 2171.66, 2447.95, (0.618,))
    assert t[0.618] == pytest.approx(2447.95 - 0.618 * (2807.53 - 2171.66))
    t = abc_targets(100, 80, 90, (1.0, 1.618))
    assert t[1.0] == 70 and t[1.618] == pytest.approx(90 - 1.618 * 20)


def _data(coin):
    p = os.path.join(ROOT, "data")
    c30 = [Candle(*r) for r in json.load(open(os.path.join(p, f"{coin}_30m.json")))]
    h = os.path.join(p, "hist", f"{coin}_4h.json")
    c4 = [Candle(*r) for r in json.load(open(h if os.path.exists(h) else os.path.join(p, f"{coin}_4h.json")))]
    return c30, c4


def test_find_signals_geometry_and_rules():
    c30, c4 = _data("ETH")
    s = find_signals("ETH", "ETH_USD", c30, c4)
    if not s:
        pytest.skip("no signal on cached data")
    s = s[0]
    assert s.wave_low < s.entry < s.t1 <= s.t2
    assert s.stop < s.wave_low                     # stop below the wave-1 start (hard Elliott rule)
    assert s.valid_until_ts - s.created_ts == 48 * 3_600_000
    # entry sits at 61.8 % retracement of wave 1
    assert s.entry == pytest.approx(s.wave1_high - 0.618 * (s.wave1_high - s.wave_low), rel=1e-6)


def test_find_signals_ignores_future_and_open_candles():
    c30, c4 = _data("ETH")
    last = c30[-1]
    now_full = last.t + M30
    base = find_signals("ETH", "ETH_USD", c30, c4, now_ts=now_full)
    # a candle that is not closed yet at now_ts must be ignored: appending garbage in the 'future' changes nothing
    fake = Candle(last.t + M30, last.c, last.c * 3, last.c * 0.2, last.c * 0.5, 1.0)
    again = find_signals("ETH", "ETH_USD", c30 + [fake], c4, now_ts=now_full)
    assert [x.to_dict() for x in base] == [x.to_dict() for x in again]
    # and the same at an earlier moment: cutting the list vs. passing now_ts gives the same answer
    k = len(c30) - 40
    a = find_signals("ETH", "ETH_USD", c30, c4, now_ts=c30[k].t + M30)
    b = find_signals("ETH", "ETH_USD", c30[:k + 1], c4, now_ts=c30[k].t + M30)
    assert [x.to_dict() for x in a] == [x.to_dict() for x in b]


def test_backtest_stop_first_and_fees():
    # candle touches both stop and T1 in the same bar after the fill bar -> stop must win
    c = mk([(100, 100, 100, 100)] * 3 + [(100, 100.5, 98.5, 99.5),          # fill bar (low <= 99)? entry 99.0
            (99.5, 105, 90, 100)], step=M30)
    entry, stop, t1, t2 = 99.0, 95.0, 103.0, 110.0
    tr, last = bt.simulate(c, 2, (c[2].t + M30, c[2].t + 48 * 3_600_000, entry, stop, t1, t2, t1), "X", "ew")
    assert tr.status == "filled" and tr.outcome == "stop"
    assert tr.r_gross < -1.0 and tr.r_net < tr.r_gross        # slippage + fees make it worse than -1 R


def test_backtest_t1_then_t2_and_cancel():
    c = mk([(100, 100, 100, 100)] * 3 + [(100, 100, 98.9, 99.2),    # fills at 99
            (99.2, 104, 99.5, 103),                                 # hits T1 (103) -> BE; low above entry
            (103, 111, 102, 110)])                                  # hits T2
    tr, _ = bt.simulate(c, 2, (c[2].t + M30, c[2].t + 99 * 3_600_000, 99.0, 95.0, 103.0, 110.0, 103.0), "X", "ew")
    assert tr.outcome == "t1+t2"
    assert tr.r_gross == pytest.approx((0.5 * (103 - 99) + 0.5 * (110 - 99)) / 4.0)
    # T1 reached before fill -> missed
    c2 = mk([(100, 100, 100, 100)] * 3 + [(100, 104, 100, 103)])
    tr2, _ = bt.simulate(c2, 2, (c2[2].t + M30, c2[2].t + 99 * 3_600_000, 99.0, 95.0, 103.0, 110.0, 103.0), "X", "ew")
    assert tr2.status == "missed"
