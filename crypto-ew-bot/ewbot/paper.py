"""Deterministic paper broker with the same private interface as CryptoComClient.

Fill model (candle based, no randomness):
* LIMIT BUY fills when candle.low <= price, LIMIT SELL when candle.high >= price. Fill price = the limit price
  (conservative: no price improvement on gaps). Maker fee.
* MARKET fills on the first candle fed AFTER the order was placed, at candle.open +/- slippage. Taker fee.
* An order can only fill on candles with t > the last candle time the broker had seen when the order was placed,
  so re-feeding the same candle is harmless and an order never fills on a candle from before its creation.
* Orders are processed in order-id sequence. No partial fills.
* Funds are reserved at placement (BUY: price*qty*(1+fee reserve), SELL: base qty); insufficient funds raise
  ExchangeError, like a real exchange rejection.

ASSUMPTIONS (not verified, adjust in config): maker_fee 0.25 %, taker_fee 0.5 %, slippage 0.05 %.
Fees are charged in the quote currency (USD) on top of / out of the trade value.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from .exchange import ExchangeError, quantize_to_tick
from .models import Candle, InstrumentInfo, Order

# tick sizes read live from public/get-instruments on 2026-11-09
DEFAULT_INSTRUMENTS = {
    "BTC_USD": InstrumentInfo("BTC_USD", "BTC", "USD", 0.01, 0.00001, 0.00001, 0.0),
    "ETH_USD": InstrumentInfo("ETH_USD", "ETH", "USD", 0.01, 0.0001, 0.0001, 0.0),
    "SOL_USD": InstrumentInfo("SOL_USD", "SOL", "USD", 0.01, 0.001, 0.001, 0.0),
}

_EPS = 1e-9


def _r(x: float) -> float:
    return round(x, 10)


class PaperBroker:
    def __init__(self, starting_balance: float = 1000.0, quote: str = "USD",
                 maker_fee: float = 0.0025, taker_fee: float = 0.005, slippage: float = 0.0005,
                 instruments: Optional[dict[str, InstrumentInfo]] = None):
        self.quote = quote
        self.starting_balance = float(starting_balance)
        self.maker_fee = float(maker_fee)
        self.taker_fee = float(taker_fee)
        self.slippage = float(slippage)
        self.instruments: dict[str, InstrumentInfo] = dict(instruments or DEFAULT_INSTRUMENTS)
        self.total: dict[str, float] = {quote: float(starting_balance)}
        self.reserved: dict[str, float] = {}
        self.orders: dict[str, Order] = {}
        self._placed_after: dict[str, int] = {}   # order_id -> candle t seen at placement
        self._reserve: dict[str, float] = {}      # order_id -> reserved amount (in reserve currency)
        self._last_t: dict[str, int] = {}         # instrument -> last candle t fed
        self._last_close: dict[str, float] = {}
        self._seq = 0

    # ---- helpers ---------------------------------------------------------------------------
    def _info(self, instrument: str) -> InstrumentInfo:
        try:
            return self.instruments[instrument]
        except KeyError:
            raise ExchangeError(f"unknown instrument {instrument!r}")

    def get_instrument(self, instrument: str) -> InstrumentInfo:
        return self._info(instrument)

    def round_price(self, instrument: str, price: float, mode: str = "nearest") -> float:
        return float(quantize_to_tick(price, self._info(instrument).price_tick, mode))

    def round_qty(self, instrument: str, qty: float) -> float:
        return float(quantize_to_tick(qty, self._info(instrument).qty_tick, "down"))

    def _available(self, ccy: str) -> float:
        return self.total.get(ccy, 0.0) - self.reserved.get(ccy, 0.0)

    def get_balances(self) -> dict[str, float]:
        """currency -> available (total minus reserved by open orders), like CryptoComClient."""
        return {c: _r(self._available(c)) for c in sorted(self.total) if abs(self.total[c]) > 0 or c == self.quote}

    def get_total_balances(self) -> dict[str, float]:
        return {c: _r(v) for c, v in sorted(self.total.items())}

    def equity(self, prices: Optional[dict[str, float]] = None) -> float:
        """Total value in quote currency. prices: instrument -> price; falls back to last candle close."""
        eq = self.total.get(self.quote, 0.0)
        for inst, info in self.instruments.items():
            base_qty = self.total.get(info.base, 0.0)
            if base_qty:
                px = (prices or {}).get(inst, self._last_close.get(inst))
                if px is None:
                    raise ExchangeError(f"no price for {inst} to value {base_qty} {info.base}")
                eq += base_qty * px
        return _r(eq)

    def _new_id(self) -> str:
        self._seq += 1
        return f"P{self._seq:06d}"

    def _now(self, instrument: str) -> int:
        return self._last_t.get(instrument, 0)

    def _check_new(self, instrument, side, qty, client_oid) -> tuple[InstrumentInfo, str, float]:
        info = self._info(instrument)
        side = str(side).upper()
        if side not in ("BUY", "SELL"):
            raise ExchangeError(f"invalid side {side!r}", code=220)
        if not client_oid or len(client_oid) > 36:
            raise ExchangeError("client_oid must be a non-empty string of at most 36 characters", code=40004)
        if any(o.client_oid == client_oid for o in self.orders.values()):
            raise ExchangeError(f"duplicate client_oid {client_oid}", code=204)
        q = self.round_qty(instrument, qty)
        if q <= 0 or q + _EPS < info.min_qty:
            raise ExchangeError(f"invalid quantity {qty} (rounded {q}, min {info.min_qty})", code=213)
        return info, side, q

    def _reserve_funds(self, order: Order, info: InstrumentInfo, est_price: Optional[float]) -> None:
        if order.side == "SELL":
            ccy, amount = info.base, order.qty
        else:
            if est_price is None:
                return  # market buy without known price: checked at fill time
            ccy = info.quote
            amount = order.qty * est_price * (1 + max(self.taker_fee, self.maker_fee))
        if self._available(ccy) + _EPS < amount:
            raise ExchangeError(f"insufficient {ccy}: need {amount:.8f}, available {self._available(ccy):.8f}", code=306)
        self.reserved[ccy] = _r(self.reserved.get(ccy, 0.0) + amount)
        self._reserve[order.order_id] = amount

    def _release(self, order: Order, info: InstrumentInfo) -> None:
        amount = self._reserve.pop(order.order_id, 0.0)
        if amount:
            ccy = info.base if order.side == "SELL" else info.quote
            self.reserved[ccy] = max(0.0, _r(self.reserved.get(ccy, 0.0) - amount))

    # ---- orders ----------------------------------------------------------------------------
    def place_limit(self, instrument: str, side: str, qty: float, price: float, client_oid: str) -> str:
        info, side, q = self._check_new(instrument, side, qty, client_oid)
        p = self.round_price(instrument, price)
        if p <= 0:
            raise ExchangeError(f"invalid price {price}", code=308)
        oid = self._new_id()
        order = Order(order_id=oid, client_oid=client_oid, instrument=instrument, side=side, type="LIMIT",
                      qty=q, price=p, status="ACTIVE", created_ts=self._now(instrument), updated_ts=self._now(instrument))
        self._reserve_funds(order, info, p)
        self.orders[oid] = order
        self._placed_after[oid] = self._now(instrument)
        return oid

    def place_market(self, instrument: str, side: str, qty: float, client_oid: str) -> str:
        info, side, q = self._check_new(instrument, side, qty, client_oid)
        oid = self._new_id()
        order = Order(order_id=oid, client_oid=client_oid, instrument=instrument, side=side, type="MARKET",
                      qty=q, price=None, status="ACTIVE", created_ts=self._now(instrument), updated_ts=self._now(instrument))
        est = self._last_close.get(instrument)
        self._reserve_funds(order, info, est * (1 + self.slippage) if est else None)
        self.orders[oid] = order
        self._placed_after[oid] = self._now(instrument)
        return oid

    def cancel(self, instrument: str, order_id: str) -> None:
        o = self.get_order(order_id)
        if o.status != "ACTIVE":
            raise ExchangeError(f"cancel {order_id}: order already {o.status}", code=40401)
        real = self.orders[order_id]
        real.status = "CANCELED"
        real.updated_ts = self._now(real.instrument)
        self._release(real, self._info(real.instrument))

    def get_order(self, order_id: str) -> Order:
        try:
            o = self.orders[order_id]
        except KeyError:
            raise ExchangeError(f"order {order_id} not found", code=40401)
        return Order(**asdict(o))

    def get_order_by_client_oid(self, client_oid: str) -> Optional[Order]:
        for o in self.orders.values():
            if o.client_oid == client_oid:
                return Order(**asdict(o))
        return None

    def open_orders(self, instrument: Optional[str] = None) -> list[Order]:
        return [Order(**asdict(o)) for o in self.orders.values()
                if o.status == "ACTIVE" and (instrument is None or o.instrument == instrument)]

    # ---- simulation ------------------------------------------------------------------------
    def on_candle(self, instrument: str, candle: Candle) -> list[Order]:
        """Feed one candle (call in time order). Returns copies of the orders that were filled by it."""
        info = self._info(instrument)
        filled: list[Order] = []
        for oid in sorted(self.orders):
            o = self.orders[oid]
            if o.status != "ACTIVE" or o.instrument != instrument:
                continue
            if candle.t <= self._placed_after.get(oid, 0):
                continue
            if o.type == "MARKET":
                px = candle.o * (1 + self.slippage) if o.side == "BUY" else candle.o * (1 - self.slippage)
                px = float(quantize_to_tick(px, info.price_tick, "up" if o.side == "BUY" else "down"))
                fee_rate = self.taker_fee
            else:
                assert o.price is not None
                if o.side == "BUY" and candle.l <= o.price:
                    px = o.price
                elif o.side == "SELL" and candle.h >= o.price:
                    px = o.price
                else:
                    continue
                fee_rate = self.maker_fee
            if self._fill(o, info, px, fee_rate, candle.t):
                filled.append(Order(**asdict(o)))
        self._last_t[instrument] = max(self._last_t.get(instrument, 0), candle.t)
        self._last_close[instrument] = candle.c
        return filled

    def _fill(self, o: Order, info: InstrumentInfo, px: float, fee_rate: float, t: int) -> bool:
        value = _r(o.qty * px)
        fee = _r(value * fee_rate)
        self._release(o, info)
        if o.side == "BUY":
            cost = value + fee
            if self._available(info.quote) + _EPS < cost:
                o.status, o.updated_ts = "REJECTED", t   # e.g. market buy without enough cash
                return False
            self.total[info.quote] = _r(self.total.get(info.quote, 0.0) - cost)
            self.total[info.base] = _r(self.total.get(info.base, 0.0) + o.qty)
        else:
            if self.total.get(info.base, 0.0) + _EPS < o.qty:
                o.status, o.updated_ts = "REJECTED", t
                return False
            self.total[info.base] = _r(self.total.get(info.base, 0.0) - o.qty)
            self.total[info.quote] = _r(self.total.get(info.quote, 0.0) + value - fee)
        o.status, o.filled_qty, o.avg_price, o.fee, o.updated_ts = "FILLED", o.qty, px, fee, t
        return True

    # ---- persistence -----------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "quote": self.quote, "starting_balance": self.starting_balance,
            "maker_fee": self.maker_fee, "taker_fee": self.taker_fee, "slippage": self.slippage,
            "instruments": {k: asdict(v) for k, v in self.instruments.items()},
            "total": dict(self.total), "reserved": dict(self.reserved),
            "orders": {k: asdict(v) for k, v in self.orders.items()},
            "placed_after": dict(self._placed_after), "reserve": dict(self._reserve),
            "last_t": dict(self._last_t), "last_close": dict(self._last_close), "seq": self._seq,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PaperBroker":
        b = cls(starting_balance=d["starting_balance"], quote=d["quote"], maker_fee=d["maker_fee"],
                taker_fee=d["taker_fee"], slippage=d["slippage"],
                instruments={k: InstrumentInfo(**v) for k, v in d["instruments"].items()})
        b.total = {k: float(v) for k, v in d["total"].items()}
        b.reserved = {k: float(v) for k, v in d["reserved"].items()}
        b.orders = {k: Order(**v) for k, v in d["orders"].items()}
        b._placed_after = {k: int(v) for k, v in d["placed_after"].items()}
        b._reserve = {k: float(v) for k, v in d["reserve"].items()}
        b._last_t = {k: int(v) for k, v in d["last_t"].items()}
        b._last_close = {k: float(v) for k, v in d["last_close"].items()}
        b._seq = int(d["seq"])
        return b
