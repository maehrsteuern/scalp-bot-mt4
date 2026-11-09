"""Shared data types. ALL modules use these. Do not change field names without updating CONTRACT.md."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass(frozen=True)
class Candle:
    t: int          # open time, ms since epoch, UTC
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass
class Signal:
    """One long setup. All prices in quote currency of `instrument` (USD for BTC_USD)."""
    coin: str               # "BTC" | "ETH" | "SOL"
    instrument: str         # e.g. "BTC_USD"
    created_ts: int         # ms, when the setup was detected (close time of trigger candle)
    valid_until_ts: int     # ms; unfilled entry must be cancelled after this
    entry: float            # limit buy price
    stop: float             # stop-loss (sell everything if price <= stop)
    t1: float               # take-profit 1: sell 50 %, then stop -> entry (break-even)
    t2: float               # take-profit 2: sell rest
    wave_low: float         # low that starts wave 1 (end of correction). Hard invalidation for entry.
    wave1_high: float       # top of confirmed wave 1
    cancel_above: float     # if price trades >= this before fill -> cancel (default t1)
    score: float = 0.0      # 0..1 confluence quality
    fib_hits: List[str] = field(default_factory=list)   # e.g. ["rally 61.8% 84.87", "C=1.272A 85.06"]
    reason_de: str = ""     # short German wave description for the page
    id: str = ""            # stable id: f"{coin}-{created_ts}"

    def to_dict(self):
        return asdict(self)


@dataclass
class Order:
    order_id: str
    client_oid: str
    instrument: str
    side: str               # "BUY" | "SELL"
    type: str               # "LIMIT" | "MARKET"
    qty: float
    price: Optional[float]
    status: str             # "NEW" | "ACTIVE" | "FILLED" | "CANCELED" | "REJECTED" | "EXPIRED"
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    fee: float = 0.0        # in quote currency
    created_ts: int = 0
    updated_ts: int = 0


@dataclass
class InstrumentInfo:
    instrument: str
    base: str
    quote: str
    price_tick: float
    qty_tick: float
    min_qty: float
    min_notional: float = 0.0
