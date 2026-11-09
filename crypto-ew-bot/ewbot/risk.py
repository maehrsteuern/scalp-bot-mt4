"""Risk and position sizing. Pure functions, no I/O. Uses Decimal for tick rounding."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR


@dataclass
class RiskConfig:
    risk_pct: float = 0.75
    max_exposure_pct: float = 90.0
    daily_loss_cap_pct: float = 2.0
    max_capital_usd: float = 1000.0
    min_notional_usd: float = 10.0


@dataclass
class SizeResult:
    ok: bool
    qty: float = 0.0
    notional: float = 0.0
    risk_usd: float = 0.0
    reason: str = ""


def floor_to_tick(x: float, tick: float) -> float:
    """Round x DOWN to a multiple of tick (exact decimal arithmetic)."""
    if tick is None or tick <= 0:
        return x
    d = (Decimal(str(x)) / Decimal(str(tick))).to_integral_value(rounding=ROUND_FLOOR)
    return float(d * Decimal(str(tick)))


def sizing_equity(equity: float, cfg: RiskConfig) -> float:
    """Equity the bot is allowed to size from: never more than max_capital_usd."""
    return max(0.0, min(float(equity), float(cfg.max_capital_usd)))


def position_size(equity: float, entry: float, stop: float, exposure_used: float, cfg: RiskConfig,
                  qty_tick: float = 0.0, min_qty: float = 0.0, min_notional: float = 0.0) -> SizeResult:
    """qty = (equity * risk%) / (entry - stop), then limited by max exposure, rounded down to qty_tick.

    exposure_used = USD value of all open positions + pending entries. Fees are NOT part of the risk
    formula (CONTRACT); real loss at the stop is therefore slightly higher than risk_pct.
    """
    if entry <= 0 or stop <= 0 or stop >= entry:
        return SizeResult(False, reason="ungueltige Preise (Stop muss unter dem Einstieg liegen)")
    eq = sizing_equity(equity, cfg)
    if eq <= 0:
        return SizeResult(False, reason="kein Kapital")
    risk_usd = eq * cfg.risk_pct / 100.0
    qty = risk_usd / (entry - stop)
    room = eq * cfg.max_exposure_pct / 100.0 - exposure_used
    if room <= 0:
        return SizeResult(False, reason="maximale Gesamt-Investition erreicht")
    capped = False
    if qty * entry > room:
        qty = room / entry
        capped = True
    qty = floor_to_tick(qty, qty_tick)
    notional = qty * entry
    need = max(cfg.min_notional_usd, min_notional or 0.0)
    if qty <= 0 or qty < (min_qty or 0.0):
        return SizeResult(False, qty, notional, 0.0, "Menge unter Mindestmenge")
    if notional < need:
        return SizeResult(False, qty, notional, 0.0, f"Order unter Mindestwert ({notional:.2f} < {need:.2f} USD)")
    return SizeResult(True, qty, notional, qty * (entry - stop),
                      "Menge wegen Gesamt-Limit gekuerzt" if capped else "")


def daily_loss_hit(day_start_equity: float, realized_today: float, cfg: RiskConfig) -> bool:
    """True if today's realized loss reached the cap (no new entries until next UTC day)."""
    base = sizing_equity(day_start_equity, cfg)
    return realized_today < 0 and -realized_today >= base * cfg.daily_loss_cap_pct / 100.0 - 1e-9
