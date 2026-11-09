"""Mechanised Elliott-Wave long setup (30m trigger, 4h degree). Pure functions, no I/O, no look-ahead.

Idea (from the manual 08.11.2026 signals):
  4h: last big rally (low->high) -> retracement levels 50/61.8/78.6 %; A-B-C projection C = B - k*A.
  30m: sharp decline makes a low (wave low) inside/near those levels, then a confirmed bounce (wave 1).
  Entry = limit at 61.8 % retracement of wave 1. Stop below wave low / nearest level - ATR buffer.
  T1 = entry + t1_r * R, T2 = entry + 1.618 * wave 1 (capped at the prior range top).
All inputs are candle lists; only candles CLOSED at `now_ts` are used.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .models import Candle, Signal
from .zigzag import Pivot, atr, confirmed, zigzag, retracement_levels, abc_targets

M30 = 1_800_000
H4 = 14_400_000


@dataclass
class StrategyParams:
    # --- 4h degree ---
    deg_atr: float = 8.0            # 4h zigzag reversal = deg_atr * ATR14(4h)  (major swings only)
    rally_min_pct: float = 0.20     # a "major rally" must be at least +20 % low->high
    lookback_4h: int = 1080         # 4h candles considered (180 days)
    fib_ratios: tuple = (0.5, 0.618, 0.786)
    abc_ratios: tuple = (0.618, 1.0, 1.272, 1.618)
    zone_atr: float = 1.0           # wave low must lie within zone_atr * ATR(4h) of a level
    min_confluence: int = 1         # number of distinct levels near the wave low
    # --- 30m trigger ---
    confirm_pb_atr: Optional[float] = None   # wave 1 counts as confirmed after a pullback of this many ATR30 from its high; None = provisional/trailing
    k30: float = 2.5                # 30m zigzag reversal = k30 * ATR14(30m)
    window_30m: int = 400           # 30m candles inspected
    thrust_atr: float = 6.0         # decline into wave low (prior high -> low) >= thrust_atr * ATR30
    w1_min_atr: float = 3.5         # wave 1 (low -> high) >= w1_min_atr * ATR30
    # --- trade geometry ---
    entry_retr: float = 0.618       # entry at this retracement of wave 1
    stop_buf_atr: float = 0.5       # stop = min(wave low, level below it) - stop_buf_atr * ATR30
    t1_r: float = 1.1               # T1 = entry + t1_r * R
    t2_proj: float = 1.618          # T2 = entry + t2_proj * wave1
    min_rr_t2: float = 1.5          # skip if (T2-entry)/R below this
    max_stop_pct: float = 0.08      # skip if stop further than 8 % from entry
    min_stop_pct: float = 0.004
    expiry_h: int = 48


# ------------------------------------------------------------------------------------------------
def _closed(c: List[Candle], tf_ms: int, now_ts: int) -> List[Candle]:
    # candles are sorted ascending: cut from the end
    j = len(c)
    while j > 0 and c[j - 1].t + tf_ms > now_ts:
        j -= 1
    return c[:j]


_CTX_CACHE: Dict[tuple, dict] = {}


def analyze_4h(c4: List[Candle], last_price: float, p: StrategyParams) -> Optional[dict]:
    """Degree analysis on closed 4h candles. Returns levels or None if there is no usable rally."""
    key = (c4[-1].t, c4[-1].c, c4[0].t, len(c4), p.deg_atr, p.rally_min_pct, p.lookback_4h, p.fib_ratios, p.abc_ratios)
    ctx = _CTX_CACHE.get(key)
    if ctx is not None:
        return ctx or None
    win = c4[-p.lookback_4h:]
    a4 = atr(win)
    # major rally = from the lowest low in the window to the highest high AFTER it
    li = min(range(len(win)), key=lambda i: win[i].l)
    if li >= len(win) - 6:
        _CTX_CACHE[key] = {}
        return None
    hi_i = max(range(li + 1, len(win)), key=lambda i: win[i].h)
    lo = Pivot("L", li, win[li].l, None)
    hi = Pivot("H", hi_i, win[hi_i].h, None)
    if (hi.price - lo.price) / lo.price < p.rally_min_pct or win[-1].c >= hi.price:
        _CTX_CACHE[key] = {}
        return None
    levels = {}
    for r, v in retracement_levels(lo.price, hi.price, p.fib_ratios).items():
        levels[f"rally {r*100:.1f}%"] = v
    # A-B-C of the decline after the rally high (degree zigzag): first A/B after the top, and the latest H-L-H
    pv = [x for x in confirmed(zigzag(win, mult=p.deg_atr)) if x.idx >= hi.idx]
    abc = None
    cands = []
    if len(pv) >= 3 and pv[0].kind == "H":
        cands.append((pv[0], pv[1], pv[2]))
    for k in range(len(pv) - 3, -1, -1):
        if pv[k].kind == "H":
            cands.append((pv[k], pv[k + 1], pv[k + 2])); break
    seen = set()
    for (h0, la, hb) in cands:
        if h0.kind == "H" and la.kind == "L" and hb.kind == "H" and hb.price < h0.price and la.price > lo.price \
                and (h0.idx, la.idx) not in seen:
            seen.add((h0.idx, la.idx))
            tag = "" if len(seen) == 1 else "'"
            abc = abc or dict(a_start=h0.price, a_end=la.price, b_end=hb.price)
            for r, v in abc_targets(h0.price, la.price, hb.price, p.abc_ratios).items():
                levels[f"C={r:g}A{tag}"] = v
    ctx = dict(atr4=a4, rally_low=lo.price, rally_high=hi.price, rally_low_t=win[lo.idx].t,
               rally_high_t=win[hi.idx].t, levels=levels, abc=abc)
    _CTX_CACHE[key] = ctx
    if len(_CTX_CACHE) > 4000:
        _CTX_CACHE.clear()
    return ctx


def _fmt(x: float) -> str:
    return f"{x:,.2f}" if x < 1000 else f"{x:,.0f}"


def find_signals(coin: str, instrument: str, c30: List[Candle], c4h: List[Candle],
                 p: Optional[StrategyParams] = None, now_ts: Optional[int] = None) -> List[Signal]:
    """0 or 1 pending long setup (the freshest valid one) using only candles closed at now_ts."""
    p = p or StrategyParams()
    if now_ts is None:
        now_ts = c30[-1].t + M30 if c30 else int(time.time() * 1000)
    c30 = _closed(c30, M30, now_ts)
    c4h = _closed(c4h, H4, now_ts)
    if len(c30) < 100 or len(c4h) < 120:
        return []
    w = c30[-p.window_30m:]
    last = w[-1].c
    ctx = analyze_4h(c4h, last, p)
    if ctx is None:
        return []
    cp = confirmed(zigzag(w, mult=p.k30))
    # wave low = latest confirmed 30m low that has a confirmed high before it (the start of the decline)
    li = None
    for k in range(len(cp) - 1, 0, -1):
        if cp[k].kind == "L" and cp[k - 1].kind == "H":
            li = k
            break
    if li is None:
        return []
    h_prev, wl = cp[li - 1], cp[li]
    # volatility unit = ATR14(30m) from BEFORE the flush (the flush candles would inflate it), floored at atr4/4
    a30 = max(atr(w[:h_prev.idx + 1]), ctx["atr4"] / 4)
    wave_low = wl.price
    if h_prev.price - wave_low < p.thrust_atr * a30:
        return []                                   # no sharp decline into the low
    # wave low must sit in the 4h confluence zone
    tol = p.zone_atr * ctx["atr4"]
    hits = {n: v for n, v in ctx["levels"].items() if abs(v - wave_low) <= tol}
    if len(hits) < p.min_confluence:
        return []
    # walk the closed candles after the low: running wave-1 high, confirmation, invalidation
    hh, created_idx, wave1_high = float("-inf"), None, None
    for j in range(wl.idx + 1, len(w)):
        c = w[j]
        if c.l <= wave_low:
            return []                               # hard rule: wave 2 never below wave-1 start
        new_high = c.h > hh
        if created_idx is None:
            if new_high:
                hh = c.h
            if hh - wave_low >= p.w1_min_atr * a30:
                if p.confirm_pb_atr is None:
                    created_idx, wave1_high = j, hh
                elif not new_high and hh - c.l >= p.confirm_pb_atr * a30:
                    created_idx, wave1_high = j, hh
        elif p.confirm_pb_atr is None and new_high:
            hh = c.h; wave1_high = hh               # provisional mode: wave 1 still extending (trailing entry)
    if created_idx is None:
        return []
    created_ts = w[created_idx].t + M30
    valid_until = created_ts + p.expiry_h * 3_600_000
    if now_ts < created_ts or now_ts >= valid_until:
        return []
    w1 = wave1_high - wave_low
    # --- geometry ---
    entry = wave1_high - p.entry_retr * w1
    below = [v for v in hits.values() if v <= wave_low]
    stop = min([wave_low] + below) - p.stop_buf_atr * a30
    risk = entry - stop
    if risk <= 0 or not (p.min_stop_pct <= risk / entry <= p.max_stop_pct):
        return []
    t1 = max(entry + p.t1_r * risk, wave1_high)     # never below the wave-1 high (prior high = first resistance)
    t2 = entry + p.t2_proj * w1
    if h_prev.price > t1 + 0.3 * risk and h_prev.price < t2:
        t2 = h_prev.price                           # prior range top caps the wave-3 projection
    if (t2 - entry) / risk < p.min_rr_t2 or t2 <= t1:
        return []
    for c in w[created_idx + 1:]:
        if c.h >= t1:
            return []          # T1 reached (cancel rule)
    if last <= entry:
        return []              # price already at/below entry: no resting buy possible
    n_hit = len(hits)
    score = min(1.0, 0.4 * n_hit + 0.3 * min(1.0, w1 / (p.w1_min_atr * a30) / 2) + 0.3 * min(1.0, (h_prev.price - wave_low) / (p.thrust_atr * a30) / 2))
    fib_hits = [f"{n} {_fmt(v)}" for n, v in hits.items()]
    reason = (f"4h: Rally {_fmt(ctx['rally_low'])} -> {_fmt(ctx['rally_high'])}. 30m: scharfer Abverkauf bis {_fmt(wave_low)} "
              f"(Zone: {', '.join(hits)}), Welle-1-Erholung bis {_fmt(wave1_high)}. Einstieg bei 61,8 % der Welle 1.")
    return [Signal(coin=coin, instrument=instrument, created_ts=created_ts, valid_until_ts=valid_until,
                   entry=round(entry, 6), stop=round(stop, 6), t1=round(t1, 6), t2=round(t2, 6),
                   wave_low=wave_low, wave1_high=wave1_high, cancel_above=round(t1, 6), score=round(score, 2),
                   fib_hits=fib_hits, reason_de=reason, id=f"{coin}-{created_ts}")]


def describe_count(coin: str, c30: List[Candle], c4h: List[Candle], p: Optional[StrategyParams] = None) -> dict:
    """Human-readable state of the count (for the page / debugging)."""
    p = p or StrategyParams()
    now_ts = c30[-1].t + M30
    c30 = _closed(c30, M30, now_ts); c4h = _closed(c4h, H4, now_ts)
    ctx = analyze_4h(c4h, c30[-1].c, p) if len(c4h) >= 120 else None
    w = c30[-p.window_30m:]
    pv = [dict(kind=x.kind, t=w[x.idx].t, price=x.price, confirmed=x.confirmed) for x in zigzag(w, mult=p.k30)[-8:]]
    if ctx is None:
        return dict(degree_rally=None, zone=None, pivots=pv, text_de=f"{coin}: keine grosse 4h-Rally im Blick, kein Setup.")
    lv = sorted(ctx["levels"].values())
    near = sorted(v for v in lv if abs(v - c30[-1].c) <= 4 * ctx["atr4"])
    zone = [near[0], near[-1]] if near else None
    txt = (f"{coin}: 4h-Rally {_fmt(ctx['rally_low'])} -> {_fmt(ctx['rally_high'])}; Rueckgang bisher "
           f"{(ctx['rally_high']-c30[-1].c)/(ctx['rally_high']-ctx['rally_low'])*100:.0f} % der Rally. "
           + "Level: " + ", ".join(f"{k} {_fmt(v)}" for k, v in ctx["levels"].items()))
    return dict(degree_rally=dict(low=ctx["rally_low"], high=ctx["rally_high"], abc=ctx["abc"]), zone=zone,
                levels=ctx["levels"], atr4=ctx["atr4"], pivots=pv, text_de=txt)
