"""Swing (pivot) detection: ATR, EMA and an ATR-based ZigZag.

Pure functions on lists of closed candles. The ZigZag only reports *confirmed* pivots: the leg that is
still running at the end of the series is never returned as a swing.
"""
from __future__ import annotations

import logging
from typing import Optional

from ewbot.config import SwingCfg
from ewbot.models import Candle, Swing, SwingKind

log = logging.getLogger(__name__)


def true_range(candles: list[Candle]) -> list[float]:
    """True range per candle; the first candle uses high - low."""
    out: list[float] = []
    prev_close: Optional[float] = None
    for c in candles:
        hl = c.high - c.low
        if prev_close is None:
            tr = hl
        else:
            tr = max(hl, abs(c.high - prev_close), abs(c.low - prev_close))
        out.append(max(0.0, tr))
        prev_close = c.close
    return out


def atr(candles: list[Candle], period: int) -> list[float]:
    """Wilder ATR, same length as ``candles``.

    The first ``period`` values are the running mean of the true ranges seen so far (seeded with TR), so the
    result never contains NaN, even for series shorter than ``period``.
    """
    tr = true_range(candles)
    if not tr:
        return []
    period = max(1, int(period))
    out: list[float] = []
    running = 0.0
    for i, t in enumerate(tr):
        if i < period:
            running += t
            out.append(running / (i + 1))
        else:
            out.append((out[-1] * (period - 1) + t) / period)
    return out


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average seeded with the first value; same length as ``values``."""
    if not values:
        return []
    period = max(1, int(period))
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * float(v) + (1.0 - alpha) * out[-1])
    return out


def detect_swings(candles: list[Candle], cfg: SwingCfg) -> list[Swing]:
    """ATR ZigZag.

    A pivot is confirmed once price moves ``atr_mult * ATR`` against the running leg and the pivot lies at
    least ``min_bars`` bars after the previous pivot. If price breaks beyond the previous pivot before the
    running leg could be confirmed, that previous pivot is dropped and the older leg is extended, so the
    output alternates HIGH/LOW strictly. The last returned swing is the last confirmed pivot.
    Returns [] for series shorter than ``atr_period`` (or < 3 candles); never raises on short input.
    """
    n = len(candles)
    if n < 3 or n < int(cfg.atr_period):
        return []
    atr_v = atr(candles, cfg.atr_period)
    mult = float(cfg.atr_mult)
    min_bars = max(0, int(cfg.min_bars))
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    pivots: list[tuple[int, float, SwingKind]] = []
    trend = 0            # +1: running leg up (last pivot LOW), -1: running leg down (last pivot HIGH)
    hi_i = 0             # pre-pivot extremes (trend == 0)
    lo_i = 0
    ext_i = 0            # extreme of the running leg
    ext_p = 0.0

    def _argmax(a: int, b: int) -> int:
        return max(range(a, b + 1), key=lambda k: highs[k])

    def _argmin(a: int, b: int) -> int:
        return min(range(a, b + 1), key=lambda k: lows[k])

    for i in range(1, n):
        thr = mult * atr_v[i]
        if thr <= 0.0:
            thr = float("inf")  # flat data: never confirm a reversal
        if trend == 0:
            up_move = highs[i] - lows[lo_i]
            dn_move = highs[hi_i] - lows[i]
            up_rev = up_move >= thr and up_move > 0
            dn_rev = dn_move >= thr and dn_move > 0
            if up_rev and (not dn_rev or lo_i <= hi_i):
                pivots.append((lo_i, lows[lo_i], SwingKind.LOW))
                trend = 1
                ext_i = _argmax(lo_i + 1, i)
                ext_p = highs[ext_i]
            elif dn_rev:
                pivots.append((hi_i, highs[hi_i], SwingKind.HIGH))
                trend = -1
                ext_i = _argmin(hi_i + 1, i)
                ext_p = lows[ext_i]
            else:
                if highs[i] > highs[hi_i]:
                    hi_i = i
                if lows[i] < lows[lo_i]:
                    lo_i = i
            continue

        last_idx = pivots[-1][0] if pivots else -(10 ** 9)
        if trend == 1:
            move = ext_p - lows[i]
            if ext_i < i and move >= thr and move > 0 and ext_i - last_idx >= min_bars:
                pivots.append((ext_i, ext_p, SwingKind.HIGH))
                trend = -1
                j = _argmin(ext_i + 1, i)
                ext_i, ext_p = j, lows[j]
                continue
            if pivots and lows[i] < pivots[-1][1]:
                # running up-leg failed below its starting LOW: the down leg before it continues
                pivots.pop()
                trend = -1
                ext_i, ext_p = i, lows[i]
                continue
            if highs[i] > ext_p:
                ext_i, ext_p = i, highs[i]
        else:
            move = highs[i] - ext_p
            if ext_i < i and move >= thr and move > 0 and ext_i - last_idx >= min_bars:
                pivots.append((ext_i, ext_p, SwingKind.LOW))
                trend = 1
                j = _argmax(ext_i + 1, i)
                ext_i, ext_p = j, highs[j]
                continue
            if pivots and highs[i] > pivots[-1][1]:
                pivots.pop()
                trend = 1
                ext_i, ext_p = i, highs[i]
                continue
            if lows[i] < ext_p:
                ext_i, ext_p = i, lows[i]

    swings = [Swing(index=k, ts=candles[k].ts, price=float(p), kind=kind) for k, p, kind in pivots]
    log.debug("detect_swings: %d candles -> %d swings", n, len(swings))
    return swings


def last_leg(candles: list[Candle], swings: list[Swing]) -> tuple[Swing, float]:
    """(last confirmed swing, current close). Raises ValueError if there is no swing or candle."""
    if not swings or not candles:
        raise ValueError("last_leg needs at least one swing and one candle")
    return swings[-1], candles[-1].close
