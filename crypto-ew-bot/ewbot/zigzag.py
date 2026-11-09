"""Causal zigzag + ATR helpers.

Differences to reference/zz.py (the 08.11.2026 manual script):
  * A pivot is only CONFIRMED when a later candle moves far enough away from it; every pivot carries
    `confirm_idx` (the candle that confirmed it). Everything is computed candle by candle, so the result
    for candles[:k] is always a prefix of the result for the full list (no look-ahead; tested).
  * One candle can never create both a high and a low pivot. If a candle makes a new extreme in the
    current direction we only extend the candidate and do NOT test for a reversal on that same candle
    (we cannot know whether its high or its low came first -> conservative).
  * Reversal distance is ATR-based (mult * ATR14 of closed candles) or percent-based.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .models import Candle


@dataclass(frozen=True)
class Pivot:
    kind: str                    # "H" or "L"
    idx: int                     # candle index of the extreme
    price: float
    confirm_idx: Optional[int]   # candle index that confirmed the pivot; None = still open (provisional)

    @property
    def confirmed(self) -> bool:
        return self.confirm_idx is not None


def true_ranges(candles: Sequence[Candle]) -> List[float]:
    out = []
    for i, c in enumerate(candles):
        if i == 0:
            out.append(c.h - c.l)
        else:
            pc = candles[i - 1].c
            out.append(max(c.h - c.l, abs(c.h - pc), abs(c.l - pc)))
    return out


def atr_series(candles: Sequence[Candle], n: int = 14) -> List[float]:
    """Simple moving average of true range; value at i uses candles[:i+1] only."""
    tr = true_ranges(candles)
    out, run = [], 0.0
    for i, x in enumerate(tr):
        run += x
        if i >= n:
            run -= tr[i - n]
        out.append(run / min(i + 1, n))
    return out


def atr(candles: Sequence[Candle], n: int = 14) -> float:
    if not candles:
        return 0.0
    tail = candles[-(n + 1):]
    tr = true_ranges(tail)
    tr = tr[1:] if len(tr) > 1 else tr
    return sum(tr) / len(tr)


def zigzag(candles: Sequence[Candle], mult: Optional[float] = None, pct: Optional[float] = None,
           atr_n: int = 14) -> List[Pivot]:
    """Return pivots in time order. All but the last are confirmed; the last is the open candidate extreme.

    Give either `mult` (reversal = mult * ATR) or `pct` (reversal = pct * extreme price).
    """
    if (mult is None) == (pct is None):
        raise ValueError("give exactly one of mult / pct")
    n = len(candles)
    if n < 2:
        return []
    at = atr_series(candles, atr_n) if mult is not None else None

    def dist(i: int, ref: float) -> float:
        return mult * at[i] if mult is not None else pct * ref

    piv: List[Pivot] = []
    trend = None                    # None | "up" | "down"
    hi_i, lo_i = 0, 0               # candidate extremes
    for i in range(1, n):
        c = candles[i]
        if trend is None:
            if c.h > candles[hi_i].h:
                hi_i = i
            if c.l < candles[lo_i].l:
                lo_i = i
            hp, lp = candles[hi_i].h, candles[lo_i].l
            d = dist(i, hp)
            if hi_i != lo_i and hp - lp >= d:
                if hi_i > lo_i:            # low came first, then rally
                    piv.append(Pivot("L", lo_i, lp, i)); trend = "up"
                else:
                    piv.append(Pivot("H", hi_i, hp, i)); trend = "down"
            continue
        if trend == "up":
            if c.h > candles[hi_i].h:
                hi_i = i                   # extend; no reversal test on this candle
            else:
                hp = candles[hi_i].h
                if hp - c.l >= dist(i, hp):
                    piv.append(Pivot("H", hi_i, hp, i)); trend = "down"; lo_i = i
        else:
            if c.l < candles[lo_i].l:
                lo_i = i
            else:
                lp = candles[lo_i].l
                if c.h - lp >= dist(i, lp):
                    piv.append(Pivot("L", lo_i, lp, i)); trend = "up"; hi_i = i
    if trend == "up":
        piv.append(Pivot("H", hi_i, candles[hi_i].h, None))
    elif trend == "down":
        piv.append(Pivot("L", lo_i, candles[lo_i].l, None))
    return piv


def confirmed(piv: List[Pivot]) -> List[Pivot]:
    return [p for p in piv if p.confirmed]


# ---- Fibonacci level math -------------------------------------------------------------------
def retracement_levels(low: float, high: float, ratios=(0.5, 0.618, 0.786)) -> dict:
    """Price levels of a retracement of the up-move low->high (measured down from the high)."""
    rng = high - low
    return {r: high - r * rng for r in ratios}


def abc_targets(a_start: float, a_end: float, b_end: float, ratios=(0.618, 1.0, 1.272, 1.618)) -> dict:
    """Projection of wave C in a down-move: C = B - k * A  (A = a_start - a_end)."""
    a = a_start - a_end
    return {k: b_end - k * a for k in ratios}


def robust_atr(candles: Sequence[Candle], n: int = 48) -> float:
    """Median true range of the last n candles (a single flush candle does not inflate it)."""
    tail = candles[-(n + 1):]
    tr = sorted(true_ranges(tail)[1:] if len(tail) > 1 else true_ranges(tail))
    return tr[len(tr) // 2] if tr else 0.0
