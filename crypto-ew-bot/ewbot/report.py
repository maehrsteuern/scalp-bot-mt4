"""German signal page renderer. One self-contained HTML string, no external requests.

render_page(data) -> str, data built by build_page_data(...). The same data is embedded as JSON in
<script type="application/json" id="ew-state"> (the calculator reads it).
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

NAMES = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana"}
STATE_DE = {"ENTRY_PENDING": "wartet auf Einstieg", "OPEN": "offen", "OPEN_BE": "offen (Stop = Einstieg)",
            "CLOSING": "wird geschlossen", "CLOSED": "geschlossen", "CANCELED": "storniert"}
MAX_CANDLES = 96


# ----------------------------------------------------------------- helpers
def _berlin_offset(dt_utc: datetime) -> int:
    """UTC offset hours for Europe/Berlin (EU rule: DST from last Sunday of March to last Sunday of October, 01:00 UTC)."""
    y = dt_utc.year

    def last_sunday(month: int) -> datetime:
        d = datetime(y, month, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    return 2 if last_sunday(3) <= dt_utc < last_sunday(10) else 1


def to_berlin(ts_ms: int) -> datetime:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:  # tzdata missing
        return dt + timedelta(hours=_berlin_offset(dt))


def fmt_dt(ts_ms: int, with_tz: bool = True) -> str:
    b = to_berlin(ts_ms)
    off = b.utcoffset().total_seconds() / 3600 if b.utcoffset() is not None else _berlin_offset(
        datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc))
    tz = "MESZ" if off == 2 else "MEZ"
    s = b.strftime("%d.%m.%Y, %H:%M") + " Uhr"
    return f"{s} ({tz})" if with_tz else s


def de_num(v: Optional[float], dec: Optional[int] = None) -> str:
    if v is None:
        return "-"
    if dec is None:
        dec = 0 if abs(v) >= 1000 else (2 if abs(v) >= 10 else 3)
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def e(s: Any) -> str:
    return html.escape(str(s), quote=True)


# ----------------------------------------------------------------- data
def _slim_trade(t: Dict[str, Any]) -> Dict[str, Any]:
    sig = t["signal"]
    return {k: t.get(k) for k in ("id", "coin", "state", "qty", "entry_qty", "entry_price", "stop", "remaining",
                                  "realized", "fees", "risk_usd", "r_multiple", "opened_ts", "closed_ts",
                                  "close_reason", "created_ts")} | {"t1": sig["t1"], "t2": sig["t2"],
                                                                    "entry": sig["entry"], "sig_stop": sig["stop"]}


def build_page_data(cfg, now_ts: int, eurusd: float, per_coin: Dict[str, Dict[str, Any]],
                    state: Optional[Dict[str, Any]] = None, equity: Optional[float] = None) -> Dict[str, Any]:
    """per_coin[coin] = {"signal": dict|None, "count": dict|None, "candles": [Candle|list...], "last": float|None}"""
    coins: Dict[str, Any] = {}
    for coin in cfg.coins:
        pc = per_coin.get(coin, {})
        rows = []
        for c in (pc.get("candles") or [])[-MAX_CANDLES:]:
            if isinstance(c, (list, tuple)):
                rows.append([int(c[0]), c[1], c[2], c[3], c[4]])
            else:
                rows.append([c.t, c.o, c.h, c.l, c.c])
        sig = pc.get("signal")
        if sig is not None and not isinstance(sig, dict):
            sig = sig.to_dict()
        coins[coin] = {"name": NAMES.get(coin, coin), "instrument": cfg.instrument(coin), "signal": sig,
                       "count": pc.get("count"), "candles": rows, "last": pc.get("last")}
    paper = None
    if state is not None:
        trades = [_slim_trade(t) for t in state.get("trades", {}).values()]
        trades.sort(key=lambda t: (t.get("created_ts") or 0, t["id"]))
        closed = [t for t in trades if t["state"] == "CLOSED"]
        paper = {
            "mode": state.get("mode", "paper"), "start_capital": state.get("start_capital"),
            "equity": equity, "trades": trades, "equity_curve": state.get("equity_curve", [])[-400:],
            "realized": sum(t.get("realized") or 0.0 for t in trades),
            "closed": len(closed), "wins": sum(1 for t in closed if (t.get("realized") or 0) > 0),
            "halt_new": bool(state.get("halt_new")), "log": state.get("log", [])[-12:],
        }
    return {"generated_ts": now_ts, "eurusd": eurusd, "risk_pct": cfg.risk_pct,
            "max_exposure_pct": cfg.max_exposure_pct, "capital_eur": 1000, "coins": coins, "paper": paper}


# ----------------------------------------------------------------- svg
def candle_svg(rows: List[list], lines: List[tuple], decimals: Optional[int] = None) -> str:
    """rows: [t,o,h,l,c]; lines: [(label, value, css_color)]. Inline SVG, theme colors via CSS variables."""
    if not rows:
        return ""
    W, H, L, R, T, B = 640, 230, 6, 92, 8, 22
    n = len(rows)
    lo = min(r[3] for r in rows)
    hi = max(r[2] for r in rows)
    for _, v, _ in lines:
        lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.04 or 1.0
    lo, hi = lo - pad, hi + pad

    def y(v: float) -> float:
        return T + (hi - v) / (hi - lo) * (H - T - B)
    step = (W - L - R) / n
    bw = max(step * 0.62, 1.0)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Kerzenchart 30 Minuten">']
    for i, r in enumerate(rows):
        x = L + step * (i + 0.5)
        col = "var(--grn)" if r[4] >= r[1] else "var(--red)"
        yt, yb = y(max(r[1], r[4])), y(min(r[1], r[4]))
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y(r[2]):.1f}" y2="{y(r[3]):.1f}" stroke="{col}" stroke-width="0.6"/>')
        o.append(f'<rect x="{x - bw / 2:.1f}" y="{yt:.1f}" width="{bw:.1f}" height="{max(yb - yt, 0.6):.1f}" fill="{col}"/>')
    labs = sorted([{"n": nm, "v": v, "c": c, "y": y(v), "ly": y(v)} for nm, v, c in lines], key=lambda d: d["y"])
    for i in range(1, len(labs)):
        if labs[i]["ly"] - labs[i - 1]["ly"] < 10:
            labs[i]["ly"] = labs[i - 1]["ly"] + 10
    for l in labs:
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{l["y"]:.1f}" y2="{l["y"]:.1f}" stroke="{l["c"]}" stroke-width="1" stroke-dasharray="4 3"/>')
        o.append(f'<text x="{W - R + 3}" y="{l["ly"] + 3:.1f}" font-size="9" fill="{l["c"]}">{e(l["n"])} {de_num(l["v"], decimals)}</text>')
    for f in (0, 0.25, 0.5, 0.75, 1):
        i = min(n - 1, round(f * (n - 1)))
        x = L + step * (i + 0.5)
        anchor = "start" if f == 0 else "end" if f == 1 else "middle"
        o.append(f'<text x="{x:.1f}" y="{H - 6}" font-size="8" fill="var(--mut)" text-anchor="{anchor}">'
                 f'{to_berlin(rows[i][0]).strftime("%d.%m. %H:%M")}</text>')
    o.append("</svg>")
    return "".join(o)


def equity_svg(curve: List[dict], start: float) -> str:
    if len(curve) < 2:
        return '<p class="grey">Noch keine Kurve - sie entsteht mit jedem Schritt.</p>'
    W, H, L, R, T, B = 640, 120, 6, 70, 8, 8
    vals = [p["equity"] for p in curve] + [start]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 1.0
    lo, hi = lo - pad, hi + pad
    n = len(curve)
    pts = " ".join(f"{L + (W - L - R) * i / (n - 1):.1f},{T + (hi - p['equity']) / (hi - lo) * (H - T - B):.1f}"
                   for i, p in enumerate(curve))
    ys = T + (hi - start) / (hi - lo) * (H - T - B)
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Eigenkapital-Kurve">'
            f'<line x1="{L}" x2="{W - R}" y1="{ys:.1f}" y2="{ys:.1f}" stroke="var(--gry)" stroke-dasharray="4 3"/>'
            f'<polyline points="{pts}" fill="none" stroke="var(--blue)" stroke-width="1.6"/>'
            f'<text x="{W - R + 3}" y="{ys + 3:.1f}" font-size="9" fill="var(--gry)">Start {de_num(start, 0)}</text>'
            f'<text x="{W - R + 3}" y="{T + 8}" font-size="9" fill="var(--blue)">{de_num(curve[-1]["equity"], 2)}</text></svg>')


# ----------------------------------------------------------------- html parts
CSS = """:root{--bg:#f6f7f9;--card:#fff;--tx:#1b1f24;--mut:#6a727c;--bd:#dde1e6;--blue:#1f6feb;--red:#d1342f;--grn:#1a9a4a;--gry:#8a929b;--warnbg:#fff6cc;--warnbd:#e5c94a;--warntx:#4a3d00;--inbg:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#111418;--card:#1a1e24;--tx:#e8eaed;--mut:#9aa3ad;--bd:#2d333b;--blue:#58a6ff;--red:#f2655f;--grn:#3fc76f;--gry:#8b949e;--warnbg:#3a3410;--warnbd:#7a6a1a;--warntx:#f3e7a6;--inbg:#111418}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:720px;margin:0 auto;padding:16px 14px 40px}
h1{font-size:1.4rem;margin:.2em 0 .3em}h2{font-size:1.15rem;margin:1.6em 0 .6em}
.sub{color:var(--mut);font-size:.88rem;margin:0 0 12px}
.note{background:var(--warnbg);border:1px solid var(--warnbd);color:var(--warntx);border-radius:10px;padding:10px 12px;font-size:.92rem}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px;margin:12px 0}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
label{display:block;font-size:.85rem;color:var(--mut);margin-bottom:3px}
input{font:inherit;color:var(--tx);background:var(--inbg);border:1px solid var(--bd);border-radius:8px;padding:8px;width:100%}
.res{margin-top:12px;font-size:.95rem}
.res div{display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--bd)}
.res div:last-child{border:0}
.warn{display:none;margin-top:8px;background:#fde7e6;color:#a31510;border:1px solid #e9a5a2;border-radius:8px;padding:8px 10px;font-weight:600}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.head h3{margin:0;font-size:1.2rem}
.badge{background:var(--grn);color:#fff;border-radius:99px;padding:2px 10px;font-size:.82rem;font-weight:600}
.badge.off{background:var(--gry)}
.valid{font-size:.85rem;color:var(--mut);margin:8px 0}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{padding:5px 4px;border-bottom:1px solid var(--bd);text-align:right}
th:first-child,td:first-child{text-align:left}
th{font-size:.8rem;color:var(--mut);font-weight:600}
.order{margin:10px 0;padding:8px 10px;border-radius:8px;background:var(--bg);font-weight:600}
svg{width:100%;height:auto;display:block;margin-top:8px}
.deut{font-size:.93rem;margin:10px 0 6px}.grey{color:var(--mut);font-size:.88rem}
.tbl{overflow-x:auto}.pos{color:var(--grn)}.neg{color:var(--red)}
.kpi{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px}
.kpi div{background:var(--bg);border-radius:8px;padding:8px;text-align:center}.kpi b{display:block;font-size:1.05rem}
.kpi span{font-size:.75rem;color:var(--mut)}
details{margin-top:8px}summary{cursor:pointer;color:var(--mut);font-size:.88rem}
pre{white-space:pre-wrap;font-size:.75rem;color:var(--mut)}
"""

JS = r"""
(function(){
var S=JSON.parse(document.getElementById('ew-state').textContent);
var nf=function(v,d){return new Intl.NumberFormat('de-DE',{maximumFractionDigits:d,minimumFractionDigits:d}).format(v);};
var eur=function(v){return nf(v,2)+' €';};
function calc(){
 var cap=parseFloat(document.getElementById('cap').value)||0, rsk=parseFloat(document.getElementById('rsk').value)||0;
 var risk=cap*rsk/100, tot=0, n=0, fx=S.eurusd;
 Object.keys(S.coins).forEach(function(c){var s=S.coins[c].signal, el=document.getElementById('ord-'+c); if(!s||!el)return;
  var perUnit=(s.entry-s.stop)*fx, units=perUnit>0?risk/perUnit:0, val=units*s.entry*fx; tot+=val; n++;
  el.innerHTML='Deine Order: <b>'+nf(units,c==='BTC'?5:c==='ETH'?4:2)+' '+c+'</b> ≈ '+eur(val)+' · Risiko ≈ '+eur(risk);});
 document.getElementById('r1').textContent=eur(risk);
 document.getElementById('r2').textContent=eur(risk*n);
 document.getElementById('r3').textContent=eur(tot);
 var pct=cap>0?tot/cap*100:0;
 document.getElementById('r4').textContent=nf(pct,1)+' %';
 document.getElementById('warn').style.display=pct>S.max_exposure_pct?'block':'none';
}
document.getElementById('cap').addEventListener('input',calc);
document.getElementById('rsk').addEventListener('input',calc);
calc();
})();
"""


def _level_rows(sig: Dict[str, Any], fx: float) -> str:
    d = sig["entry"] - sig["stop"]
    rows = [("Einstieg (Limit-Kauf)", sig["entry"], None), ("Stop-Loss", sig["stop"], -1.0),
            ("Ziel 1 (50 % verkaufen)", sig["t1"], (sig["t1"] - sig["entry"]) / d if d else None),
            ("Ziel 2 (Rest)", sig["t2"], (sig["t2"] - sig["entry"]) / d if d else None)]
    out = ['<div class="tbl"><table><thead><tr><th></th><th>USD</th><th>≈ EUR</th><th>CRV</th></tr></thead><tbody>']
    for name, v, rr in rows:
        crv = "-" if rr is None else (f"{de_num(rr, 2)} R")
        out.append(f"<tr><td>{e(name)}</td><td>{de_num(v)}</td><td>{de_num(v * fx)}</td><td>{crv}</td></tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _coin_card(coin: str, c: Dict[str, Any], fx: float) -> str:
    sig = c["signal"]
    h = [f'<div class="card"><div class="head"><h3>{e(coin)} <span class="grey" style="font-weight:400">{e(c["name"])}</span></h3>']
    if sig:
        h.append('<span class="badge">LONG (Kauf) - Limit-Order</span></div>')
        h.append(f'<p class="valid">Gültig bis {fmt_dt(sig["valid_until_ts"])}. Bis dahin nicht ausgeführt → Order löschen. '
                 f'Erreicht der Kurs vorher {de_num(sig["cancel_above"])} USD (Ziel 1) → Order ebenfalls löschen.</p>')
        h.append(_level_rows(sig, fx))
        h.append(f'<div class="order" id="ord-{e(coin)}"></div>')
        lines = [("Ziel 2", sig["t2"], "var(--grn)"), ("Ziel 1", sig["t1"], "var(--grn)"),
                 ("Einstieg", sig["entry"], "var(--blue)"), ("Stop", sig["stop"], "var(--red)")]
        h.append(candle_svg(c["candles"], lines))
        if sig.get("reason_de"):
            h.append(f'<p class="deut">{e(sig["reason_de"])}</p>')
        if sig.get("fib_hits"):
            h.append(f'<p class="grey">Fibonacci-Treffer: {e("; ".join(sig["fib_hits"]))} · Qualität: {de_num(sig.get("score", 0) * 100, 0)} %</p>')
    else:
        h.append('<span class="badge off">kein Setup</span></div>')
        cnt = c.get("count") or {}
        last = c.get("last")
        h.append(f'<p class="valid">Aktuell kein gültiges Signal.' + (f' Letzter Kurs: {de_num(last)} USD.' if last else "") + "</p>")
        if cnt.get("text_de"):
            h.append(f'<p class="deut">{e(cnt["text_de"])}</p>')
        if c["candles"]:
            h.append(candle_svg(c["candles"], []))
    h.append("</div>")
    return "".join(h)


def _paper_section(p: Dict[str, Any]) -> str:
    start = p.get("start_capital") or 0.0
    eq = p.get("equity") if p.get("equity") is not None else start
    tr = p["trades"]
    h = ['<h2>Paper-Trading (Übungskonto, kein echtes Geld)</h2><div class="card">']
    ret = (eq / start - 1) * 100 if start else 0.0
    wr = f"{p['wins']}/{p['closed']}" if p["closed"] else "-"
    h.append('<div class="kpi">'
             f'<div><b>{de_num(eq, 2)} $</b><span>Eigenkapital</span></div>'
             f'<div><b class="{"pos" if ret >= 0 else "neg"}">{de_num(ret, 2)} %</b><span>seit Start</span></div>'
             f'<div><b>{wr}</b><span>Gewinner/geschlossen</span></div></div>')
    if p.get("halt_new"):
        h.append('<div class="warn" style="display:block">Neue Trades sind gesperrt (Abgleich mit der Börse unklar).</div>')
    h.append(equity_svg(p.get("equity_curve", []), start))
    active = [t for t in tr if t["state"] in ("ENTRY_PENDING", "OPEN", "OPEN_BE", "CLOSING")]
    done = [t for t in tr if t["state"] in ("CLOSED", "CANCELED")]
    h.append("<h3 style='font-size:1rem;margin:14px 0 4px'>Offene Positionen / wartende Orders</h3>")
    if active:
        h.append('<div class="tbl"><table><thead><tr><th>Coin</th><th>Status</th><th>Einstieg</th><th>Menge</th><th>Stop</th><th>Ziele</th></tr></thead><tbody>')
        for t in active:
            qty = t["remaining"] if t["state"] != "ENTRY_PENDING" else t["qty"]
            px = t["entry_price"] or t["entry"]
            h.append(f'<tr><td>{e(t["coin"])}</td><td>{e(STATE_DE.get(t["state"], t["state"]))}</td><td>{de_num(px)}</td>'
                     f'<td>{de_num(qty, 5)}</td><td>{de_num(t["stop"])}</td><td>{de_num(t["t1"])} / {de_num(t["t2"])}</td></tr>')
        h.append("</tbody></table></div>")
    else:
        h.append('<p class="grey">Keine.</p>')
    h.append("<h3 style='font-size:1rem;margin:14px 0 4px'>Abgeschlossene Trades</h3>")
    if done:
        h.append('<div class="tbl"><table><thead><tr><th>Coin</th><th>Ende</th><th>Grund</th><th>Ergebnis $</th><th>R</th></tr></thead><tbody>')
        for t in done:
            res = t.get("realized") or 0.0
            r = t.get("r_multiple")
            h.append(f'<tr><td>{e(t["coin"])}</td><td>{fmt_dt(t["closed_ts"], False) if t.get("closed_ts") else "-"}</td>'
                     f'<td>{e(t.get("close_reason") or "")}</td><td class="{"pos" if res >= 0 else "neg"}">{de_num(res, 2)}</td>'
                     f'<td>{de_num(r, 2) if r is not None else "-"}</td></tr>')
        h.append("</tbody></table></div>")
    else:
        h.append('<p class="grey">Noch keine.</p>')
    if p.get("log"):
        h.append("<details><summary>Letzte Meldungen</summary><pre>" + e("\n".join(p["log"])) + "</pre></details>")
    h.append("</div>")
    return "".join(h)


def render_page(data: Dict[str, Any]) -> str:
    fx = data["eurusd"]
    parts = ["<!DOCTYPE html><html lang=\"de\"><head><meta charset=\"utf-8\">"
             "<title>Elliott-Wave Swing-Signale BTC · ETH · SOL</title>"
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
             f"<style>{CSS}</style></head><body><main>",
             "<h1>Elliott-Wave Swing-Signale BTC · ETH · SOL</h1>",
             f'<p class="sub">Stand: {fmt_dt(data["generated_ts"])} · Daten: Crypto.com Exchange (USD-Paare), '
             f'30-Min-Chart, 4h als Trendfilter · EUR-Werte sind Näherungen (1 USD ≈ {de_num(fx, 4)} EUR)</p>',
             '<div class="note"><b>Keine Anlageberatung.</b> Elliott-Wellen (eine Methode, Kursmuster in Wellen zu deuten) '
             'sind eine Deutung, keine Gewissheit. Jeder Trade hat einen festen Stop-Loss (automatischer Ausstieg bei Verlust). '
             'Du kannst das eingesetzte Geld ganz oder teilweise verlieren. Die Signale sind ein Schnappschuss und veralten - '
             'nur bis zum genannten Ablauf gültig.</div>',
             '<h2>Rechner</h2><div class="card"><div class="row2">'
             f'<div><label for="cap">Trading-Kapital in €</label><input id="cap" type="number" inputmode="decimal" value="{data["capital_eur"]}" min="0" step="50"></div>'
             f'<div><label for="rsk">Risiko pro Trade in %</label><input id="rsk" type="number" inputmode="decimal" value="{data["risk_pct"]}" min="0.25" max="2" step="0.25"></div></div>'
             '<div class="res"><div><span>Max. Verlust pro Trade</span><b id="r1"></b></div>'
             '<div><span>Max. Verlust, wenn alle Stops greifen</span><b id="r2"></b></div>'
             '<div><span>Gesamt investiert</span><b id="r3"></b></div>'
             '<div><span>Anteil am Kapital</span><b id="r4"></b></div></div>'
             '<div class="warn" id="warn">Zu viel investiert - Risiko senken</div></div>']
    for coin, c in data["coins"].items():
        parts.append(_coin_card(coin, c, fx))
    if data.get("paper"):
        parts.append(_paper_section(data["paper"]))
    parts.append('<p class="grey">Hinweis: Fehler, Ausfälle der Börse oder Kurssprünge über den Stop hinaus können zu '
                 'größeren Verlusten führen als geplant. Vergangene Ergebnisse sagen nichts über die Zukunft. '
                 'Gewinne aus dem Verkauf von Kryptowerten können steuerpflichtig sein (§ 23 EStG).</p>')
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    parts.append(f'<script type="application/json" id="ew-state">{blob}</script><script>{JS}</script></main></body></html>')
    return "".join(parts)
