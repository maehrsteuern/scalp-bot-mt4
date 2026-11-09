"""Trade lifecycle engine.

Per coin one small explicit state machine (never two positions per coin):

    (IDLE) -> ENTRY_PENDING -> OPEN -> OPEN_BE -> CLOSING -> CLOSED
                  |                                   ^
                  +-> CANCELED          (OPEN/OPEN_BE -> CLOSING when the synthetic stop fires)

* ENTRY_PENDING : LIMIT buy placed, waiting for the fill.
* OPEN          : bought. LIMIT sell 50 % at T1 and LIMIT sell of the rest at T2 are resting. Stop = signal stop.
* OPEN_BE       : T1 filled. Stop moved to the entry price (break-even). Only T2 is resting.
* CLOSING       : synthetic stop (or kill/flatten) fired, MARKET sell sent, waiting for the fill.
* CLOSED/CANCELED : final.

The stop is SYNTHETIC: the exchange does not hold it. The engine fires a MARKET sell when the 30m candle low
(closed candles) or - in run mode - the ticker price (every minute) is <= stop. If the bot is not running,
there is NO stop. The state is saved to JSON after every change. The bot only sells quantities it bought itself.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .journal import Journal
from .models import Candle, Signal
from .risk import RiskConfig, daily_loss_hit, floor_to_tick, position_size

log = logging.getLogger("ewbot")

CANDLE_MS = 30 * 60 * 1000
H4_MS = 4 * 3600 * 1000
ACTIVE = ("ENTRY_PENDING", "OPEN", "OPEN_BE", "CLOSING")
POSITION = ("OPEN", "OPEN_BE", "CLOSING")


def utc_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --------------------------------------------------------------------------- state store
def new_state(mode: str, capital: float, now_ts: int = 0) -> Dict[str, Any]:
    return {
        "version": 1, "mode": mode, "created_ts": now_ts, "start_capital": float(capital),
        "cursor": {}, "trades": {}, "seen_signals": [], "pnl_events": [],
        "day": {"date": utc_date(now_ts) if now_ts else "", "start_equity": float(capital)},
        "equity_curve": [], "last_prices": {}, "halt_new": False, "log": [], "last_step_ts": 0,
    }


class StateStore:
    """JSON file with atomic writes. The broker state (paper) is stored under the key 'broker'."""

    def __init__(self, path: str):
        self.path = path

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def load(self) -> Dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, state: Dict[str, Any]) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


# --------------------------------------------------------------------------- engine
class Engine:
    def __init__(self, cfg, broker, state: Dict[str, Any], store: Optional[StateStore] = None,
                 journal: Optional[Journal] = None, infos: Optional[Dict[str, Any]] = None,
                 strategy_fn: Optional[Callable] = None, live: bool = False):
        self.cfg = cfg
        self.broker = broker
        self.state = state
        self.store = store
        self.journal = journal
        self.infos = infos or {}
        self.strategy_fn = strategy_fn
        self.live = live
        self.risk = RiskConfig(cfg.risk_pct, cfg.max_exposure_pct, cfg.daily_loss_cap_pct,
                               cfg.max_capital_usd, cfg.min_notional_usd)
        self.now_ts = int(state.get("last_step_ts") or 0)
        self.safe_mode = False          # set on API errors -> no new entries in this cycle
        self.events: List[Dict[str, Any]] = []
        self._prestop: Dict[str, bool] = {}

    # ----- small helpers
    def _say(self, msg: str, level: int = logging.INFO) -> None:
        log.log(level, msg)
        lines = self.state.setdefault("log", [])
        lines.append(f"{iso(self.now_ts) if self.now_ts else '-'} {msg}")
        del lines[:-200]

    def _err(self, msg: str, exc: Optional[BaseException] = None) -> None:
        self.safe_mode = True
        if exc is not None and type(exc).__name__ == "OrderStateUnknown":
            # request may or may not have reached the exchange: block new trades until reconcile/manual check
            self.state["halt_new"] = True
            msg += " (Order-Status unklar - neue Trades gesperrt)"
        self._say("FEHLER: " + msg, logging.ERROR)

    def persist(self) -> None:
        if self.store:
            if hasattr(self.broker, "to_dict"):
                self.state["broker"] = self.broker.to_dict()
            self.store.save(self.state)

    def begin_cycle(self, now_ts: Optional[int] = None) -> None:
        self.safe_mode = False
        if now_ts is not None:
            self.now_ts = int(now_ts)

    @property
    def trades(self) -> Dict[str, Dict[str, Any]]:
        return self.state["trades"]

    def active_trade(self, coin: str) -> Optional[Dict[str, Any]]:
        for t in self.trades.values():
            if t["coin"] == coin and t["state"] in ACTIVE:
                return t
        return None

    def kill_mode(self) -> Optional[str]:
        """None | 'cancel' | 'flatten' depending on the KILL file."""
        p = self.cfg.kill_path
        if not os.path.exists(p):
            return None
        try:
            txt = open(p, encoding="utf-8").read().lower()
        except OSError:
            txt = ""
        return "flatten" if "flatten" in txt else "cancel"

    def _info(self, instrument: str):
        return self.infos.get(instrument)

    def _round_qty(self, instrument: str, qty: float) -> float:
        try:
            return float(self.broker.round_qty(instrument, qty))
        except Exception:
            info = self._info(instrument)
            return floor_to_tick(qty, info.qty_tick) if info else qty

    def _oid(self, t: Dict[str, Any], kind: str) -> str:
        n = t.setdefault("oid_n", {})
        n[kind] = n.get(kind, 0) + 1
        suffix = "" if n[kind] == 1 else f"x{n[kind]}"
        return f"ew{t['coin']}{t['created_ts'] // 60000}{kind}{suffix}"

    # ----- accounting
    def unrealized(self, t: Dict[str, Any]) -> float:
        if t["state"] not in POSITION or not t.get("entry_qty"):
            return 0.0
        px = self.state["last_prices"].get(t["instrument"], t.get("entry_price") or 0.0)
        rem = t["remaining"]
        return rem * px - t["cost"] * rem / t["entry_qty"]

    def equity(self) -> float:
        realized = sum(t.get("realized", 0.0) for t in self.trades.values())
        unreal = sum(self.unrealized(t) for t in self.trades.values())
        return self.state["start_capital"] + realized + unreal

    def exposure(self) -> float:
        tot = 0.0
        for t in self.trades.values():
            if t["state"] == "ENTRY_PENDING":
                tot += t["qty"] * t["signal"]["entry"]
            elif t["state"] in POSITION:
                tot += t["remaining"] * (t.get("entry_price") or t["signal"]["entry"])
        return tot

    def realized_today(self, ts: int) -> float:
        d = utc_date(ts)
        return sum(e["pnl"] for e in self.state["pnl_events"] if utc_date(e["ts"]) == d)

    def _roll_day(self, ts: int) -> None:
        d = utc_date(ts)
        if self.state["day"].get("date") != d:
            self.state["day"] = {"date": d, "start_equity": self.equity()}

    def record_equity(self, ts: int) -> None:
        curve = self.state["equity_curve"]
        pt = {"ts": ts, "equity": round(self.equity(), 4)}
        if curve and curve[-1]["ts"] == ts:
            curve[-1] = pt
        elif not curve or curve[-1]["ts"] < ts:
            curve.append(pt)
        if len(curve) > 3000:
            del curve[1:1000:2]

    # ----- broker wrappers
    def _poll(self, order_id: Optional[str]):
        if not order_id:
            return None
        try:
            return self.broker.get_order(order_id)
        except Exception as e:  # noqa: BLE001 - any API problem => safe mode
            self._err(f"Order {order_id} nicht abrufbar: {e}")
            return None

    def _cancel(self, instrument: str, order_id: Optional[str]) -> bool:
        if not order_id:
            return True
        try:
            self.broker.cancel(instrument, order_id)
            return True
        except Exception as e:  # noqa: BLE001
            # order may already be filled/canceled - the following poll decides
            log.debug("Cancel %s: %s", order_id, e)
            return False

    # ----- recording fills
    def _record_buy(self, t: Dict[str, Any], o) -> None:
        qty = float(o.filled_qty)
        px = float(o.avg_price or t["signal"]["entry"])
        fee = float(o.fee or 0.0)
        t["entry_qty"] = qty
        t["entry_price"] = px
        t["entry_fee"] = fee
        t["cost"] = qty * px + fee
        t["remaining"] = qty
        t["fees"] = t.get("fees", 0.0) + fee
        t["opened_ts"] = self.now_ts
        self._log_fill(t, "BUY", qty, px, fee, o.order_id, "Einstieg")
        self.events.append({"type": "fill", "trade": t["id"], "coin": t["coin"], "side": "BUY",
                            "qty": qty, "price": px, "ts": self.now_ts})

    def _record_sell(self, t: Dict[str, Any], o, why: str) -> None:
        qty = min(float(o.filled_qty), t["remaining"])
        px = float(o.avg_price or o.price or 0.0)
        fee = float(o.fee or 0.0)
        proceeds = qty * px - fee
        pnl = proceeds - t["cost"] * qty / t["entry_qty"]
        t["remaining"] = max(0.0, t["remaining"] - qty)
        if t["remaining"] < 1e-12:
            t["remaining"] = 0.0
        t["realized"] = t.get("realized", 0.0) + pnl
        t["fees"] = t.get("fees", 0.0) + fee
        self.state["pnl_events"].append({"ts": self.now_ts, "pnl": pnl, "trade": t["id"]})
        self._log_fill(t, "SELL", qty, px, fee, o.order_id, why)
        self.events.append({"type": "exit", "trade": t["id"], "coin": t["coin"], "why": why,
                            "qty": qty, "price": px, "pnl": round(pnl, 4), "ts": self.now_ts})

    def _log_fill(self, t, side, qty, px, fee, order_id, note) -> None:
        t.setdefault("fills", []).append({"ts": self.now_ts, "side": side, "qty": qty, "price": px,
                                          "fee": fee, "order_id": order_id, "note": note})
        if self.journal:
            self.journal.append(self.now_ts, t["coin"], side, qty, px, fee, order_id, t["id"],
                                f"{self.state.get('mode', '')}: {note}")
        self._say(f"{t['coin']} {side} {qty:g} @ {px:g} ({note})")

    def _close(self, t: Dict[str, Any], reason: str) -> None:
        t["state"] = "CLOSED"
        t["closed_ts"] = self.now_ts
        t["close_reason"] = reason
        risk = t.get("risk_usd") or 0.0
        t["r_multiple"] = round(t.get("realized", 0.0) / risk, 3) if risk else None
        self._say(f"{t['coin']} geschlossen ({reason}), Ergebnis {t.get('realized', 0.0):+.2f} USD")

    # ----- new signals
    def consider_signal(self, sig: Signal, now_ts: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Open an ENTRY_PENDING trade for a signal if all risk rules allow it. Returns the trade or None."""
        now = now_ts if now_ts is not None else self.now_ts
        if sig.id in self.state["seen_signals"]:
            return None
        if sig.instrument != self.cfg.instrument(sig.coin) or sig.coin not in self.cfg.coins:
            self._say(f"Signal {sig.id} ignoriert: Instrument nicht erlaubt")
            return None
        if self.kill_mode() or self.state.get("halt_new") or self.safe_mode:
            return None
        if self.active_trade(sig.coin) is not None:
            return None
        if now >= sig.valid_until_ts:
            return None
        self._roll_day(now)
        if daily_loss_hit(self.state["day"]["start_equity"], self.realized_today(now), self.risk):
            self._say(f"{sig.coin}: Tagesverlust-Limit erreicht - kein neuer Einstieg bis zum naechsten UTC-Tag")
            return None
        info = self._info(sig.instrument)
        price = sig.entry
        try:
            price = float(self.broker.round_price(sig.instrument, sig.entry))
        except Exception:
            pass
        res = position_size(self.equity(), price, sig.stop, self.exposure(), self.risk,
                            qty_tick=getattr(info, "qty_tick", 0.0), min_qty=getattr(info, "min_qty", 0.0),
                            min_notional=getattr(info, "min_notional", 0.0))
        if not res.ok:
            self._say(f"{sig.coin}: kein Einstieg ({res.reason})")
            self.state["seen_signals"].append(sig.id)
            self.persist()
            return None
        try:
            free = float(self.broker.get_balances().get(self.cfg.quote, 0.0))
            if free < res.notional * (1 + self.cfg.taker_fee):
                self._say(f"{sig.coin}: nicht genug {self.cfg.quote} frei ({free:.2f} < {res.notional:.2f})")
                return None
        except Exception as e:  # noqa: BLE001
            self._err(f"Kontostand nicht abrufbar: {e}")
            return None
        t = {
            "id": sig.id, "coin": sig.coin, "instrument": sig.instrument, "state": "ENTRY_PENDING",
            "signal": sig.to_dict(), "created_ts": sig.created_ts, "placed_ts": now,
            "qty": res.qty, "risk_usd": res.risk_usd, "stop": sig.stop, "t1_done": False,
            "entry_order": None, "t1_order": None, "t2_order": None, "stop_order": None,
            "entry_qty": 0.0, "entry_price": None, "cost": 0.0, "remaining": 0.0, "realized": 0.0, "fees": 0.0,
        }
        self.state["seen_signals"].append(sig.id)
        self.trades[sig.id] = t
        try:
            t["entry_order"] = self.broker.place_limit(sig.instrument, "BUY", res.qty, price, self._oid(t, "E"))
        except Exception as e:  # noqa: BLE001
            del self.trades[sig.id]
            self._err(f"Entry-Order fuer {sig.coin} fehlgeschlagen: {e}", e)
            self.persist()
            return None
        self._say(f"{sig.coin}: Limit-Kauf {res.qty:g} @ {price:g}, Stop {sig.stop:g}, Risiko {res.risk_usd:.2f} USD")
        self.events.append({"type": "new_signal", "trade": sig.id, "coin": sig.coin, "entry": price,
                            "stop": sig.stop, "t1": sig.t1, "t2": sig.t2, "qty": res.qty, "ts": now})
        self.persist()
        return t

    # ----- order synchronisation (state machine transitions driven by order status)
    def sync_orders(self, instrument: Optional[str] = None) -> None:
        for t in list(self.trades.values()):
            if t["state"] not in ACTIVE or (instrument and t["instrument"] != instrument):
                continue
            before = (t["state"], t["remaining"], t["entry_qty"])
            if t["state"] == "ENTRY_PENDING":
                self._sync_entry(t)
            elif t["state"] in ("OPEN", "OPEN_BE"):
                self._sync_exits(t)
                if t["state"] in ("OPEN", "OPEN_BE") and t.get("stop_pending"):
                    self.stop_out(t, t["stop_pending"])
            elif t["state"] == "CLOSING":
                self._sync_closing(t)
            if before != (t["state"], t["remaining"], t["entry_qty"]):
                self.persist()

    def _sync_entry(self, t) -> None:
        o = self._poll(t["entry_order"])
        if o is None:
            return
        filled = float(o.filled_qty or 0.0)
        if o.status == "FILLED" or (o.status in ("CANCELED", "EXPIRED", "REJECTED") and filled > 0):
            self._record_buy(t, o)
            self._open_position(t)
        elif o.status in ("CANCELED", "EXPIRED", "REJECTED"):
            t["state"] = "CANCELED"
            t["closed_ts"] = self.now_ts
            t["close_reason"] = f"Order {o.status}"
            self._say(f"{t['coin']}: Entry-Order {o.status}")

    def _open_position(self, t) -> None:
        t["state"] = "OPEN"
        sig = t["signal"]
        qty = t["entry_qty"]
        inst = t["instrument"]
        t1q = self._round_qty(inst, qty * 0.5)
        info = self._info(inst)
        min_n = max(self.cfg.min_notional_usd, getattr(info, "min_notional", 0.0) or 0.0)
        t2q = self._round_qty(inst, qty - t1q)
        if t1q <= 0 or t2q <= 0 or t1q * sig["t1"] < min_n or t2q * sig["t2"] < min_n:
            t1q, t2q = 0.0, self._round_qty(inst, qty)
            t["t1_done"] = True        # position too small to split: everything goes to T2, no break-even move
        t["t1_qty"], t["t2_qty"] = t1q, t2q
        try:
            if t1q > 0:
                t["t1_order"] = self.broker.place_limit(inst, "SELL", t1q, float(self.broker.round_price(inst, sig["t1"])),
                                                         self._oid(t, "T1"))
            t["t2_order"] = self.broker.place_limit(inst, "SELL", t2q, float(self.broker.round_price(inst, sig["t2"])),
                                                     self._oid(t, "T2"))
        except Exception as e:  # noqa: BLE001
            self._err(f"Take-Profit-Order fuer {t['coin']} fehlgeschlagen: {e} (Position bleibt mit Stop offen)", e)
            t["exit_orders_missing"] = True
        self.persist()

    def _sync_exits(self, t) -> None:
        if t.get("exit_orders_missing"):
            self._replace_exits(t)
        if not t["t1_done"] and t.get("t1_order"):
            o = self._poll(t["t1_order"])
            if o is not None and o.status == "FILLED":
                self._record_sell(t, o, "Ziel 1")
                t["t1_done"] = True
                if t["remaining"] > 0:
                    t["state"] = "OPEN_BE"
                    t["stop"] = t["entry_price"]
                    self._say(f"{t['coin']}: Ziel 1 erreicht - Stop auf Einstieg {t['entry_price']:g}")
        if t.get("t2_order") and not t.get("t2_done") and t["state"] in ("OPEN", "OPEN_BE"):
            o = self._poll(t["t2_order"])
            if o is not None and o.status == "FILLED":
                self._record_sell(t, o, "Ziel 2")
                t["t2_done"] = True
        if t["state"] in ("OPEN", "OPEN_BE") and t["remaining"] <= 1e-12:
            self._close(t, "Ziel 2" if t.get("t2_done") else "Ziele")

    def _replace_exits(self, t) -> None:
        inst, sig = t["instrument"], t["signal"]
        try:
            if t["t1_qty"] > 0 and not t["t1_done"] and not t.get("t1_order"):
                t["t1_order"] = self.broker.place_limit(inst, "SELL", t["t1_qty"],
                                                         float(self.broker.round_price(inst, sig["t1"])), self._oid(t, "T1"))
            if not t.get("t2_order"):
                rest = t["remaining"] - (0 if t["t1_done"] else t["t1_qty"])
                t["t2_order"] = self.broker.place_limit(inst, "SELL", self._round_qty(inst, rest),
                                                         float(self.broker.round_price(inst, sig["t2"])), self._oid(t, "T2"))
            t["exit_orders_missing"] = False
        except Exception as e:  # noqa: BLE001
            self._err(f"Take-Profit-Order {t['coin']} erneut fehlgeschlagen: {e}")

    def _sync_closing(self, t) -> None:
        o = self._poll(t.get("stop_order"))
        if o is None:
            return
        if o.status == "FILLED" or (o.status in ("CANCELED", "EXPIRED") and float(o.filled_qty or 0) > 0):
            self._record_sell(t, o, t.get("close_why", "Stop"))
            if t["remaining"] > 1e-12:           # partial: sell the rest again
                t["state"] = "OPEN"
                self.stop_out(t, t.get("close_why", "Stop"))
            else:
                self._close(t, t.get("close_why", "Stop"))
        elif o.status in ("CANCELED", "EXPIRED", "REJECTED"):
            self._say(f"{t['coin']}: Stop-Verkauf {o.status} - neuer Versuch", logging.WARNING)
            t["state"] = "OPEN"
            t["stop_pending"] = t.get("close_why", "Stop")

    # ----- synthetic stop
    def stop_out(self, t, why: str = "Stop") -> None:
        """Cancel resting exits and sell the rest of the bot's own position at MARKET."""
        if t["state"] not in ("OPEN", "OPEN_BE"):
            return
        inst = t["instrument"]
        for k in ("t1_order", "t2_order"):
            if t.get(k):
                self._cancel(inst, t[k])
        # exits may have filled while we cancelled -> take them into account first
        for k, label, done in (("t1_order", "Ziel 1", "t1_done"), ("t2_order", "Ziel 2", "t2_done")):
            if t.get(k) and not t.get(done):
                o = self._poll(t[k])
                if o is not None and o.status in ("FILLED", "CANCELED", "EXPIRED") and float(o.filled_qty or 0) > 0:
                    self._record_sell(t, o, label)
                    t[done] = True
        t["t1_order"] = t["t2_order"] = None
        if t["remaining"] <= 1e-12:
            self._close(t, "Ziele")
            self.persist()
            return
        qty = self._round_qty(inst, t["remaining"])
        if self.live:                      # never sell more than is really there
            try:
                base = inst.split("_")[0]
                qty = min(qty, self._round_qty(inst, float(self.broker.get_balances().get(base, 0.0))))
            except Exception as e:  # noqa: BLE001
                self._err(f"Bestand nicht abrufbar: {e}")
        if qty <= 0:
            self._err(f"{t['coin']}: keine verkaufbare Menge gefunden - bitte manuell pruefen")
            t["stop_pending"] = why
            self.persist()
            return
        try:
            t["stop_order"] = self.broker.place_market(inst, "SELL", qty, self._oid(t, "S"))
        except Exception as e:  # noqa: BLE001
            self._err(f"STOP-VERKAUF {t['coin']} fehlgeschlagen: {e} - neuer Versuch im naechsten Durchlauf", e)
            t["stop_pending"] = why
            self.persist()
            return
        t["stop_pending"] = None
        t["state"] = "CLOSING"
        t["close_why"] = why
        self._say(f"{t['coin']}: {why} ausgeloest - Markt-Verkauf {qty:g}", logging.WARNING)
        self.persist()

    def cancel_entry(self, t, why: str) -> None:
        if t["state"] != "ENTRY_PENDING":
            return
        self._cancel(t["instrument"], t["entry_order"])
        o = self._poll(t["entry_order"])
        if o is not None and float(o.filled_qty or 0) > 0:     # got (partly) filled in the meantime
            self._record_buy(t, o)
            self._open_position(t)
            return
        if o is None and self.live:
            return                                             # unknown -> keep, retry next cycle
        t["state"] = "CANCELED"
        t["closed_ts"] = self.now_ts
        t["close_reason"] = why
        self.events.append({"type": "cancel", "trade": t["id"], "coin": t["coin"], "why": why, "ts": self.now_ts})
        self._say(f"{t['coin']}: Entry storniert ({why})")
        self.persist()

    # ----- kill switch
    def apply_kill(self) -> None:
        mode = self.kill_mode()
        if not mode:
            return
        for t in list(self.trades.values()):
            if t["state"] == "ENTRY_PENDING":
                self.cancel_entry(t, "KILL")
            elif mode == "flatten" and t["state"] in ("OPEN", "OPEN_BE"):
                self.stop_out(t, "KILL (flatten)")

    # ----- candle processing (paper-step and closed candles in run mode)
    def handle_candle(self, instrument: str, c: Candle, hist30: Optional[List[Candle]] = None,
                      hist4h: Optional[List[Candle]] = None) -> None:
        close_ts = c.t + CANDLE_MS
        self.now_ts = close_ts
        self.state["last_step_ts"] = close_ts
        self._roll_day(close_ts)
        self.state["last_prices"][instrument] = c.c
        mine = [t for t in self.trades.values() if t["instrument"] == instrument and t["state"] in ACTIVE]
        stop_before = {t["id"]: t["stop"] for t in mine}

        # A) pessimistic pre-phase: expiry before the candle; if the low reaches the stop, resting take-profits
        #    must not fill on this candle (we cannot know the order inside a candle).
        for t in mine:
            if t["state"] == "ENTRY_PENDING" and c.t >= t["signal"]["valid_until_ts"]:
                self.cancel_entry(t, "abgelaufen")
            elif t["state"] in ("OPEN", "OPEN_BE") and c.l <= t["stop"]:
                for k in ("t1_order", "t2_order"):
                    if t.get(k):
                        self._cancel(instrument, t[k])
        # B) paper broker: fill resting orders against the candle
        if hasattr(self.broker, "on_candle"):
            self.broker.on_candle(instrument, c)
        # C) order status -> state transitions
        self.sync_orders(instrument)
        # D) synthetic stop on the candle low (stop level as it was before this candle)
        for t in list(self.trades.values()):
            if t["instrument"] == instrument and t["state"] in ("OPEN", "OPEN_BE"):
                if c.l <= stop_before.get(t["id"], t["stop"]):
                    self.stop_out(t, "Stop" if t["state"] == "OPEN" else "Stop (Break-even)")
        # E) cancel unfilled entries: price already at/above target, or close under the wave low
        for t in list(self.trades.values()):
            if t["instrument"] == instrument and t["state"] == "ENTRY_PENDING":
                sig = t["signal"]
                if c.h >= sig["cancel_above"]:
                    self.cancel_entry(t, "Kurs hat Ziel erreicht ohne Ausfuehrung")
                elif c.c < sig["wave_low"]:
                    self.cancel_entry(t, "Kurs unter Wellen-Tief")
                elif close_ts >= sig["valid_until_ts"]:
                    self.cancel_entry(t, "abgelaufen")
        self.apply_kill()
        self.state["cursor"][instrument] = c.t
        # F) new signal for this coin (only if flat)
        coin = instrument.split("_")[0]
        if self.strategy_fn and hist30 is not None and coin in self.cfg.coins and self.active_trade(coin) is None \
                and not self.kill_mode():
            try:
                c4 = [x for x in (hist4h or []) if x.t + H4_MS <= close_ts]
                for sig in self.strategy_fn(coin, instrument, hist30, c4, now_ts=close_ts) or []:
                    self.consider_signal(sig, close_ts)
            except Exception as e:  # noqa: BLE001
                self._err(f"Strategie-Fehler {coin}: {e}")
        self.persist()

    # ----- ticker check (run mode, every minute)
    def check_price(self, instrument: str, bid: float, last: float, ts_ms: int) -> None:
        self.now_ts = ts_ms
        self.state["last_prices"][instrument] = last
        px = min(bid, last) if bid else last
        for t in list(self.trades.values()):
            if t["instrument"] != instrument:
                continue
            if t["state"] in ("OPEN", "OPEN_BE") and px <= t["stop"]:
                self.sync_orders(instrument)         # book fills that happened first
                if t["state"] in ("OPEN", "OPEN_BE"):
                    self.stop_out(t, "Stop" if t["state"] == "OPEN" else "Stop (Break-even)")
            elif t["state"] == "ENTRY_PENDING":
                sig = t["signal"]
                if last >= sig["cancel_above"]:
                    self.sync_orders(instrument)
                    if t["state"] == "ENTRY_PENDING":
                        self.cancel_entry(t, "Kurs hat Ziel erreicht ohne Ausfuehrung")
                elif ts_ms >= sig["valid_until_ts"]:
                    self.cancel_entry(t, "abgelaufen")

    # ----- reconciliation (live start)
    def reconcile(self) -> List[str]:
        issues: List[str] = []
        known = set()
        for t in self.trades.values():
            if t["state"] not in ACTIVE:
                continue
            for k in ("entry_order", "t1_order", "t2_order", "stop_order"):
                oid = t.get(k)
                if not oid:
                    continue
                known.add(oid)
                try:
                    self.broker.get_order(oid)
                except Exception as e:  # noqa: BLE001
                    issues.append(f"{t['coin']}: Order {oid} ({k}) nicht auffindbar: {e}")
        try:
            for o in self.broker.open_orders():
                if o.order_id not in known and str(o.client_oid).startswith("ew"):
                    issues.append(f"Unbekannte Bot-Order auf der Boerse: {o.order_id} {o.instrument} {o.side}")
            bal = self.broker.get_balances()
            for inst in self.cfg.instruments.values():
                need = sum(t["remaining"] for t in self.trades.values()
                           if t["instrument"] == inst and t["state"] in POSITION)
                have = float(bal.get(inst.split("_")[0], 0.0))
                if need > 0 and have + 1e-9 < need * 0.995:
                    issues.append(f"{inst}: Bestand {have:g} kleiner als erwartet {need:g}")
        except Exception as e:  # noqa: BLE001
            issues.append(f"Abgleich mit der Boerse fehlgeschlagen: {e}")
        if issues:
            self.state["halt_new"] = True
            for i in issues:
                self._err("Abgleich: " + i)
            self._say("Keine neuen Trades, bis das geklaert ist (python -m ewbot status --clear-halt)", logging.ERROR)
        self.persist()
        return issues

    def sync_journal(self) -> None:
        """Re-create missing journal rows from the fills kept in the state (journal dedups by order id)."""
        if not self.journal:
            return
        for t in self.trades.values():
            for f in t.get("fills", []):
                self.journal.append(f["ts"], t["coin"], f["side"], f["qty"], f["price"], f["fee"],
                                    f["order_id"], t["id"], f"{self.state.get('mode', '')}: {f['note']}")

    # ----- manual signals
    def seed_manual(self, path: str) -> List[str]:
        sigs = load_manual_signals(path, self.cfg)
        added = []
        for s in sigs:
            if s.id in self.state["seen_signals"]:
                continue
            if self.consider_signal(s, max(self.now_ts, s.created_ts)):
                added.append(s.id)
        return added

    # ----- summaries
    def summary(self) -> Dict[str, Any]:
        trades = list(self.trades.values())
        closed = [t for t in trades if t["state"] == "CLOSED"]
        wins = [t for t in closed if t.get("realized", 0) > 0]
        return {
            "equity": round(self.equity(), 2), "start_capital": self.state["start_capital"],
            "open": [t["id"] for t in trades if t["state"] in POSITION],
            "pending": [t["id"] for t in trades if t["state"] == "ENTRY_PENDING"],
            "closed": len(closed), "wins": len(wins),
            "realized": round(sum(t.get("realized", 0.0) for t in trades), 2),
            "halt_new": bool(self.state.get("halt_new")), "kill": self.kill_mode(),
        }


# --------------------------------------------------------------------------- manual signals
def load_manual_signals(path: str, cfg) -> List[Signal]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    created = int(data.get("created_ts") or datetime(2026, 11, 8, 22, 50, tzinfo=timezone.utc).timestamp() * 1000)
    valid = int(data.get("valid_until_ts") or datetime(2026, 11, 10, 22, 50, tzinfo=timezone.utc).timestamp() * 1000)
    out = []
    for coin, d in data["coins"].items():
        if coin not in cfg.coins:
            continue
        out.append(Signal(
            coin=coin, instrument=cfg.instrument(coin), created_ts=created, valid_until_ts=valid,
            entry=float(d["entry"]), stop=float(d["stop"]), t1=float(d["t1"]), t2=float(d["t2"]),
            wave_low=float(d.get("low", d["stop"])), wave1_high=float(d.get("bounce", d["t1"])),
            cancel_above=float(d.get("cancel_above", d["t1"])), score=0.0,
            fib_hits=[f"Rally 61,8 % {d['fib_rally']['0.618']}"] if d.get("fib_rally") else [],
            reason_de="Manuelles Signal vom 08.11.2026 (Rally-Rücksetzer + Gegenbewegung)",
            id=f"{coin}-{created}"))
    return out


# --------------------------------------------------------------------------- orchestration
def collect_new_candles(client, instrument: str, last_t: Optional[int], now_ts: int) -> List[Candle]:
    """Closed 30m candles with t > last_t (or just the newest closed one if last_t is None)."""
    if last_t is None:
        count = 5
    else:
        count = int((now_ts - last_t) // CANDLE_MS) + 5
    count = max(5, count)
    if count > 300 and hasattr(client, "get_candles_paged"):
        cs = client.get_candles_paged(instrument, "30m", count)
    else:
        cs = client.get_candles(instrument, "30m", min(count, 300))
    cs = sorted(cs, key=lambda x: x.t)
    return [c for c in cs if c.t + CANDLE_MS <= now_ts]


def run_paper_step(engine: Engine, client, now_ts: int, seed_path: Optional[str] = None) -> Dict[str, Any]:
    """One deterministic step: process every closed 30m candle since the last step. Safe to repeat."""
    cfg = engine.cfg
    engine.begin_cycle(now_ts)
    engine.events = []
    engine.sync_journal()
    fresh = not engine.state["cursor"]
    seeded: List[str] = []
    seed_sigs = load_manual_signals(seed_path, cfg) if seed_path else []
    if seed_sigs and fresh:     # replay from the signal time so fills since then are simulated
        first = -(-min(s.created_ts for s in seed_sigs) // CANDLE_MS) * CANDLE_MS   # first candle opening after creation
        for inst in cfg.instruments.values():
            engine.state["cursor"][inst] = first - CANDLE_MS
        engine.now_ts = min(s.created_ts for s in seed_sigs)
    # candles
    work: List[tuple] = []
    hist: Dict[str, List[Candle]] = {}
    hist4: Dict[str, List[Candle]] = {}
    for coin, inst in cfg.instruments.items():
        last_t = engine.state["cursor"].get(inst)
        new = collect_new_candles(client, inst, last_t, now_ts)
        if last_t is None and new:        # first run without seed: start at the newest closed candle, no backfill
            engine.state["cursor"][inst] = new[-1].t - CANDLE_MS
            last_t = new[-1].t - CANDLE_MS
        new = [c for c in new if c.t > (last_t if last_t is not None else -1)]
        full = sorted(client.get_candles(inst, "30m", 300), key=lambda x: x.t)
        hist[inst] = full
        try:
            hist4[inst] = sorted(client.get_candles(inst, "4h", 300), key=lambda x: x.t)
        except Exception as e:  # noqa: BLE001
            engine._err(f"4h-Daten {inst}: {e}")
            hist4[inst] = []
        work += [(c.t, inst, c) for c in new]
    if seed_sigs and fresh:
        seeded = engine.seed_manual(seed_path)
    elif seed_sigs:
        for s in seed_sigs:
            if s.id not in engine.state["seen_signals"]:
                if engine.consider_signal(s, now_ts):
                    seeded.append(s.id)
    work.sort(key=lambda x: (x[0], x[1]))
    n = 0
    for t, inst, c in work:
        h30 = [x for x in hist[inst] if x.t <= c.t]
        engine.handle_candle(inst, c, h30, hist4[inst])
        engine.record_equity(c.t + CANDLE_MS)
        n += 1
    if not work:
        engine.sync_orders()            # nothing new: still pick up order states
    engine.apply_kill()
    engine.persist()
    ev = engine.events
    out = engine.summary()
    out.update({
        "candles_processed": n, "seeded": seeded,
        "new_signals": [e["trade"] for e in ev if e["type"] == "new_signal"],
        "fills": [e for e in ev if e["type"] == "fill"],
        "exits": [e for e in ev if e["type"] == "exit"],
        "canceled": [e for e in ev if e["type"] == "cancel"],
    })
    return out


def run_loop(engine: Engine, client, stop_flag: Callable[[], bool], poll_s: int = 60,
             sleep: Callable[[float], None] = time.sleep) -> None:
    """Long-running loop: every minute ticker check + sync, new closed 30m candle -> handle_candle."""
    cfg = engine.cfg
    if engine.live:
        engine.reconcile()
    while not stop_flag():
        now_ts = int(time.time() * 1000)
        try:
            run_cycle(engine, client, now_ts)
        except Exception as e:  # noqa: BLE001 - never die silently, never open trades on errors
            engine._err(f"Durchlauf fehlgeschlagen: {e}")
        for _ in range(poll_s):
            if stop_flag():
                break
            sleep(1)


def run_cycle(engine: Engine, client, now_ts: int) -> None:
    engine.begin_cycle(now_ts)
    engine.events = []
    cfg = engine.cfg
    engine.apply_kill()
    # new closed candles first (they decide entries), then ticker stops
    for coin, inst in cfg.instruments.items():
        last_t = engine.state["cursor"].get(inst)
        try:
            new = collect_new_candles(client, inst, last_t, now_ts)
            if last_t is None and new:
                engine.state["cursor"][inst] = new[-1].t - CANDLE_MS
                last_t = new[-1].t - CANDLE_MS
            new = [c for c in new if c.t > last_t]
            if new:
                h30 = sorted(client.get_candles(inst, "30m", 300), key=lambda x: x.t)
                h4 = sorted(client.get_candles(inst, "4h", 300), key=lambda x: x.t)
            for c in new:
                engine.handle_candle(inst, c, [x for x in h30 if x.t <= c.t], h4)
                engine.record_equity(c.t + CANDLE_MS)
        except Exception as e:  # noqa: BLE001
            engine._err(f"Kerzen {inst}: {e}")
        try:
            tk = client.get_ticker(inst)
            engine.check_price(inst, float(tk.get("bid") or 0), float(tk.get("last") or 0), now_ts)
        except Exception as e:  # noqa: BLE001
            engine._err(f"Ticker {inst}: {e}")
    engine.sync_orders()
    engine.persist()
