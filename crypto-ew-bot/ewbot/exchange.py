"""Crypto.com Exchange API v1 client (spot only).

Verified against the official docs (https://exchange-developer.crypto.com/exchange/v1/docs/api/...):
signing, create/cancel/get-order-detail/get-open-orders/user-balance, advanced (trigger) orders,
public get-instruments / get-candlestick / get-tickers, error codes and rate limits.
See the report of the build agent for what is NOT verified (private endpoints were never called live).

Safety rules implemented here:
* spot only: orders are refused unless the instrument is a CCY_PAIR; no margin / leverage / derivative fields,
  no withdraw or transfer endpoints exist in this module
* create-order is never retried blindly. After a timeout / connection error the order is looked up by client_oid.
  If its state stays unknown, OrderStateUnknown is raised and the caller must NOT assume anything.
* secrets are never logged and never put into exception messages (the API echoes the request in `original`,
  which is deliberately dropped)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, InvalidOperation
from typing import Any, Optional

import requests

from .models import Candle, InstrumentInfo, Order

log = logging.getLogger("ewbot.exchange")

DEFAULT_BASE_URL = "https://api.crypto.com/exchange/v1"

# Timeframes accepted by public/get-candlestick (docs) -> milliseconds
TIMEFRAME_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000,
    "2h": 7_200_000, "4h": 14_400_000, "12h": 43_200_000, "1D": 86_400_000,
    "7D": 604_800_000, "14D": 1_209_600_000,
}
MAX_CANDLES_PER_REQUEST = 300  # observed live: larger counts are silently clamped to 300

# Reason codes (docs: "Response and Reason Codes")
CODE_NOT_FOUND = 40401
CODE_DUPLICATE_CLORDID = 204
CODE_DUPLICATE_REQUEST = 40006
CODE_TOO_MANY_REQUESTS = 42901
CODE_REQUEST_TIMEOUT = 40801
CODE_INVALID_NONCE = 40102
_RETRYABLE_CODES = {CODE_TOO_MANY_REQUESTS, CODE_REQUEST_TIMEOUT, 50001}
_RATE_LIMIT_CODES = {CODE_TOO_MANY_REQUESTS}

_CLOSED_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}


class ExchangeError(Exception):
    """Any API / transport problem. `code` is the exchange reason code (int) or None for transport errors."""

    def __init__(self, message: str, code: Optional[int] = None, method: str = "",
                 http_status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.method = method
        self.http_status = http_status


class OrderStateUnknown(ExchangeError):
    """create-order outcome could not be determined (timeout and not found by client_oid).
    The order MAY exist on the exchange. Do not open new trades until resolved (see open_orders / get_order_by_client_oid)."""


# ----------------------------------------------------------------------------------------------
# number formatting helpers
# ----------------------------------------------------------------------------------------------
def to_decimal(x: Any) -> Decimal:
    """float / str / int -> Decimal using the shortest repr (no binary float noise)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not a number")
    try:
        return Decimal(str(x).strip())
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"not a number: {x!r}") from e


def fmt_decimal(d: Decimal) -> str:
    """Plain positional notation, no exponent, no trailing zeros ('0.00001', '85000', never '1E-5')."""
    if not d.is_finite():
        raise ValueError(f"not finite: {d}")
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("", "-0"):
        s = "0"
    return s


def quantize_to_tick(value: Any, tick: Any, mode: str = "nearest") -> Decimal:
    """Round value to a multiple of tick. mode: 'down' | 'up' | 'nearest'."""
    v, t = to_decimal(value), to_decimal(tick)
    if t <= 0:
        raise ValueError("tick must be > 0")
    rounding = {"down": ROUND_DOWN, "up": ROUND_UP, "nearest": ROUND_HALF_UP}[mode]
    steps = (v / t).to_integral_value(rounding=rounding)
    return steps * t


def _f(x: Any, default: float = 0.0) -> float:
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------------------------------
# signing
# ----------------------------------------------------------------------------------------------
_MAX_LEVEL = 3  # official docs: nesting deeper than this is stringified


def _params_to_str(obj: Any, level: int = 0) -> str:
    """paramString per official docs: keys sorted ascending, key+value concatenated, lists flattened,
    None -> 'null'. Follows the official Java reference (maps nested inside maps are recursed, list items that are
    scalars are appended with str())."""
    if level >= _MAX_LEVEL:
        return str(obj)
    if isinstance(obj, dict):
        out = []
        for key in sorted(obj):
            out.append(str(key))
            val = obj[key]
            if val is None:
                out.append("null")
            elif isinstance(val, (list, tuple, dict)):
                out.append(_params_to_str(val, level + 1))
            else:
                out.append(str(val))
        return "".join(out)
    if isinstance(obj, (list, tuple)):
        return "".join(_params_to_str(o, level + 1) for o in obj)
    if obj is None:
        return "null"
    return str(obj)


def sign_request(method: str, req_id: int, api_key: str, params: Optional[dict], nonce: int, secret: str) -> str:
    """HMAC-SHA256 hex over method + id + api_key + paramString + nonce (official algorithm)."""
    param_str = _params_to_str(params) if params else ""
    payload = f"{method}{req_id}{api_key}{param_str}{nonce}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


# ----------------------------------------------------------------------------------------------
# client
# ----------------------------------------------------------------------------------------------
class CryptoComClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 base_url: str = DEFAULT_BASE_URL, timeout: float = 15,
                 max_retries: int = 3, session: Optional[requests.Session] = None,
                 sleep=time.sleep, clock=time.time):
        self._api_key = api_key or None
        self._api_secret = api_secret or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._instruments: dict[str, InstrumentInfo] = {}
        self._instrument_types: dict[str, str] = {}
        self._instruments_loaded_at = 0.0
        self._lock = threading.Lock()
        self._last_private_call = 0.0
        self._req_counter = 0
        self.min_private_interval = 0.05  # docs: >= 3 req / 100 ms for most calls; stay well below

    def __repr__(self) -> str:  # never show secrets
        return f"CryptoComClient(base_url={self.base_url!r}, has_key={bool(self._api_key)})"

    # ---- transport -------------------------------------------------------------------------
    def _next_id(self) -> int:
        with self._lock:
            self._req_counter += 1
            return int(self._clock() * 1000) * 1000 + (self._req_counter % 1000)

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(8.0, 0.5 * (2 ** attempt)))

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_private_call + self.min_private_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_private_call = self._clock()

    @staticmethod
    def _parse(resp: requests.Response, method: str) -> dict:
        try:
            body = resp.json()
        except ValueError:
            raise ExchangeError(f"{method}: HTTP {resp.status_code}, response is not JSON",
                                http_status=resp.status_code, method=method)
        if not isinstance(body, dict):
            raise ExchangeError(f"{method}: unexpected response type", http_status=resp.status_code, method=method)
        return body

    def _request(self, method: str, params: Optional[dict] = None, *, private: bool,
                 retry: str = "safe") -> dict:
        """retry: 'safe'   -> retry on timeouts, connection errors, HTTP 5xx, 429 and transient codes (idempotent calls)
                  'ratelimit' -> retry ONLY when the exchange says explicitly it did not execute the request (HTTP 429 /
                                 code 42901). Used for create-order (client_oid makes the repeat idempotent anyway).
                  'none'   -> never retry.
        Returns the `result` dict ({} if absent)."""
        if private and not (self._api_key and self._api_secret):
            raise ExchangeError(f"{method}: API key/secret missing (private endpoint)", method=method)
        attempt = 0
        while True:
            transient: Optional[ExchangeError] = None
            try:
                if private:
                    self._throttle()
                    req_id = self._next_id()
                    nonce = int(self._clock() * 1000)  # fresh nonce + fresh signature on every attempt
                    body = {"id": req_id, "method": method, "api_key": self._api_key,
                            "params": params or {}, "nonce": nonce}
                    body["sig"] = sign_request(method, req_id, self._api_key, params, nonce, self._api_secret)
                    resp = self._session.post(f"{self.base_url}/{method}", data=json.dumps(body),
                                              headers={"Content-Type": "application/json"}, timeout=self.timeout)
                else:
                    resp = self._session.get(f"{self.base_url}/{method}", params=params or {}, timeout=self.timeout)
            except requests.exceptions.Timeout as e:
                transient = ExchangeError(f"{method}: request timed out ({type(e).__name__})", method=method)
                transient.timeout = True  # type: ignore[attr-defined]
            except requests.exceptions.RequestException as e:
                # message of requests exceptions can contain URL only (no body), still keep it short
                transient = ExchangeError(f"{method}: connection problem ({type(e).__name__})", method=method)
                transient.timeout = True  # type: ignore[attr-defined]
            else:
                body = self._parse(resp, method)
                code = _i(body.get("code"), -1) if body.get("code") is not None else 0
                status = resp.status_code
                if code == 0 and status < 400:
                    res = body.get("result")
                    return res if isinstance(res, dict) else {}
                msg = str(body.get("message") or "")[:200]  # NOT body['original'] (echoes api_key + sig)
                err = ExchangeError(f"{method}: code {code} {msg} (HTTP {status})".replace("  ", " "),
                                    code=code, method=method, http_status=status)
                is_rl = status == 429 or code in _RATE_LIMIT_CODES
                is_transient = is_rl or status >= 500 or code in _RETRYABLE_CODES
                if retry == "ratelimit":
                    is_transient = is_rl
                if not is_transient or retry == "none":
                    raise err
                transient = err
            # transient branch
            if retry == "ratelimit" and not (transient.code in _RATE_LIMIT_CODES or transient.http_status == 429):
                raise transient  # timeout/connection on create: state unknown, never repeat blindly
            if retry == "none" or attempt >= self.max_retries:
                raise transient
            log.warning("retry %d/%d for %s after: %s", attempt + 1, self.max_retries, method, transient)
            self._backoff(attempt)
            attempt += 1

    # ---- public ----------------------------------------------------------------------------
    def get_candles(self, instrument: str, timeframe: str, count: int = 300, end_ts: Optional[int] = None,
                    *, closed_only: bool = False) -> list[Candle]:
        """Ascending candles. `end_ts` (ms): returns candles that lie fully before it (live-tested: candle t is
        returned if t + period <= end_ts, so end_ts = oldest t of the previous page pages backwards without overlap).
        Max 300 per request (exchange clamps). The newest candle is usually still OPEN; closed_only=True drops it."""
        if timeframe not in TIMEFRAME_MS:
            raise ExchangeError(f"unsupported timeframe {timeframe!r}")
        params: dict[str, Any] = {"instrument_name": instrument, "timeframe": timeframe,
                                  "count": max(1, min(int(count), MAX_CANDLES_PER_REQUEST))}
        if end_ts is not None:
            params["end_ts"] = int(end_ts)
        res = self._request("public/get-candlestick", params, private=False)
        out: dict[int, Candle] = {}
        for row in res.get("data", []) or []:
            try:
                c = Candle(t=int(row["t"]), o=float(row["o"]), h=float(row["h"]), l=float(row["l"]),
                           c=float(row["c"]), v=float(row.get("v", 0) or 0))
            except (KeyError, TypeError, ValueError) as e:
                raise ExchangeError(f"public/get-candlestick: malformed candle row ({e})")
            out[c.t] = c
        candles = [out[t] for t in sorted(out)]
        if closed_only:
            now_ms = int(self._clock() * 1000)
            tf = TIMEFRAME_MS[timeframe]
            candles = [c for c in candles if c.t + tf <= now_ms]
        return candles

    def get_candles_paged(self, instrument: str, timeframe: str, total: int, *,
                          closed_only: bool = False) -> list[Candle]:
        """Page backwards with end_ts until `total` candles (or no more history). Deduplicated, ascending."""
        got: dict[int, Candle] = {}
        end_ts: Optional[int] = None
        while len(got) < total:
            page = self.get_candles(instrument, timeframe, min(MAX_CANDLES_PER_REQUEST, total - len(got) + 5),
                                    end_ts=end_ts)
            if not page:
                break
            new = [c for c in page if c.t not in got]
            if not new:
                break
            for c in new:
                got[c.t] = c
            end_ts = page[0].t  # oldest of this page; next page is strictly older
        res = [got[t] for t in sorted(got)]
        if closed_only:
            now_ms = int(self._clock() * 1000)
            tf = TIMEFRAME_MS[timeframe]
            res = [c for c in res if c.t + tf <= now_ms]
        return res[-total:] if total > 0 else res

    def get_ticker(self, instrument: str) -> dict:
        res = self._request("public/get-tickers", {"instrument_name": instrument}, private=False)
        for row in res.get("data", []) or []:
            if row.get("i") == instrument:
                bid, ask, last = _f(row.get("b")), _f(row.get("k")), _f(row.get("a"))
                return {"bid": bid, "ask": ask, "last": last, "ts": _i(row.get("t"))}
        raise ExchangeError(f"public/get-tickers: no data for {instrument}")

    def _load_instruments(self, force: bool = False) -> None:
        if not force and self._instruments and self._clock() - self._instruments_loaded_at < 3600:
            return
        res = self._request("public/get-instruments", None, private=False)
        inst: dict[str, InstrumentInfo] = {}
        types: dict[str, str] = {}
        for row in res.get("data", []) or []:
            sym = row.get("symbol")
            if not sym:
                continue
            try:
                qty_tick = float(row["qty_tick_size"])
                inst[sym] = InstrumentInfo(
                    instrument=sym, base=str(row.get("base_ccy", "")), quote=str(row.get("quote_ccy", "")),
                    price_tick=float(row["price_tick_size"]), qty_tick=qty_tick,
                    min_qty=qty_tick,      # ASSUMPTION: API has no min-qty field; smallest tradable step
                    min_notional=0.0,      # API has no min-notional field; engine config must enforce its own minimum
                )
                types[sym] = str(row.get("inst_type", ""))
            except (KeyError, ValueError):
                continue
        if not inst:
            raise ExchangeError("public/get-instruments: empty or malformed answer")
        self._instruments, self._instrument_types = inst, types
        self._instruments_loaded_at = self._clock()

    def get_instrument(self, instrument: str) -> InstrumentInfo:
        self._load_instruments()
        if instrument not in self._instruments:
            self._load_instruments(force=True)
        try:
            return self._instruments[instrument]
        except KeyError:
            raise ExchangeError(f"unknown instrument {instrument!r}")

    def _spot_instrument(self, instrument: str) -> InstrumentInfo:
        info = self.get_instrument(instrument)
        if self._instrument_types.get(instrument) != "CCY_PAIR":
            raise ExchangeError(f"{instrument} is not a spot pair (inst_type="
                                f"{self._instrument_types.get(instrument)!r}); this bot is spot-only")
        return info

    def round_price(self, instrument: str, price: float, mode: str = "nearest") -> float:
        info = self.get_instrument(instrument)
        return float(quantize_to_tick(price, info.price_tick, mode))

    def round_qty(self, instrument: str, qty: float) -> float:
        """Floor to qty_tick."""
        info = self.get_instrument(instrument)
        return float(quantize_to_tick(qty, info.qty_tick, "down"))

    def _fmt_price(self, info: InstrumentInfo, price: float, mode: str = "nearest") -> str:
        p = quantize_to_tick(price, info.price_tick, mode)
        if p <= 0:
            raise ExchangeError(f"price {price} rounds to {p} for {info.instrument}")
        return fmt_decimal(p)

    def _fmt_qty(self, info: InstrumentInfo, qty: float) -> str:
        q = quantize_to_tick(qty, info.qty_tick, "down")
        if q <= 0 or q < to_decimal(info.min_qty):
            raise ExchangeError(f"quantity {qty} rounds to {q} (< min {info.min_qty}) for {info.instrument}")
        return fmt_decimal(q)

    # ---- private: account ------------------------------------------------------------------
    def get_balances(self) -> dict[str, float]:
        """currency -> AVAILABLE amount (quantity - reserved_qty; reserved = locked in open orders)."""
        res = self._request("private/user-balance", {}, private=True)
        out: dict[str, float] = {}
        for acct in res.get("data", []) or []:
            for pb in acct.get("position_balances", []) or []:
                cur = pb.get("instrument_name")
                if not cur:
                    continue
                avail = max(0.0, _f(pb.get("quantity")) - _f(pb.get("reserved_qty")))
                out[cur] = out.get(cur, 0.0) + avail
        return out

    # ---- private: orders -------------------------------------------------------------------
    @staticmethod
    def _check_side(side: str) -> str:
        s = str(side).upper()
        if s not in ("BUY", "SELL"):
            raise ExchangeError(f"invalid side {side!r}")
        return s

    @staticmethod
    def _check_client_oid(client_oid: str) -> str:
        if not client_oid or not isinstance(client_oid, str) or len(client_oid) > 36:
            raise ExchangeError("client_oid must be a non-empty string of at most 36 characters")
        return client_oid

    def _create(self, method: str, params: dict, client_oid: str, instrument: str) -> str:
        try:
            res = self._request(method, params, private=True, retry="ratelimit")
        except OrderStateUnknown:
            raise
        except ExchangeError as e:
            if e.code in (CODE_DUPLICATE_CLORDID, CODE_DUPLICATE_REQUEST):
                # same client_oid already exists -> idempotent: return the existing order id
                existing = self.get_order_by_client_oid(client_oid)
                if existing is not None:
                    return existing.order_id
                raise
            if getattr(e, "timeout", False) or (e.http_status is not None and e.http_status >= 500) \
                    or e.code in (CODE_REQUEST_TIMEOUT, 50001):
                return self._recover_order_id(client_oid, instrument, e)
            raise
        oid = res.get("order_id")
        if not oid:
            return self._recover_order_id(client_oid, instrument,
                                          ExchangeError(f"{method}: success without order_id", method=method))
        return str(oid)

    def _recover_order_id(self, client_oid: str, instrument: str, cause: ExchangeError) -> str:
        """Outcome of create-order unknown: look the order up by client_oid (detail, then open orders)."""
        for i in range(4):
            if i:
                self._sleep(1.0 * i)
            try:
                o = self.get_order_by_client_oid(client_oid)
                if o is not None:
                    log.warning("create-order outcome recovered via client_oid %s -> order %s", client_oid, o.order_id)
                    return o.order_id
                for o in self.open_orders(instrument) + self.open_stop_orders(instrument):
                    if o.client_oid == client_oid:
                        return o.order_id
            except ExchangeError as e:  # lookup itself failing is not "order does not exist"
                log.warning("lookup by client_oid failed: %s", e)
        raise OrderStateUnknown(
            f"order state UNKNOWN for client_oid={client_oid} ({instrument}) after: {cause}. "
            "It may exist on the exchange - check open orders before doing anything else.",
            code=cause.code, method=cause.method, http_status=cause.http_status)

    def place_limit(self, instrument: str, side: str, qty: float, price: float, client_oid: str,
                    *, post_only: bool = False) -> str:
        info = self._spot_instrument(instrument)
        side = self._check_side(side)
        self._check_client_oid(client_oid)
        params: dict[str, Any] = {
            "instrument_name": instrument, "side": side, "type": "LIMIT",
            "price": self._fmt_price(info, price), "quantity": self._fmt_qty(info, qty),
            "client_oid": client_oid, "time_in_force": "GOOD_TILL_CANCEL",
        }
        if post_only:
            params["exec_inst"] = ["POST_ONLY"]
        return self._create("private/create-order", params, client_oid, instrument)

    def place_market(self, instrument: str, side: str, qty: float, client_oid: str) -> str:
        info = self._spot_instrument(instrument)
        side = self._check_side(side)
        self._check_client_oid(client_oid)
        params = {"instrument_name": instrument, "side": side, "type": "MARKET",
                  "quantity": self._fmt_qty(info, qty), "client_oid": client_oid}
        return self._create("private/create-order", params, client_oid, instrument)

    def place_stop_market(self, instrument: str, qty: float, stop_price: float, client_oid: str,
                          *, ref_price_type: str = "LAST_PRICE") -> str:
        """Exchange-side SELL STOP_LOSS (market order when ref_price is reached) via private/advanced/create-order.
        Documented fields verified; behaviour on spot (balance reservation, trigger direction) NOT tested live.
        Use only as an extra safety net, managed separately (cancel_stop / get_stop_order / open_stop_orders)."""
        info = self._spot_instrument(instrument)
        self._check_client_oid(client_oid)
        if ref_price_type not in ("LAST_PRICE", "MARK_PRICE", "INDEX_PRICE"):
            raise ExchangeError(f"invalid ref_price_type {ref_price_type!r}")
        params = {"instrument_name": instrument, "side": "SELL", "type": "STOP_LOSS",
                  "quantity": self._fmt_qty(info, qty), "ref_price": self._fmt_price(info, stop_price),
                  "ref_price_type": ref_price_type, "client_oid": client_oid}
        return self._create("private/advanced/create-order", params, client_oid, instrument)

    def cancel(self, instrument: str, order_id: str) -> None:
        """Cancel is idempotent, so it may be retried. The API call is asynchronous (confirmation only)."""
        self._cancel_via("private/cancel-order", order_id, self.get_order)

    def cancel_stop(self, instrument: str, order_id: str) -> None:
        self._cancel_via("private/advanced/cancel-order", order_id, self.get_stop_order)

    def _cancel_via(self, method: str, order_id: str, getter) -> None:
        try:
            self._request(method, {"order_id": str(order_id)}, private=True, retry="safe")
            return
        except ExchangeError as e:
            # a cancel that fails because the order is already closed is not a transport problem: tell the caller
            try:
                o = getter(order_id)
            except ExchangeError:
                raise e
            if o.status == "CANCELED":
                return
            if o.status in _CLOSED_STATUSES:
                err = ExchangeError(f"cancel {order_id}: order already {o.status} (filled {o.filled_qty})",
                                    code=e.code, method=method, http_status=e.http_status)
                err.order_status = o.status  # type: ignore[attr-defined]
                raise err
            raise

    def _parse_order(self, d: dict) -> Order:
        qty = _f(d.get("quantity"))
        limit_price = _f(d.get("limit_price")) or _f(d.get("ref_price")) or None
        status = str(d.get("status", "")).upper()
        if status == "PENDING":
            status = "NEW"
        filled = _f(d.get("cumulative_quantity"))
        avg = _f(d.get("avg_price")) or None
        if avg is None and filled > 0:
            val = _f(d.get("cumulative_value"))
            avg = val / filled if val > 0 else None
        fee = _f(d.get("cumulative_fee"))
        fee_raw = fee
        inst = str(d.get("instrument_name", ""))
        fee_ccy = str(d.get("fee_instrument_name", "") or "")
        quote = inst.split("_")[1] if "_" in inst else ""
        base = inst.split("_")[0] if "_" in inst else ""
        if fee and fee_ccy and fee_ccy != quote:
            # fee not in quote currency: convert if it is the base (approx at avg price), else unknown -> 0 (flagged)
            if fee_ccy == base and avg:
                fee = fee * avg
            else:
                log.warning("order %s: fee in %s cannot be converted to %s; fee set to 0", d.get("order_id"), fee_ccy, quote)
                fee = 0.0
        side = str(d.get("side", "")).upper()
        if side == "BUY" and fee_raw and fee_ccy and fee_ccy == base and filled > 0:
            # Fee charged in the BASE coin: the gross filled quantity is NOT what lands in the wallet.
            # Convention: Order.filled_qty is the NET quantity (gross - fee) for such BUY orders, and `fee` stays
            # the quote-equivalent (fee * avg), so that qty_net * avg + fee == gross cost. See Order.fee_ccy below.
            filled = max(0.0, filled - fee_raw)
        order = Order(
            order_id=str(d.get("order_id", "")), client_oid=str(d.get("client_oid", "") or ""),
            instrument=inst, side=str(d.get("side", "")).upper(),
            type=str(d.get("order_type", d.get("type", ""))).upper(), qty=qty, price=limit_price,
            status=status, filled_qty=filled, avg_price=avg, fee=fee,
            created_ts=_i(d.get("create_time")), updated_ts=_i(d.get("update_time")),
        )
        order.fee_ccy = fee_ccy        # extra attribute (not a dataclass field): currency the fee was charged in
        return order

    def _detail(self, method: str, params: dict) -> Optional[Order]:
        try:
            res = self._request(method, params, private=True, retry="safe")
        except ExchangeError as e:
            if e.code == CODE_NOT_FOUND:
                return None
            raise
        d = res.get("order_info") if isinstance(res.get("order_info"), dict) else res  # old docs wrapped it
        if not d or not d.get("order_id"):
            return None
        return self._parse_order(d)

    def get_order(self, order_id: str) -> Order:
        o = self._detail("private/get-order-detail", {"order_id": str(order_id)})
        if o is None:
            o = self._detail("private/advanced/get-order-detail", {"order_id": str(order_id)})
        if o is None:
            raise ExchangeError(f"order {order_id} not found", code=CODE_NOT_FOUND)
        return o

    def get_stop_order(self, order_id: str) -> Order:
        o = self._detail("private/advanced/get-order-detail", {"order_id": str(order_id)})
        if o is None:
            raise ExchangeError(f"stop order {order_id} not found", code=CODE_NOT_FOUND)
        return o

    def get_order_by_client_oid(self, client_oid: str) -> Optional[Order]:
        """None if the exchange does not know this client_oid (yet)."""
        o = self._detail("private/get-order-detail", {"client_oid": client_oid})
        if o is None:
            o = self._detail("private/advanced/get-order-detail", {"client_oid": client_oid})
        return o

    def _open(self, method: str, instrument: Optional[str]) -> list[Order]:
        params = {"instrument_name": instrument} if instrument else {}
        res = self._request(method, params, private=True, retry="safe")
        return [self._parse_order(d) for d in res.get("data", []) or []]

    def open_orders(self, instrument: Optional[str] = None) -> list[Order]:
        return self._open("private/get-open-orders", instrument)

    def open_stop_orders(self, instrument: Optional[str] = None) -> list[Order]:
        return self._open("private/advanced/get-open-orders", instrument)
