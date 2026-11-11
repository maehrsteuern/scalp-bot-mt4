"""Orchestration: the live bot loop and the per-candle decision path shared with the backtester.

`Bot.process_candle` is the single decision path. Live (`Bot.step`) and backtest (`ewbot.backtest`)
both call it, so a backtest exercises exactly the code that trades live.

Module A/B classes are only imported lazily (inside functions) so this module can be imported and
unit-tested with stub collaborators.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import logging
import math
import os
import signal as _signal
import tempfile
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from .config import BotCfg, MarketCfg
from .models import Candle, Fill, Position, Side, Signal, TradeRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .broker import Broker
    from .data import MarketData
    from .notify import Telegram
    from .risk import RiskManager
    from .strategy import ElliottStrategy


# --------------------------------------------------------------------------------------------- helpers

HTF_WARMUP = 60   # minimum closed HTF candles before the backtester makes decisions

_TF_UNITS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}


def timeframe_ms(timeframe: str) -> int:
    """'15m' -> 900000. Uses MarketData.timeframe_ms when available, else a local parser."""
    try:
        from .data import MarketData  # noqa: WPS433 (lazy on purpose)

        return int(MarketData.timeframe_ms(timeframe))
    except Exception:  # module B missing or unknown format -> local parser
        unit = timeframe[-1]
        if unit not in _TF_UNITS:
            raise ValueError(f"unsupported timeframe {timeframe!r}")
        return int(timeframe[:-1]) * _TF_UNITS[unit]


def last_atr(candles: list[Candle], period: int) -> float:
    """Latest ATR value. Prefers swings.atr (module A); falls back to a local Wilder ATR."""
    if not candles:
        return 0.0
    try:
        from .swings import atr  # noqa: WPS433

        values = atr(candles, period)
        if values:
            val = float(values[-1])
            if math.isfinite(val):
                return val
    except Exception:
        pass
    value = candles[0].high - candles[0].low
    prev_close = candles[0].close
    for i, c in enumerate(candles[1:], start=1):
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        n = min(i + 1, period)
        value = value + (tr - value) / n
        prev_close = c.close
    return float(value)


def utc_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def safe_symbol(symbol: str) -> str:
    """'BTC/USD:USD' -> 'BTC-USD-USD' (file-name safe)."""
    return symbol.replace("/", "-").replace(":", "-")


def _enum_value(obj: Any) -> Any:
    return obj.value if hasattr(obj, "value") else obj


# ---- state persistence: use ewbot.state (module B); local fallback keeps the bot testable alone ----

def _fallback_save_state(path: str | os.PathLike[str], data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=_enum_value)
    os.replace(tmp, p)


def _fallback_load_state(path: str | os.PathLike[str]) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8") or "{}")


def _fallback_position_to_dict(pos: Position) -> dict:
    d = dataclasses.asdict(pos)
    d["side"] = pos.side.value
    d["setup"] = pos.setup.value
    return d


def _fallback_position_from_dict(d: dict) -> Position:
    from .models import SetupType

    d = dict(d)
    d["side"] = Side(d["side"])
    d["setup"] = SetupType(d["setup"])
    return Position(**d)


def _fallback_trade_to_dict(tr: TradeRecord) -> dict:
    return {"position": _fallback_position_to_dict(tr.position), "closed_ts": tr.closed_ts,
            "exit_price": tr.exit_price, "pnl": tr.pnl, "pnl_pct": tr.pnl_pct, "reason": tr.reason}


def _fallback_trade_from_dict(d: dict) -> TradeRecord:
    d = dict(d)
    d["position"] = _fallback_position_from_dict(d["position"])
    return TradeRecord(**d)


def state_api() -> dict[str, Callable]:
    """Return the state helpers from ewbot.state, or local equivalents if that module is absent."""
    try:
        from . import state as st  # noqa: WPS433

        return {
            "save_state": st.save_state, "load_state": st.load_state,
            "position_to_dict": st.position_to_dict, "position_from_dict": st.position_from_dict,
            "trade_to_dict": st.trade_to_dict, "trade_from_dict": st.trade_from_dict,
        }
    except Exception:
        return {
            "save_state": _fallback_save_state, "load_state": _fallback_load_state,
            "position_to_dict": _fallback_position_to_dict, "position_from_dict": _fallback_position_from_dict,
            "trade_to_dict": _fallback_trade_to_dict, "trade_from_dict": _fallback_trade_from_dict,
        }


class NullNotifier:
    """Notifier that does nothing (backtests, or when Telegram is unavailable)."""

    def send(self, text: str) -> bool:  # noqa: D401
        return False

    def poll_commands(self) -> list[tuple[str, str]]:
        return []


# ---------------------------------------------------------------------------------------- logging

def setup_logging(cfg: BotCfg, to_file: bool = True) -> logging.Logger:
    """Logger `ewbot.<name>` writing to stdout and (optionally) a 5 MB x 5 rotating file."""
    logger = logging.getLogger(f"ewbot.{cfg.name}")
    logger.setLevel(getattr(logging, str(cfg.log_level).upper(), logging.INFO))
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    if to_file and cfg.log_file:
        Path(cfg.log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(cfg.log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


# -------------------------------------------------------------------------------------------- Bot

class Bot:
    """Live orchestration around one config (= one instance, e.g. ewbot-15m)."""

    def __init__(self, cfg: BotCfg, data: Optional["MarketData"], broker: "Broker",
                 strategy: "ElliottStrategy", risk: "RiskManager", notifier: Optional["Telegram"],
                 logger: Optional[logging.Logger] = None, *, persist_enabled: bool = True) -> None:
        self.cfg = cfg
        self.data = data
        self.broker = broker
        self.strategy = strategy
        self.risk = risk
        self.notifier = notifier if notifier is not None else NullNotifier()
        self.log = logger or logging.getLogger(f"ewbot.{cfg.name}")
        self.persist_enabled = persist_enabled
        self.exec_tf = cfg.strategy.exec_timeframe
        self.exec_tf_ms = timeframe_ms(self.exec_tf)
        self.markets: dict[str, MarketCfg] = {m.symbol: m for m in cfg.markets}
        # candles handed to the strategy (exec: swing lookback; HTF: enough for the slow EMA as well)
        self.exec_window = max(int(cfg.swing.lookback), 1)
        self.htf_window = max(self.exec_window, HTF_WARMUP, int(cfg.strategy.ema_slow) + 50)

        self.last_seen: dict[str, int] = {}
        self.paused: bool = False
        self.day_start: dict[str, Any] = {}          # {"date", "equity", "ts"}
        self.last_summary_date: str = ""
        self.trades_count: int = 0
        self.last_signal: dict[str, dict] = {}       # symbol -> short info on the last signal
        self._trades_seen: int = len(self._safe_trades())
        self._stop_requested = False
        self._state = state_api()

    # ---------------------------------------------------------------- small utilities
    def _safe_trades(self) -> list[TradeRecord]:
        try:
            return list(self.broker.trades())
        except Exception:
            return []

    def _equity_known(self) -> Optional[float]:
        """Broker equity, or None while it is unknown (no balance fetched yet / not a finite number)."""
        value = self.broker.equity()
        if value is None:
            return None
        value = float(value)
        return value if math.isfinite(value) else None

    def _equity(self) -> float:
        """Equity for display / reporting; NaN while unknown."""
        value = self._equity_known()
        return float("nan") if value is None else value

    def _free_cash(self) -> Optional[float]:
        """Cash available for a new spot entry (PaperBroker.free_cash, else broker.cash())."""
        for name in ("free_cash", "cash"):
            fn = getattr(self.broker, name, None)
            if callable(fn):
                try:
                    value = fn()
                    return None if value is None else float(value)
                except Exception as exc:
                    self.log.warning("broker.%s failed: %s", name, exc)
                    return None
        return None

    def _positions(self, symbol: str | None = None) -> list[Position]:
        pos = list(self.broker.positions())
        return [p for p in pos if symbol is None or p.symbol == symbol]

    def notify(self, text: str) -> None:
        try:
            self.notifier.send(text)
        except Exception as exc:  # notifier must never break trading
            self.log.warning("notify failed: %s", exc)

    def _fmt(self, method: str, fallback: str, *args: Any) -> str:
        fn = getattr(self.notifier, method, None)
        if callable(fn):
            try:
                text = fn(*args)
                if text:
                    return str(text)
            except Exception as exc:
                self.log.debug("formatter %s failed: %s", method, exc)
        return fallback

    def _min_notional(self, market: MarketCfg) -> float:
        value = float(market.min_notional)
        fn = getattr(self.broker, "min_notional", None)
        if callable(fn):
            try:
                value = max(value, float(fn(market.symbol) or 0.0))
            except Exception:
                pass
        return value

    # ---------------------------------------------------------------- day handling
    def check_day_rollover(self, now_ms: int) -> None:
        """At the first call of a new UTC day: reset the risk day-start equity."""
        today = utc_date(now_ms)
        if self.day_start.get("date") == today:
            return
        equity = self._equity_known()
        if equity is None or equity <= 0:
            # never take an unknown/zero equity as the daily baseline (it would disable the loss cap);
            # retried on the next call, entries are skipped meanwhile
            self.log.warning("day rollover to %s postponed: equity unknown (%s)", today, equity)
            return
        prev = dict(self.day_start)
        self.day_start = {"date": today, "equity": equity, "ts": now_ms}
        self.risk.set_day_start(equity, now_ms)
        if prev:
            self.log.info("day rollover %s -> %s, equity %.2f", prev.get("date"), today, equity)

    def day_pnl(self) -> float:
        start = float(self.day_start.get("equity") or 0.0)
        return self._equity() - start if start else 0.0

    def trades_today(self, now_ms: int) -> list[TradeRecord]:
        today = utc_date(now_ms)
        return [t for t in self._safe_trades() if utc_date(t.closed_ts) == today]

    def maybe_daily_summary(self, now_ms: int) -> bool:
        """Send the daily summary once per UTC day after telegram.daily_summary_utc."""
        try:
            hh, mm = (int(x) for x in str(self.cfg.telegram.daily_summary_utc).split(":"))
        except ValueError:
            hh, mm = 21, 0
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if self.last_summary_date == today or (now.hour, now.minute) < (hh, mm):
            return False
        trades = self.trades_today(now_ms)
        pnl = self.day_pnl()
        fallback = (f"<b>{self.cfg.name} Tagesbilanz {today}</b>\n"
                    f"Equity: {self._equity():.2f} {self.cfg.exchange.quote}\n"
                    f"Tages-PnL: {pnl:+.2f}\nTrades heute: {len(trades)}\n"
                    f"Offene Positionen: {len(self._positions())}")
        self.notify(self._fmt("format_summary", fallback, self._equity(), pnl, trades))
        self.last_summary_date = today
        return True

    # ---------------------------------------------------------------- the shared decision path
    def process_candle(self, symbol: str, exec_candles: list[Candle],
                       htf_candles_by_tf: dict[str, list[Candle]], now_ms: int) -> Optional[Position]:
        """Handle one newly closed exec-timeframe candle for `symbol`.

        1. let the broker simulate/check stop & take-profit inside the candle
        2. risk management actions on open positions (BE, trailing, time stop)
        3. HTF context -> strategy signal -> filters -> sizing -> entry
        Returns the opened Position or None. Used by live `step()` AND by the backtester.
        """
        if not exec_candles:
            return None
        market = self.markets.get(symbol) or MarketCfg(symbol)
        candle = exec_candles[-1]

        # 1. stops / targets inside the candle
        records = self.broker.on_candle(symbol, candle) or []
        for rec in records:
            self.log.info("%s closed by broker: %s pnl=%.4f", symbol, rec.reason, rec.pnl)
        if self._report_partial_fills(symbol) or records:
            self.persist()                     # exits / TP1 partials are on disk immediately

        # 2. position management
        atr_now = last_atr(exec_candles[-(self.cfg.swing.atr_period * 5):], self.cfg.swing.atr_period)
        for pos in self._positions(symbol):
            try:
                actions = self.risk.manage(pos, candle, atr_now) or []
            except Exception as exc:
                self.log.warning("risk.manage failed for %s: %s", pos.id, exc)
                continue
            for action, value in actions:
                if self._execute_action(pos, action, float(value), candle, now_ms):
                    self.persist()
        self._report_new_trades()

        # 3. new entries
        if self.paused:
            return None
        window = exec_candles[-self.exec_window:]
        htf_ctx = []
        for tf in self.cfg.strategy.htf_timeframes:
            htf_candles = (htf_candles_by_tf or {}).get(tf) or []
            if not htf_candles:
                continue
            htf_ctx.append(self.strategy.analyse_htf(tf, htf_candles[-self.htf_window:]))
        sig = self.strategy.evaluate(symbol, window, htf_ctx)
        if sig is None:
            return None
        self.last_signal[symbol] = {"ts": sig.ts, "side": sig.side.value, "setup": sig.setup.value,
                                    "score": round(sig.score, 3)}
        if sig.side is Side.SHORT and not market.allow_short:
            self.log.info("%s short signal ignored (allow_short=false)", symbol)
            return None
        return self._try_open(sig, market, now_ms, candle.ts)

    def _try_open(self, sig: Signal, market: MarketCfg, now_ms: int,
                  candle_ts: Optional[int] = None) -> Optional[Position]:
        equity = self._equity_known()
        if equity is None:
            self.log.warning("%s signal skipped: equity unknown (balance not available)", sig.symbol)
            return None
        ok, reason = self.risk.can_open(now_ms, equity, self._positions(), self._safe_trades(), sig.symbol)
        if not ok:
            self.log.info("%s %s %s signal blocked: %s", sig.symbol, sig.side.value, sig.setup.value, reason)
            return None
        qty = float(self.risk.position_size(equity, sig, market, self._min_notional(market)))
        if qty <= 0:
            self.log.info("%s signal skipped: size 0 (equity %.2f below exchange minimum?)", sig.symbol, equity)
            return None
        if ":" not in sig.symbol:              # spot: no leverage -> needs free cash for the order
            free = self._free_cash()
            min_notional = max(self._min_notional(market), 1e-9)
            if free is not None and free < min_notional:
                self.log.info("%s signal skipped: free cash %.4f below min notional %.4f", sig.symbol,
                              free, min_notional)
                return None
        self.log.info("SIGNAL %s %s %s entry=%.6g stop=%.6g tp1=%.6g tp2=%.6g score=%.2f qty=%.8g | %s",
                      sig.symbol, sig.side.value, sig.setup.value, sig.entry, sig.stop, sig.tp1, sig.tp2,
                      sig.score, qty, "; ".join(sig.reasons))
        if self.cfg.telegram.notify_signals:
            self.notify(self._fmt("format_signal", self._signal_text(sig), sig))
        # mark the candle as consumed BEFORE sending the order: a crash after the fill must not lead to
        # a second entry on the same candle after a restart
        if candle_ts is not None:
            self.last_seen[sig.symbol] = max(int(candle_ts), int(self.last_seen.get(sig.symbol, candle_ts)))
            self.persist()
        pos = self.broker.open(sig, qty, now_ms)
        fills = [f for f in self._pop_fills() if f.reason == "entry"]
        if pos is None:
            self.log.warning("%s entry order failed / rejected", sig.symbol)
            return None
        if candle_ts is not None:
            pos.tags["signal_ts"] = str(int(candle_ts))   # broker checks stops from the next candle on
        self.persist()
        # remember the initial risk so R-multiples stay correct after BE / trailing moves
        try:
            pos.tags.setdefault("stop0", f"{sig.stop:.10g}")
            pos.tags.setdefault("risk_quote", f"{abs(pos.entry - sig.stop) * pos.qty:.10g}")
            pos.tags.setdefault("equity_at_open", f"{equity:.10g}")
            pos.tags.setdefault("score", f"{sig.score:.3f}")
        except Exception:
            pass
        self.log.info("OPENED %s %s qty=%.8g @ %.6g (id %s)", pos.symbol, pos.side.value, pos.qty, pos.entry, pos.id)
        if self.cfg.telegram.notify_fills:
            entry_fill = fills[-1] if fills else Fill(ts=now_ms, symbol=pos.symbol, side=pos.side, qty=pos.qty,
                                                      price=pos.entry, fee=pos.fees, reason="entry")
            self.notify(self._fmt("format_fill", self._open_text(pos), entry_fill, pos))
        return pos

    def _execute_action(self, pos: Position, action: str, value: float, candle: Candle, now_ms: int) -> bool:
        """Execute one management action; True if position state changed (caller persists)."""
        if pos.qty_open <= 0:
            return False
        if action == "stop":
            if value > 0 and value != pos.stop:
                self.broker.update_stop(pos, value)
                if abs(value - pos.entry) <= 1e-12 * max(1.0, abs(pos.entry)):
                    pos.be_moved = True
                self.log.info("%s stop -> %.6g", pos.id, value)
                return True
            return False
        if action == "tp1" and pos.tp1_done:
            return False  # broker already took the partial inside the candle
        reason = {"tp1": "tp1", "close": "time"}.get(action, action)
        qty = min(value, pos.qty_open) if value > 0 else pos.qty_open
        fill = self.broker.close(pos, qty, candle.close, now_ms, reason)
        self._pop_fills()  # reported right here / via the trade record
        if fill is not None:
            self.log.info("%s %s %.8g @ %.6g", pos.id, reason, fill.qty, fill.price)
            if action == "tp1":
                pos.tp1_done = True
            if self.cfg.telegram.notify_fills and pos.qty_open > 0:
                self.notify(self._fmt("format_fill", f"{reason}: {pos.symbol} {fill.qty:.8g} @ {fill.price:.6g}",
                                      fill, pos))
            return True
        return False

    def _pop_fills(self) -> list[Fill]:
        fn = getattr(self.broker, "pop_fills", None)
        if not callable(fn):
            return []
        try:
            return list(fn() or [])
        except Exception:
            return []

    def _report_partial_fills(self, symbol: str) -> int:
        """Notify partial exits the broker made inside the candle (TP1); full exits go via trades.
        Returns the number of fills drained."""
        open_pos = {p.symbol: p for p in self._positions(symbol)}
        fills = self._pop_fills()
        for fill in fills:
            pos = open_pos.get(fill.symbol)
            if fill.reason == "entry" or pos is None or pos.qty_open <= 0:
                continue
            self.log.info("%s partial %s %.8g @ %.6g", pos.id, fill.reason, fill.qty, fill.price)
            if self.cfg.telegram.notify_fills:
                self.notify(self._fmt("format_fill", f"{fill.reason}: {fill.symbol} {fill.qty:.8g} @ {fill.price:.6g}",
                                      fill, pos))
        return len(fills)

    def _report_new_trades(self) -> None:
        trades = self._safe_trades()
        new = trades[self._trades_seen:]
        self._trades_seen = len(trades)
        for tr in new:
            self.trades_count += 1
            p = tr.position
            self.log.info("CLOSED %s %s %s exit=%.6g pnl=%+.4f (%s)", p.symbol, p.side.value, p.setup.value,
                          tr.exit_price, tr.pnl, tr.reason)
            if self.cfg.telegram.notify_fills:
                fallback = (f"{'GEWINN' if tr.pnl >= 0 else 'VERLUST'}: <b>{p.symbol}</b> {p.side.value} "
                            f"{p.setup.value} geschlossen ({tr.reason})\nExit {tr.exit_price:.6g} | "
                            f"PnL {tr.pnl:+.2f} {self.cfg.exchange.quote}")
                text = self._fmt("format_trade", fallback, tr)
                self.notify(f"{text}\nEquity {self._equity():.2f} {self.cfg.exchange.quote}")

    def _signal_text(self, s: Signal) -> str:
        return (f"<b>Signal {s.symbol} {s.side.value.upper()}</b> ({s.setup.value}, {s.timeframe})\n"
                f"Entry {s.entry:.6g} | SL {s.stop:.6g} | TP1 {s.tp1:.6g} | TP2 {s.tp2:.6g}\n"
                f"Score {s.score:.2f} | RR1 {s.rr1:.2f}\n" + "; ".join(s.reasons))

    def _open_text(self, p: Position) -> str:
        return (f"<b>Eröffnet {p.symbol} {p.side.value.upper()}</b> {p.qty:.8g} @ {p.entry:.6g}\n"
                f"SL {p.stop:.6g} | TP1 {p.tp1:.6g} | TP2 {p.tp2:.6g}")

    # ---------------------------------------------------------------- live loop
    def step(self, now_ms: int) -> None:
        """One live iteration: commands, day rollover, new closed candles per market, summary, persist."""
        self.handle_commands(now_ms)
        self.check_day_rollover(now_ms)
        changed = False
        for market in self.cfg.markets:
            try:
                changed |= self._step_symbol(market.symbol, now_ms)
            except Exception as exc:
                self.log.exception("step %s failed: %s", market.symbol, exc)
        if self.maybe_daily_summary(now_ms):
            changed = True
        if changed:
            self.persist()

    def _step_symbol(self, symbol: str, now_ms: int) -> bool:
        assert self.data is not None, "live step needs MarketData"
        candles = self.data.fetch(symbol, self.exec_tf)
        if not candles:
            return False
        newest = candles[-1].ts
        seen = self.last_seen.get(symbol)
        if seen is not None and newest <= seen:
            return False
        # candles missed while offline / between polls: let the broker check stops on them first
        if seen is not None:
            for c in candles[:-1]:
                if c.ts > seen:
                    if self.broker.on_candle(symbol, c):
                        self.persist()
        htf = {tf: self.data.fetch(symbol, tf) for tf in self.cfg.strategy.htf_timeframes}
        self.process_candle(symbol, candles, htf, now_ms)
        self.last_seen[symbol] = newest
        return True

    def run_forever(self) -> None:
        """Main loop: market step every poll_seconds, Telegram commands every telegram.poll_seconds."""
        self._install_signal_handlers()
        self.log.info("%s started (mode=%s, exec=%s, htf=%s, markets=%s)", self.cfg.name,
                      self.cfg.exchange.mode, self.exec_tf, ",".join(self.cfg.strategy.htf_timeframes),
                      ",".join(self.markets))
        self.notify(f"<b>{self.cfg.name}</b> gestartet ({self.cfg.exchange.mode}), "
                    f"Equity {self._safe_equity():.2f} {self.cfg.exchange.quote}")
        tick = max(1, min(int(self.cfg.poll_seconds),
                          int(self.cfg.telegram.poll_seconds) if self.cfg.telegram.enabled else 10**6))
        next_step = 0.0
        while not self._stop_requested:
            now = time.time()
            try:
                if now >= next_step:
                    self.step(int(now * 1000))
                    next_step = now + max(1, int(self.cfg.poll_seconds))
                else:
                    if self.handle_commands(int(now * 1000)):
                        self.persist()
            except Exception as exc:  # never die on a single bad iteration
                self.log.exception("loop error: %s", exc)
            slept = 0.0
            while slept < tick and not self._stop_requested:
                time.sleep(0.5)
                slept += 0.5
        self.log.info("stopping: persisting state")
        self.persist()
        self.notify(f"<b>{self.cfg.name}</b> gestoppt")

    def _safe_equity(self) -> float:
        try:
            return self._equity()
        except Exception:
            return float("nan")

    def _state_equity(self) -> Optional[float]:
        try:
            return self._equity_known()
        except Exception:
            return None

    def stop(self, *_: Any) -> None:
        self._stop_requested = True

    def _install_signal_handlers(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, self.stop)
            except (ValueError, OSError):  # not in main thread
                pass

    # ---------------------------------------------------------------- telegram commands
    def handle_commands(self, now_ms: int) -> bool:
        """Poll and execute Telegram commands. Returns True if state changed."""
        try:
            commands = self.notifier.poll_commands() or []
        except Exception as exc:
            self.log.warning("poll_commands failed: %s", exc)
            return False
        changed = False
        for cmd, args in commands:
            try:
                changed |= self.handle_command(cmd, args, now_ms)
            except Exception as exc:
                self.log.exception("command %s failed: %s", cmd, exc)
                self.notify(f"Befehl {cmd} fehlgeschlagen: {exc}")
        return changed

    def handle_command(self, cmd: str, args: str, now_ms: int) -> bool:
        name = cmd.strip().lstrip("/").split("@")[0].lower()
        q = self.cfg.exchange.quote
        if name == "status":
            self.notify(self.status_text(now_ms))
        elif name == "pause":
            self.paused = True
            self.notify(f"{self.cfg.name}: pausiert – keine neuen Einstiege, offene Positionen werden weiter verwaltet.")
            return True
        elif name == "resume":
            self.paused = False
            self.notify(f"{self.cfg.name}: läuft wieder.")
            return True
        elif name == "close_all":
            n = self.close_all(now_ms, reason="manual")
            self.notify(f"{self.cfg.name}: {n} Position(en) geschlossen. Equity {self._equity():.2f} {q}")
            return True
        elif name == "equity":
            self.notify(f"{self.cfg.name}: Equity {self._equity():.2f} {q} | Tages-PnL {self.day_pnl():+.2f}")
        elif name == "positions":
            self.notify(self.positions_text())
        elif name in ("help", "start"):
            self.notify("Befehle: /status /pause /resume /close_all /equity /positions")
        else:
            self.notify(f"Unbekannter Befehl: {cmd}")
        return False

    def close_all(self, now_ms: int, reason: str = "manual") -> int:
        n = 0
        for pos in self._positions():
            try:
                price = float(self.broker.last_price(pos.symbol))
            except Exception:
                price = pos.entry
            if self.broker.close(pos, pos.qty_open, price, now_ms, reason) is not None:
                n += 1
                self.persist()
        self._report_new_trades()
        return n

    def status_text(self, now_ms: int) -> str:
        q = self.cfg.exchange.quote
        lines = [f"<b>{self.cfg.name}</b> ({self.cfg.exchange.mode}, {self.exec_tf})",
                 f"Status: {'PAUSIERT' if self.paused else 'aktiv'}",
                 f"Equity: {self._equity():.2f} {q} | Tages-PnL: {self.day_pnl():+.2f}",
                 f"Offene Positionen: {len(self._positions())} | Trades gesamt: {len(self._safe_trades())}"]
        for sym, ts in sorted(self.last_seen.items()):
            lines.append(f"{sym}: letzte Kerze {iso(ts)} UTC")
        return "\n".join(lines)

    def positions_text(self) -> str:
        pos = self._positions()
        if not pos:
            return f"{self.cfg.name}: keine offenen Positionen."
        out = [f"<b>{self.cfg.name} – offene Positionen</b>"]
        for p in pos:
            try:
                last = float(self.broker.last_price(p.symbol))
                upnl = (last - p.entry) * p.qty_open * p.side.sign
                extra = f" | Kurs {last:.6g} | uPnL {upnl:+.2f}"
            except Exception:
                extra = ""
            out.append(f"{p.symbol} {p.side.value} {p.setup.value}: {p.qty_open:.8g} @ {p.entry:.6g} "
                       f"SL {p.stop:.6g} TP1 {p.tp1:.6g}{' (erreicht)' if p.tp1_done else ''} TP2 {p.tp2:.6g}{extra}")
        return "\n".join(out)

    # ---------------------------------------------------------------- persistence
    def state_dict(self) -> dict:
        to_pos = self._state["position_to_dict"]
        to_tr = self._state["trade_to_dict"]
        data: dict[str, Any] = {
            "name": self.cfg.name,
            "mode": self.cfg.exchange.mode,
            "updated_ts": int(time.time() * 1000),
            "last_seen": dict(self.last_seen),
            "paused": self.paused,
            "day_start": dict(self.day_start),
            "last_summary_date": self.last_summary_date,
            "trades_count": self.trades_count,
            "equity": self._state_equity(),
            "positions": [to_pos(p) for p in self._positions()],
            "trades": [to_tr(t) for t in self._safe_trades()[-200:]],
            "last_signal": dict(self.last_signal),
        }
        for attr in ("snapshot", "to_state", "to_dict"):
            fn = getattr(self.broker, attr, None)
            if callable(fn):
                try:
                    data["broker"] = fn()
                except Exception as exc:
                    self.log.warning("broker.%s failed: %s", attr, exc)
                break
        return data

    def persist(self) -> None:
        if not self.persist_enabled:
            return
        try:
            self._state["save_state"](self.cfg.state_file, self.state_dict())
        except Exception as exc:
            self.log.exception("persist failed: %s", exc)

    def restore(self) -> None:
        """Load state file (if any) and push positions / paper balances back into the broker."""
        data = self._state["load_state"](self.cfg.state_file) or {}
        if not data:
            self.log.info("no state file at %s – fresh start", self.cfg.state_file)
            return
        self.last_seen = {k: int(v) for k, v in (data.get("last_seen") or {}).items()}
        self.paused = bool(data.get("paused", False))
        self.last_summary_date = str(data.get("last_summary_date") or "")
        self.trades_count = int(data.get("trades_count") or 0)
        self.last_signal = dict(data.get("last_signal") or {})
        positions = [self._state["position_from_dict"](d) for d in data.get("positions") or []]
        trades = [self._state["trade_from_dict"](d) for d in data.get("trades") or []]
        restored = False
        if data.get("broker") is not None:
            for attr in ("restore_snapshot", "from_state", "from_dict"):
                fn = getattr(self.broker, attr, None)
                if callable(fn):
                    try:
                        fn(data["broker"])
                        restored = True
                    except Exception as exc:
                        self.log.warning("broker.%s failed: %s", attr, exc)
                    break
        if not restored:
            for attr in ("load_positions", "restore_positions", "restore"):
                fn = getattr(self.broker, attr, None)
                if callable(fn):
                    try:
                        try:
                            fn(positions, trades)
                        except TypeError:
                            fn(positions)
                        restored = True
                    except Exception as exc:
                        self.log.warning("broker.%s failed: %s", attr, exc)
                    break
        if positions and not restored:
            self.log.warning("broker cannot restore %d persisted position(s); they are NOT managed", len(positions))
        self._trades_seen = len(self._safe_trades())
        day = data.get("day_start") or {}
        if day.get("date") and day.get("equity") is not None:
            self.day_start = {"date": day["date"], "equity": float(day["equity"]), "ts": int(day.get("ts") or 0)}
            self.risk.set_day_start(float(day["equity"]), int(day.get("ts") or 0))
        self.log.info("state restored: %d position(s), paused=%s, last_seen=%s",
                      len(positions), self.paused, self.last_seen)


# ------------------------------------------------------------------------------------- factory

def make_broker(cfg: BotCfg, logger: Optional[logging.Logger] = None) -> "Broker":
    """PaperBroker for mode=paper, CcxtBroker for mode=live (module B)."""
    from .broker import CcxtBroker, PaperBroker

    if cfg.exchange.mode == "paper":
        return PaperBroker(cfg)
    return CcxtBroker(cfg)


def build_bot(cfg: BotCfg, logger: Optional[logging.Logger] = None) -> Bot:
    """Wire the real collaborators (modules A and B) for a live/paper run."""
    from .data import MarketData
    from .notify import Telegram
    from .risk import RiskManager
    from .strategy import ElliottStrategy

    logger = logger or setup_logging(cfg)
    data = MarketData(cfg)
    broker = make_broker(cfg, logger)
    return Bot(cfg, data, broker, ElliottStrategy(cfg), RiskManager(cfg.risk), Telegram(cfg.telegram), logger)


def paper_copy(cfg: BotCfg, start_equity: float) -> BotCfg:
    """Deep copy of cfg forced to paper mode with the given start equity and Telegram off."""
    c = copy.deepcopy(cfg)
    c.exchange.mode = "paper"
    c.exchange.paper_start_equity = float(start_equity)
    c.telegram.enabled = False
    return c
