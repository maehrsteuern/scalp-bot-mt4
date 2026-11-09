import math
from ewbot import scenarios as sc
from ewbot.history import gap_report, merge_rows

M30 = 1_800_000


def synth_rows():
    """30m rows from 2022-01-01: rise to a peak on 2022-02-10, fall to a trough on 2022-03-20, then rise again."""
    t0 = sc.ts_ms("2022-01-01")
    peak_t, low_t = sc.ts_ms("2022-02-10") + 5 * M30, sc.ts_ms("2022-03-20") + 7 * M30
    rows = []
    for i in range(48 * 120):
        t = t0 + i * M30
        if t <= peak_t:
            px = 100 + (t - t0) / (peak_t - t0) * 50
        elif t <= low_t:
            px = 150 - (t - peak_t) / (low_t - peak_t) * 70
        else:
            px = 80 + (t - low_t) / (48 * 3600e3) * 0.5
        rows.append([t, px, px + 0.5, px - 0.5, px, 1.0])
    return rows, peak_t, low_t


def test_verify_window_finds_real_swings():
    rows, peak_t, low_t = synth_rows()
    # approximate dates are a week off on both sides, kinds high -> low
    v = sc.verify_window(rows, "2022-02-03", "2022-03-27", "high", "low", tol_days=14)
    assert v["start_ts"] == peak_t and v["end_ts"] == low_t + M30
    assert math.isclose(v["start_px"], 150.5) and math.isclose(v["end_px"], 79.5)
    assert math.isclose(v["move_pct"], (79.5 / 150.5 - 1) * 100)
    assert v["shift_start_days"] > 0 and v["shift_end_days"] < 0
    # tolerance too small to reach the peak -> picks the best candle inside the window instead
    v2 = sc.verify_window(rows, "2022-01-20", "2022-03-20", "high", "low", tol_days=3)
    assert v2["start_ts"] < peak_t


def test_verify_window_end_after_start_and_fixed():
    rows, peak_t, low_t = synth_rows()
    v = sc.verify_window(rows, "2022-01-01", "2022-02-10", "fixed", "high", 14)
    assert v["start_ts"] == rows[0][0] and v["end_ts"] == peak_t + M30 and v["move_pct"] > 40
    v = sc.verify_window(rows, "2022-03-20", "2022-05-01", "low", "fixed", 14)
    assert v["end_ts"] == rows[-1][0] + M30


def test_monte_carlo_seeded_and_sane():
    r = [1.0, -1.0, -1.0, 2.0, -1.0, 0.5, -1.0, -1.0, 1.5, -1.0] * 5
    a = sc.monte_carlo(r, years=2.0, n_sims=2000, seed=7)
    b = sc.monte_carlo(r, years=2.0, n_sims=2000, seed=7)
    assert a == b                                              # seeded
    assert a["dd_r_p95"] >= a["dd_r_med"] >= 0 and a["dd_pct_p95"] >= a["dd_pct_med"]
    assert a["ny"] == 25 and math.isclose(a["trades_per_year"], 25)
    assert a["streak_max"] >= a["streak_p95"] >= a["streak_med"] >= 1
    # all winners: no drawdown, never negative; all losers: drawdown = sum
    w = sc.monte_carlo([1.0] * 20, years=1.0, n_sims=200, seed=1)
    assert w["dd_r_p95"] == 0 and w["p_neg_year"] == 0 and w["streak_max"] == 0
    l = sc.monte_carlo([-1.0] * 20, years=1.0, n_sims=200, seed=1)
    assert l["dd_r_med"] == 20 and l["p_neg_year"] == 1 and l["streak_med"] == 20


def test_gap_report_and_merge():
    step = 1_800_000
    rows = [[i * step, 1, 1, 1, 1, 1] for i in (0, 1, 2, 5, 6, 10)]
    g = gap_report(rows, "30m")
    assert g == dict(gaps=2, missing=5, longest=3)
    m = merge_rows(rows[:3], [[2 * step, 9, 9, 9, 9, 9], [3 * step, 2, 2, 2, 2, 2]])
    assert [r[0] // step for r in m] == [0, 1, 2, 3] and m[2][1] == 9
