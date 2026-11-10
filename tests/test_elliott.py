import pytest

from ewbot.config import ElliottCfg, SwingCfg
from ewbot.elliott import best_count, bias_from_counts, find_counts, primary_count
from ewbot.models import Bias, PatternType, Side, Swing, SwingKind
from ewbot.swings import detect_swings

try:
    from tests.synthetic import impulse_candles, impulse_pivots, wave3_setup_candles, zigzag_pivots
except ImportError:  # pragma: no cover
    from synthetic import impulse_candles, impulse_pivots, wave3_setup_candles, zigzag_pivots

ECFG = ElliottCfg()


def mk_swings(prices, first=SwingKind.LOW, step=10):
    kinds = [first, SwingKind.HIGH if first is SwingKind.LOW else SwingKind.LOW]
    return [Swing(index=i * step, ts=i * step * 60_000, price=p, kind=kinds[i % 2]) for i, p in enumerate(prices)]


def impulses(counts, complete=True):
    return [c for c in counts if c.pattern is PatternType.IMPULSE and c.complete is complete]


def test_textbook_impulse_from_candles_scores_high():
    candles, piv = impulse_candles(w2=0.618, w3=1.618, w4=0.382, w5=1.0, noise=0.2, seed=5)
    swings = detect_swings(candles, SwingCfg())
    counts = find_counts(swings, candles[-1].close, ECFG)
    imp = [c for c in impulses(counts) if c.points == pytest.approx(piv)]
    assert imp, "impulse not found"
    c = imp[0]
    assert c.direction is Side.LONG and c.score > 0.7
    assert c.ratios["w2/w1"] == pytest.approx(0.618, abs=1e-3)
    assert c.ratios["w3/w1"] == pytest.approx(1.618, abs=1e-3)
    assert c.ratios["w4/w3"] == pytest.approx(0.382, abs=1e-3)
    assert c.ratios["w5/w1"] == pytest.approx(1.0, abs=1e-3)
    assert c.violations == []
    assert len(c.swings) == 6 and [s.price for s in c.swings] == c.points
    assert counts == sorted(counts, key=lambda k: -k.score)


def test_down_impulse_mirrors():
    piv = impulse_pivots(direction=-1)
    counts = find_counts(mk_swings(piv, SwingKind.HIGH), piv[-1] + 1.0, ECFG)
    c = impulses(counts)[0]
    assert c.direction is Side.SHORT and c.score > 0.7
    up = impulses(find_counts(mk_swings(impulse_pivots()), 0.0, ECFG))[0]
    assert c.score == pytest.approx(up.score)
    assert c.ratios == pytest.approx(up.ratios)


def test_overlap_is_rejected():
    # p4 (108) below p1 (110): wave 4 overlaps wave 1
    piv = [100.0, 110.0, 104.0, 125.0, 108.0, 130.0]
    assert impulses(find_counts(mk_swings(piv), 129.0, ECFG)) == []


@pytest.mark.parametrize("piv", [
    [100.0, 110.0, 99.0, 125.0, 115.0, 130.0],   # wave 2 beyond p0
    [100.0, 110.0, 104.0, 109.0, 106.0, 112.0],  # wave 3 below end of wave 1 (structure)
    [100.0, 110.0, 104.0, 120.0, 114.0, 119.0],  # wave 5 truncated (p5 < p3)
    [100.0, 110.0, 105.0, 113.0, 111.0, 125.0],  # wave 3 shortest / shorter than wave 1
])
def test_hard_rule_violators_rejected(piv):
    assert impulses(find_counts(mk_swings(piv), piv[-1], ECFG)) == []


def test_bad_ratios_lower_score_and_list_violations():
    good = impulses(find_counts(mk_swings(impulse_pivots()), 0.0, ECFG))[0]
    cfg = ElliottCfg(min_score=0.0)
    bad_piv = impulse_pivots(w2=0.2, w3=1.05, w4=0.7, w5=2.5)
    bad = impulses(find_counts(mk_swings(bad_piv), 0.0, cfg))[0]
    assert bad.score < good.score and bad.score < 0.55
    assert bad.violations
    assert impulses(find_counts(mk_swings(bad_piv), 0.0, ECFG)) == []   # filtered by min_score


def test_in_progress_wave3_count():
    candles, (p0, p1, p2) = wave3_setup_candles()
    swings = detect_swings(candles, SwingCfg())
    price = candles[-1].close
    counts = find_counts(swings, price, ECFG)
    run = [c for c in impulses(counts, complete=False) if len(c.swings) == 3]
    assert run
    c = run[0]
    assert c.points == pytest.approx([p0, p1, p2, price])
    assert c.direction is Side.LONG and "w3/w1_run" in c.ratios
    assert bias_from_counts(counts, price) is Bias.BULL


def test_in_progress_wave4_overlap_rejected_and_wave5_running():
    piv = impulse_pivots()[:4]                    # p0..p3, wave 4 running
    sw = mk_swings(piv)
    ok = [c for c in impulses(find_counts(sw, 116.0, ECFG), complete=False) if len(c.swings) == 4]
    assert ok and bias_from_counts(find_counts(sw, 116.0, ECFG), 116.0) is Bias.NEUTRAL
    bad = [c for c in impulses(find_counts(sw, 109.0, ECFG), complete=False) if len(c.swings) == 4]
    assert bad == []                              # running wave 4 below p1
    sw5 = mk_swings(impulse_pivots()[:5])
    run5 = [c for c in impulses(find_counts(sw5, 118.0, ECFG), complete=False) if len(c.swings) == 5]
    assert run5 and run5[0].ratios["alternation"] == 1.0


def test_zigzag_rules():
    zz = zigzag_pivots(direction=-1)                     # A down, B up, C down
    counts = find_counts(mk_swings(zz, SwingKind.HIGH), zz[-1] + 0.5, ECFG)
    z = [c for c in counts if c.pattern is PatternType.ZIGZAG and c.complete]
    assert z and z[0].direction is Side.SHORT and z[0].score > 0.7
    assert bias_from_counts([z[0]], zz[-1] + 0.5) is Bias.BULL     # completed zigzag down -> bull
    # B retraces more than 100 % of A
    bad = [100.0, 90.0, 101.0, 85.0]
    assert [c for c in find_counts(mk_swings(bad, SwingKind.HIGH), 86.0, ECFG)
            if c.pattern is PatternType.ZIGZAG and c.complete] == []
    # C does not exceed the end of A
    bad2 = [100.0, 90.0, 96.0, 91.0]
    assert [c for c in find_counts(mk_swings(bad2, SwingKind.HIGH), 92.0, ECFG)
            if c.pattern is PatternType.ZIGZAG and c.complete] == []
    # in progress: A, B confirmed, C running
    run = [c for c in find_counts(mk_swings(zz[:3], SwingKind.HIGH), 93.0, ECFG)
           if c.pattern is PatternType.ZIGZAG and not c.complete]
    assert run and run[0].points[-1] == 93.0 and "C/A_run" in run[0].ratios


def test_bias_complete_impulse_and_helpers():
    piv = impulse_pivots()
    counts = find_counts(mk_swings(piv), piv[-1] - 2.0, ECFG)
    assert bias_from_counts(counts, piv[-1] - 2.0) is Bias.BEAR
    assert bias_from_counts([], 1.0) is Bias.NEUTRAL
    assert best_count(counts) is counts[0]
    assert best_count(counts, PatternType.IMPULSE).pattern is PatternType.IMPULSE
    assert best_count([], None) is None and primary_count([]) is None


def test_deterministic():
    candles, _ = impulse_candles(noise=0.3, seed=9)
    swings = detect_swings(candles, SwingCfg())
    a = find_counts(swings, candles[-1].close, ECFG)
    b = find_counts(list(swings), candles[-1].close, ECFG)
    assert [(c.pattern, c.direction, c.points, c.score) for c in a] == \
           [(c.pattern, c.direction, c.points, c.score) for c in b]


def test_max_swings_window():
    piv = impulse_pivots()
    sw = mk_swings([95.0, 112.0] + piv)          # extra older swings
    assert impulses(find_counts(sw, 0.0, ElliottCfg(max_swings=6)))
    assert impulses(find_counts(sw, 0.0, ElliottCfg(max_swings=5))) == []
    assert find_counts([], 1.0, ECFG) == []
