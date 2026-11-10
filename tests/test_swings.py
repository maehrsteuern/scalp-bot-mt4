import math

import pytest

from ewbot.config import SwingCfg
from ewbot.fib import EXTEND, RETRACE, extension, in_band, ratio_of, retracement
from ewbot.models import Candle, SwingKind
from ewbot.swings import atr, detect_swings, ema, last_leg, true_range

try:
    from tests.synthetic import impulse_candles, mirror_candles, path_to_candles, random_walk
except ImportError:  # pragma: no cover - when tests/ itself is on sys.path
    from synthetic import impulse_candles, mirror_candles, path_to_candles, random_walk

CFG = SwingCfg()


def _alternates(swings):
    return all(a.kind != b.kind for a, b in zip(swings, swings[1:]))


def test_atr_same_length_and_nan_free():
    candles = random_walk(50, seed=2)
    for period in (1, 14, 100):
        values = atr(candles, period)
        assert len(values) == len(candles)
        assert all(not math.isnan(v) and v >= 0 for v in values)
    assert values[0] == pytest.approx(true_range(candles)[0])
    assert atr([], 14) == []


def test_ema_basic():
    assert ema([], 5) == []
    assert ema([3.0] * 10, 4) == pytest.approx([3.0] * 10)
    out = ema([1.0, 2.0, 3.0, 4.0], 3)
    assert len(out) == 4 and out[0] == 1.0 and out[-1] < 4.0 and out == sorted(out)


def test_short_series_returns_empty():
    assert detect_swings([], CFG) == []
    c = Candle(0, 1.0, 1.1, 0.9, 1.0, 1.0)
    assert detect_swings([c], CFG) == []
    assert detect_swings(random_walk(CFG.atr_period - 1, seed=3), CFG) == []


def test_flat_series_has_no_swings():
    flat = [Candle(i, 1.0, 1.0, 1.0, 1.0, 1.0) for i in range(100)]
    assert detect_swings(flat, CFG) == []


def test_impulse_swings_match_pivots_and_alternate():
    candles, piv = impulse_candles(noise=0.3, seed=7)
    swings = detect_swings(candles, CFG)
    assert _alternates(swings)
    prices = [s.price for s in swings]
    # lead-in high, p0..p5 (p5 confirmed by the tail)
    assert len(swings) == 7
    assert prices[1:] == pytest.approx(piv)
    assert [s.kind for s in swings[1:3]] == [SwingKind.LOW, SwingKind.HIGH]
    for s in swings:
        assert candles[s.index].ts == s.ts
        if s.kind is SwingKind.HIGH:
            assert s.price == candles[s.index].high
        else:
            assert s.price == candles[s.index].low


def test_in_progress_leg_is_not_a_swing():
    candles, piv = impulse_candles(tail=None)
    swings = detect_swings(candles, CFG)
    assert swings[-1].price == pytest.approx(piv[4])      # p5 is the running leg, not confirmed
    assert swings[-1].kind is SwingKind.LOW
    sw, close = last_leg(candles, swings)
    assert sw is swings[-1] and close == candles[-1].close
    with pytest.raises(ValueError):
        last_leg(candles, [])


@pytest.mark.parametrize("seed", range(8))
def test_random_walk_alternation_and_spacing(seed):
    candles = random_walk(600, seed=seed)
    swings = detect_swings(candles, CFG)
    assert len(swings) > 5
    assert _alternates(swings)
    assert all(b.index - a.index >= CFG.min_bars for a, b in zip(swings, swings[1:]))
    assert all(b.index > a.index for a, b in zip(swings, swings[1:]))
    for a, b in zip(swings, swings[1:]):   # a HIGH is above the neighbouring LOWs
        if a.kind is SwingKind.HIGH:
            assert a.price > b.price
        else:
            assert a.price < b.price


def test_mirror_symmetry():
    candles = random_walk(400, seed=11)
    up = detect_swings(candles, CFG)
    dn = detect_swings(mirror_candles(candles, 400.0), CFG)
    assert [s.index for s in up] == [s.index for s in dn]
    assert all(a.kind != b.kind for a, b in zip(up, dn))


def test_min_bars_blocks_close_pivots():
    # a 1-bar spike: up 3, down 3 inside min_bars -> not a separate swing pair
    path = [100.0, 90.0, 93.0, 80.0, 95.0]
    candles = path_to_candles(path, [20, 1, 20, 30])
    swings = detect_swings(candles, SwingCfg(atr_period=14, atr_mult=2.0, min_bars=3))
    assert _alternates(swings)
    assert all(b.index - a.index >= 3 for a, b in zip(swings, swings[1:]))


def test_fib_helpers():
    r = retracement(100.0, 110.0)
    assert set(r.levels) == set(RETRACE)
    assert r.levels[0.618] == pytest.approx(103.82)
    assert r.levels[0.5] == pytest.approx(105.0)
    assert r.nearest(104.0)[0] == 0.618
    rd = retracement(110.0, 100.0)
    assert rd.levels[0.382] == pytest.approx(103.82)
    e = extension(100.0, 110.0, 103.82)
    assert set(e.levels) == set(EXTEND)
    assert e.levels[1.618] == pytest.approx(103.82 + 16.18)
    ed = extension(110.0, 100.0, 106.0, ratios=(1.0,))
    assert ed.levels[1.0] == pytest.approx(96.0)
    assert ratio_of(-5.0, 10.0) == 0.5 and ratio_of(3.0, 0.0) == 0.0
    assert in_band(0.5, 0.382, 0.618) and not in_band(0.7, 0.382, 0.618) and in_band(0.382, 0.382, 0.5)
