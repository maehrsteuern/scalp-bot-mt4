"""Synthetic candle generators for tests (pure python, deterministic, no extra dependencies).

Prices move linearly between pivot prices; pivots are the exact highs/lows of the series so the ZigZag
finds them. ``noise`` jitters interior closes (as a fraction of the per-bar step) without breaking pivots.
"""
from __future__ import annotations

import random
from typing import Optional, Sequence, Union

from ewbot.models import Candle

TF_MS = 15 * 60 * 1000
START_TS = 1_700_000_000_000


def leg_bars(pivots: Sequence[float], bars_per_unit: float = 2.0, min_bars: int = 4) -> list[int]:
    """Bars per leg proportional to the leg size (constant speed)."""
    return [max(min_bars, int(round(abs(b - a) * bars_per_unit))) for a, b in zip(pivots, pivots[1:])]


def path_to_candles(pivots: Sequence[float], bars: Union[int, Sequence[int]], start_ts: int = START_TS,
                    tf_ms: int = TF_MS, noise: float = 0.0, wick: float = 0.2, seed: int = 0,
                    volume: float = 1.0) -> list[Candle]:
    """Candles walking linearly through ``pivots``; leg i takes ``bars[i]`` bars (or ``bars`` for all).

    Bar 0 closes at pivots[0]; the last candle closes at pivots[-1]. ``wick`` adds high/low wicks as a
    fraction of the leg's per-bar step, clipped to the leg's pivot range.
    """
    if len(pivots) < 2:
        raise ValueError("need at least two pivots")
    nlegs = len(pivots) - 1
    bl = [int(bars)] * nlegs if isinstance(bars, int) else [int(b) for b in bars]
    if len(bl) != nlegs or min(bl) < 1:
        raise ValueError("bars must give >= 1 bar per leg")
    rng = random.Random(seed)
    closes: list[float] = [float(pivots[0])]
    bounds: list[tuple[float, float, float]] = [(pivots[0], pivots[0], 0.0)]
    for (a, b), nb in zip(zip(pivots, pivots[1:]), bl):
        step = (b - a) / nb
        lo, hi = min(a, b), max(a, b)
        for k in range(1, nb + 1):
            c = a + step * k
            if k < nb and noise:
                c = min(hi, max(lo, c + rng.uniform(-noise, noise) * abs(step)))
            closes.append(c)
            bounds.append((lo, hi, abs(step)))
    out: list[Candle] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        lo, hi, st = bounds[i]
        o = prev
        w = wick * st
        h = max(o, c) + w
        l = min(o, c) - w
        if i > 0:
            h = min(h, max(hi, o))
            l = max(l, min(lo, o))
        out.append(Candle(ts=start_ts + i * tf_ms, open=o, high=h, low=l, close=c, volume=volume))
        prev = c
    return out


def impulse_pivots(p0: float = 100.0, w1: float = 10.0, w2: float = 0.618, w3: float = 1.618,
                   w4: float = 0.382, w5: float = 1.0, direction: int = 1) -> list[float]:
    """[p0..p5]: w2 = retrace of w1, w3 = ext of w1, w4 = retrace of w3, w5 = size relative to w1."""
    s = 1 if direction >= 0 else -1
    p1 = p0 + s * w1
    p2 = p1 - s * w2 * w1
    big3 = w3 * w1
    p3 = p2 + s * big3
    p4 = p3 - s * w4 * big3
    p5 = p4 + s * w5 * w1
    return [p0, p1, p2, p3, p4, p5]


def zigzag_pivots(p0: float = 100.0, a: float = 10.0, b: float = 0.618, c: float = 1.0,
                  direction: int = -1) -> list[float]:
    """[p0, A, B, C] where ``direction`` is the direction of wave A; b = B/A, c = C/A."""
    s = 1 if direction >= 0 else -1
    p1 = p0 + s * a
    p2 = p1 - s * b * a
    p3 = p2 + s * c * a
    return [p0, p1, p2, p3]


def impulse_candles(p0: float = 100.0, w1: float = 10.0, w2: float = 0.618, w3: float = 1.618,
                    w4: float = 0.382, w5: float = 1.0, direction: int = 1, lead: float = 0.8,
                    tail: Optional[float] = 0.382, bars_per_unit: float = 2.0, min_bars: int = 4,
                    noise: float = 0.0, seed: int = 0) -> tuple[list[Candle], list[float]]:
    """5-wave impulse with a lead-in leg (so p0 is a confirmed swing) and an optional retracement ``tail``
    (fraction of the whole impulse) that confirms p5. Returns (candles, [p0..p5])."""
    s = 1 if direction >= 0 else -1
    piv = impulse_pivots(p0, w1, w2, w3, w4, w5, s)
    path = [p0 + s * lead * w1] + piv
    if tail:
        path.append(piv[5] - s * tail * abs(piv[5] - piv[0]))
    candles = path_to_candles(path, leg_bars(path, bars_per_unit, min_bars), noise=noise, seed=seed)
    return candles, piv


def zigzag_candles(p0: float = 100.0, a: float = 10.0, b: float = 0.618, c: float = 1.0,
                   direction: int = -1, lead: float = 0.8, tail: Optional[float] = 0.5,
                   bars_per_unit: float = 2.0, min_bars: int = 4) -> tuple[list[Candle], list[float]]:
    """A-B-C zigzag with lead-in and a tail (fraction of A) that confirms the end of C."""
    s = 1 if direction >= 0 else -1
    piv = zigzag_pivots(p0, a, b, c, s)
    path = [p0 - s * lead * a] + piv
    if tail:
        path.append(piv[3] - s * tail * a)
    return path_to_candles(path, leg_bars(path, bars_per_unit, min_bars)), piv


def wave3_setup_candles(p0: float = 100.0, w1: float = 10.0, w2: float = 0.618, direction: int = 1,
                        rally: float = 2.0, rally_bars: int = 3, bars_per_unit: float = 2.0
                        ) -> tuple[list[Candle], list[float]]:
    """Lead-in, waves 1 and 2, then a sharp start of wave 3 (``rally`` price units in ``rally_bars``
    bars) so that p2 is confirmed and the last candle closes up. Returns (candles, [p0, p1, p2])."""
    s = 1 if direction >= 0 else -1
    p1 = p0 + s * w1
    p2 = p1 - s * w2 * w1
    path = [p0 + s * 0.8 * w1, p0, p1, p2]
    bars = leg_bars(path, bars_per_unit) + [rally_bars]
    path.append(p2 + s * rally)
    return path_to_candles(path, bars), [p0, p1, p2]


def random_walk(n: int = 500, seed: int = 1, start: float = 100.0, vol: float = 0.5,
                tf_ms: int = TF_MS, start_ts: int = START_TS) -> list[Candle]:
    """Gaussian random walk candles."""
    rng = random.Random(seed)
    out: list[Candle] = []
    price = start
    for i in range(n):
        o = price
        c = max(0.01, o + rng.gauss(0.0, vol))
        h = max(o, c) + abs(rng.gauss(0.0, vol * 0.3))
        l = max(0.001, min(o, c) - abs(rng.gauss(0.0, vol * 0.3)))
        out.append(Candle(ts=start_ts + i * tf_ms, open=o, high=h, low=l, close=c, volume=1.0))
        price = c
    return out


def mirror_candles(candles: Sequence[Candle], axis: float = 200.0) -> list[Candle]:
    """Reflect prices around ``axis / 2`` (p -> axis - p); highs and lows swap. Turns longs into shorts."""
    return [Candle(ts=c.ts, open=axis - c.open, high=axis - c.low, low=axis - c.high, close=axis - c.close,
                   volume=c.volume) for c in candles]
