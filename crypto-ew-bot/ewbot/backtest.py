"""Walk-forward backtest of the EW strategy. Usage:
    python -m ewbot.backtest --coins BTC ETH SOL            # full run, writes BACKTEST.md
    python -m ewbot.backtest --tune                         # small grid on IN-SAMPLE part only
    python -m ewbot.backtest --download                     # refresh data/hist first

Simulation rules (all conservative, candle = closed 30m bar, no look-ahead):
  * Signal is created at the close of candle i; the limit buy rests from candle i+1 on.
  * Fill if low <= entry (fill price = entry, no price improvement). Maker fee.
  * In the fill candle only the stop is checked (targets are not credited: order of high/low unknown).
  * Stop if low <= stop (checked BEFORE targets in every candle); exit at min(stop, open) minus slippage, taker fee.
  * T1 if high > T1: sell 50 % (maker), stop -> entry (break-even). If the T1 candle also touched entry, the rest is
    stopped at break-even (conservative). T2 if high > T2: sell rest (maker).
  * Unfilled order is cancelled if high >= cancel_above (T1) or at expiry (48 h after creation).
  * Fees (assumption): maker 0.25 %, taker 0.50 %; stop slippage 0.10 %.
"""
from __future__ import annotations
import argparse, json, os, random, statistics, sys, time
from dataclasses import dataclass, asdict, replace
from typing import List, Optional

from .models import Candle
from .strategy import StrategyParams, find_signals, M30, H4
from .history import load_history, DATA_DIR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKER, TAKER, SLIP = 0.0025, 0.005, 0.001
WARMUP = 600          # 30m candles before the first evaluation
WIN30 = 450


@dataclass
class Trade:
    coin: str
    kind: str                 # "ew" | "periodic" | "random"
    created_ts: int
    entry: float
    stop: float
    t1: float
    t2: float
    status: str               # "filled" | "missed" (T1 before fill) | "expired" | "open"
    fill_ts: int = 0
    exit_ts: int = 0
    outcome: str = ""         # "stop" | "be" | "t1+t2" | "open"
    r_gross: float = 0.0
    r_net: float = 0.0
    fee_r: float = 0.0
    score: float = 0.0


def load_candles(coin: str):
    c30 = [Candle(*r) for r in load_history(coin, "30m")]
    c4 = [Candle(*r) for r in load_history(coin, "4h")]
    return c30, c4


def _manage_position(c30, j0, entry, stop, t1, t2, fill_j):
    """Simulate from the candle AFTER the fill. Returns (exit_j, outcome, r_gross, fee_r). Risk-normalised (1R)."""
    risk = entry - stop
    f_left, stop_cur, t1_done = 1.0, stop, False
    gross, fees = 0.0, MAKER * entry          # entry maker fee (per unit)
    def sell(frac, px, taker):
        nonlocal gross, fees, f_left
        gross += frac * (px - entry)
        fees += frac * px * (TAKER if taker else MAKER)
        f_left -= frac
    for j in range(fill_j + 1, len(c30)):
        c = c30[j]
        if c.l <= stop_cur:
            px = min(stop_cur, c.o) * (1 - SLIP)
            sell(f_left, px, True)
            return j, ("be" if t1_done else "stop"), gross / risk, fees / risk
        if not t1_done and c.h > t1:
            sell(0.5, t1, False); t1_done = True; stop_cur = entry
            if c.l <= entry:                        # touched break-even in same candle: conservative
                sell(f_left, min(entry, c.o) * (1 - SLIP), True)
                return j, "be", gross / risk, fees / risk
        if t1_done and c.h > t2:
            sell(f_left, t2, False)
            return j, "t1+t2", gross / risk, fees / risk
    # data ends: mark remainder at last close, taker exit
    sell(f_left, c30[-1].c, True)
    return len(c30) - 1, "open", gross / risk, fees / risk


def simulate(c30, i, sig_vals, coin, kind, score=0.0) -> (Trade, int):
    """sig_vals=(created_ts, valid_until, entry, stop, t1, t2, cancel_above). Returns trade and last candle index used."""
    created_ts, valid_until, entry, stop, t1, t2, cancel_above = sig_vals
    tr = Trade(coin, kind, created_ts, entry, stop, t1, t2, "expired", score=score)
    for j in range(i + 1, len(c30)):
        c = c30[j]
        if c.t >= valid_until:
            return tr, j - 1
        if c.l <= entry:
            tr.status, tr.fill_ts = "filled", c.t
            if c.l <= stop:                         # filled and stopped in the same candle
                px = min(stop, c.o) * (1 - SLIP)
                risk = entry - stop
                g = (px - entry) / risk
                fee = (MAKER * entry + TAKER * px) / risk
                tr.exit_ts, tr.outcome, tr.r_gross, tr.fee_r = c.t, "stop", g, fee
                tr.r_net = g - fee
                return tr, j
            xj, out, g, fee = _manage_position(c30, j, entry, stop, t1, t2, j)
            tr.exit_ts, tr.outcome, tr.r_gross, tr.fee_r = c30[xj].t, out, g, fee
            tr.r_net = g - fee
            if out == "open":
                tr.status = "open"
            return tr, xj
        if c.h >= cancel_above:
            tr.status = "missed"
            return tr, j
    tr.status = "expired"
    return tr, len(c30) - 1


def run_coin(coin: str, p: StrategyParams, kind: str = "ew", end_ts: Optional[int] = None,
             base_geom: Optional[dict] = None, period: int = 24, seed: int = 0, rate: float = 0.0,
             data=None) -> List[Trade]:
    c30, c4 = data or load_candles(coin)
    trades: List[Trade] = []
    rnd = random.Random(seed)
    k4 = 0
    used = set()
    i = WARMUP
    n = len(c30)
    while i < n - 1:
        c = c30[i]
        now = c.t + M30
        if end_ts is not None and now > end_ts:
            break
        while k4 + 1 < len(c4) and c4[k4 + 1].t + H4 <= now:
            k4 += 1
        sv, score = None, 0.0
        if kind == "ew":
            if c4[k4].t + H4 > now:
                i += 1; continue
            sigs = find_signals(coin, f"{coin}_USD", c30[max(0, i - WIN30 + 1):i + 1], c4[max(0, k4 - 1300):k4 + 1], p, now)
            if sigs and sigs[0].id not in used:
                s = sigs[0]
                used.add(s.id)
                sv = (s.created_ts, s.valid_until_ts, s.entry, s.stop, s.t1, s.t2, s.cancel_above)
                score = s.score
        else:
            fire = (i % period == 0) if kind == "periodic" else (rnd.random() < rate)
            if fire:
                g = base_geom
                entry = c.c * (1 - g["off"])
                risk = entry * g["risk_pct"]
                stop = entry - risk
                sv = (now, now + 48 * 3_600_000, entry, stop, entry + g["t1_r"] * risk, entry + g["t2_r"] * risk,
                      entry + g["t1_r"] * risk)
        if sv is None:
            i += 1; continue
        tr, last = simulate(c30, i, sv, coin, kind, score)
        trades.append(tr)
        i = max(i + 1, last + 1) if tr.status in ("filled", "open") else i + 1   # one position at a time per coin
        if tr.status in ("missed", "expired") and kind != "ew":
            i = max(i, last + 1)
    return trades


# ------------------------------------------------------------------------------------------------
def stats(trades: List[Trade]) -> dict:
    f = [t for t in trades if t.status in ("filled", "open")]
    sig = len(trades)
    out = dict(signals=sig, trades=len(f), fill_rate=(len(f) / sig if sig else 0.0))
    if not f:
        out.update(win_rate=0, avg_r=0, avg_r_gross=0, pf=0, total_r=0, max_dd_r=0, ci_lo=0, ci_hi=0)
        return out
    f = sorted(f, key=lambda t: t.exit_ts)
    r = [t.r_net for t in f]
    wins = [x for x in r if x > 0]
    losses = [-x for x in r if x <= 0]
    cum, peak, dd = 0.0, 0.0, 0.0
    for x in r:
        cum += x; peak = max(peak, cum); dd = max(dd, peak - cum)
    rnd = random.Random(1)
    boots = sorted(sum(rnd.choice(r) for _ in r) / len(r) for _ in range(1000))
    out.update(win_rate=len(wins) / len(r), avg_r=sum(r) / len(r), avg_r_gross=sum(t.r_gross for t in f) / len(f),
               pf=(sum(wins) / sum(losses) if losses and sum(losses) > 0 else float("inf")),
               total_r=sum(r), max_dd_r=dd, ci_lo=boots[25], ci_hi=boots[974],
               avg_fee_r=sum(t.fee_r for t in f) / len(f))
    return out


def portfolio(trades: List[Trade], c30map: dict, risk_pct=0.0075, exp_cap=0.9) -> dict:
    """Compounding equity: risk_pct of equity per trade, total exposure capped; returns % return and max DD %."""
    f = [t for t in trades if t.status in ("filled", "open")]
    ev = []
    for k, t in enumerate(f):
        ev.append((t.fill_ts, 1, k)); ev.append((t.exit_ts, 0, k))
    ev.sort()
    eq, peak, mdd = 1.0, 1.0, 0.0
    open_pos = {}
    for ts, is_entry, k in ev:
        t = f[k]
        if is_entry:
            exposure = sum(v[0] for v in open_pos.values())
            want = risk_pct / ((t.entry - t.stop) / t.entry)          # notional as share of equity
            cur_eq = eq
            notional = min(want, max(0.0, exp_cap - exposure))
            open_pos[k] = (notional, notional / want if want else 0.0, cur_eq)
        elif k in open_pos:
            notional, scale, cur_eq = open_pos.pop(k)
            eq += cur_eq * risk_pct * scale * t.r_net
            peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    return dict(ret_pct=(eq - 1) * 100, max_dd_pct=mdd * 100)


def split_ts(c30):
    t0, t1 = c30[WARMUP].t, c30[-1].t
    return int(t0 + 0.6 * (t1 - t0))


def geom_from(trades: List[Trade], c30map=None) -> dict:
    """Median geometry of EW signals, used to build the baselines."""
    ss = [t for t in trades if t.kind == "ew"]
    risk_pct = statistics.median((t.entry - t.stop) / t.entry for t in ss)
    t1_r = statistics.median((t.t1 - t.entry) / (t.entry - t.stop) for t in ss)
    t2_r = statistics.median((t.t2 - t.entry) / (t.entry - t.stop) for t in ss)
    return dict(risk_pct=risk_pct, t1_r=t1_r, t2_r=t2_r, off=risk_pct * 0.4)


# ------------------------------------------------------------------------------------------------
def _task(args):
    coin, pd, end_ts = args
    p = StrategyParams(**pd)
    return coin, run_coin(coin, p, "ew", end_ts)


def tune(coins, procs=2, stage=1):
    from multiprocessing import Pool
    base = StrategyParams()
    data = {c: load_candles(c) for c in coins}
    sp = split_ts(data[coins[0]][0])
    grid = []
    if stage == 1:
        for pb in (None, 1.0):
            for z in (1.0, 2.0):
                for sb in (0.5, 2.0):
                    grid.append(dict(confirm_pb_atr=pb, zone_atr=z, stop_buf_atr=sb))
    else:      # stage 2: on top of the best stage-1 set (= StrategyParams defaults)
        for er in (0.5, 0.618):
            for mc in (1, 2):
                for k in (2.5, 3.5):
                    grid.append(dict(entry_retr=er, min_confluence=mc, k30=k))
    tasks = []
    for g in grid:
        pd = asdict(base); pd.update(g)
        for c in coins:
            tasks.append((c, pd, sp))
    with Pool(procs) as pool:
        res = pool.map(_task, tasks)
    rows = []
    for gi, g in enumerate(grid):
        tr = []
        for ci in range(len(coins)):
            tr += res[gi * len(coins) + ci][1]
        s = stats(tr)
        rows.append(dict(params=g, **s))
        print(g, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}, flush=True)
    json.dump(dict(split_ts=sp, rows=rows), open(os.path.join(DATA_DIR, "hist", f"tune_is_stage{stage}.json"), "w"), indent=1, default=str)
    return rows


def _fmt_ts(ms):
    return time.strftime("%d.%m.%Y", time.gmtime(ms / 1000))


def _row(name, s):
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    ci = f"[{s['ci_lo']:+.2f} ; {s['ci_hi']:+.2f}]" if s["trades"] else "-"
    return (f"| {name} | {s['signals']} | {s['trades']} | {s['win_rate']*100:.0f} % | {s['avg_r']:+.2f} | "
            f"{s['avg_r_gross']:+.2f} | {pf} | {s['total_r']:+.1f} | {s['max_dd_r']:.1f} | {ci} |")


HEAD = ("| Gruppe | Signale | Trades | Trefferquote | Ø R netto | Ø R brutto | Profit-Faktor | Summe R | Max. DD (R) | 95 %-Bereich Ø R |\n"
        "|---|---|---|---|---|---|---|---|---|---|")


def _split(trades, sp):
    return [t for t in trades if t.created_ts < sp], [t for t in trades if t.created_ts >= sp]


def full_run(coins, procs=2, write=True):
    global MAKER, TAKER
    from .strategy import describe_count
    p = StrategyParams()
    data = {c: load_candles(c) for c in coins}
    sp = split_ts(data[coins[0]][0])
    t_start, t_end = data[coins[0]][0][WARMUP].t, data[coins[0]][0][-1].t
    ew = {c: run_coin(c, p, "ew", None, data=data[c]) for c in coins}
    allew = [t for c in coins for t in ew[c]]
    ew_is = [t for t in allew if t.created_ts < sp]
    geom = geom_from(ew_is)
    per = {c: run_coin(c, p, "periodic", None, base_geom=geom, period=24, data=data[c]) for c in coins}
    rnd = {c: [run_coin(c, p, "random", None, base_geom=geom, seed=sd, rate=1 / 48, data=data[c]) for sd in range(5)] for c in coins}
    # fee scenario (assumption: lower fee tier)
    MAKER, TAKER = 0.001, 0.002
    ew_lo = [t for c in coins for t in run_coin(c, p, "ew", None, data=data[c])]
    MAKER, TAKER = 0.0025, 0.005
    # exploratory variant (NOT chosen by the tuning rule: only 6 in-sample trades)
    p2 = replace(p, min_confluence=2)
    ew2 = [t for c in coins for t in run_coin(c, p2, "ew", None, data=data[c])]

    L = []
    L.append("# Backtest: Elliott-Wellen-Strategie (BTC, ETH, SOL)\n")
    L.append("Alle Zahlen kommen aus dem Code (`python -m ewbot.backtest`). Erzeugt am "
             + time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime()) + ".\n")
    L.append("## Daten\n")
    L.append("| Coin | 30m-Kerzen | von | bis | 4h-Kerzen (ab) | Kursänderung im Testzeitraum |\n|---|---|---|---|---|---|")
    for c in coins:
        c30, c4 = data[c]
        bh = (c30[-1].c / c30[WARMUP].c - 1) * 100
        L.append(f"| {c}_USD | {len(c30)} | {_fmt_ts(c30[0].t)} | {_fmt_ts(c30[-1].t)} | {len(c4)} ({_fmt_ts(c4[0].t)}) | {bh:+.0f} % |")
    L.append(f"\nQuelle: öffentliche Crypto.com-API (nur geschlossene Kerzen). Die ersten {WARMUP} Kerzen sind Anlaufzeit. "
             f"Ausgewertet wird {_fmt_ts(t_start)} bis {_fmt_ts(t_end)}. Der Download war auf 30 000 Kerzen je Coin begrenzt (ca. 20 Monate 30m); "
             "mehr wäre vermutlich möglich, wurde aber nicht geholt.\n")
    L.append(f"**Aufteilung:** erste 60 % (bis {_fmt_ts(sp)}) = *In-Sample* (hier wurde getestet und eingestellt), letzte 40 % = *Out-of-Sample* "
             "(blind, erst nach Festlegung der Parameter angeschaut). Ein Trade zählt zu dem Teil, in dem das Signal entstand.\n")
    L.append("## Annahmen der Simulation (vorsichtig)\n")
    L.append("- Kauf-Limit füllt, wenn das Tief der Kerze den Einstieg berührt (Fülpreis = Einstieg, keine Preisverbesserung). Maker-Gebühr **0,25 %** (Annahme).\n"
             "- Stop (synthetisch, auf dem 30m-Tief): Berührt eine Kerze Stop und Ziel, gilt **der Stop zuerst**. Taker-Gebühr **0,50 %** (Annahme) plus **0,10 %** Slippage.\n"
             "- In der Einstiegskerze werden Ziele nicht gewertet (Reihenfolge Hoch/Tief unbekannt). T1 verkauft 50 %, danach Stop auf Einstand; berührt die T1-Kerze auch den Einstand, wird der Rest dort gestoppt.\n"
             "- Order verfällt nach 48 h oder wird gelöscht, wenn T1 vor dem Fill erreicht wird. Eine Position je Coin.\n"
             "- R = Abstand Einstieg bis Stop. Alle Gebühren sind in R umgerechnet (Ø R netto = nach Gebühren).\n")
    L.append("## Parameter (Standardwerte)\n")
    L.append("```\n" + "\n".join(f"{k} = {v}" for k, v in asdict(p).items()) + "\n```\n")
    L.append("Eingestellt wurde nur im In-Sample, mit 16 Varianten in zwei kleinen Rastern "
             "(`--tune 1`, `--tune 2`; Ergebnisse in `data/hist/tune_is_stage*.json`). Regel: beste Ø R netto mit mindestens 20 Trades. "
             "Die Variante `min_confluence=2` hatte im In-Sample nur 6 Trades (Ø +0,58 R) und wurde deshalb **nicht** gewählt – sie wird unten nur als Zusatz gezeigt.\n")

    def block(title, sel):
        L.append(f"### {title}\n"); L.append(HEAD)
        for c in coins:
            a, b = _split(ew[c], sp)
            L.append(_row(f"{c} In-Sample", stats(sel(a))))
            L.append(_row(f"{c} Out-of-Sample", stats(sel(b))))
        a, b = _split(allew, sp)
        L.append(_row("**Gesamt In-Sample**", stats(a)))
        L.append(_row("**Gesamt Out-of-Sample**", stats(b)))
        L.append("")
    block("EW-Strategie je Coin", lambda x: x)
    ia, oa = _split(allew, sp)
    s_is, s_oos = stats(ia), stats(oa)
    pa, pb = portfolio(ia, None), portfolio(oa, None)
    L.append("Portfolio-Rechnung (0,75 % Risiko je Trade, Gesamtrisiko-Exposure max. 90 %, mit Zinseszins):\n")
    L.append(f"- In-Sample: Rendite {pa['ret_pct']:+.1f} %, max. Drawdown {pa['max_dd_pct']:.1f} %\n- Out-of-Sample: Rendite {pb['ret_pct']:+.1f} %, max. Drawdown {pb['max_dd_pct']:.1f} %\n")
    fl = {}
    for t in oa:
        fl[t.status] = fl.get(t.status, 0) + 1
    L.append(f"Out-of-Sample Signale nach Ausgang: {fl}. 'missed' = T1 wurde erreicht, ohne dass der Einstieg gefüllt wurde; 'expired' = 48 h abgelaufen.\n")

    L.append("## Vergleich mit Zufalls-Einstiegen (gleiche Ausstiege)\n")
    L.append(f"Gleiche Geometrie wie die EW-Signale (Median aus dem In-Sample: Stop {geom['risk_pct']*100:.2f} % vom Einstieg, T1 {geom['t1_r']:.2f} R, T2 {geom['t2_r']:.2f} R, "
             f"Limit {geom['off']*100:.2f} % unter dem Kurs), 48 h Verfall, gleiche Gebühren. Einstiege: alle 12 h (periodisch) bzw. zufällig (ca. 1 pro Tag, 5 Zufallsläufe zusammen).\n")
    L.append(HEAD)
    pall = [t for c in coins for t in per[c]]
    rall = [t for c in coins for r in rnd[c] for t in r]
    for nm, tr in (("EW-Strategie", allew), ("Periodisch (12 h)", pall), ("Zufall (5 Läufe)", rall)):
        a, b = _split(tr, sp)
        L.append(_row(f"{nm} In-Sample", stats(a)))
        L.append(_row(f"{nm} Out-of-Sample", stats(b)))
    L.append("")
    L.append("Lesehilfe: *Ø R brutto* ohne Gebühren zeigt, ob der Einstieg überhaupt etwas bringt. Zufalls-Einstiege liegen brutto bei ca. 0 R (kein Vorteil, wie erwartet).\n")

    L.append("## Gebühren-Szenario und Zusatzvariante\n")
    L.append(HEAD)
    a, b = _split(ew_lo, sp)
    L.append(_row("EW mit Maker 0,10 % / Taker 0,20 % (Szenario) In-Sample", stats(a)))
    L.append(_row("EW mit Maker 0,10 % / Taker 0,20 % (Szenario) Out-of-Sample", stats(b)))
    a, b = _split(ew2, sp)
    L.append(_row("EW `min_confluence=2` (Zusatz, nicht gewählt) In-Sample", stats(a)))
    L.append(_row("EW `min_confluence=2` (Zusatz, nicht gewählt) Out-of-Sample", stats(b)))
    L.append("")
    L.append(f"Gebühren kosten im Schnitt {s_oos.get('avg_fee_r', 0):.2f} R je Trade (Out-of-Sample), weil der Stop nur ca. {geom['risk_pct']*100:.1f} % entfernt ist und Kauf plus Verkauf zusammen oft 0,5–0,75 % kosten.\n")

    # verdict
    o = s_oos
    L.append("## Urteil\n")
    if o["trades"] < 20:
        sample = f"Nur {o['trades']} Trades Out-of-Sample: das ist zu wenig für ein sicheres Urteil."
    else:
        sample = f"{o['trades']} Trades Out-of-Sample: wenig, aber ein erster Hinweis."
    if o["trades"] and o["ci_lo"] > 0:
        v = "Out-of-Sample **positiv** und statistisch klar von 0 verschieden."
    elif o["avg_r"] > 0:
        v = "Out-of-Sample **leicht positiv, aber nicht belastbar**: der 95 %-Bereich schließt 0 R ein."
    else:
        v = "Out-of-Sample **negativ nach Gebühren**."
    rb = stats([t for t in rall if t.created_ts >= sp])
    L.append(f"- {v} Ø R netto {o['avg_r']:+.2f}, Ø R brutto {o['avg_r_gross']:+.2f}, Profit-Faktor {o['pf']:.2f}. {sample}")
    L.append(f"- In-Sample war das Ergebnis Ø R netto {s_is['avg_r']:+.2f} (brutto {s_is['avg_r_gross']:+.2f}) – also schon beim Einstellen kein Gewinn nach Gebühren.")
    L.append(f"- Gegen Zufall: Out-of-Sample brutto EW {o['avg_r_gross']:+.2f} R vs. Zufall {rb['avg_r_gross']:+.2f} R. "
             + ("Der EW-Filter zeigt einen kleinen Vorteil vor Gebühren, aber bei so wenigen Trades kann das Zufall sein." if o['avg_r_gross'] > rb['avg_r_gross'] + 0.1
                else "Kein klarer Vorteil des EW-Filters gegenüber Zufall."))
    L.append("- **Fazit: Mit den angenommenen Gebühren (0,25 % / 0,50 %) ist keine tragfähige Kante nachgewiesen.** "
             "Die Strategie sollte nur im Papier-Modus laufen, bis deutlich mehr Trades vorliegen oder die Gebühren sinken. Kein Echtgeld auf Basis dieses Backtests.")
    L.append(("- Warum so wenige Trades: Es braucht eine große 4h-Rally, einen scharfen Abverkauf in eine Fibonacci-Zone und eine bestätigte Erholung. Nur {fr:.0f} % der Signale werden gefüllt (Out-of-Sample), bei den übrigen läuft der Kurs vorher zu T1 weg oder die 48 h laufen ab.\n").format(fr=o['fill_rate'] * 100))
    L.append("**Grenzen:** nur ca. 20 Monate Daten, ein Marktzyklus; 3 Coins stark korreliert (die Trades sind nicht unabhängig); 16 Varianten getestet (Mehrfachtest-Effekt); "
             "Gebühren sind Annahmen; 30m-Kerzen kennen die Reihenfolge von Hoch und Tief nicht (daher die vorsichtigen Regeln); die manuelle Methode enthält Ermessen, das ein Skript nicht abbildet.\n")

    # reproduction of tonight's setups
    L.append("## Vergleich mit den manuellen Signalen vom 08.11.2026\n")
    man = json.load(open(os.path.join(ROOT, "signals", "manual_2026-11-08.json")))["coins"]
    L.append("`find_signals` auf den zwischengespeicherten Daten `data/*_30m.json` (Stand 08.11.2026 ca. 23:00 UTC) mit den Standardwerten und mit der Variante `zone_atr=2.0` "
             "(wie großzügig der manuelle BTC-Einstieg war):\n")
    L.append("| Coin | manuell (Einstieg / Stop / T1 / T2) | Bot Standard | Bot `zone_atr=2.0` |\n|---|---|---|---|")
    for c in coins:
        c30 = [Candle(*r) for r in json.load(open(os.path.join(DATA_DIR, f"{c}_30m.json")))]
        c4 = data[c][1]
        m = man[c]
        cells = []
        for z in (None, 2.0):
            pp = p if z is None else replace(p, zone_atr=z)
            sg = find_signals(c, f"{c}_USD", c30, c4, pp)
            cells.append(f"{sg[0].entry:.2f} / {sg[0].stop:.2f} / {sg[0].t1:.2f} / {sg[0].t2:.2f}" if sg else "kein Signal")
        L.append(f"| {c} | {m['entry']} / {m['stop']} / {m['t1']} / {m['t2']} | {cells[0]} | {cells[1]} |")
    L.append("")
    for c in coins:
        c30 = [Candle(*r) for r in json.load(open(os.path.join(DATA_DIR, f"{c}_30m.json")))]
        L.append(f"- {describe_count(c, c30, data[c][1], p)['text_de']}")
    L.append("""
Unterschiede und Gründe:
- Die **4h-Rally und die Fibonacci-Level stimmen genau** mit der manuellen Rechnung überein (z. B. BTC 57 737 -> 87 428, 50 % = 72 582; SOL 61,8 % = 84,87).
- **ETH und SOL** werden mit den Standardwerten reproduziert. Einstiege liegen nah an den manuellen (ETH 2 087,55 statt 2 090; SOL 85,70 statt 85,60), weil beide bei 61,8 % der Welle 1 liegen (Welle-1-Hoch ETH 2 137,22 exakt wie manuell).
- **Stops und Ziele sind anders**: Der Bot setzt den Stop knapp unter Welle-Tief bzw. das Level darunter (minus 0,5 ATR), also eng (ca. 1–1,5 %). Die manuellen Stops waren weiter (2–5 %). Dafür liegt T1 beim Bot am Welle-1-Hoch (mindestens 1,1 R) und T2 bei 1,618 x Welle 1; manuell waren die Ziele etwas höher.
- **BTC**: Das Tief 73 326 liegt 743 USD über dem 50-%-Level (mehr als 1 ATR(4h)). Mit Standard `zone_atr=1.0` gibt es kein Signal; mit `zone_atr=2.0` entsteht fast der manuelle Einstieg (73 857 statt 73 900). Die manuelle Methode war hier großzügiger.
- **ETH, C-Projektion**: Der Bot findet die A-B-C-Punkte automatisch (4h-Zickzack). Sein Treffer ist C=1,272 x A bei 2 066 statt der manuellen C-Marke 2 055. Das Signal hängt an dieser einen Zone.
- Der Bot arbeitet nur mit **geschlossenen Kerzen** und wartet bis die Erholung (Welle 1) groß genug ist; die manuellen Signale waren Vorab-Limits.
- Bei den Standardwerten wird die Zone nur gewertet, wenn der Abverkauf davor scharf war (6 ATR) und die Erholung mindestens 3,5 ATR beträgt. Die ATR stammt aus der ruhigen Zeit vor dem Abverkauf, sonst würde der Crash die Schwellen selbst hochtreiben.
""")
    txt = "\n".join(L)
    if write:
        open(os.path.join(ROOT, "BACKTEST.md"), "w").write(txt)
        print("BACKTEST.md written")
    print(txt[:3000])
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", nargs="*", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--tune", type=int, default=0, help="1 or 2 = in-sample grid stage")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--no-md", action="store_true")
    a = ap.parse_args()
    if a.download:
        from .history import download_all
        download_all(tuple(a.coins))
    if a.tune:
        tune(a.coins, a.procs, a.tune); return
    full_run(a.coins, a.procs, write=not a.no_md)


if __name__ == "__main__":
    main()
