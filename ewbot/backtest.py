"""Bar-by-bar backtester that drives the SAME decision path as the live bot (`Bot.process_candle`).

No look-ahead: for an exec candle closing at T, an HTF candle is visible only if ts + tf_ms <= T.
"""
from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .bot import HTF_WARMUP, Bot, NullNotifier, _construct, iso, paper_copy, timeframe_ms
from .config import BotCfg
from .models import Candle, TradeRecord


@dataclass
class BacktestResult:
    start_equity: float
    final_equity: float
    trades: list[TradeRecord]
    equity_curve: list[tuple[int, float]]
    metrics: dict[str, Any] = field(default_factory=dict)
    name: str = "backtest"
    exec_timeframe: str = ""
    symbols: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ reporting
    def to_markdown(self) -> str:
        m = self.metrics
        q = m.get("quote", "")
        start = iso(self.equity_curve[0][0]) if self.equity_curve else "-"
        end = iso(self.equity_curve[-1][0]) if self.equity_curve else "-"
        pf = m.get("profit_factor", 0.0)
        pf_s = "inf" if pf == math.inf else f"{pf:.2f}"
        lines = [
            f"# Backtest {self.name} ({self.exec_timeframe})",
            "",
            f"Zeitraum: {start} – {end} UTC | Märkte: {', '.join(self.symbols)}",
            "",
            "| Kennzahl | Wert |",
            "|---|---|",
            f"| Startkapital | {self.start_equity:.2f} {q} |",
            f"| Endkapital | {self.final_equity:.2f} {q} |",
            f"| Netto-PnL | {m.get('net_pnl', 0.0):+.2f} {q} |",
            f"| Rendite | {m.get('return_pct', 0.0):+.2f} % |",
            f"| Trades | {m.get('trades', 0)} |",
            f"| Trefferquote | {m.get('win_rate', 0.0):.1f} % |",
            f"| Profit-Faktor | {pf_s} |",
            f"| Max. Drawdown | {m.get('max_drawdown_pct', 0.0):.2f} % |",
            f"| Ø R-Multiple | {m.get('avg_rr', 0.0):+.2f} |",
            f"| Gebühren | {m.get('fees_paid', 0.0):.4f} {q} |",
            "",
        ]
        per_setup = m.get("trades_per_setup") or {}
        if per_setup:
            lines += ["| Setup | Trades | Trefferquote | Netto-PnL | Ø R |", "|---|---|---|---|---|"]
            for setup, s in sorted(per_setup.items()):
                lines.append(f"| {setup} | {s['trades']} | {s['win_rate']:.1f} % | {s['net_pnl']:+.2f} | "
                             f"{s['avg_rr']:+.2f} |")
            lines.append("")
        per_symbol = m.get("trades_per_symbol") or {}
        if per_symbol:
            lines += ["| Markt | Trades | Trefferquote | Netto-PnL |", "|---|---|---|---|"]
            for sym, s in sorted(per_symbol.items()):
                lines.append(f"| {sym} | {s['trades']} | {s['win_rate']:.1f} % | {s['net_pnl']:+.2f} |")
            lines.append("")
        lines.append("_Vergangene Ergebnisse sind keine Garantie für zukünftige Gewinne._")
        return "\n".join(lines)

    def save_csv(self, directory: str | Path) -> tuple[Path, Path]:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        eq_path, tr_path = d / "equity.csv", d / "trades.csv"
        with eq_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ts", "time_utc", "equity"])
            for ts, eq in self.equity_curve:
                w.writerow([ts, iso(ts), f"{eq:.6f}"])
        with tr_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "side", "setup", "timeframe", "opened_ts", "opened_utc", "closed_ts",
                        "closed_utc", "entry", "stop_initial", "tp1", "tp2", "exit", "qty", "pnl", "pnl_pct",
                        "fees", "r_multiple", "reason"])
            for t in self.trades:
                p = t.position
                w.writerow([p.symbol, p.side.value, p.setup.value, p.timeframe, p.opened_ts, iso(p.opened_ts),
                            t.closed_ts, iso(t.closed_ts), p.entry, p.tags.get("stop0", p.stop), p.tp1, p.tp2,
                            t.exit_price, p.qty, f"{t.pnl:.6f}", f"{t.pnl_pct:.6f}", f"{p.fees:.6f}",
                            f"{r_multiple(t):.3f}", t.reason])
        return eq_path, tr_path


# ---------------------------------------------------------------------------------------- metrics

def r_multiple(t: TradeRecord) -> float:
    """Realised PnL in units of the initial risk (uses the risk stored at entry by the bot)."""
    p = t.position
    try:
        risk = float(p.tags.get("risk_quote", "nan"))
    except (TypeError, ValueError):
        risk = math.nan
    if not (risk > 0):
        risk = abs(p.entry - float(p.tags.get("stop0", p.stop))) * p.qty
    return t.pnl / risk if risk > 0 else 0.0


def _group(trades: list[TradeRecord]) -> dict[str, float]:
    n = len(trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    return {"trades": n, "win_rate": 100.0 * wins / n if n else 0.0,
            "net_pnl": sum(t.pnl for t in trades),
            "avg_rr": sum(r_multiple(t) for t in trades) / n if n else 0.0}


def compute_metrics(start_equity: float, final_equity: float, trades: list[TradeRecord],
                    equity_curve: list[tuple[int, float]], quote: str = "") -> dict[str, Any]:
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = -sum(t.pnl for t in trades if t.pnl < 0)
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = math.inf if gross_win > 0 else 0.0
    peak, max_dd = -math.inf, 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)
    base = _group(trades)
    per_setup: dict[str, list[TradeRecord]] = {}
    per_symbol: dict[str, list[TradeRecord]] = {}
    for t in trades:
        per_setup.setdefault(t.position.setup.value, []).append(t)
        per_symbol.setdefault(t.position.symbol, []).append(t)
    return {
        "quote": quote,
        "net_pnl": final_equity - start_equity,
        "return_pct": (final_equity / start_equity - 1.0) * 100.0 if start_equity else 0.0,
        "trades": base["trades"],
        "win_rate": base["win_rate"],
        "profit_factor": pf,
        "max_drawdown_pct": max_dd,
        "avg_rr": base["avg_rr"],
        "fees_paid": sum(t.position.fees for t in trades),
        "trades_per_setup": {k: _group(v) for k, v in per_setup.items()},
        "trades_per_symbol": {k: _group(v) for k, v in per_symbol.items()},
    }


# --------------------------------------------------------------------------------------- engine

def run_backtest(cfg: BotCfg, candles_by_tf: dict[str, dict[str, list[Candle]]], start_equity: float, *,
                 strategy: Any = None, broker: Any = None, risk: Any = None,
                 logger: Optional[logging.Logger] = None, close_at_end: bool = True) -> BacktestResult:
    """Walk the exec timeframe bar by bar over all symbols in `candles_by_tf[symbol][timeframe]`.

    strategy / broker / risk default to ElliottStrategy / PaperBroker / RiskManager; they are injectable
    for tests. Positions still open at the end are closed at the last close (reason "end").
    """
    bcfg = paper_copy(cfg, start_equity)
    log = logger or logging.getLogger(f"ewbot.backtest.{cfg.name}")
    if strategy is None:
        from .strategy import ElliottStrategy
        strategy = ElliottStrategy(bcfg)
    if risk is None:
        from .risk import RiskManager
        risk = RiskManager(bcfg.risk)
    if broker is None:
        from .broker import PaperBroker
        broker = _construct(PaperBroker, bcfg, log)

    bot = Bot(bcfg, None, broker, strategy, risk, NullNotifier(), log, persist_enabled=False)
    exec_tf = bcfg.strategy.exec_timeframe
    exec_ms = timeframe_ms(exec_tf)
    htf_tfs = list(bcfg.strategy.htf_timeframes)
    htf_ms = {tf: timeframe_ms(tf) for tf in htf_tfs}
    lookback, htf_lookback = bot.exec_window, bot.htf_window

    symbols = [m.symbol for m in bcfg.markets if exec_tf in (candles_by_tf.get(m.symbol) or {})]
    exec_data = {s: candles_by_tf[s][exec_tf] for s in symbols}
    htf_data = {s: {tf: (candles_by_tf[s].get(tf) or []) for tf in htf_tfs} for s in symbols}
    index_of = {s: {c.ts: i for i, c in enumerate(exec_data[s])} for s in symbols}
    htf_ptr = {s: {tf: 0 for tf in htf_tfs} for s in symbols}
    timeline = sorted({c.ts for s in symbols for c in exec_data[s]})

    equity_curve: list[tuple[int, float]] = []
    last_close: dict[str, float] = {}
    for ts in timeline:
        close_time = ts + exec_ms
        bot.check_day_rollover(close_time)
        for s in symbols:
            i = index_of[s].get(ts)
            if i is None:
                continue
            last_close[s] = exec_data[s][i].close
            htf_window: dict[str, list[Candle]] = {}
            ready = i + 1 >= lookback
            for tf in htf_tfs:
                series, k = htf_data[s][tf], htf_ptr[s][tf]
                while k < len(series) and series[k].ts + htf_ms[tf] <= close_time:
                    k += 1
                htf_ptr[s][tf] = k
                if k < HTF_WARMUP:
                    ready = False
                htf_window[tf] = series[max(0, k - htf_lookback):k]
            if not ready:
                continue
            window = exec_data[s][max(0, i + 1 - lookback):i + 1]
            bot.process_candle(s, window, htf_window, close_time)
        equity_curve.append((close_time, float(broker.equity())))

    if close_at_end and timeline:
        end_ts = timeline[-1] + exec_ms
        for pos in list(broker.positions()):
            broker.close(pos, pos.qty_open, last_close.get(pos.symbol, pos.entry), end_ts, "end")
        if equity_curve:
            equity_curve[-1] = (end_ts, float(broker.equity()))

    trades = list(broker.trades())
    final_equity = float(broker.equity())
    result = BacktestResult(start_equity=float(start_equity), final_equity=final_equity, trades=trades,
                            equity_curve=equity_curve, name=cfg.name, exec_timeframe=exec_tf, symbols=symbols)
    result.metrics = compute_metrics(float(start_equity), final_equity, trades, equity_curve, bcfg.exchange.quote)
    return result
