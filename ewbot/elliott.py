"""Elliott-Wave candidate counting over ZigZag swings.

``find_counts`` labels windows of consecutive swings as IMPULSE (0-1-2-3-4-5) or ZIGZAG (A-B-C) candidates,
complete or still in progress (the running final point is the current price), filters them with the hard
Elliott rules and ranks them by a Fibonacci-conformity score.
"""
from __future__ import annotations

import logging
from typing import Optional

from ewbot.config import ElliottCfg
from ewbot.fib import ratio_of
from ewbot.models import Bias, PatternType, Side, Swing, SwingKind, WaveCount

log = logging.getLogger(__name__)

ALTERNATION_BONUS = 0.1
_SHARP = 0.5          # a retracement >= 50 % counts as "sharp", below as "shallow"


def _closeness(r: float, ideal_lo: float, ideal_hi: float, band_lo: float, band_hi: float) -> float:
    """1.0 inside the ideal range, linearly down to 0.5 at the band edges, decaying to 0 outside."""
    if ideal_lo <= r <= ideal_hi:
        return 1.0
    scale = max(0.25, 0.5 * (ideal_lo + ideal_hi) / 2.0)
    if r < ideal_lo:
        span = ideal_lo - band_lo
        if span > 0 and r >= band_lo:
            return 1.0 - 0.5 * (ideal_lo - r) / span
        excess = (band_lo - r) if span > 0 else (ideal_lo - r)
    else:
        span = band_hi - ideal_hi
        if span > 0 and r <= band_hi:
            return 1.0 - 0.5 * (r - ideal_hi) / span
        excess = (r - band_hi) if span > 0 else (r - ideal_hi)
    return max(0.0, 0.5 * (1.0 - excess / scale))


def _rate(name: str, r: float, ideal: tuple[float, float], band: tuple[float, float],
          violations: list[str]) -> float:
    if not (band[0] <= r <= band[1]):
        violations.append(f"{name}={r:.3f} outside [{band[0]:g},{band[1]:g}]")
    return _closeness(r, ideal[0], ideal[1], band[0], band[1])


def _legs_ok(q: list[float], complete: bool) -> bool:
    """Legs alternate up/down starting with up (q is normalised to the upward case)."""
    m = len(q)
    for i in range(1, m):
        leg = q[i] - q[i - 1]
        up = i % 2 == 1
        if i == m - 1 and not complete:
            if (up and leg < 0) or (not up and leg > 0):
                return False
        elif (up and leg <= 0) or (not up and leg >= 0):
            return False
    return True


def _impulse(swings: list[Swing], points: list[float], complete: bool, cfg: ElliottCfg) -> Optional[WaveCount]:
    direction = Side.LONG if swings[0].kind is SwingKind.LOW else Side.SHORT
    s = direction.sign
    q = [s * p for p in points]
    m = len(q)
    last_conf = m - 1 if complete else m - 2
    if not _legs_ok(q, complete):
        return None
    w1 = q[1] - q[0]
    # hard rules (normalised upward)
    if m > 2 and not q[2] > q[0]:
        return None                                   # wave 2 retraced > 100 % of wave 1
    if last_conf >= 3 and not q[3] > q[1]:
        return None                                   # wave 3 must exceed the end of wave 1
    if m > 4 and not q[4] > q[1]:
        return None                                   # wave 4 overlaps wave 1
    if complete and not q[5] > q[3]:
        return None                                   # wave 5 must exceed wave 3
    w3 = q[3] - q[2] if m > 3 else 0.0
    if last_conf >= 3 and w3 < cfg.w3_min_ext * w1:
        return None                                   # wave 3 too short vs wave 1
    if m > 5:
        w5 = q[5] - q[4]
        if complete and w3 < w1 and w3 < w5:
            return None                               # wave 3 is the shortest
        if not complete and w3 < w1 and w5 > w3:
            return None                               # running wave 5 already made wave 3 the shortest

    ratios: dict[str, float] = {}
    violations: list[str] = []
    parts: list[float] = []
    w2r = ratio_of(q[2] - q[1], w1)
    ratios["w2/w1"] = w2r
    parts.append(_rate("w2/w1", w2r, (0.618, 0.618), (cfg.w2_min, cfg.w2_max), violations))
    if last_conf >= 3:
        w3r = ratio_of(w3, w1)
        ratios["w3/w1"] = w3r
        parts.append(_rate("w3/w1", w3r, (1.618, 1.618), (cfg.w3_min_ext, 2.618), violations))
    if last_conf >= 4:
        w4r = ratio_of(q[4] - q[3], w3)
        ratios["w4/w3"] = w4r
        parts.append(_rate("w4/w3", w4r, (0.382, 0.382), (cfg.w4_min, cfg.w4_max), violations))
    if complete:
        w5r = ratio_of(q[5] - q[4], w1)
        ratios["w5/w1"] = w5r
        parts.append(_rate("w5/w1", w5r, (0.618, 1.0), (0.382, 1.618), violations))
    if not complete:
        run = m - 1
        base = w3 if run == 4 else w1
        key = {3: "w3/w1", 4: "w4/w3", 5: "w5/w1"}[run]
        ratios[key + "_run"] = ratio_of(q[run] - q[run - 1], base)
    score = sum(parts) / len(parts)
    if "w4/w3" in ratios:
        if (ratios["w2/w1"] >= _SHARP) != (ratios["w4/w3"] >= _SHARP):
            score += ALTERNATION_BONUS
            ratios["alternation"] = 1.0
        else:
            violations.append("no alternation between wave 2 and wave 4")
            ratios["alternation"] = 0.0
    score = min(1.0, max(0.0, score))
    return WaveCount(PatternType.IMPULSE, direction, list(swings), list(points), complete, score, ratios,
                     violations)


def _zigzag(swings: list[Swing], points: list[float], complete: bool, cfg: ElliottCfg) -> Optional[WaveCount]:
    direction = Side.LONG if swings[0].kind is SwingKind.LOW else Side.SHORT
    s = direction.sign
    q = [s * p for p in points]
    if not _legs_ok(q, complete):
        return None
    a = q[1] - q[0]
    if not q[2] > q[0]:
        return None                                   # B retraced >= 100 % of A
    if complete and not q[3] > q[1]:
        return None                                   # C must exceed the end of A
    ratios: dict[str, float] = {}
    violations: list[str] = []
    parts: list[float] = []
    br = ratio_of(q[2] - q[1], a)
    ratios["B/A"] = br
    parts.append(_rate("B/A", br, (0.618, 0.618), (cfg.wb_min, cfg.wb_max), violations))
    cr = ratio_of(q[3] - q[2], a)
    if complete:
        ratios["C/A"] = cr
        parts.append(_rate("C/A", cr, (1.0, 1.618), (0.618, 2.618), violations))
    else:
        ratios["C/A_run"] = cr
    score = min(1.0, max(0.0, sum(parts) / len(parts)))
    return WaveCount(PatternType.ZIGZAG, direction, list(swings), list(points), complete, score, ratios,
                     violations)


def find_counts(swings: list[Swing], current_price: float, cfg: ElliottCfg) -> list[WaveCount]:
    """All valid IMPULSE / ZIGZAG candidates over the last ``cfg.max_swings`` swings, best score first.

    Complete counts use consecutive confirmed swings only. In-progress counts end at the last confirmed swing
    and append ``current_price`` as the running final point (impulse: 3..5 confirmed points, zigzag: 3).
    Counts scoring below ``cfg.min_score`` are dropped.
    """
    sw = list(swings[-max(0, int(cfg.max_swings)):]) if cfg.max_swings > 0 else []
    n = len(sw)
    out: list[WaveCount] = []
    # complete impulses (6 swings) and zigzags (4 swings)
    for size, builder in ((6, _impulse), (4, _zigzag)):
        for j in range(0, n - size + 1):
            win = sw[j:j + size]
            c = builder(win, [x.price for x in win], True, cfg)
            if c is not None:
                out.append(c)
    # in-progress impulses: points 0..k confirmed (k = 2..4) + running final point
    for k in (2, 3, 4):
        if n >= k + 1:
            win = sw[n - k - 1:]
            c = _impulse(win, [x.price for x in win] + [float(current_price)], False, cfg)
            if c is not None:
                out.append(c)
    # in-progress zigzag: A, B confirmed + running C
    if n >= 3:
        win = sw[n - 3:]
        c = _zigzag(win, [x.price for x in win] + [float(current_price)], False, cfg)
        if c is not None:
            out.append(c)

    out = [c for c in out if c.score >= cfg.min_score]
    out.sort(key=lambda c: (-c.score, -c.swings[-1].index, -len(c.points), c.pattern.value,
                            c.direction.value, c.complete))
    log.debug("find_counts: %d swings -> %d counts", n, len(out))
    return out


def best_count(counts: list[WaveCount], pattern: Optional[PatternType] = None) -> Optional[WaveCount]:
    """Highest scoring count (optionally of one pattern type)."""
    cands = [c for c in counts if pattern is None or c.pattern is pattern]
    if not cands:
        return None
    return min(cands, key=lambda c: -c.score)


def primary_count(counts: list[WaveCount]) -> Optional[WaveCount]:
    """The most relevant count right now: among counts ending at the most recent swing, the best scored."""
    if not counts:
        return None
    latest = max(c.swings[-1].index for c in counts)
    return best_count([c for c in counts if c.swings[-1].index == latest])


def bias_from_counts(counts: list[WaveCount], current_price: float) -> Bias:
    """Directional bias implied by the primary count.

    Impulse in progress in wave 3 or 5 -> its direction; in wave 4 -> NEUTRAL; complete impulse -> the
    opposite (a correction is due). Zigzag with C in progress -> its direction; complete zigzag -> the
    opposite (the larger trend resumes, e.g. a completed zigzag down implies BULL). A complete count whose
    terminal point has already been exceeded by ``current_price`` gives NEUTRAL.
    """
    c = primary_count(counts)
    if c is None:
        return Bias.NEUTRAL
    s = c.direction.sign
    last_up = (len(c.points) - 1) % 2 == 1          # final wave travels in the count's direction?
    final_sign = s if last_up else -s
    implied: Optional[Side]
    if c.complete:
        if final_sign * (current_price - c.points[-1]) > 0:
            return Bias.NEUTRAL
        implied = c.direction.opposite
    elif c.pattern is PatternType.IMPULSE:
        running = len(c.points) - 1
        implied = c.direction if running in (3, 5) else None
    else:
        implied = c.direction
    if implied is None:
        return Bias.NEUTRAL
    return Bias.BULL if implied is Side.LONG else Bias.BEAR
