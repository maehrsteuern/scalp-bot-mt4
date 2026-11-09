"""Scenario backtest of the FROZEN strategy (StrategyParams() defaults, no re-tuning) over 2021 .. now.

    python -m ewbot.scenarios            # computes everything, writes SCENARIOS.md
    python -m ewbot.scenarios --no-md    # only print
    python -m ewbot.scenarios --fresh    # ignore the trade cache in data/hist/scen_ew_*.json
    python -m ewbot.history --extend     # (re)download 30m + 4h from 2021-01-01 first

Every number in SCENARIOS.md is computed here. Simulation = ewbot.backtest (run_coin / simulate / stats), unchanged.
"""
from __future__ import annotations
import argparse, bisect, json, os, re, time
from dataclasses import asdict
from typing import Dict, List, Optional

import numpy as np

from . import backtest as bt
from .backtest import Trade, stats, portfolio, run_coin, geom_from, load_candles, WARMUP
from .history import DATA_DIR, load_history, gap_report, TF_MS
from .strategy import StrategyParams, M30

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COINS = ("BTC", "ETH", "SOL")
DAY = 86_400_000
RISK = 0.0075

# Period borders: identical to the 60/40 split of BACKTEST.md (first evaluated candle 06.03.2025 12:00 UTC, data end 08.11.2026).
P_B_START = 1741262400000                                # 2025-03-06 12:00 UTC  = first evaluated candle of the old backtest
P_C_START = int(P_B_START + 0.6 * (1794178800000 - P_B_START))   # = 2026-03-08, the old in/out-of-sample border
PERIODS = (("a", "(a) 2021 bis 05.03.2025 – nie gesehen (echtes Out-of-Sample)", None, P_B_START),
           ("b", "(b) 06.03.2025 bis 08.03.2026 – Einstellperiode (In-Sample)", P_B_START, P_C_START),
           ("c", "(c) 08.03.2026 bis heute – späteres Out-of-Sample", P_C_START, None))


def ts_ms(d: str) -> int:
    """'YYYY-MM-DD' -> ms (UTC)."""
    import calendar
    y, m, dd = (int(x) for x in d.split("-"))
    return calendar.timegm((y, m, dd, 0, 0, 0)) * 1000


def fmt(ms: int) -> str:
    return time.strftime("%d.%m.%Y", time.gmtime(ms / 1000))


# ------------------------------------------------------------------------------------------------ window verification
def verify_window(rows: List[list], a_start: str, a_end: str, kind_start: str, kind_end: str, tol_days: float = 14) -> dict:
    """Find the real swing points of a price series (rows = [t,o,h,l,c,v], ascending) near the approximate dates.

    kind 'high' / 'low': the extreme high/low candle within +-tol_days of the approximate date.
    kind 'fixed': first candle on/after the date (start) or the last candle before it (end).
    The end is searched only AFTER the verified start. Returns window [start_ts, end_ts) in ms and the move in %
    (swing price to swing price: high/low extreme, or open of first / close of last candle for 'fixed').
    """
    ts = [r[0] for r in rows]

    def pick(center: int, kind: str, lo_bound: int = 0):
        lo = max(center - int(tol_days * DAY), lo_bound)
        i0, i1 = bisect.bisect_left(ts, lo), bisect.bisect_right(ts, center + int(tol_days * DAY))
        seg = range(i0, i1)
        if not len(seg):
            raise ValueError(f"no data around {fmt(center)}")
        if kind == "high":
            i = max(seg, key=lambda k: rows[k][2]); return i, rows[i][2]
        i = min(seg, key=lambda k: rows[k][3]); return i, rows[i][3]

    s0 = ts_ms(a_start)
    if kind_start == "fixed":
        i = bisect.bisect_left(ts, s0); s_px = rows[i][1]
    else:
        i, s_px = pick(s0, kind_start)
    s_idx = i
    e0 = ts_ms(a_end)
    if kind_end == "fixed":
        j = bisect.bisect_left(ts, e0) - 1 if e0 <= ts[-1] else len(rows) - 1
        e_px = rows[j][4]
    else:
        j, e_px = pick(e0, kind_end, lo_bound=ts[s_idx] + 1)
    if j <= s_idx:
        raise ValueError("end before start")
    return dict(start_ts=ts[s_idx], end_ts=ts[j] + TF_MS["30m"], start_px=s_px, end_px=e_px,
                move_pct=(e_px / s_px - 1) * 100, shift_start_days=(ts[s_idx] - s0) / DAY, shift_end_days=(ts[j] - e0) / DAY)


# name, approx start, approx end, kind start, kind end, tolerance (days), cause note (only if well known), group
SCENARIOS = [
    ("Bullenmarkt Q1 2021", "2021-01-01", "2021-04-14", "fixed", "high", 14, "", 1),
    ("Crash Mai 2021", "2021-05-12", "2021-05-23", "high", "low", 5, "Kritik am Energieverbrauch von Bitcoin (Tesla-Zahlungsstopp) und Chinas Vorgehen gegen Mining", 1),
    ("Sommer-Boden / Erholung 2021", "2021-07-20", "2021-11-10", "low", "high", 14, "", 1),
    ("Bärenmarkt 2022 (gesamt)", "2021-11-10", "2022-11-21", "high", "low", 14, "Zinserhöhungen und mehrere Pleiten im Kryptomarkt", 1),
    ("  Terra/Luna-Zusammenbruch", "2022-05-07", "2022-05-13", "high", "low", 4, "Zusammenbruch des Stablecoins TerraUSD und des Luna-Tokens", 2),
    ("  Celsius / 3AC", "2022-06-10", "2022-06-18", "high", "low", 4, "Auszahlungsstopp bei Celsius, Probleme bei Three Arrows Capital", 2),
    ("  FTX-Zusammenbruch", "2022-11-06", "2022-11-10", "high", "low", 4, "Pleite der Börse FTX", 2),
    ("Seitwärts / Erholung 2023", "2022-11-21", "2023-10-12", "low", "low", 14, "", 1),
    ("  SVB-Bankenkrise", "2023-03-10", "2023-03-14", "low", "high", 3, "Zusammenbruch der Silicon Valley Bank", 2),
    ("ETF-Rally", "2023-10-12", "2024-03-14", "low", "high", 14, "Erwartung und Zulassung von Bitcoin-Spot-ETFs in den USA", 1),
    ("Seitwärts März–Okt 2024", "2024-03-14", "2024-11-04", "high", "low", 14, "", 1),
    ("  Crash 05.08.2024", "2024-07-29", "2024-08-05", "high", "low", 4, "Börsenturbulenzen in Japan (Zinserhöhung, Yen-Carry-Trades)", 2),
    ("Wahl-Rally Nov–Dez 2024", "2024-11-04", "2024-12-17", "low", "high", 14, "US-Präsidentschaftswahl", 1),
    ("Rückgang Jan–Apr 2025", "2025-01-20", "2025-04-07", "high", "low", 14, "Zollstreit der USA", 1),
    ("Rally bis Hoch Okt 2025", "2025-04-07", "2025-10-06", "low", "high", 14, "", 1),
    ("  Liquidations-Crash 10.10.2025", "2025-10-06", "2025-10-10", "high", "low", 4, "Zolldrohungen der USA gegen China, sehr hohe Zwangsverkäufe bei Hebel-Positionen", 2),
    ("Bärenphase Okt 2025–Jul 2026 (gesamt)", "2025-10-06", "2026-07-01", "high", "low", 14, "", 1),
    ("  Abwärts bis Tief Feb 2026", "2025-10-06", "2026-02-06", "high", "low", 14, "", 2),
    ("  Seitwärts Feb–Jul 2026", "2026-02-06", "2026-07-01", "low", "low", 14, "", 2),
    ("Rally Jul–Sep 2026", "2026-07-01", "2026-09-15", "low", "high", 14, "", 1),
    ("Korrektur Sep–Nov 2026", "2026-09-15", "2026-11-09", "high", "fixed", 14, "", 1),
]
# Special rule: scenarios whose start should follow the verified end of the previous full-size scenario are NOT chained
# automatically; every window is verified on its own against BTC (this keeps each line reproducible and checkable).


def verified_scenarios(btc_rows: List[list]) -> List[dict]:
    out = []
    for name, a, b, ks, ke, tol, cause, grp in SCENARIOS:
        v = verify_window(btc_rows, a, b, ks, ke, tol)
        v.update(name=name, approx_start=a, approx_end=b, cause=cause, group=grp, kind_start=ks, kind_end=ke)
        out.append(v)
    return out


# ------------------------------------------------------------------------------------------------ data + EW run
def load_all() -> dict:
    data = {c: load_candles(c) for c in COINS}
    return data


def _key(coin: str, c30, c4) -> dict:
    return dict(n30=len(c30), f30=c30[0].t, l30=c30[-1].t, n4=len(c4), l4=c4[-1].t, c=c30[-1].c, params=asdict(StrategyParams()))


def _ew_worker(coin):
    data = load_candles(coin)
    return coin, run_coin(coin, StrategyParams(), "ew", None, data=data)


def ew_trades(data: dict, fresh: bool = False, procs: int = 2) -> Dict[str, List[Trade]]:
    res, todo = {}, []
    for c in COINS:
        path = os.path.join(DATA_DIR, "hist", f"scen_ew_{c}.json")
        key = _key(c, *data[c])
        if not fresh and os.path.exists(path):
            j = json.load(open(path))
            if j.get("key") == key:
                res[c] = [Trade(**t) for t in j["trades"]]
                continue
        todo.append(c)
    if todo:
        from multiprocessing import Pool
        with Pool(min(procs, len(todo))) as pool:
            for c, tr in pool.map(_ew_worker, todo):
                res[c] = tr
                json.dump(dict(key=_key(c, *data[c]), trades=[asdict(t) for t in tr]),
                          open(os.path.join(DATA_DIR, "hist", f"scen_ew_{c}.json"), "w"))
    return res


# ------------------------------------------------------------------------------------------------ helpers
def filled(trades: List[Trade]) -> List[Trade]:
    return [t for t in trades if t.status in ("filled", "open")]


def in_range(trades: List[Trade], t0: Optional[int], t1: Optional[int]) -> List[Trade]:
    return [t for t in trades if (t0 is None or t.created_ts >= t0) and (t1 is None or t.created_ts < t1)]


def buy_hold(c30, t0: int, t1: int) -> Optional[float]:
    """% change of the coin from the open of the first candle >= t0 to the close of the last candle < t1; None if no data."""
    ts = [c.t for c in c30]
    i = bisect.bisect_left(ts, t0)
    j = bisect.bisect_left(ts, t1) - 1
    if i >= len(c30) or j <= i or c30[i].t > t0 + 2 * DAY:
        return None
    return (c30[j].c / c30[i].o - 1) * 100


def resim(trades: List[Trade], c30map: dict, maker: float, taker: float, slip: float) -> List[Trade]:
    """Re-run the exit simulation of already found, filled trades with other fees / slippage (signals and fills do not depend on fees)."""
    old = (bt.MAKER, bt.TAKER, bt.SLIP)
    bt.MAKER, bt.TAKER, bt.SLIP = maker, taker, slip
    out = []
    try:
        idx = {c: {x.t: k for k, x in enumerate(c30)} for c, c30 in c30map.items()}
        for t in filled(trades):
            c30 = c30map[t.coin]
            i = idx[t.coin][t.created_ts - M30]
            sv = (t.created_ts, t.created_ts + 48 * 3_600_000, t.entry, t.stop, t.t1, t.t2, float("inf"))
            n, _ = bt.simulate(c30, i, sv, t.coin, t.kind, t.score)
            out.append(n)
    finally:
        bt.MAKER, bt.TAKER, bt.SLIP = old
    return out


def avg_r(trades: List[Trade], key="r_net") -> float:
    f = filled(trades)
    return sum(getattr(t, key) for t in f) / len(f) if f else 0.0


def monte_carlo(r: List[float], years: float, n_sims: int = 10_000, seed: int = 42, risk: float = RISK) -> dict:
    """Reshuffle the net-R sequence n_sims times. DD in R (additive) and in % (compounding with `risk` of equity per R)."""
    a = np.asarray(r, dtype=float)
    n = len(a)
    rng = np.random.default_rng(seed)
    perm = np.argsort(rng.random((n_sims, n)), axis=1)
    seqs = a[perm]
    cum = np.cumsum(seqs, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.zeros((n_sims, 1)), cum], axis=1), axis=1)[:, 1:]
    dd_r = (peak - cum).max(axis=1)
    eq = np.cumprod(1 + risk * seqs, axis=1)
    epeak = np.maximum.accumulate(np.concatenate([np.ones((n_sims, 1)), eq], axis=1), axis=1)[:, 1:]
    dd_pct = ((epeak - eq) / epeak).max(axis=1) * 100
    loss = seqs <= 0
    streak = np.zeros(n_sims); best = np.zeros(n_sims)
    for k in range(n):
        streak = (streak + 1) * loss[:, k]
        best = np.maximum(best, streak)
    ny = max(1, int(round(n / years))) if years > 0 else n
    ny = min(ny, n)
    year_sum = cum[:, ny - 1]
    # observed (original order)
    c0 = np.cumsum(a); pk0 = np.maximum.accumulate(np.maximum(c0, 0)); obs_dd = float((pk0 - c0).max())
    s, b0 = 0, 0
    for x in a:
        s = s + 1 if x <= 0 else 0; b0 = max(b0, s)
    return dict(n=n, n_sims=n_sims, trades_per_year=n / years if years > 0 else float("nan"), ny=ny,
                dd_r_med=float(np.median(dd_r)), dd_r_p95=float(np.percentile(dd_r, 95)),
                dd_pct_med=float(np.median(dd_pct)), dd_pct_p95=float(np.percentile(dd_pct, 95)),
                p_neg_year=float((year_sum < 0).mean()), year_med=float(np.median(year_sum)),
                year_p5=float(np.percentile(year_sum, 5)), year_p95=float(np.percentile(year_sum, 95)),
                streak_med=float(np.median(best)), streak_p95=float(np.percentile(best, 95)), streak_max=float(best.max()),
                obs_dd_r=obs_dd, obs_streak=b0, mean_r=float(a.mean()))


def find_breakeven(trades: List[Trade], c30map: dict, ratio: float, lo=0.0, hi=0.0025, slip=0.001) -> Optional[float]:
    """Largest maker fee m (taker = ratio*m) with avg net R >= 0 on this trade list; None if even m=0 is negative."""
    f = lambda m: avg_r(resim(trades, c30map, m, ratio * m, slip))
    if f(lo) <= 0:
        return None
    if f(hi) >= 0:
        return hi
    for _ in range(25):
        mid = (lo + hi) / 2
        if f(mid) >= 0: lo = mid
        else: hi = mid
    return lo


def month_regimes(btc_rows: List[list]) -> Dict[str, dict]:
    months: Dict[str, list] = {}
    for r in btc_rows:
        k = time.strftime("%Y-%m", time.gmtime(r[0] / 1000))
        m = months.setdefault(k, [r[1], r[4], r[0]])
        m[1] = r[4]
    out = {}
    for k, (o, c, t) in months.items():
        pct = (c / o - 1) * 100
        out[k] = dict(pct=pct, regime="steigend" if pct > 10 else ("fallend" if pct < -10 else "seitwärts"))
    return out


# ------------------------------------------------------------------------------------------------ report
def R(x, d=2):
    return f"{x:+.{d}f}"


def row_stats(s: dict) -> str:
    return f"{s['signals']} | {s['trades']} | {s['win_rate']*100:.0f} % | {R(s['avg_r'])} | {R(s['avg_r_gross'])} | {s['total_r']:+.1f} | {s['max_dd_r']:.1f}"


def bh_txt(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:+.0f} %"


def read_backtest_md() -> dict:
    out = {}
    try:
        for line in open(os.path.join(ROOT, "BACKTEST.md"), encoding="utf-8"):
            for key in ("Gesamt In-Sample", "Gesamt Out-of-Sample"):
                if line.startswith(f"| **{key}**"):
                    p = [x.strip() for x in line.strip().strip("|").split("|")]
                    out[key] = dict(signals=p[1], trades=p[2], avg_r=p[4], avg_r_gross=p[5], total_r=p[7])
    except OSError:
        pass
    return out


def build(fresh: bool = False, procs: int = 2) -> str:
    data = load_all()
    c30map = {c: data[c][0] for c in COINS}
    ew = ew_trades(data, fresh, procs)
    allew = sorted([t for c in COINS for t in ew[c]], key=lambda t: t.created_ts)
    fl = filled(allew)
    btc_rows = load_history("BTC", "30m")
    t_first = c30map["BTC"][WARMUP].t
    t_last = c30map["BTC"][-1].t + M30
    years = (t_last - t_first) / (365.25 * DAY)
    L: List[str] = []
    A = L.append

    # ---------------- numbers used in the summary
    per = {}
    for k, title, t0, t1 in PERIODS:
        sel = in_range(allew, t0, t1)
        per[k] = dict(title=title, t0=t0, t1=t1, all=sel, s=stats(sel), pf=portfolio(sel, None),
                      coin={c: stats(in_range(ew[c], t0, t1)) for c in COINS})
    sa, sb, sc = per["a"]["s"], per["b"]["s"], per["c"]["s"]
    reg = month_regimes(btc_rows)
    # regime of the month of the signal
    rstat = {}
    for rg in ("steigend", "seitwärts", "fallend"):
        tr = [t for t in allew if reg.get(time.strftime("%Y-%m", time.gmtime(t.created_ts / 1000)), {}).get("regime") == rg]
        rstat[rg] = dict(months=sum(1 for k, v in reg.items() if v["regime"] == rg and k >= time.strftime("%Y-%m", time.gmtime(t_first / 1000))),
                         s=stats(tr), n_sig=len(tr))
    ver = verified_scenarios(btc_rows)

    # stress
    fee_levels = [("0,25 % / 0,50 % (Annahme, Basis)", 0.0025, 0.005), ("0,10 % / 0,20 %", 0.001, 0.002),
                  ("0,075 % / 0,075 %", 0.00075, 0.00075), ("0 % / 0 % (brutto)", 0.0, 0.0)]
    fee_rows = []
    for nm, m, tk in fee_levels:
        tr = resim(allew, c30map, m, tk, 0.001)
        tr_a = [t for t in tr if t.created_ts < P_B_START]
        fee_rows.append((nm, m, tk, tr, tr_a))
    base_chk = resim(allew, c30map, 0.0025, 0.005, 0.001)
    assert abs(sum(t.r_net for t in base_chk) - sum(t.r_net for t in fl)) < 1e-6, "re-simulation does not reproduce the base run"
    slip_rows = [(s, resim(allew, c30map, 0.0025, 0.005, s)) for s in (0.001, 0.003)]
    be_ratio2 = find_breakeven(allew, c30map, 2.0)
    be_equal = find_breakeven(allew, c30map, 1.0)
    be_ratio2_a = find_breakeven([t for t in allew if t.created_ts < P_B_START], c30map, 2.0)
    mc = monte_carlo([t.r_net for t in sorted(fl, key=lambda t: t.exit_ts)], years)

    # baseline
    ew_b = in_range(allew, P_B_START, P_C_START)
    geom = geom_from(ew_b)
    p = StrategyParams()
    per_tr = {c: run_coin(c, p, "periodic", None, base_geom=geom, period=24, data=data[c]) for c in COINS}
    rnd_tr = {c: [run_coin(c, p, "random", None, base_geom=geom, seed=sd, rate=1 / 48, data=data[c]) for sd in range(5)] for c in COINS}
    pall = [t for c in COINS for t in per_tr[c]]
    rall = [t for c in COINS for r in rnd_tr[c] for t in r]

    old = read_backtest_md()
    L_hdr = "| Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) |\n|---|---|---|---|---|---|---|---|"

    # ---------------- gap info for trades
    gaps = {}
    gaps_btc = []
    for c in COINS:
        ts = [x.t for x in c30map[c]]
        gaps[c] = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > M30 * 1.5]
    gaps_btc = gaps["BTC"]
    def touches_gap(t):
        for g in gaps[t.coin]:
            if t.created_ts - 400 * M30 <= g[1] and g[0] <= (t.exit_ts or t.created_ts):
                return True
        return False
    gap_tr = [t for t in fl if touches_gap(t)]
    clean = [t for t in fl if not touches_gap(t)]

    # ================= document
    A("# Szenario-Backtest: eingefrorene EW-Strategie über 2021 bis heute\n")
    A(f"Alle Zahlen kommen aus dem Code (`python -m ewbot.scenarios`). Datenstand: letzte Kerze {fmt(t_last)}. "
      "Die Strategie ist **eingefroren**: `StrategyParams()` mit Standardwerten, keine neue Einstellung, keine neuen Parameter.\n")

    # ---- Kernaussage
    A("## Kernaussage\n")
    A(f"- **Nie gesehener Zeitraum 2021 bis 05.03.2025:** {sa['trades']} Trades, Ø **{R(sa['avg_r'])} R netto** (brutto {R(sa['avg_r_gross'])} R), "
      f"Trefferquote {sa['win_rate']*100:.0f} %, Summe {sa['total_r']:+.1f} R, 95 %-Bereich für Ø R [{R(sa['ci_lo'])} ; {R(sa['ci_hi'])}].")
    A(f"- Einstellperiode (b): {sb['trades']} Trades, Ø {R(sb['avg_r'])} R netto. Späteres Out-of-Sample (c): {sc['trades']} Trades, Ø {R(sc['avg_r'])} R netto.")
    sall = stats(allew)
    A(f"- Alles zusammen 2021 bis heute: {sall['trades']} Trades, Ø {R(sall['avg_r'])} R netto, brutto {R(sall['avg_r_gross'])} R, Summe {sall['total_r']:+.1f} R, "
      f"95 %-Bereich [{R(sall['ci_lo'])} ; {R(sall['ci_hi'])}].")
    if be_ratio2 is None:
        A("- **Gebühren-Schwelle:** Schon ohne Gebühren ist der Durchschnitt nicht positiv – kein Gebührenniveau macht daraus eine Kante.")
    else:
        A(f"- **Gebühren-Schwelle:** Der Durchschnitt wird erst bei Maker-Gebühr ≤ {be_ratio2*100:.3f} % (Taker doppelt so hoch: {be_ratio2*200:.3f} %) "
          f"nicht mehr negativ; bei gleich hohen Gebühren für Kauf und Verkauf liegt die Schwelle bei " + (f"{be_equal*100:.3f} %." if be_equal is not None else "unter 0 (nie)."))
    A(f"- **Zufallstest (Monte Carlo):** mittlerer größter Verlust (Max. Drawdown) {mc['dd_r_med']:.1f} R / {mc['dd_pct_med']:.1f} %, im schlechten Fall (95 %) "
      f"{mc['dd_r_p95']:.1f} R / {mc['dd_pct_p95']:.1f} %. Wahrscheinlichkeit, nach einem Jahr im Minus zu sein: {mc['p_neg_year']*100:.0f} %.")
    best_rg = max(rstat, key=lambda k: rstat[k]['s']['avg_r'] if rstat[k]['s']['trades'] >= 5 else -9)
    worst_rg = min(rstat, key=lambda k: rstat[k]['s']['avg_r'] if rstat[k]['s']['trades'] >= 5 else 9)
    A(f"- **Marktphase:** Am besten lief es in Monaten mit BTC-Trend *{best_rg}* (Ø {R(rstat[best_rg]['s']['avg_r'])} R, {rstat[best_rg]['s']['trades']} Trades), "
      f"am schlechtesten bei *{worst_rg}* (Ø {R(rstat[worst_rg]['s']['avg_r'])} R, {rstat[worst_rg]['s']['trades']} Trades).")
    # verdict one-liner
    if sa["trades"] == 0:
        v1 = "Im nie gesehenen Zeitraum gab es keine Trades – kein Urteil möglich."
    elif sa["avg_r"] <= 0:
        v1 = "Der nie gesehene Zeitraum **bestätigt** BACKTEST.md: nach Gebühren kein Gewinn."
    elif sa["ci_lo"] > 0:
        v1 = "Der nie gesehene Zeitraum **widerspricht** BACKTEST.md: nach Gebühren klar positiv."
    else:
        v1 = "Der nie gesehene Zeitraum ist **leicht positiv, aber nicht belastbar**: er widerspricht BACKTEST.md nicht klar, bestätigt eine Kante aber auch nicht."
    A(f"- **Urteil in einem Satz:** {v1}\n")

    # ---- Daten
    A("## 1. Daten\n")
    A("| Coin | 30m-Kerzen | von | bis | Lücken (Anzahl) | fehlende Kerzen | längste Lücke | 4h-Kerzen | 4h-Lücken |\n|---|---|---|---|---|---|---|---|---|")
    for c in COINS:
        rows30, rows4 = load_history(c, "30m"), load_history(c, "4h")
        g, g4 = gap_report(rows30, "30m"), gap_report(rows4, "4h")
        lg = g["longest"]
        longest = f"{lg} Kerzen ({lg/48:.1f} Tage)"
        A(f"| {c}_USD | {len(rows30)} | {fmt(rows30[0][0])} | {fmt(rows30[-1][0])} | {g['gaps']} | {g['missing']} | {longest} | {len(rows4)} | {g4['gaps']} |")
    starts = ", ".join(f"{c} ab {fmt(load_history(c, '30m')[0][0])}" for c in COINS)
    bg = [(a, b) for a, b in gaps_btc if b - a > 7 * DAY]
    gap_txt = "; ".join(f"{fmt(a)} bis {fmt(b)} ({(b - a) / DAY:.0f} Tage)" for a, b in bg) or "keine"
    A(f"\nQuelle: öffentliche Crypto.com-API, nur geschlossene Kerzen, Download mit `python -m ewbot.history --extend`. "
      f"Frühester Kerzenbeginn, den die API liefert: {starts}. ETH und SOL gibt es in der API erst ab diesem Datum "
      f"(nach meinem Kenntnisstand wegen des späteren Börsenstarts der Paare, nicht verifiziert). "
      f"Große Lücken (über 7 Tage) bei BTC: {gap_txt} – dort liefert die API gar keine Kerzen. "
      "In der Tabelle zählt eine solche Lücke als eine Lücke.\n")
    first_eval = ", ".join(f"{c} ab {fmt(c30map[c][WARMUP].t)}" for c in COINS)
    A(f"Die ersten {WARMUP} Kerzen je Coin sind Anlaufzeit. Erste Auswertung: {first_eval}.")
    A(f"Trades, deren Laufzeit oder 30m-Fenster (400 Kerzen vor dem Signal) eine Datenlücke berührt: {len(gap_tr)} von {len(fl)}. "
      f"Ohne diese Trades: Ø {R(avg_r(clean))} R netto ({len(clean)} Trades) statt {R(avg_r(fl))} R.\n")

    # ---- Perioden
    A("## 2. Drei Zeiträume\n")
    A("Ein Trade zählt zu dem Zeitraum, in dem das Signal entstand. Grenzen wie in BACKTEST.md (Einstellperiode = die ersten 60 % des damaligen Tests). "
      "Die Strategie lief hier **in einem Durchgang ab 2021**; Trades ab 2025 können deshalb leicht von BACKTEST.md abweichen (anderer Startzustand, eine Position je Coin).\n")
    A("| Zeitraum / Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) | 95 %-Bereich Ø R | Portfolio-Rendite* | Portfolio-DD* |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for k in ("a", "b", "c"):
        d = per[k]
        for c in COINS:
            s = d["coin"][c]
            ci = f"[{R(s['ci_lo'])} ; {R(s['ci_hi'])}]" if s["trades"] else "-"
            A(f"| {k}: {c} | {row_stats(s)} | {ci} | | |")
        s = d["s"]; ci = f"[{R(s['ci_lo'])} ; {R(s['ci_hi'])}]" if s["trades"] else "-"
        A(f"| **{k}: Gesamt** | {row_stats(s)} | {ci} | {d['pf']['ret_pct']:+.1f} % | {d['pf']['max_dd_pct']:.1f} % |")
    A("\n*Portfolio: 0,75 % Risiko je Trade, mit Zinseszins, Gesamt-Exposure max. 90 % (Funktion `portfolio` aus `backtest.py`).\n")
    for k in ("a", "b", "c"):
        A(f"- {per[k]['title']}")
    if old:
        io, oo = old.get("Gesamt In-Sample"), old.get("Gesamt Out-of-Sample")
        if io and oo:
            A(f"\nZum Vergleich die Zahlen in BACKTEST.md (nur Daten ab 2025): In-Sample {io['trades']} Trades, Ø {io['avg_r']} R netto (brutto {io['avg_r_gross']}), "
              f"Out-of-Sample {oo['trades']} Trades, Ø {oo['avg_r']} R netto (brutto {oo['avg_r_gross']}). "
              f"Hier: (b) {sb['trades']} Trades, Ø {R(sb['avg_r'])} (brutto {R(sb['avg_r_gross'])}); (c) {sc['trades']} Trades, Ø {R(sc['avg_r'])} (brutto {R(sc['avg_r_gross'])}).")
    A("")

    # ---- Szenarien
    A("## 3. Benannte Marktphasen (Szenarien)\n")
    A("Jede Phase wurde an den **BTC-30m-Kursen geprüft**: Start und Ende sind das echte Hoch bzw. Tief (30m-Kerze) in der Nähe des ungefähren Datums "
      "(Toleranz ±14 Tage, bei kurzen Crash-Fenstern ±3 bis ±5 Tage). Die BTC-Bewegung ist von Extrem zu Extrem gerechnet. "
      "Phasen mit eingerückten Namen liegen **innerhalb** einer größeren Phase (Trades werden dann doppelt gezählt, nur die Hauptphasen sind getrennt). "
      "Die Bezeichnungen sind bewusst neutral. Ursachen stehen nur dort, wo sie allgemein bekannt sind – *nach meinem Kenntnisstand*.\n")
    A("### 3.1 Geprüfte Fenster\n")
    A("| Phase | ungefähr (Vorgabe) | geprüft: Start | geprüft: Ende | Verschiebung Start / Ende | BTC-Bewegung | Ursache (nach meinem Kenntnisstand) |\n|---|---|---|---|---|---|---|")
    for v in ver:
        sh = f"{v['shift_start_days']:+.1f} / {v['shift_end_days']:+.1f} Tage"
        A(f"| {v['name'].strip()} | {fmt(ts_ms(v['approx_start']))} – {fmt(ts_ms(v['approx_end']))} | {fmt(v['start_ts'])} | {fmt(v['end_ts'] - M30)} | {sh} | {v['move_pct']:+.1f} % | {v['cause'] or '–'} |")
    A("\nVerschiebungen von mehr als 7 Tagen bedeuten: das genannte Datum war nicht das echte Extrem; es gilt das geprüfte Datum.\n")
    A("### 3.2 Ergebnis je Phase (alle Coins)\n")
    A("P&L = Portfolio-Rendite in % des Kapitals bei 0,75 % Risiko je Trade. Buy-and-Hold = einfach halten über dasselbe Fenster (n/a = Coin dort noch nicht an der Börse).\n")
    A("| Phase | BTC-Bew. | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) | P&L % Kapital | Halten BTC | Halten ETH | Halten SOL |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    scen_res = []
    for v in ver:
        sel = in_range(allew, v["start_ts"], v["end_ts"])
        s = stats(sel); pf = portfolio(sel, None)
        bh = {c: buy_hold(c30map[c], v["start_ts"], v["end_ts"]) for c in COINS}
        scen_res.append((v, s, pf, bh, sel))
        A(f"| {v['name']} | {v['move_pct']:+.0f} % | {row_stats(s)} | {pf['ret_pct']:+.1f} % | {bh_txt(bh['BTC'])} | {bh_txt(bh['ETH'])} | {bh_txt(bh['SOL'])} |")
    A("\n### 3.3 Ergebnis je Phase und Coin\n")
    A("| Phase | Coin | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) | Halten |\n|---|---|---|---|---|---|---|---|---|---|")
    for v, s, pf, bh, sel in scen_res:
        for c in COINS:
            sc_ = stats([t for t in sel if t.coin == c])
            A(f"| {v['name']} | {c} | {row_stats(sc_)} | {bh_txt(bh[c])} |")
    # best / worst scenarios (main groups + events with >=3 trades)
    cand = [(v, s) for v, s, pf, bh, sel in scen_res if s["trades"] >= 3]
    cand_sorted = sorted(cand, key=lambda x: x[1]["total_r"])
    A("\n### 3.4 Beste und schlechteste Phasen (nach Summe R, mindestens 3 Trades)\n")
    A("| Rang | Phase | Trades | Summe R | Ø R netto |\n|---|---|---|---|---|")
    for lab, lst in (("beste", cand_sorted[::-1][:3]), ("schlechteste", cand_sorted[:3])):
        for k, (v, s) in enumerate(lst, 1):
            A(f"| {lab} {k} | {v['name'].strip()} | {s['trades']} | {s['total_r']:+.1f} | {R(s['avg_r'])} |")
    A("")

    # ---- Regime
    A("## 4. Marktregime nach Monaten\n")
    A("Jeder Monat wird nach der BTC-Veränderung vom ersten Open bis zum letzten Close eingestuft: **steigend** über +10 %, **fallend** unter −10 %, sonst **seitwärts**. "
      "Ein Trade zählt zum Monat seines Signals. Der laufende Monat ist unvollständig.\n")
    months = sorted(reg)
    years_l = sorted({m[:4] for m in months})
    A("| Jahr | " + " | ".join(f"{i:02d}" for i in range(1, 13)) + " |\n|---|" + "---|" * 12)
    sym = {"steigend": "↑", "fallend": "↓", "seitwärts": "→"}
    for y in years_l:
        cells = []
        for mth in range(1, 13):
            k = f"{y}-{mth:02d}"
            cells.append(f"{reg[k]['pct']:+.0f} % {sym[reg[k]['regime']]}" if k in reg else "")
        A(f"| {y} | " + " | ".join(cells) + " |")
    A("\n(↑ steigend, → seitwärts, ↓ fallend; Zahl = BTC-Monatsveränderung)\n")
    A("| Regime (BTC-Monat) | Monate | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | 95 %-Bereich Ø R |\n|---|---|---|---|---|---|---|---|---|")
    for rg in ("steigend", "seitwärts", "fallend"):
        d = rstat[rg]; s = d["s"]
        ci = f"[{R(s['ci_lo'])} ; {R(s['ci_hi'])}]" if s["trades"] else "-"
        A(f"| {rg} | {d['months']} | {s['signals']} | {s['trades']} | {s['win_rate']*100:.0f} % | {R(s['avg_r'])} | {R(s['avg_r_gross'])} | {s['total_r']:+.1f} | {ci} |")
    A("\nMonate = Monate ab der ersten Auswertung. Die Strategie kauft Rücksetzer nach einer großen Rally; deshalb gibt es kaum Signale, wenn der Markt lange in einer Richtung läuft.\n")

    # ---- Stress
    A("## 5. Stresstests (alle Trades 2021 bis heute)\n")
    A("### 5.1 Gebührenstufen (Slippage 0,10 % wie Basis)\n")
    A("| Maker / Taker | Trades | Ø R netto | Summe R | Ø R netto nur Zeitraum (a) | Summe R (a) |\n|---|---|---|---|---|---|")
    for nm, m, tk, tr, tr_a in fee_rows:
        A(f"| {nm} | {len(tr)} | {R(avg_r(tr))} | {sum(t.r_net for t in tr):+.1f} | {R(avg_r(tr_a))} | {sum(t.r_net for t in tr_a):+.1f} |")
    A("")
    if be_ratio2 is None:
        A("**Break-even:** Auch bei 0 % Gebühren ist der Durchschnitt nicht positiv; es gibt keine Gebührenstufe mit positiver Kante.")
    else:
        A(f"**Break-even (alle Trades):** Ø R netto wird 0 bei Maker {be_ratio2*100:.3f} % / Taker {be_ratio2*200:.3f} % (Taker = 2 × Maker) "
          f"bzw. bei gleichen Gebühren von " + (f"{be_equal*100:.3f} %." if be_equal is not None else "– (nie)."))
        A(f"Nur Zeitraum (a): " + (f"Maker {be_ratio2_a*100:.3f} % / Taker {be_ratio2_a*200:.3f} %." if be_ratio2_a is not None else "auch ohne Gebühren nicht positiv."))
    A("")
    A("### 5.2 Slippage beim Stop (Gebühren wie Basis)\n")
    A("| Slippage | Trades | Ø R netto | Summe R |\n|---|---|---|---|")
    for s_, tr in slip_rows:
        A(f"| {s_*100:.1f} % | {len(tr)} | {R(avg_r(tr))} | {sum(t.r_net for t in tr):+.1f} |")
    A("")
    A("### 5.3 Monte Carlo (10 000 Mischungen der Netto-R-Folge)\n")
    A(f"Die {mc['n']} Netto-R-Werte aller Trades werden {mc['n_sims']} Mal zufällig neu gemischt (Seed fest). Das zeigt, wie groß Verlustserien allein durch die Reihenfolge werden können. "
      f"Trades pro Jahr (aus den Daten): {mc['trades_per_year']:.1f}; 1 Jahr = {mc['ny']} Trades. Prozentwerte: 0,75 % Risiko je Trade, mit Zinseszins, ohne Exposure-Grenze, "
      "alle Coins als eine Folge (die Coins sind aber korreliert – in Wirklichkeit liegen Verluste öfter gleichzeitig).\n")
    A("| Kennzahl | Median | schlechter Fall (95 %) | tatsächliche Reihenfolge |\n|---|---|---|---|")
    A(f"| Max. Drawdown in R | {mc['dd_r_med']:.1f} | {mc['dd_r_p95']:.1f} | {mc['obs_dd_r']:.1f} |")
    A(f"| Max. Drawdown in % des Kapitals | {mc['dd_pct_med']:.1f} % | {mc['dd_pct_p95']:.1f} % | – |")
    A(f"| Längste Verlustserie (Trades) | {mc['streak_med']:.0f} | {mc['streak_p95']:.0f} (Maximum {mc['streak_max']:.0f}) | {mc['obs_streak']} |")
    A(f"| Ergebnis nach 1 Jahr ({mc['ny']} Trades), Summe R | {R(mc['year_med'],1)} | 5 %: {R(mc['year_p5'],1)} / 95 %: {R(mc['year_p95'],1)} | – |")
    A(f"\nWahrscheinlichkeit, dass die Summe nach 1 Jahr Trades negativ ist: **{mc['p_neg_year']*100:.0f} %** (Ø R je Trade in den Daten: {R(mc['mean_r'])}). "
      "Das ist nur so gut wie die Annahme, dass die Zukunft wie die Vergangenheit aussieht.\n")
    A("### 5.4 Vergleich mit Zufalls-Einstiegen (gleiche Ausstiege)\n")
    A(f"Geometrie wie in BACKTEST.md aus den EW-Signalen der Einstellperiode (b): Stop {geom['risk_pct']*100:.2f} % vom Einstieg, T1 {geom['t1_r']:.2f} R, T2 {geom['t2_r']:.2f} R, "
      f"Limit {geom['off']*100:.2f} % unter dem Kurs. Periodisch = alle 12 h, Zufall = ca. 1 Einstieg pro Tag (5 Läufe zusammen). Gleiche Gebühren und Slippage.\n")
    A("| Zeitraum | Gruppe | Trades | Trefferquote | Ø R netto | Ø R brutto | Summe R | Max. DD (R) |\n|---|---|---|---|---|---|---|---|")
    for lab, t0, t1 in (("2021 bis heute", None, None), ("(a)", None, P_B_START), ("(b)", P_B_START, P_C_START), ("(c)", P_C_START, None)):
        for nm, tr in (("EW-Strategie", allew), ("Periodisch", pall), ("Zufall", rall)):
            s = stats(in_range(tr, t0, t1))
            A(f"| {lab} | {nm} | {s['trades']} | {s['win_rate']*100:.0f} % | {R(s['avg_r'])} | {R(s['avg_r_gross'])} | {s['total_r']:+.1f} | {s['max_dd_r']:.1f} |")
    A("")

    # ---- Urteil
    sr_all = stats(rall); sp_all = stats(pall)
    A("## 6. Urteil\n")
    A(f"**Bestätigt oder widerspricht der nie gesehene Zeitraum BACKTEST.md?** {v1} "
      f"BACKTEST.md sagte: nach Gebühren keine tragfähige Kante, vor Gebühren höchstens ein kleiner Vorteil. "
      f"Zeitraum (a) ({sa['trades']} Trades): Ø {R(sa['avg_r'])} R netto, {R(sa['avg_r_gross'])} R brutto; Zufalls-Einstiege brutto im selben Zeitraum: "
      f"{R(stats(in_range(rall, None, P_B_START))['avg_r_gross'])} R.\n")
    ew_g, rn_g = stats(in_range(allew, None, P_B_START))['avg_r_gross'], stats(in_range(rall, None, P_B_START))['avg_r_gross']
    A(f"Gegen Zufall (Zeitraum a, brutto): EW {R(ew_g)} R, Zufalls-Einstiege {R(rn_g)} R. "
      + ("Das ist ein kleiner Vorteil vor Gebühren; er ist aber kleiner als die Gebühren (siehe unten) und bei der Tradezahl nicht gesichert.\n" if ew_g > rn_g + 0.1
         else "Kein klarer Vorteil des EW-Filters gegenüber Zufall.\n"))
    A("**Wann funktioniert die Strategie, wann nicht?**\n")
    for rg in ("steigend", "seitwärts", "fallend"):
        s = rstat[rg]["s"]
        flag = "positiv" if s["avg_r"] > 0 else "negativ"
        thin = " (zu wenige Trades für ein Urteil)" if s["trades"] < 20 else ""
        sig = " Der 95 %-Bereich liegt komplett unter 0 – das ist ein klares Minus." if s["trades"] and s["ci_hi"] < 0 else (
            " Der 95 %-Bereich schließt 0 ein – nicht von Null unterscheidbar." if s["trades"] else "")
        A(f"- BTC-Monat *{rg}*: {s['trades']} Trades, Ø {R(s['avg_r'])} R netto, brutto {R(s['avg_r_gross'])} R ({flag}){thin}.{sig}")
    if cand_sorted:
        v_b, s_b = cand_sorted[-1]; v_w, s_w = cand_sorted[0]
        A(f"- Beste Phase: {v_b['name'].strip()} ({s_b['total_r']:+.1f} R aus {s_b['trades']} Trades). Schlechteste Phase: {v_w['name'].strip()} ({s_w['total_r']:+.1f} R aus {s_w['trades']} Trades).")
    A("")
    A("**Gebühren:** " + (f"Mit Maker 0,25 % / Taker 0,50 % ist der Durchschnitt {R(avg_r(fee_rows[0][3]))} R. Er wird erst bei Maker ≤ {be_ratio2*100:.3f} % "
                          f"(Taker doppelt) nicht mehr negativ. Brutto (ohne Gebühren) liegt er bei {R(avg_r(fee_rows[3][3]))} R."
                          if be_ratio2 is not None else
                          f"Auch ohne Gebühren ist der Durchschnitt {R(avg_r(fee_rows[3][3]))} R – Gebühren sind nicht das einzige Problem."))
    A("")
    A("**Empfehlung:** Weiter nur Papier-Modus. Echtgeld erst, wenn eine Gebührenstufe unter der Break-even-Schwelle sicher verfügbar ist **und** weitere Trades "
      "außerhalb der Stichprobe das Bild bestätigen. Dieser Test hat nichts neu eingestellt, daher ist (a) ein fairer Blindtest – aber nur ein Marktzyklus.\n")

    A("## 7. Grenzen\n")
    A("- **Korrelation der Coins:** BTC, ETH und SOL fallen und steigen meist gemeinsam. Die Trades sind nicht unabhängig; die Zahl der echten, unabhängigen Chancen ist kleiner als die Tradezahl. "
      "Der Monte-Carlo-Test mischt alle Coins als eine Folge und unterschätzt gleichzeitige Verluste.")
    A("- **30m-Unschärfe innerhalb der Kerze:** Die Simulation kennt die Reihenfolge von Hoch und Tief in einer Kerze nicht. Sie nimmt vorsichtig immer den Stop zuerst und wertet in der Einstiegskerze keine Ziele. "
      "Das drückt das Ergebnis eher nach unten; echte Fills (Warteschlange, Teilfüllung) können anders sein.")
    A(f"- **Datenlücken:** Siehe Abschnitt 1. Bei BTC fehlt der ganze Juni 2021 (Börse liefert nichts); dazu einige kleine Lücken bis zu einem Tag. "
      f"{len(gap_tr)} Trades berühren eine Lücke (Ergebnis ohne sie: Ø {R(avg_r(clean))} R). Der Kurssprung über die Juni-Lücke kann das 30m-Fenster der Strategie im Juli 2021 verfälschen.")
    n_a = {c: per['a']['coin'][c]['trades'] for c in COINS}
    A(f"- **Weniger Daten vor Mitte 2021:** Von Januar bis Juni 2021 läuft nur BTC; ETH startet erst am {fmt(c30map['ETH'][0].t)}, SOL am {fmt(c30map['SOL'][0].t)}. "
      f"Der Zeitraum (a) hat deshalb je Coin unterschiedlich viele Trades (BTC {n_a['BTC']}, ETH {n_a['ETH']}, SOL {n_a['SOL']}).")
    A(f"- **SOL-Börsenstart / Überlebens-Verzerrung:** SOL-Kurse gibt es erst ab {fmt(c30map['SOL'][0].t)}; frühere Phasen enthalten SOL nicht (in den Tabellen „n/a“). "
      "Außerdem sind BTC, ETH und SOL die Coins, die bis heute überlebt haben und groß wurden; gescheiterte Coins fehlen (Überlebens-Verzerrung). Das macht Ergebnisse eher zu gut als zu schlecht.")
    A("- **Einstellung:** Die Standardwerte wurden 2025/2026 im Zeitraum (b) ausgewählt (16 Varianten). Zeitraum (a) war dabei nicht sichtbar, ist aber ein einziger Marktzyklus mit nur wenigen Trends. "
      "Phasen-Auswertung mit wenigen Trades ist anfällig für Zufall (nicht mit Statistik absicherbar).")
    A("- **Gebühren, Slippage und Börse:** Gebühren sind Annahmen, die Slippage ist pauschal; Kurse stammen von Crypto.com (USD-Paare, in der Frühzeit eventuell dünner Handel).")
    A("- **Ursachen der Phasen:** Nur dort genannt, wo sie allgemein bekannt sind, und nach meinem Kenntnisstand (nicht aus den Daten abgeleitet). Für 2026 nenne ich keine Ursachen.\n")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-md", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args()
    txt = build(a.fresh, a.procs)
    if not a.no_md:
        with open(os.path.join(ROOT, "SCENARIOS.md"), "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        print("SCENARIOS.md written")
    print(txt[:2500])


if __name__ == "__main__":
    main()
