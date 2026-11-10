"""Brokers: PaperBroker (full simulation) and CcxtBroker (Crypto.com via ccxt).

Shared accounting (both brokers):
  * Position.entry is the actual fill price, Position.fees accumulates entry + exit fees,
    Position.realized_pnl = gross realised pnl - all fees paid so far (starts at -entry_fee).
  * TradeRecord is produced once a position is fully closed: pnl = realized_pnl (net of fees),
    pnl_pct = pnl / equity at open * 100, exit_price = qty-weighted average exit price,
    reason = reason of the final exit fill.
  * Fills (entries and exits, incl. TP1 partials) are queued; the caller drains them via pop_fills().
  * Tags: "equity_at_open", "initial_stop" (and "stop_order_id" for live exchange stops).
"""
from __future__ import annotations

import dataclasses
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import ccxt

from .config import BotCfg, MarketCfg, RiskCfg, env_secret
from .data import trust_proxy_env
from .models import Candle, Fill, Position, Side, Signal, TradeRecord
from .state import position_from_dict, position_to_dict, trade_from_dict, trade_to_dict

log = logging.getLogger("ewbot.broker")

_EPS = 1e-12


def is_perp(symbol: str) -> bool:
    return ":" in symbol


class Broker(ABC):
    def __init__(self, cfg: BotCfg) -> None:
        self.cfg = cfg
        self.risk: RiskCfg = cfg.risk
        self._positions: list[Position] = []
        self._trades: list[TradeRecord] = []
        self._pending_fills: list[Fill] = []
        self._prices: dict[str, float] = {}
        self._counter = 0

    # ------------------------------------------------------------- interface
    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def cash(self) -> float: ...

    @abstractmethod
    def open(self, signal: Signal, qty: float, ts: int) -> Position | None: ...

    @abstractmethod
    def close(self, position: Position, qty: float, price_hint: float, ts: int,
              reason: str) -> Fill | None: ...

    def positions(self) -> list[Position]:
        return list(self._positions)

    def trades(self) -> list[TradeRecord]:
        return list(self._trades)

    def pop_fills(self) -> list[Fill]:
        """Fills (entries, partial and full exits) since the last call."""
        fills, self._pending_fills = self._pending_fills, []
        return fills

    def last_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)

    def set_price(self, symbol: str, price: float) -> None:
        if price and price > 0:
            self._prices[symbol] = float(price)

    def update_stop(self, position: Position, new_stop: float) -> None:
        position.stop = float(new_stop)
        if (position.stop - position.entry) * position.side.sign >= -_EPS:
            position.be_moved = True

    def on_candle(self, symbol: str, candle: Candle) -> list[TradeRecord]:
        """Check every open position of `symbol` against the candle's range (stop first)."""
        before = len(self._trades)
        for pos in [p for p in self._positions if p.symbol == symbol]:
            try:
                self._process_position(pos, candle)
            except Exception:  # never let one position break the loop
                log.exception("on_candle failed for %s", pos.id)
        self.set_price(symbol, candle.close)
        return self._trades[before:]

    # ------------------------------------------------------------ persistence
    def snapshot(self) -> dict:
        return {
            "positions": [position_to_dict(p) for p in self._positions],
            "trades": [trade_to_dict(t) for t in self._trades],
            "prices": dict(self._prices),
            "counter": self._counter,
        }

    def restore_snapshot(self, data: dict) -> None:
        self._positions = [position_from_dict(d) for d in data.get("positions", [])]
        self._trades = [trade_from_dict(d) for d in data.get("trades", [])]
        self._prices = {str(k): float(v) for k, v in (data.get("prices") or {}).items()}
        self._counter = int(data.get("counter", self._counter))

    def load_positions(self, positions: list[Position]) -> None:
        self._positions = list(positions)

    # --------------------------------------------------------------- helpers
    def _new_id(self, symbol: str, ts: int) -> str:
        self._counter += 1
        return f"{symbol}-{ts}-{self._counter}"

    def _fee(self, price: float, qty: float) -> float:
        return abs(price * qty) * self.risk.fee_pct / 100.0

    def _unrealized(self, p: Position) -> float:
        last = self.last_price(p.symbol) or p.entry
        return (last - p.entry) * p.qty_open * p.side.sign

    def _make_position(self, signal: Signal, qty: float, price: float, fee: float, ts: int,
                       equity_at_open: float) -> Position:
        pos = Position(
            id=self._new_id(signal.symbol, ts), symbol=signal.symbol, side=signal.side, qty=qty,
            entry=price, stop=signal.stop, tp1=signal.tp1, tp2=signal.tp2, opened_ts=ts,
            setup=signal.setup, timeframe=signal.timeframe, qty_open=qty,
            realized_pnl=-fee, fees=fee,
            tags={"equity_at_open": repr(float(equity_at_open)), "initial_stop": repr(float(signal.stop)),
                  "score": f"{signal.score:.3f}"},
        )
        self._positions.append(pos)
        self._pending_fills.append(Fill(ts, signal.symbol, signal.side, qty, price, fee, "entry"))
        self.set_price(signal.symbol, price)
        return pos

    def _apply_exit(self, p: Position, qty: float, price: float, fee: float, ts: int,
                    reason: str) -> tuple[Fill, float]:
        """Book an exit fill; returns (fill, net realised amount). Closes the position if flat."""
        qty = min(qty, p.qty_open)
        gross = (price - p.entry) * qty * p.side.sign
        net = gross - fee
        p.qty_open -= qty
        p.realized_pnl += net
        p.fees += fee
        if reason == "tp1":
            p.tp1_done = True
        fill = Fill(ts, p.symbol, p.side.opposite, qty, price, fee, reason)
        self._pending_fills.append(fill)
        if p.qty_open <= max(_EPS, p.qty * 1e-9):
            p.qty_open = 0.0
            self._finish(p, ts, reason)
        return fill, net

    def _finish(self, p: Position, ts: int, reason: str) -> TradeRecord:
        if p in self._positions:
            self._positions.remove(p)
        try:
            eq_open = float(p.tags.get("equity_at_open", "0"))
        except ValueError:
            eq_open = 0.0
        gross_total = p.realized_pnl + p.fees
        exit_avg = p.entry + p.side.sign * gross_total / p.qty if p.qty > 0 else p.entry
        snap = dataclasses.replace(p, tags=dict(p.tags))
        snap.qty_open = 0.0
        rec = TradeRecord(position=snap, closed_ts=ts, exit_price=exit_avg, pnl=p.realized_pnl,
                          pnl_pct=(p.realized_pnl / eq_open * 100.0) if eq_open > 0 else 0.0,
                          reason=reason)
        self._trades.append(rec)
        log.info("closed %s %s pnl=%.4f (%s)", p.id, p.side.value, p.realized_pnl, reason)
        return rec

    def _process_position(self, p: Position, c: Candle) -> None:
        if c.ts <= p.opened_ts or p.qty_open <= _EPS:
            return
        long = p.side is Side.LONG

        def stop_hit() -> bool:
            return c.low <= p.stop if long else c.high >= p.stop

        def hit(level: float) -> bool:
            return c.high >= level if long else c.low <= level

        # 1) Pessimistic: if the stop was touched at all, assume it filled before any target.
        if stop_hit():
            price = min(p.stop, c.open) if long else max(p.stop, c.open)   # gap through the stop
            self.close(p, p.qty_open, price, c.ts, "stop")
            return
        # 2) TP1 partial, then break-even.
        frac = self.risk.tp1_fraction
        if not p.tp1_done and frac > 0 and hit(p.tp1):
            q = p.qty * frac
            if q >= p.qty_open * (1 - 1e-9):
                self.close(p, p.qty_open, p.tp1, c.ts, "tp1")
                return
            if self.close(p, q, p.tp1, c.ts, "tp1") is None:
                return
            if self.risk.move_to_be_after_tp1 and (p.entry - p.stop) * p.side.sign > _EPS:
                self.update_stop(p, p.entry)
            if p.qty_open > _EPS and stop_hit():          # pessimistic: BE stop also hit this candle
                self.close(p, p.qty_open, p.stop, c.ts, "stop")
                return
        # 3) TP2 closes the rest.
        if p.qty_open > _EPS and hit(p.tp2):
            self.close(p, p.qty_open, p.tp2, c.ts, "tp2")


class PaperBroker(Broker):
    """Simulated account. Margin-style accounting: cash only changes by fees and realised pnl;
    equity = cash + unrealised pnl at the last known price. Spot symbols are long-only and capped
    at the free cash (no leverage); perps ("BASE/QUOTE:SETTLE") may be shorted and are uncapped."""

    def __init__(self, cfg: BotCfg, start_equity: float | None = None) -> None:
        super().__init__(cfg)
        self.start_equity = float(start_equity if start_equity is not None
                                  else cfg.exchange.paper_start_equity)
        self._cash = self.start_equity

    def equity(self) -> float:
        return self._cash + sum(self._unrealized(p) for p in self._positions)

    def cash(self) -> float:
        return self._cash

    def set_cash(self, value: float) -> None:
        self._cash = float(value)

    def free_cash(self) -> float:
        """Cash not tied up in open spot positions (spot cannot use leverage)."""
        tied = sum(p.qty_open * p.entry for p in self._positions if not is_perp(p.symbol))
        return self._cash - tied

    def _slip(self, price: float, side_sign: int) -> float:
        """Adverse slippage for a trade in direction side_sign (+1 buy, -1 sell)."""
        return price * (1 + side_sign * self.risk.slippage_pct / 100.0)

    def open(self, signal: Signal, qty: float, ts: int) -> Position | None:
        if qty <= 0 or signal.entry <= 0:
            return None
        if signal.side is Side.SHORT and not is_perp(signal.symbol):
            log.warning("paper: refusing short on spot symbol %s", signal.symbol)
            return None
        price = self._slip(signal.entry, signal.side.sign)
        if not is_perp(signal.symbol):
            max_qty = self.free_cash() / (price * (1 + self.risk.fee_pct / 100.0))
            if qty > max_qty:
                log.info("paper: spot qty %.8f capped to %.8f by free cash", qty, max_qty)
                qty = max_qty
            if qty <= _EPS:
                log.warning("paper: no free cash for %s", signal.symbol)
                return None
        equity_before = self.equity()
        fee = self._fee(price, qty)
        self._cash -= fee
        pos = self._make_position(signal, qty, price, fee, ts, equity_before)
        log.info("paper open %s %s qty=%.8f @ %.6f", pos.id, pos.side.value, qty, price)
        return pos

    def close(self, position: Position, qty: float, price_hint: float, ts: int,
              reason: str) -> Fill | None:
        if position not in self._positions or qty <= 0 or position.qty_open <= _EPS:
            return None
        qty = min(qty, position.qty_open)
        price = self._slip(price_hint, position.side.opposite.sign)
        fee = self._fee(price, qty)
        fill, net = self._apply_exit(position, qty, price, fee, ts, reason)
        self._cash += net
        self.set_price(position.symbol, price_hint)
        return fill

    def snapshot(self) -> dict:
        data = super().snapshot()
        data["cash"] = self._cash
        data["start_equity"] = self.start_equity
        return data

    def restore_snapshot(self, data: dict) -> None:
        super().restore_snapshot(data)
        if "cash" in data:
            self._cash = float(data["cash"])
        if "start_equity" in data:
            self.start_equity = float(data["start_equity"])


class CcxtBroker(Broker):
    """Live trading on Crypto.com (or any ccxt exchange id) with locally tracked positions.

    Spot: long only (market buy / market sell). Perps (symbol contains ':'): both sides, exits use
    reduceOnly. Equity = total quote balance + value of held spot positions + unrealised perp pnl.
    Every exchange call is wrapped: failures are logged and None / [] / last known value returned.
    """

    def __init__(self, cfg: BotCfg, exchange: Any = None, place_exchange_stops: bool = True) -> None:
        super().__init__(cfg)
        self.place_exchange_stops = place_exchange_stops
        self._last_equity = 0.0
        self._last_cash = 0.0
        if exchange is None:
            ex = cfg.exchange
            klass = getattr(ccxt, ex.id)
            exchange = klass({
                "apiKey": env_secret(ex.api_key_env) or "",
                "secret": env_secret(ex.api_secret_env) or "",
                "enableRateLimit": bool(ex.rate_limit),
            })
            trust_proxy_env(exchange)
            try:
                exchange.set_sandbox_mode(bool(ex.sandbox))
            except Exception:
                log.exception("set_sandbox_mode(%s) failed", ex.sandbox)
        self.exchange = exchange
        self._markets_loaded = False

    # ----------------------------------------------------------- exchange utils
    def _ensure_markets(self) -> None:
        if self._markets_loaded:
            return
        try:
            self.exchange.load_markets()
            self._markets_loaded = True
        except Exception:
            log.exception("load_markets failed")

    def _market_cfg(self, symbol: str) -> MarketCfg | None:
        for m in self.cfg.markets:
            if m.symbol == symbol:
                return m
        return None

    def _limits(self, symbol: str) -> tuple[float, float]:
        """(min_cost, min_amount); exchange limits when known, else MarketCfg.min_notional / 0."""
        min_cost = min_amount = None
        try:
            market = self.exchange.market(symbol)
            limits = market.get("limits") or {}
            min_cost = (limits.get("cost") or {}).get("min")
            min_amount = (limits.get("amount") or {}).get("min")
        except Exception:
            log.debug("no market info for %s", symbol)
        if min_cost is None:
            mc = self._market_cfg(symbol)
            min_cost = mc.min_notional if mc else 1.0
        return float(min_cost or 0.0), float(min_amount or 0.0)

    def _amount(self, symbol: str, qty: float) -> float:
        try:
            return float(self.exchange.amount_to_precision(symbol, qty))
        except Exception as exc:   # ccxt raises if below precision
            log.warning("amount_to_precision(%s, %s) failed: %s", symbol, qty, exc)
            return 0.0

    def _price(self, symbol: str, price: float) -> float:
        try:
            return float(self.exchange.price_to_precision(symbol, price))
        except Exception:
            return float(price)

    def _quote(self) -> str:
        return self.cfg.exchange.quote

    def _base(self, symbol: str) -> str:
        return symbol.split("/")[0]

    def _balance(self) -> dict | None:
        try:
            return self.exchange.fetch_balance()
        except Exception:
            log.exception("fetch_balance failed")
            return None

    def _order_fill(self, order: Any, symbol: str, amount: float, ref: float) -> tuple[float, float]:
        """(filled qty, average price) from a ccxt order, fetching it once if needed."""
        order = order or {}
        avg = order.get("average") or None
        filled = order.get("filled") or None
        if (avg is None or filled is None) and order.get("id"):
            try:
                fetched = self.exchange.fetch_order(order["id"], symbol)
                avg = avg or fetched.get("average") or fetched.get("price")
                filled = filled or fetched.get("filled")
            except Exception:
                log.debug("fetch_order %s failed", order.get("id"))
        avg = float(avg or order.get("price") or ref)
        filled = float(filled or amount)
        return filled, avg

    def _place_stop(self, p: Position) -> None:
        if not self.place_exchange_stops or p.qty_open <= _EPS:
            return
        try:
            params: dict[str, Any] = {"stopLossPrice": self._price(p.symbol, p.stop)}
            if is_perp(p.symbol):
                params["reduceOnly"] = True
            side = "sell" if p.side is Side.LONG else "buy"
            amount = self._amount(p.symbol, p.qty_open)
            if amount <= 0:
                return
            order = self.exchange.create_order(p.symbol, "market", side, amount, None, params)
            if order and order.get("id"):
                p.tags["stop_order_id"] = str(order["id"])
        except Exception as exc:
            log.warning("exchange stop order for %s not placed (managed locally): %s", p.id, exc)

    def _cancel_stop(self, p: Position) -> None:
        oid = p.tags.pop("stop_order_id", None)
        if not oid:
            return
        try:
            self.exchange.cancel_order(oid, p.symbol)
        except Exception as exc:
            log.warning("cancel stop order %s for %s failed: %s", oid, p.id, exc)

    # --------------------------------------------------------------- interface
    def last_price(self, symbol: str) -> float:
        price = self._prices.get(symbol)
        if price:
            return price
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker.get("last") or ticker.get("close") or 0.0)
            self.set_price(symbol, price)
            return price
        except Exception:
            log.exception("fetch_ticker %s failed", symbol)
            return 0.0

    def equity(self) -> float:
        bal = self._balance()
        if bal is None:
            return self._last_equity
        try:
            total = float((bal.get("total") or {}).get(self._quote()) or 0.0)
            for p in self._positions:
                last = self.last_price(p.symbol) or p.entry
                if is_perp(p.symbol):
                    total += (last - p.entry) * p.qty_open * p.side.sign
                else:
                    total += last * p.qty_open
            self._last_equity = total
        except Exception:
            log.exception("equity computation failed")
        return self._last_equity

    def cash(self) -> float:
        bal = self._balance()
        if bal is None:
            return self._last_cash
        try:
            self._last_cash = float((bal.get("free") or {}).get(self._quote()) or 0.0)
        except Exception:
            log.exception("cash computation failed")
        return self._last_cash

    def open(self, signal: Signal, qty: float, ts: int) -> Position | None:
        symbol = signal.symbol
        try:
            if qty <= 0:
                return None
            if signal.side is Side.SHORT and not is_perp(symbol):
                log.warning("live: refusing short on spot symbol %s", symbol)
                return None
            self._ensure_markets()
            ref = signal.entry if signal.entry > 0 else self.last_price(symbol)
            if ref <= 0:
                return None
            equity_before = self.equity()
            if not is_perp(symbol):
                free = self.cash()
                max_qty = free / (ref * (1 + self.risk.fee_pct / 100.0)) if ref > 0 else 0.0
                if qty > max_qty:
                    log.info("live: spot qty %.8f capped to %.8f by free %s", qty, max_qty, self._quote())
                    qty = max_qty
            amount = self._amount(symbol, qty)
            min_cost, min_amount = self._limits(symbol)
            if amount <= 0 or amount < min_amount or amount * ref < min_cost:
                log.warning("live: order %s qty=%s notional=%.4f below minimum (cost %.4f, amount %s)",
                            symbol, amount, amount * ref, min_cost, min_amount)
                return None
            side = "buy" if signal.side is Side.LONG else "sell"
            order = self.exchange.create_order(symbol, "market", side, amount, ref, {})
            filled, avg = self._order_fill(order, symbol, amount, ref)
            if filled <= 0:
                return None
            fee = self._fee(avg, filled)
            pos = self._make_position(signal, filled, avg, fee, ts, equity_before)
            if order and order.get("id"):
                pos.tags["entry_order_id"] = str(order["id"])
            log.info("live open %s %s qty=%.8f @ %.6f", pos.id, side, filled, avg)
            self._place_stop(pos)
            return pos
        except Exception:
            log.exception("live open %s failed", symbol)
            return None

    def close(self, position: Position, qty: float, price_hint: float, ts: int,
              reason: str) -> Fill | None:
        p = position
        if p not in self._positions or qty <= 0 or p.qty_open <= _EPS:
            return None
        symbol = p.symbol
        try:
            self._ensure_markets()
            self._cancel_stop(p)
            qty = min(qty, p.qty_open)
            _, min_amount = self._limits(symbol)
            amount = self._amount(symbol, qty)
            rest = self._amount(symbol, p.qty_open - amount) if p.qty_open - amount > _EPS else 0.0
            if rest <= 0 or rest < min_amount:          # do not leave unsellable dust behind
                amount = self._amount(symbol, p.qty_open)
                full = True
            else:
                full = False
            if not is_perp(symbol):
                bal = self._balance()
                if bal is not None:
                    held = float((bal.get("free") or {}).get(self._base(symbol)) or 0.0)
                    if 0 < held < amount:
                        amount = self._amount(symbol, held)   # fees may have been taken in base
            if amount <= 0:
                log.warning("live close %s: nothing to sell", p.id)
                self._place_stop(p)
                return None
            side = "sell" if p.side is Side.LONG else "buy"
            params: dict[str, Any] = {"reduceOnly": True} if is_perp(symbol) else {}
            order = self.exchange.create_order(symbol, "market", side, amount, price_hint or None, params)
            filled, avg = self._order_fill(order, symbol, amount, price_hint or p.entry)
            booked = p.qty_open if full else min(filled, p.qty_open)
            fee = self._fee(avg, filled)
            fill, _ = self._apply_exit(p, booked, avg, fee, ts, reason)
            self.set_price(symbol, avg)
            if p in self._positions:
                self._place_stop(p)
            return fill
        except Exception:
            log.exception("live close %s failed", p.id)
            if p in self._positions and "stop_order_id" not in p.tags:
                self._place_stop(p)
            return None

    def update_stop(self, position: Position, new_stop: float) -> None:
        super().update_stop(position, new_stop)
        if position in self._positions and self.place_exchange_stops:
            self._cancel_stop(position)
            self._place_stop(position)
