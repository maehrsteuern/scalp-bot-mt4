import dataclasses

import pytest

from ewbot.config import BotCfg, StrategyCfg
from ewbot.fib import retracement
from ewbot.models import Bias, HtfContext, PatternType, SetupType, Side
from ewbot.strategy import ElliottStrategy

try:
    from tests.synthetic import (impulse_candles, impulse_pivots, leg_bars, mirror_candles, path_to_candles,
                                 wave3_setup_candles)
except ImportError:  # pragma: no cover
    from synthetic import (impulse_candles, impulse_pivots, leg_bars, mirror_candles, path_to_candles,
                           wave3_setup_candles)

AXIS = 200.0


def make_cfg(**strategy) -> BotCfg:
    cfg = BotCfg()
    cfg.strategy = dataclasses.replace(StrategyCfg(), **strategy)
    return cfg


def htf(bias: Bias, tf: str = "1h", fib=None, atr: float = 1.0) -> HtfContext:
    return HtfContext(tf, bias, None, fib, 0.0, 0.0, atr)


def wave5_candles():
    piv = impulse_pivots()[:5]
    path = [108.0] + piv + [piv[4] + 2.0]
    return path_to_candles(path, leg_bars(path[:-1]) + [3]), piv


def wavec_candles():
    imp = impulse_pivots(direction=-1)                  # 100 -> 76.18
    a_end = imp[5] + 10.0
    b_end = a_end - 6.18
    path = [92.0] + imp + [a_end, b_end, b_end + 2.0]
    return path_to_candles(path, leg_bars(path[:-1]) + [3]), [imp[5], a_end, b_end]


def test_wave3_long_signal():
    candles, (p0, p1, p2) = wave3_setup_candles()
    sig = ElliottStrategy(BotCfg()).evaluate("BTC/USD", candles, [htf(Bias.BULL), htf(Bias.NEUTRAL, "4h")])
    assert sig is not None
    assert sig.side is Side.LONG and sig.setup is SetupType.WAVE3
    assert sig.stop < p0
    assert sig.rr1 >= 1.0
    assert sig.entry == candles[-1].close and sig.ts == candles[-1].ts
    assert sig.tp1 == pytest.approx(p2 + (p1 - p0))
    assert sig.tp2 == pytest.approx(p2 + 1.618 * (p1 - p0))
    assert sig.count.pattern is PatternType.IMPULSE and not sig.count.complete
    assert sig.score == pytest.approx(0.6 * sig.count.score + 0.25 * 0.5)    # one of two HTFs agrees
    assert sig.reasons and sig.timeframe == "15m"
    full = ElliottStrategy(BotCfg()).evaluate("BTC/USD", candles, [htf(Bias.BULL), htf(Bias.BULL, "4h")])
    assert full.score == pytest.approx(min(1.0, 0.6 * full.count.score + 0.25))


def test_opposing_htf_blocks_signal():
    candles, _ = wave3_setup_candles()
    st = ElliottStrategy(BotCfg())
    assert st.evaluate("BTC/USD", candles, [htf(Bias.BEAR)]) is None
    assert st.evaluate("BTC/USD", candles, [htf(Bias.BULL), htf(Bias.BEAR, "4h")]) is None
    assert st.evaluate("BTC/USD", candles, [htf(Bias.NEUTRAL)]) is None       # none agrees
    assert st.evaluate("BTC/USD", candles, []) is None


def test_htf_gate_can_be_disabled():
    candles, _ = wave3_setup_candles()
    st = ElliottStrategy(make_cfg(require_htf_agreement=False, min_signal_score=0.5))
    sig = st.evaluate("BTC/USD", candles, [htf(Bias.BEAR)])
    assert sig is not None and sig.score == pytest.approx(0.6 * sig.count.score)


def test_short_mirrors_long():
    for builder, setups in ((wave3_setup_candles, ["wave3"]), (wave5_candles, ["wave5"]),
                            (wavec_candles, ["waveC"])):
        candles, _ = builder()
        st = ElliottStrategy(make_cfg(setups=setups))
        lng = st.evaluate("ETH/USD", candles, [htf(Bias.BULL)])
        sht = st.evaluate("ETH/USD", mirror_candles(candles, AXIS), [htf(Bias.BEAR)])
        assert lng is not None and sht is not None, builder.__name__
        assert lng.side is Side.LONG and sht.side is Side.SHORT
        assert sht.setup is lng.setup
        for attr in ("entry", "stop", "tp1", "tp2"):
            assert getattr(sht, attr) == pytest.approx(AXIS - getattr(lng, attr)), attr
        assert sht.stop > sht.entry > sht.tp1 > sht.tp2
        assert sht.rr1 == pytest.approx(lng.rr1) and sht.score == pytest.approx(lng.score)
        # a short is never produced with a bullish HTF
        assert st.evaluate("ETH/USD", mirror_candles(candles, AXIS), [htf(Bias.BULL)]) is None


def test_htf_fib_confluence_bonus():
    candles, (p0, p1, p2) = wave3_setup_candles()
    st = ElliottStrategy(BotCfg())
    base = st.evaluate("BTC/USD", candles, [htf(Bias.BULL), htf(Bias.NEUTRAL, "4h")])
    grid = retracement(p0 - 5.0, p1 + 5.0)                     # 0.618 level lands near p2? check tolerance
    near = min(abs(v - p2) for v in grid.levels.values())
    tol_atr = (near + 0.01) / 0.5
    boosted = st.evaluate("BTC/USD", candles, [htf(Bias.BULL), htf(Bias.NEUTRAL, "4h", grid, tol_atr)])
    assert boosted.score == pytest.approx(base.score + 0.15)
    assert any("confluence" in r for r in boosted.reasons)
    far = st.evaluate("BTC/USD", candles, [htf(Bias.BULL), htf(Bias.NEUTRAL, "4h", grid, 1e-6)])
    assert far.score == pytest.approx(base.score)


def test_rejections():
    candles, _ = wave3_setup_candles()
    bull = [htf(Bias.BULL)]
    assert ElliottStrategy(make_cfg(min_rr1=5.0)).evaluate("X", candles, bull) is None
    assert ElliottStrategy(make_cfg(min_signal_score=0.99)).evaluate("X", candles, bull) is None
    assert ElliottStrategy(make_cfg(setups=["wave5", "waveC"])).evaluate("X", candles, bull) is None
    # stale: the wave-2 low is more than max_signal_age_bars old
    slow, _ = wave3_setup_candles(rally=3.0, rally_bars=7)
    assert ElliottStrategy(BotCfg()).evaluate("X", slow, bull) is None
    assert ElliottStrategy(make_cfg(max_signal_age_bars=10)).evaluate("X", slow, bull) is not None
    # last candle closes down -> no confirmation
    down = candles[:-1] + [dataclasses.replace(candles[-1], close=candles[-2].close - 0.01)]
    assert ElliottStrategy(BotCfg()).evaluate("X", down, bull) is None
    assert ElliottStrategy(make_cfg(confirm_with_close=False)).evaluate("X", down, bull) is not None
    # too little data
    assert ElliottStrategy(BotCfg()).evaluate("X", candles[:10], bull) is None
    assert ElliottStrategy(BotCfg()).evaluate("X", [], bull) is None


def test_wave5_signal():
    candles, (p0, p1, p2, p3, p4) = wave5_candles()
    sig = ElliottStrategy(BotCfg()).evaluate("SOL/USD", candles, [htf(Bias.BULL)])
    assert sig is not None and sig.setup is SetupType.WAVE5 and sig.side is Side.LONG
    assert sig.stop < p4 < sig.entry
    # p4 + 0.618*w1 does not exceed p3 here -> tp1 = p3 + 0.1*(p3-p2)
    assert sig.tp1 == pytest.approx(p3 + 0.1 * (p3 - p2))
    assert sig.tp2 == pytest.approx(p4 + (p1 - p0))
    assert sig.rr1 >= 1.0


def test_wavec_signal():
    candles, (c0, a_end, b_end) = wavec_candles()
    sig = ElliottStrategy(make_cfg(setups=["waveC"])).evaluate("PAXG/USD", candles, [htf(Bias.BULL)])
    assert sig is not None and sig.setup is SetupType.WAVEC and sig.side is Side.LONG
    assert sig.count.pattern is PatternType.ZIGZAG
    assert sig.stop < b_end < sig.entry
    assert sig.tp1 == pytest.approx(b_end + (a_end - c0))
    # without the preceding down impulse there is no waveC setup
    plain, _ = wave3_setup_candles()
    assert ElliottStrategy(make_cfg(setups=["waveC"])).evaluate("X", plain, [htf(Bias.BULL)]) is None


def test_analyse_htf():
    st = ElliottStrategy(BotCfg())
    candles, piv = impulse_candles()
    ctx = st.analyse_htf("4h", candles)
    assert ctx.timeframe == "4h"
    assert ctx.bias is Bias.BEAR                            # completed impulse up -> correction due
    assert ctx.count is not None and ctx.count.complete
    assert ctx.fib is not None
    assert ctx.fib.start == pytest.approx(piv[4]) and ctx.fib.end == pytest.approx(piv[5])
    assert ctx.atr > 0
    w3, _ = wave3_setup_candles()
    assert st.analyse_htf("1h", w3).bias is Bias.BULL
    assert st.analyse_htf("1h", mirror_candles(w3, AXIS)).bias is Bias.BEAR
    # no swings -> EMA decides
    trend = path_to_candles([100.0, 150.0], 120)
    assert st.analyse_htf("1h", trend).bias is Bias.BULL
    assert st.analyse_htf("1h", mirror_candles(trend, AXIS)).bias is Bias.BEAR
    empty = st.analyse_htf("1h", [])
    assert empty.bias is Bias.NEUTRAL and empty.count is None and empty.fib is None
    short = st.analyse_htf("1h", trend[:5])
    assert short.bias in (Bias.BULL, Bias.NEUTRAL)
