"""Elliott-Wave signal generation (WAVE3 / WAVE5 / WAVEC setups) with higher-timeframe confirmation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ewbot.config import BotCfg
from ewbot.elliott import bias_from_counts, find_counts, primary_count
from ewbot.fib import in_band, retracement
from ewbot.models import (Bias, Candle, HtfContext, PatternType, SetupType, Side, Signal, Swing, WaveCount)
from ewbot.swings import atr, detect_swings, ema

log = logging.getLogger(__name__)

CONFLUENCE_BONUS = 0.15
_SETUP_ORDER = (SetupType.WAVE3, SetupType.WAVE5, SetupType.WAVEC)


@dataclass
class _Ctx:
    n: int
    close: float
    prev_close: float
    atr: float
    ts: int
    last_swing: Swing


@dataclass
class _Candidate:
    setup: SetupType
    side: Side
    count: WaveCount
    zone: float                 # end of the retracement (p2 / p4 / B) used for HTF fib confluence
    entry: float
    stop: float
    tp1: float
    tp2: float
    reasons: list[str] = field(default_factory=list)


def _bias_side(bias: Bias) -> Optional[Side]:
    if bias is Bias.BULL:
        return Side.LONG
    if bias is Bias.BEAR:
        return Side.SHORT
    return None


class ElliottStrategy:
    def __init__(self, cfg: BotCfg) -> None:
        self.cfg = cfg
        enabled = {s.lower() for s in cfg.strategy.setups}
        self.setups: list[SetupType] = [s for s in _SETUP_ORDER if s.value.lower() in enabled]

    # ------------------------------------------------------------------ HTF
    def analyse_htf(self, timeframe: str, candles: list[Candle]) -> HtfContext:
        candles = candles[-self.cfg.swing.lookback:] if self.cfg.swing.lookback > 0 else list(candles)
        if not candles:
            return HtfContext(timeframe, Bias.NEUTRAL, None, None, 0.0, 0.0, 0.0, ["no candles"])
        closes = [c.close for c in candles]
        price = closes[-1]
        ema_f = ema(closes, self.cfg.strategy.ema_fast)[-1]
        ema_s = ema(closes, self.cfg.strategy.ema_slow)[-1]
        atr_v = atr(candles, self.cfg.swing.atr_period)[-1]
        swings = detect_swings(candles, self.cfg.swing)
        counts = find_counts(swings, price, self.cfg.elliott)
        count = primary_count(counts)
        bias = bias_from_counts(counts, price)
        notes: list[str] = []
        if count is not None:
            notes.append(f"count {count.degree_label} {'complete' if count.complete else 'running'} "
                         f"score={count.score:.2f}")
        if bias is Bias.NEUTRAL:
            if price > ema_f > ema_s:
                bias = Bias.BULL
            elif price < ema_f < ema_s:
                bias = Bias.BEAR
            notes.append(f"ema bias {bias.value}")
        else:
            notes.append(f"wave bias {bias.value}")
        fib = retracement(swings[-2].price, swings[-1].price) if len(swings) >= 2 else None
        return HtfContext(timeframe, bias, count, fib, ema_f, ema_s, atr_v, notes)

    # ------------------------------------------------------------------ exec timeframe
    def evaluate(self, symbol: str, candles: list[Candle], htf: list[HtfContext]) -> Optional[Signal]:
        if self.cfg.swing.lookback > 0:
            candles = candles[-self.cfg.swing.lookback:]
        if len(candles) < 3:
            return None
        swings = detect_swings(candles, self.cfg.swing)
        if len(swings) < 3:
            return None
        ctx = _Ctx(n=len(candles), close=candles[-1].close, prev_close=candles[-2].close,
                   atr=atr(candles, self.cfg.swing.atr_period)[-1], ts=candles[-1].ts, last_swing=swings[-1])
        counts = find_counts(swings, ctx.close, self.cfg.elliott)

        cands: list[_Candidate] = []
        for setup in self.setups:
            for c in counts:
                cand = None
                if setup is SetupType.WAVE3:
                    cand = self._wave3(c, ctx)
                elif setup is SetupType.WAVE5:
                    cand = self._wave5(c, ctx)
                elif setup is SetupType.WAVEC:
                    cand = self._wavec(c, counts, ctx)
                if cand is not None:
                    cands.append(cand)

        best: Optional[Signal] = None
        for cand in cands:
            sig = self._finalise(symbol, cand, htf, ctx)
            if sig is not None and (best is None or sig.score > best.score):
                best = sig
        return best

    # ------------------------------------------------------------------ setups
    def _trigger_ok(self, side: Side, pivot: Swing, ctx: _Ctx) -> bool:
        s = side.sign
        if pivot.index != ctx.last_swing.index:
            return False
        if not s * (ctx.close - pivot.price) > 0:
            return False
        if self.cfg.strategy.confirm_with_close and not s * (ctx.close - ctx.prev_close) > 0:
            return False
        return (ctx.n - 1 - pivot.index) <= self.cfg.strategy.max_signal_age_bars

    def _wave3(self, c: WaveCount, ctx: _Ctx) -> Optional[_Candidate]:
        if c.pattern is not PatternType.IMPULSE or c.complete or len(c.swings) != 3:
            return None
        e = self.cfg.elliott
        side = c.direction
        s = side.sign
        p0, p1, p2 = c.points[0], c.points[1], c.points[2]
        w2r = c.ratios.get("w2/w1", 0.0)
        if not in_band(w2r, e.w2_min, e.w2_max) or not self._trigger_ok(side, c.swings[2], ctx):
            return None
        w1 = p1 - p0
        stop = p0 - s * self.cfg.strategy.stop_buffer_atr * ctx.atr
        return _Candidate(SetupType.WAVE3, side, c, p2, ctx.close, stop, p2 + 1.0 * w1, p2 + 1.618 * w1,
                          [f"wave3 {side.value}: w2/w1={w2r:.3f}", f"count score {c.score:.2f}"])

    def _wave5(self, c: WaveCount, ctx: _Ctx) -> Optional[_Candidate]:
        if c.pattern is not PatternType.IMPULSE or c.complete or len(c.swings) != 5:
            return None
        e = self.cfg.elliott
        side = c.direction
        s = side.sign
        p0, p1, p2, p3, p4 = c.points[:5]
        w4r = c.ratios.get("w4/w3", 0.0)
        if not in_band(w4r, e.w4_min, e.w4_max) or not s * (p4 - p1) > 0:
            return None
        if not self._trigger_ok(side, c.swings[4], ctx):
            return None
        w1 = p1 - p0
        stop = p4 - s * self.cfg.strategy.stop_buffer_atr * ctx.atr
        tp1 = p4 + 0.618 * w1
        tp2 = p4 + 1.0 * w1
        reasons = [f"wave5 {side.value}: w4/w3={w4r:.3f}", f"count score {c.score:.2f}"]
        if not s * (tp1 - p3) > 0:
            tp1 = p3 + 0.1 * (p3 - p2)
            reasons.append("tp1 moved beyond wave-3 end")
        if not s * (tp2 - tp1) > 0:
            tp2 = tp1 + 0.5 * (tp1 - ctx.close)
        return _Candidate(SetupType.WAVE5, side, c, p4, ctx.close, stop, tp1, tp2, reasons)

    def _wavec(self, c: WaveCount, counts: list[WaveCount], ctx: _Ctx) -> Optional[_Candidate]:
        if c.pattern is not PatternType.ZIGZAG or c.complete or len(c.swings) != 3:
            return None
        e = self.cfg.elliott
        side = c.direction
        s = side.sign
        p0, p1, p2 = c.points[0], c.points[1], c.points[2]
        prior = [k for k in counts if k.pattern is PatternType.IMPULSE and k.complete
                 and k.direction is side.opposite and k.swings[-1].index == c.swings[0].index]
        if not prior:
            return None
        bar = c.ratios.get("B/A", 0.0)
        if not in_band(bar, e.wb_min, e.wb_max) or not s * (p2 - p0) > 0:
            return None
        if not self._trigger_ok(side, c.swings[2], ctx):
            return None
        a = p1 - p0
        stop = p2 - s * self.cfg.strategy.stop_buffer_atr * ctx.atr
        imp = prior[0]
        return _Candidate(SetupType.WAVEC, side, c, p2, ctx.close, stop, p2 + 1.0 * a, p2 + 1.618 * a,
                          [f"waveC {side.value}: B/A={bar:.3f}", f"count score {c.score:.2f}",
                           f"after {imp.degree_label} score {imp.score:.2f}"])

    # ------------------------------------------------------------------ scoring / gating
    def _finalise(self, symbol: str, cand: _Candidate, htf: list[HtfContext], ctx: _Ctx) -> Optional[Signal]:
        st = self.cfg.strategy
        side = cand.side
        s = side.sign
        reasons = list(cand.reasons)
        if not (s * (cand.entry - cand.stop) > 0 and s * (cand.tp1 - cand.entry) > 0
                and s * (cand.tp2 - cand.entry) > 0):
            log.debug("%s %s %s: price levels on wrong side", symbol, cand.setup.value, side.value)
            return None

        sides = [_bias_side(h.bias) for h in htf]
        agree = sum(1 for x in sides if x is side)
        oppose = sum(1 for x in sides if x is side.opposite)
        if st.require_htf_agreement and (oppose > 0 or agree == 0):
            log.debug("%s %s %s: HTF gate failed (agree=%d oppose=%d)", symbol, cand.setup.value,
                      side.value, agree, oppose)
            return None
        if oppose > 0 or agree == 0:
            agreement = 0.0
        elif agree == len(htf):
            agreement = 1.0
        else:
            agreement = 0.5
        for h in htf:
            if _bias_side(h.bias) is side:
                reasons.append(f"HTF {h.timeframe} {h.bias.value}")

        bonus = 0.0
        for h in htf:
            if h.fib is None or h.atr <= 0:
                continue
            tol = st.htf_fib_confluence_atr * h.atr
            hits = [(abs(lvl - cand.zone), r, lvl) for r, lvl in h.fib.levels.items()
                    if abs(lvl - cand.zone) <= tol]
            if hits:
                _, r, lvl = min(hits)
                bonus = CONFLUENCE_BONUS
                reasons.append(f"HTF {h.timeframe} fib {r:g} confluence @ {lvl:.6g}")
                break

        score = min(1.0, max(0.0, 0.6 * cand.count.score + 0.25 * agreement + bonus))
        sig = Signal(symbol=symbol, timeframe=st.exec_timeframe, side=side, setup=cand.setup,
                     entry=cand.entry, stop=cand.stop, tp1=cand.tp1, tp2=cand.tp2, ts=ctx.ts, score=score,
                     count=cand.count, htf=list(htf), reasons=reasons)
        sig.reasons.append(f"score {score:.2f} rr1 {sig.rr1:.2f}")
        if score < st.min_signal_score:
            log.debug("%s %s %s: score %.3f < %.3f", symbol, cand.setup.value, side.value, score,
                      st.min_signal_score)
            return None
        if sig.rr1 < st.min_rr1:
            log.debug("%s %s %s: rr1 %.3f < %.3f", symbol, cand.setup.value, side.value, sig.rr1, st.min_rr1)
            return None
        return sig
