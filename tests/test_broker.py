import ccxt
import pytest

from ewbot.broker import CcxtBroker, PaperBroker
from ewbot.config import BotCfg, MarketCfg
from ewbot.models import (Candle, PatternType, SetupType, Side, Signal, Swing, SwingKind,
                          WaveCount)


def make_signal(symbol="BTC/USD:USD", side=Side.LONG, entry=100.0, stop=98.0, tp1=105.0,
                tp2=110.0, ts=0):
    swings = [Swing(0, 0, 90.0, SwingKind.LOW), Swing(5, 5, 100.0, SwingKind.HIGH),
              Swing(9, 9, 95.0, SwingKind.LOW)]
    count = WaveCount(PatternType.IMPULSE, side, swings, [90.0, 100.0, 95.0, entry], False, 0.8)
    return Signal(symbol, "15m", side, SetupType.WAVE3, entry, stop, tp1, tp2, ts, 0.8, count, [])


def cfg(slippage=0.0, fee=0.075, equity=1000.0):
    c = BotCfg()
    c.risk.slippage_pct = slippage
    c.risk.fee_pct = fee
    c.exchange.paper_start_equity = equity
    return c


def candle(ts, o, h, l, c):
    return Candle(ts, o, h, l, c, 1.0)


def test_paper_tp1_partial_be_then_tp2_pnl_net_of_fees():
    b = PaperBroker(cfg())
    pos = b.open(make_signal(), 1.0, ts=0)
    assert pos is not None and pos.id == "BTC/USD:USD-0-1"
    f = 0.075 / 100
    assert b.cash() == pytest.approx(1000 - 100 * f)
    # candle reaches TP1 only
    recs = b.on_candle(pos.symbol, candle(1, 100.5, 105.5, 100.5, 104))
    assert recs == []
    assert pos.tp1_done and pos.be_moved and pos.stop == pytest.approx(100.0)
    assert pos.qty_open == pytest.approx(0.5)
    # equity = cash + unrealized at last price (104)
    assert b.equity() == pytest.approx(b.cash() + 0.5 * 4)
    # candle reaches TP2
    recs = b.on_candle(pos.symbol, candle(2, 104, 111, 103, 110))
    assert len(recs) == 1
    expected = 0.5 * 5 + 0.5 * 10 - (100 * f + 0.5 * 105 * f + 0.5 * 110 * f)
    rec = recs[0]
    assert rec.pnl == pytest.approx(expected)
    assert rec.reason == "tp2"
    assert rec.exit_price == pytest.approx(107.5)
    assert rec.pnl_pct == pytest.approx(expected / 1000 * 100)
    assert b.positions() == []
    assert b.cash() == pytest.approx(1000 + expected)
    assert b.equity() == pytest.approx(1000 + expected)
    reasons = [x.reason for x in b.pop_fills()]
    assert reasons == ["entry", "tp1", "tp2"]
    assert b.pop_fills() == []


def test_paper_stop_first_when_stop_and_tp_in_same_candle():
    b = PaperBroker(cfg())
    pos = b.open(make_signal(), 1.0, ts=0)
    recs = b.on_candle(pos.symbol, candle(1, 100, 111, 97, 105))   # touches SL, TP1 and TP2
    assert len(recs) == 1 and recs[0].reason == "stop"
    f = 0.075 / 100
    assert recs[0].pnl == pytest.approx(-2.0 - 100 * f - 98 * f)
    assert not recs[0].position.tp1_done


def test_paper_tp1_then_be_stop_same_candle_is_pessimistic():
    b = PaperBroker(cfg(fee=0.0))
    pos = b.open(make_signal(), 1.0, ts=0)
    recs = b.on_candle(pos.symbol, candle(1, 101, 106, 99.5, 101))   # TP1 hit, low below entry
    assert len(recs) == 1 and recs[0].reason == "stop"
    assert recs[0].pnl == pytest.approx(0.5 * 5)


def test_paper_candle_of_entry_is_ignored_and_gap_through_stop():
    b = PaperBroker(cfg(fee=0.0))
    pos = b.open(make_signal(ts=10), 1.0, ts=10)
    assert b.on_candle(pos.symbol, candle(10, 100, 120, 80, 100)) == []
    recs = b.on_candle(pos.symbol, candle(11, 95, 96, 94, 95))   # opens below the stop
    assert recs[0].exit_price == pytest.approx(95.0)


def test_paper_slippage_short_and_spot_rules():
    b = PaperBroker(cfg(slippage=0.1, fee=0.0, equity=20.0))
    # spot short refused
    assert b.open(make_signal(symbol="BTC/USD", side=Side.SHORT, stop=102, tp1=95, tp2=90), 1, 0) is None
    # spot long capped by free cash (20 USD can't buy 0.5 @ 100)
    pos = b.open(make_signal(symbol="BTC/USD"), 0.5, 0)
    assert pos.entry == pytest.approx(100.1)
    assert pos.qty * pos.entry == pytest.approx(20.0)
    # perp short allowed, exit slippage adverse (buy higher)
    b2 = PaperBroker(cfg(slippage=0.1, fee=0.0))
    s = b2.open(make_signal(side=Side.SHORT, stop=102, tp1=95, tp2=90), 1.0, 0)
    assert s.entry == pytest.approx(99.9)
    fill = b2.close(s, 1.0, 95.0, 5, "manual")
    assert fill.price == pytest.approx(95.095) and fill.side is Side.LONG
    assert b2.trades()[0].pnl == pytest.approx(99.9 - 95.095)


def test_paper_snapshot_roundtrip():
    b = PaperBroker(cfg())
    b.open(make_signal(), 1.0, 0)
    b.on_candle("BTC/USD:USD", candle(1, 100.5, 105.5, 100.5, 104))
    snap = b.snapshot()
    b2 = PaperBroker(cfg())
    b2.restore_snapshot(snap)
    assert b2.cash() == pytest.approx(b.cash())
    assert b2.positions()[0] == b.positions()[0]
    assert b2.equity() == pytest.approx(b.equity())


# ---------------------------------------------------------------- CcxtBroker
class FakeExchange:
    def __init__(self, quote_free=100.0, min_cost=None):
        self.orders = []
        self.cancelled = []
        self.quote_free = quote_free
        self.min_cost = min_cost
        self.fail_stop = True

    def load_markets(self):
        return {}

    def market(self, symbol):
        return {"symbol": symbol, "limits": {"cost": {"min": self.min_cost}, "amount": {"min": None}}}

    def amount_to_precision(self, symbol, amount):
        return f"{int(amount * 1e5) / 1e5:.5f}"

    def price_to_precision(self, symbol, price):
        return f"{price:.2f}"

    def fetch_balance(self):
        return {"total": {"USD": self.quote_free, "BTC": 1.0},
                "free": {"USD": self.quote_free, "BTC": 1.0}}

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        params = params or {}
        if "stopLossPrice" in params and self.fail_stop:
            raise RuntimeError("stop orders not supported")
        oid = str(len(self.orders) + 1)
        self.orders.append({"id": oid, "symbol": symbol, "type": type, "side": side,
                            "amount": amount, "price": price, "params": params})
        fill_price = 100.0 if side == "buy" else 105.0
        return {"id": oid, "average": fill_price, "filled": amount, "status": "closed"}

    def cancel_order(self, oid, symbol):
        self.cancelled.append(oid)

    def fetch_ticker(self, symbol):
        return {"last": 101.0}


def live_cfg():
    c = BotCfg()
    c.markets = [MarketCfg("BTC/USD", min_notional=5.0), MarketCfg("BTC/USD:USD", min_notional=5.0)]
    return c


def test_ccxt_market_buy_and_reduce_only_exit():
    ex = FakeExchange()
    b = CcxtBroker(live_cfg(), exchange=ex)
    pos = b.open(make_signal(symbol="BTC/USD"), 0.123456789, ts=0)
    assert pos is not None
    o = ex.orders[0]
    assert (o["type"], o["side"], o["amount"]) == ("market", "buy", 0.12345)
    assert pos.qty == pytest.approx(0.12345) and pos.entry == 100.0
    assert "stop_order_id" not in pos.tags          # stop placement failed but did not crash
    assert b.last_price("BTC/USD") == 100.0
    assert b.equity() == pytest.approx(100.0 + 0.12345 * 100.0)

    fill = b.close(pos, pos.qty_open, 105.0, 1, "manual")
    assert fill is not None and fill.price == 105.0
    assert ex.orders[-1]["side"] == "sell" and "reduceOnly" not in ex.orders[-1]["params"]
    assert ex.orders[-1]["params"]["clientOrderId"].startswith("ewb")
    assert b.trades()[0].pnl == pytest.approx(0.12345 * 5 - 0.075 / 100 * (0.12345 * 100 + 0.12345 * 105))

    # perp exit uses reduceOnly
    ex.fail_stop = False
    perp = b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=2)
    assert perp.tags.get("stop_order_id")
    b.close(perp, 0.2, 105.0, 3, "manual")
    assert ex.orders[-1]["params"]["reduceOnly"] is True
    assert perp.tags.get("stop_order_id") is None and ex.cancelled


def test_ccxt_refuses_below_min_cost_and_spot_short():
    ex = FakeExchange()
    b = CcxtBroker(live_cfg(), exchange=ex)
    assert b.open(make_signal(symbol="BTC/USD"), 0.01, ts=0) is None        # 1 USD < 5 USD fallback
    ex.min_cost = 50.0
    assert b.open(make_signal(symbol="BTC/USD"), 0.3, ts=0) is None         # 30 USD < exchange 50
    assert b.open(make_signal(symbol="BTC/USD", side=Side.SHORT, stop=102, tp1=95, tp2=90), 1, 0) is None
    assert ex.orders == []


def test_ccxt_exchange_errors_never_raise():
    class Broken(FakeExchange):
        def create_order(self, *a, **k):
            raise RuntimeError("boom")

        def fetch_balance(self):
            raise RuntimeError("down")

    b = CcxtBroker(live_cfg(), exchange=Broken())
    assert b.open(make_signal(symbol="BTC/USD:USD"), 0.5, ts=0) is None
    assert b.equity() is None and b.cash() == 0.0      # never fetched -> unknown, not 0


def test_ccxt_on_candle_sends_market_exit_on_stop():
    ex = FakeExchange()
    b = CcxtBroker(live_cfg(), exchange=ex)
    pos = b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0)
    recs = b.on_candle("BTC/USD:USD", candle(1, 99, 99.5, 97.5, 98))
    assert len(recs) == 1 and recs[0].reason == "stop"
    assert ex.orders[-1]["side"] == "sell" and ex.orders[-1]["params"]["reduceOnly"] is True
    assert b.positions() == []


# ---------------------------------------------------------------- audit fixes
TFMS = 15 * 60_000


def test_paper_bar_after_entry_is_checked_and_exit_stamped_with_close_time():
    """Entry on bar N (opened at N's close == N+1's open ts); a stop inside bar N+1 must execute."""
    b = PaperBroker(cfg(fee=0.0))
    n_ts = 1_000 * TFMS
    pos = b.open(make_signal(ts=n_ts), 1.0, ts=n_ts + TFMS)          # backtest: now = close time of N
    assert pos.tags["signal_ts"] == str(n_ts)
    assert b.on_candle(pos.symbol, candle(n_ts, 100, 120, 80, 100)) == []   # signal candle itself skipped
    recs = b.on_candle(pos.symbol, candle(n_ts + TFMS, 100, 100.5, 97.0, 99))
    assert len(recs) == 1 and recs[0].reason == "stop"
    assert recs[0].exit_price == pytest.approx(98.0)
    assert recs[0].closed_ts == n_ts + 2 * TFMS                        # close time of bar N+1
    fills = b.pop_fills()
    assert fills[-1].reason == "stop" and fills[-1].ts == n_ts + 2 * TFMS


def test_paper_bar_after_entry_checked_with_live_wallclock_open_ts():
    b = PaperBroker(cfg(fee=0.0))
    n_ts = 1_000 * TFMS
    pos = b.open(make_signal(ts=n_ts), 1.0, ts=n_ts + TFMS + 7_000)    # live: wall clock after N's close
    recs = b.on_candle(pos.symbol, candle(n_ts + TFMS, 100.5, 106, 100.5, 104))
    assert recs == [] and pos.tp1_done                                  # TP1 partial executed on N+1


class FillExchange(FakeExchange):
    """create_order result is configurable; fetch_order looks up stored orders by id / client id."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.fail_stop = False
        self.create_result = None          # callable(order) -> dict returned by create_order
        self.raise_on_create = None        # exception raised by create_order (after recording it)
        self.stored = {}                   # id or client id -> order dict for fetch_order
        self.balance_base_total = 1.0

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        params = params or {}
        oid = str(len(self.orders) + 1)
        rec = {"id": oid, "symbol": symbol, "type": type, "side": side, "amount": amount,
               "price": price, "params": params}
        self.orders.append(rec)
        if "stopLossPrice" in params:
            return {"id": oid, "status": "open", "filled": 0.0}
        if self.raise_on_create is not None:
            raise self.raise_on_create
        if self.create_result is not None:
            return self.create_result(rec)
        return {"id": oid, "average": 100.0 if side == "buy" else 105.0, "filled": amount, "status": "closed"}

    def fetch_order(self, oid, symbol=None, params=None):
        if oid in self.stored:
            return self.stored[oid]
        raise ccxt.OrderNotFound(oid)

    def fetch_balance(self):
        return {"total": {"USD": self.quote_free, "BTC": self.balance_base_total},
                "free": {"USD": self.quote_free, "BTC": self.balance_base_total}}


def test_ccxt_zero_fill_is_not_booked():
    ex = FillExchange()
    ex.create_result = lambda rec: {"id": rec["id"], "filled": 0.0, "average": None, "status": "canceled"}
    b = CcxtBroker(live_cfg(), exchange=ex)
    assert b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0) is None
    assert b.positions() == [] and b.pop_fills() == []

    # filled unknown -> fetched once; still 0 / open -> not booked
    ex.create_result = lambda rec: {"id": rec["id"]}
    ex.stored = {str(len(ex.orders) + 1): {"id": "x", "filled": 0.0, "status": "open"}}
    assert b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0) is None
    assert b.positions() == []


def test_ccxt_partial_fill_books_only_filled_qty():
    ex = FillExchange()
    ex.create_result = lambda rec: {"id": rec["id"], "filled": 0.1, "average": 100.0, "status": "closed"}
    b = CcxtBroker(live_cfg(), exchange=ex)
    pos = b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0)
    assert pos is not None and pos.qty == pytest.approx(0.1)


def test_ccxt_network_error_on_create_is_reconciled_by_client_id():
    ex = FillExchange()
    ex.raise_on_create = ccxt.RequestTimeout("timeout")
    b = CcxtBroker(live_cfg(), exchange=ex)
    # order not found anywhere -> nothing booked
    assert b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0) is None
    assert b.positions() == []

    # the order did reach the exchange: fetch_order by client id finds the fill
    orig = ex.create_order

    def create_and_store(symbol, type, side, amount, price=None, params=None):
        cid = (params or {}).get("clientOrderId")
        if cid and "stopLossPrice" not in (params or {}):
            ex.stored[cid] = {"id": "srv-9", "clientOrderId": cid, "filled": amount, "average": 100.5,
                              "status": "closed"}
        return orig(symbol, type, side, amount, price, params)

    ex.create_order = create_and_store
    pos = b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0)
    assert pos is not None and pos.qty == pytest.approx(0.2) and pos.entry == pytest.approx(100.5)
    assert pos.tags["entry_order_id"] == "srv-9"


def test_ccxt_close_books_already_triggered_exchange_stop():
    ex = FillExchange()
    b = CcxtBroker(live_cfg(), exchange=ex)
    pos = b.open(make_signal(symbol="BTC/USD:USD"), 0.2, ts=0)
    stop_id = pos.tags["stop_order_id"]
    ex.stored[stop_id] = {"id": stop_id, "status": "closed", "filled": 0.2, "average": 97.9,
                          "fee": {"cost": 0.01, "currency": "USD"}}
    n_orders = len(ex.orders)
    fill = b.close(pos, pos.qty_open, 101.0, 5, "time")
    assert fill is not None and fill.reason == "stop" and fill.price == pytest.approx(97.9)
    assert fill.fee == pytest.approx(0.01)
    assert len(ex.orders) == n_orders                        # no second exit order was sent
    assert b.positions() == [] and b.trades()[0].reason == "stop"


def test_ccxt_close_spot_with_zero_base_balance_finishes_at_stop():
    ex = FillExchange()
    b = CcxtBroker(live_cfg(), exchange=ex)
    pos = b.open(make_signal(symbol="BTC/USD"), 0.1, ts=0)
    ex.balance_base_total = 0.0                               # stop executed / sold elsewhere
    n_orders = len(ex.orders)
    fill = b.close(pos, pos.qty_open, 101.0, 5, "time")
    assert fill is not None and fill.price == pytest.approx(98.0) and fill.reason == "stop"
    assert all(o["side"] != "sell" or "stopLossPrice" in o["params"] for o in ex.orders[n_orders:])
    assert b.positions() == [] and len(b.trades()) == 1


def test_ccxt_equity_keeps_last_known_value_after_first_success():
    ex = FillExchange()
    b = CcxtBroker(live_cfg(), exchange=ex)
    assert b.equity() == pytest.approx(100.0)

    def down():
        raise ccxt.NetworkError("down")

    ex.fetch_balance = down
    assert b.equity() == pytest.approx(100.0)
