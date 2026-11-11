"""Position sizing, entry gating (limits, daily loss cap, loss-streak pause) and trade management."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from .config import MarketCfg, RiskCfg
from .data import timeframe_ms
from .models import Candle, Position, Side, Signal, TradeRecord

log = logging.getLogger("ewbot.risk")

_EPS = 1e-12


def utc_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class RiskManager:
    def __init__(self, cfg: RiskCfg) -> None:
        self.cfg = cfg
        self.day_start_equity: float | None = None
        self.day_start_ts: int | None = None

    # ------------------------------------------------------------------ sizing
    def position_size(self, equity: float, signal: Signal, market: MarketCfg,
                      min_notional: float) -> float:
        """Base qty so that a stop-out loses ~risk_pct of equity *including* round-trip fees.

        risk_amount = equity * risk_pct/100 * weight
        loss/unit   = |entry - stop| + fee_rate * (entry + stop)     (entry fee + exit fee at stop)
        qty         = risk_amount / loss_per_unit ; 0 if qty*entry < min_notional.
        """
        if equity <= 0 or signal.entry <= 0:
            return 0.0
        risk_per_unit = signal.risk_per_unit
        if risk_per_unit <= 0:
            return 0.0
        if self.cfg.min_stop_to_cost > 0:
            round_trip_pct = 2.0 * (self.cfg.fee_pct + self.cfg.slippage_pct)
            stop_pct = risk_per_unit / signal.entry * 100.0
            if stop_pct < self.cfg.min_stop_to_cost * round_trip_pct:
                log.info("%s: stop %.3f%% too tight vs costs %.3f%% (need %.1fx)", signal.symbol,
                         stop_pct, round_trip_pct, self.cfg.min_stop_to_cost)
                return 0.0
        weight = market.weight if market is not None else 1.0
        risk_amount = equity * self.cfg.risk_pct / 100.0 * weight
        if risk_amount <= 0:
            return 0.0
        fee_rate = self.cfg.fee_pct / 100.0
        loss_per_unit = risk_per_unit + fee_rate * (signal.entry + abs(signal.stop))
        qty = risk_amount / loss_per_unit
        if qty * signal.entry < max(min_notional, 0.0):
            return 0.0
        return qty

    # ------------------------------------------------------------------ gating
    def set_day_start(self, equity: float | None, ts: int) -> None:
        """Reset the daily loss-cap baseline. Unknown / non-positive equity is ignored (a 0 baseline
        would silently disable the daily loss cap); the previous baseline stays in force."""
        try:
            value = float(equity) if equity is not None else float("nan")
        except (TypeError, ValueError):
            value = float("nan")
        if not math.isfinite(value) or value <= 0:
            log.warning("set_day_start ignored: equity %r is unknown or <= 0", equity)
            return
        self.day_start_equity = value
        self.day_start_ts = int(ts)

    def day_pnl_pct(self, equity: float) -> float:
        if not self.day_start_equity:
            return 0.0
        return (equity - self.day_start_equity) / self.day_start_equity * 100.0

    def loss_streak(self, trades: list[TradeRecord]) -> tuple[int, int | None]:
        """(number of consecutive losing trades at the end, closed_ts of the latest one)."""
        streak, last_ts = 0, None
        for t in sorted(trades, key=lambda t: t.closed_ts, reverse=True):
            if t.pnl < 0:
                streak += 1
                if last_ts is None:
                    last_ts = t.closed_ts
            else:
                break
        return streak, last_ts

    def can_open(self, now_ts: int, equity: float, open_positions: list[Position],
                 trades: list[TradeRecord], symbol: str) -> tuple[bool, str]:
        cfg = self.cfg
        # Fallback day rollover if the caller forgot (or on first call).
        if self.day_start_ts is None or utc_day(self.day_start_ts) != utc_day(now_ts):
            self.set_day_start(equity, now_ts)

        open_now = [p for p in open_positions if p.qty_open > _EPS]
        if len(open_now) >= cfg.max_positions:
            return False, f"max positions reached ({len(open_now)}/{cfg.max_positions})"
        same = sum(1 for p in open_now if p.symbol == symbol)
        if same >= cfg.max_positions_per_symbol:
            return False, f"max positions for {symbol} reached ({same}/{cfg.max_positions_per_symbol})"

        if cfg.daily_loss_cap_pct > 0 and self.day_start_equity:
            dd = -self.day_pnl_pct(equity)
            if dd >= cfg.daily_loss_cap_pct:
                return False, (f"daily loss cap hit ({dd:.1f}% >= {cfg.daily_loss_cap_pct:.1f}%), "
                               f"halted until next UTC day")

        if cfg.max_consecutive_losses > 0:
            streak, last_ts = self.loss_streak(trades)
            if streak >= cfg.max_consecutive_losses and last_ts is not None:
                until = last_ts + cfg.pause_minutes_after_losses * 60_000
                if now_ts < until:
                    mins = (until - now_ts) / 60_000
                    return False, f"{streak} losses in a row, paused for {mins:.0f} more min"
        return True, "ok"

    # -------------------------------------------------------------- management
    def manage(self, position: Position, candle: Candle, atr: float) -> list[tuple[str, float]]:
        """Management actions for an open position on a just-closed candle.

        ("tp1", qty)        partial take profit at tp1 (only if not done yet)
        ("stop", new_stop)  move stop (break-even after TP1, ATR trailing)
        ("close", qty)      close the remaining qty (time stop)
        Does not mutate the position. Brokers already simulate/execute stop/tp hits in on_candle,
        so normally only BE/trailing/time-stop actions are produced here.
        """
        cfg = self.cfg
        actions: list[tuple[str, float]] = []
        if position.qty_open <= _EPS:
            return actions
        sign = position.side.sign
        long = position.side is Side.LONG

        def better(new: float, old: float) -> bool:
            return (new - old) * sign > _EPS

        tp1_done = position.tp1_done
        stop = position.stop
        if not tp1_done and cfg.tp1_fraction > 0:
            touched = candle.high >= position.tp1 if long else candle.low <= position.tp1
            stop_touched = candle.low <= stop if long else candle.high >= stop
            if touched and not stop_touched:
                actions.append(("tp1", position.qty * cfg.tp1_fraction))
                tp1_done = True

        if tp1_done and cfg.move_to_be_after_tp1 and not position.be_moved and better(position.entry, stop):
            actions.append(("stop", position.entry))
            stop = position.entry

        if tp1_done and cfg.trail_after_tp1_atr > 0 and atr > 0:
            trail = candle.close - sign * cfg.trail_after_tp1_atr * atr
            if better(trail, stop) and (trail < candle.close if long else trail > candle.close):
                actions.append(("stop", trail))
                stop = trail

        if cfg.max_hold_bars > 0:
            try:
                tf = timeframe_ms(position.timeframe)
            except ValueError:
                tf = 0
            if tf > 0:
                bars = (candle.ts - position.opened_ts) // tf
                if bars >= cfg.max_hold_bars:
                    actions.append(("close", position.qty_open))
        return actions
