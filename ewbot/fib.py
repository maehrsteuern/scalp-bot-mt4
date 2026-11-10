"""Fibonacci retracement / extension helpers."""
from __future__ import annotations

from ewbot.models import FibLevels

RETRACE: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTEND: tuple[float, ...] = (1.0, 1.272, 1.618, 2.0, 2.618)


def retracement(start: float, end: float, ratios: tuple[float, ...] = RETRACE) -> FibLevels:
    """Retracement levels of the leg start->end, measured back from ``end`` towards ``start``."""
    move = end - start
    return FibLevels(start=start, end=end, levels={r: end - move * r for r in ratios})


def extension(start: float, end: float, from_price: float, ratios: tuple[float, ...] = EXTEND) -> FibLevels:
    """Project |end-start| * ratio from ``from_price`` in the direction of (end - start)."""
    move = end - start
    return FibLevels(start=start, end=end, levels={r: from_price + move * r for r in ratios})


def ratio_of(move: float, base: float) -> float:
    """abs(move) / abs(base); 0.0 if base == 0."""
    if base == 0:
        return 0.0
    return abs(move) / abs(base)


def in_band(ratio: float, lo: float, hi: float) -> bool:
    """Inclusive band check."""
    return lo <= ratio <= hi
