"""Regression tests for the safety review fixes (stop/exit order handling, unknown order state, locks, ...)."""
import json
import os

import pytest

from ewbot.config import Config
from ewbot.engine import (CANDLE_MS, Engine, StateLock, StateLockError, StateStore, new_state, run_cycle,
                          run_paper_step)
from ewbot.exchange import CryptoComClient, OrderStateUnknown
from ewbot.journal import Journal
from ewbot.models import Candle, InstrumentInfo, Order, Signal
from ewbot.paper import PaperBroker

from test_engine import FakeBroker, T0, cndl, mk_signal


# ---------------------------------------------------------------- helpers
def paper_env(tmp_path, broker=None, live=False, sleep=None):
    cfg = Config(kill_path=str(tmp_path / "KILL"), journal_path=str(tmp_path / "j.csv"),
                 state_path=str(tmp_path / "paper.json"))
    b = broker or PaperBroker()
    eng = Engine(cfg, b, new_state("paper", 1000.0, T0), None, None, dict(b.instruments), live=live, sleep=sleep)
    eng.now_ts = T0
    return eng, b


def fake_env(tmp_path, broker=None, live=False, sleep=None):
    cfg = Config(kill_path=str(tmp_path / "KILL"), journal_path=str(tmp_path / "j.csv"),
                 state_path=str(tmp_path / "paper.json"))
    infos = {f"{c}_USD": InstrumentInfo(f"{c}_USD", c, "USD", 0.01, 0.00001, 0.0001, 1.0) for c in ("BTC", "ETH", "SOL")}
    b = broker or FakeBroker()
    eng = Engine(cfg, b, new_state("paper", 1000.0, T0), None, None, infos, live=live, sleep=sleep)
    eng.now_ts = T0
    return eng, b


def psig():
    return Signal('BTC', 'BTC_USD', T0, T0 + 10 ** 9, 100.0, 95.0, 110.0, 120.0, 90.0, 105.0, 110.0, id='BTC-1')


def open_paper_position(eng):
    eng.begin_cycle(T0)
    eng.consider_signal(psig(), T0)
    eng.handle_candle('BTC_USD', cndl(1, 101, 101, 99, 100))
    t = eng.trades['BTC-1']
    assert t['state'] == 'OPEN'
    return t


def market_sells(b):
    return [o for o in b.orders.values() if o.side == 'SELL' and o.type == 'MARKET']


# ---------------------------------------------------------------- 1. failed cancel must not orphan a TP
class CancelFails(PaperBroker):
    fail = False

    def cancel(self, i, o):
        if self.fail:
            raise RuntimeError('net')
        return super().cancel(i, o)


def test_failed_cancel_keeps_exit_ids_and_sends_no_stop(tmp_path):
    eng, b = paper_env(tmp_path, CancelFails())
    t = open_paper_position(eng)
    b.fail = True
    eng.handle_candle('BTC_USD', cndl(2, 100, 100, 94, 99))        # stop hit
    assert t['state'] == 'OPEN' and t['stop_pending']
    assert t['t1_order'] and t['t2_order']                        # ids kept
    assert eng.state['halt_new'] is True
    assert not market_sells(b)                                    # no stop-sell while TPs may still be active
    b.fail = False
    eng.sync_orders()                                             # next cycle retries
    assert t['state'] == 'CLOSING' and t['t1_order'] is None and t['t2_order'] is None
    assert len(market_sells(b)) == 1
    assert all(o.status != 'ACTIVE' for o in b.orders.values() if o.type == 'LIMIT')


# ---------------------------------------------------------------- 2. unknown entry state keeps the trade
class EntryUnknown(PaperBroker):
    def __init__(self, create=True):
        super().__init__()
        self.create = create
        self.first = True

    def place_limit(self, *a, **k):
        if not self.first:
            return super().place_limit(*a, **k)
        self.first = False
        if self.create:
            super().place_limit(*a, **k)
        raise OrderStateUnknown('x')


def test_unknown_entry_is_kept_and_adopted(tmp_path):
    eng, b = paper_env(tmp_path, EntryUnknown(create=True))
    eng.begin_cycle(T0)
    eng.consider_signal(psig(), T0)
    t = eng.trades['BTC-1']                                       # NOT deleted
    assert t['state'] == 'ENTRY_PENDING' and t['entry_order'] is None and t['entry_oid']
    assert eng.state['halt_new'] is True
    eng.sync_orders()
    assert t['entry_order'] and b.orders[t['entry_order']].client_oid == t['entry_oid']
    eng.handle_candle('BTC_USD', cndl(1, 101, 101, 99, 100))      # the adopted order fills and is managed
    assert t['state'] == 'OPEN' and t['t1_order']


def test_unknown_entry_absent_is_canceled(tmp_path):
    eng, b = paper_env(tmp_path, EntryUnknown(create=False))
    eng.begin_cycle(T0)
    eng.consider_signal(psig(), T0)
    t = eng.trades['BTC-1']
    assert t['state'] == 'ENTRY_PENDING'
    eng.sync_orders()
    assert t['state'] == 'CANCELED'


# ---------------------------------------------------------------- 3. stop retry reuses the client_oid
class MarketUnknownAfterCreate(PaperBroker):
    n = 0
    create = True

    def place_market(self, *a, **k):
        if self.n == 0:
            self.n = 1
            if self.create:
                super().place_market(*a, **k)
            raise OrderStateUnknown('x')
        return super().place_market(*a, **k)


def test_stop_retry_does_not_double_sell(tmp_path):
    eng, b = paper_env(tmp_path, MarketUnknownAfterCreate())
    t = open_paper_position(eng)
    eng.handle_candle('BTC_USD', cndl(2, 100, 100, 94, 99))
    assert t['state'] == 'OPEN' and t['stop_pending']
    eng.sync_orders()                                             # retry: finds the order by client_oid
    assert t['state'] == 'CLOSING'
    assert len(market_sells(b)) == 1


def test_stop_retry_reuses_same_client_oid_when_absent(tmp_path):
    b = MarketUnknownAfterCreate()
    b.create = False
    eng, _ = paper_env(tmp_path, b)
    t = open_paper_position(eng)
    eng.handle_candle('BTC_USD', cndl(2, 100, 100, 94, 99))
    first = t['stop_oid']
    assert first and not market_sells(b)
    eng.sync_orders()
    sells = market_sells(b)
    assert len(sells) == 1 and sells[0].client_oid == first


# ---------------------------------------------------------------- 4. kill CLI + locks
def test_kill_cli_only_writes_file(tmp_path, monkeypatch, capsys):
    from ewbot.__main__ import main
    monkeypatch.chdir(tmp_path)
    StateStore(str(tmp_path / 'state' / 'paper.json')).save(new_state('paper', 1000.0, T0))
    before = open(tmp_path / 'state' / 'paper.json', 'rb').read()
    assert main(['kill', '--flatten']) == 0
    assert 'flatten' in open(tmp_path / 'state' / 'KILL').read()
    assert open(tmp_path / 'state' / 'paper.json', 'rb').read() == before   # CLI never touches the state
    assert main(['kill']) == 0
    assert 'cancel' in open(tmp_path / 'state' / 'KILL').read()


def test_state_lock_is_exclusive(tmp_path):
    p = str(tmp_path / 'x.json')
    with StateLock(p):
        with pytest.raises(StateLockError):
            StateLock(p).acquire()
    StateLock(p).acquire().release()                              # free again after release


def test_paper_step_and_run_refuse_when_locked(tmp_path, monkeypatch):
    from ewbot.__main__ import main
    monkeypatch.chdir(tmp_path)
    p = str(tmp_path / 'st.json')
    with StateLock(p):
        assert main(['paper-step', '--state', p]) == 3
        assert main(['run', '--mode', 'paper', '--state', p]) == 3


class Client:
    """Public-data stub."""
    def __init__(self, c30=None, fail_ticker=(), now=None):
        self.c30 = c30 or {}
        self.fail_ticker = fail_ticker
        self.calls = []

    def get_candles(self, inst, tf, count=300, end_ts=None):
        return list(self.c30.get(inst, [])) if tf == "30m" else []

    def get_ticker(self, inst):
        self.calls.append(("ticker", inst))
        if inst in self.fail_ticker:
            raise RuntimeError("down")
        px = self.c30[inst][-1].c if self.c30.get(inst) else 100.0
        return {"bid": px, "ask": px, "last": px, "ts": 0}


def test_running_loop_executes_kill_flatten(tmp_path):
    eng, b = fake_env(tmp_path)
    eng.consider_signal(mk_signal(), T0)
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    t = next(iter(eng.trades.values()))
    assert t['state'] == 'OPEN'
    open(eng.cfg.kill_path, 'w').write('flatten\n')
    run_cycle(eng, Client(), T0 + 2 * CANDLE_MS)
    assert t['state'] == 'CLOSING'


# ---------------------------------------------------------------- 5. live: poll TP cancel before reading balance
class SlowCancel(FakeBroker):
    """cancel() takes effect only after `delay` get_order polls."""
    delay = 2

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.pending = {}

    def cancel(self, inst, oid):
        self.pending[oid] = self.delay

    def get_order(self, oid):
        if oid in self.pending:
            self.pending[oid] -= 1
            if self.pending[oid] < 0:
                del self.pending[oid]
                self.orders[oid].status = "CANCELED"
        return self.orders[oid]

    def get_balances(self):
        # TP orders reserve coins while active
        reserved = sum(o.qty for o in self.orders.values() if o.side == "SELL" and o.status == "ACTIVE" and o.type == "LIMIT")
        return {"USD": self.usd, "BTC": self.base.get("BTC", 0) - reserved}


def test_live_stop_waits_for_tp_cancel_and_clamps_to_available(tmp_path):
    sleeps = []
    eng, b = fake_env(tmp_path, SlowCancel(), live=True, sleep=sleeps.append)
    t = eng.consider_signal(mk_signal(), T0)
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    assert t['state'] == 'OPEN'
    b.base['BTC'] -= 0.1                                         # less in the wallet than the bot thinks
    eng.stop_out(t, "Stop")
    assert t['state'] == 'CLOSING' and sleeps                    # polled with sleeps
    sell = [o for o in b.orders.values() if o.type == "MARKET"][0]
    assert sell.qty == pytest.approx(t['entry_qty'] - 0.1, abs=1e-5)
    assert all(o.status == "CANCELED" for o in b.orders.values() if o.type == "LIMIT" and o.side == "SELL")


# ---------------------------------------------------------------- 6. paper stop fill model
def test_paper_stop_fills_at_stop_after_wick_and_recovery(tmp_path):
    eng, b = paper_env(tmp_path)
    t = open_paper_position(eng)
    eng.handle_candle('BTC_USD', cndl(2, 100, 100, 94, 99))      # wick through 95, closes back up
    eng.handle_candle('BTC_USD', cndl(3, 102, 103, 101, 102))    # next open is 102 (recovered)
    assert t['state'] == 'CLOSED'
    px = t['fills'][-1]['price']
    assert px <= 95 * (1 - b.slippage) + 0.01 and px < 100       # NOT 102


def test_paper_stop_gap_down_fills_at_worse_open(tmp_path):
    eng, b = paper_env(tmp_path)
    t = open_paper_position(eng)
    eng.handle_candle('BTC_USD', cndl(2, 100, 100, 94, 90))
    eng.handle_candle('BTC_USD', cndl(3, 88, 90, 87, 89))
    assert t['fills'][-1]['price'] == pytest.approx(88 * (1 - b.slippage), abs=0.01)


# ---------------------------------------------------------------- 7. base-coin BUY fee
def test_parse_buy_fee_in_base_gives_net_qty():
    c = CryptoComClient()
    o = c._parse_order({"order_id": "1", "client_oid": "a", "instrument_name": "BTC_USD", "side": "BUY",
                        "order_type": "LIMIT", "status": "FILLED", "quantity": "1", "limit_price": "100",
                        "cumulative_quantity": "1", "avg_price": "100", "cumulative_fee": "0.0025",
                        "fee_instrument_name": "BTC"})
    assert o.filled_qty == pytest.approx(0.9975)
    assert o.fee == pytest.approx(0.25)                          # quote equivalent
    assert o.filled_qty * o.avg_price + o.fee == pytest.approx(100.0)
    assert o.fee_ccy == "BTC"
    q = c._parse_order({"order_id": "2", "instrument_name": "BTC_USD", "side": "BUY", "status": "FILLED",
                        "quantity": "1", "cumulative_quantity": "1", "avg_price": "100", "cumulative_fee": "0.25",
                        "fee_instrument_name": "USD"})
    assert q.filled_qty == 1.0


def test_live_exit_orders_clamped_to_wallet(tmp_path):
    eng, b = fake_env(tmp_path, live=True)
    t = eng.consider_signal(mk_signal(), T0)
    orig = b._fill

    def fill_with_base_fee(o, px, fee_rate):
        orig(o, px, fee_rate)
        if o.side == "BUY":
            b.base["BTC"] -= 0.01                                # fee taken from the coins, gross qty reported
    b._fill = fill_with_base_fee
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    assert t['state'] == 'OPEN'
    tp = [o for o in b.orders.values() if o.side == 'SELL']
    assert sum(o.qty for o in tp) <= b.base['BTC'] + 1e-9
    assert t['remaining'] <= b.base['BTC'] + 1e-9


# ---------------------------------------------------------------- 8. partial entry fill
class PartialEntry(FakeBroker):
    def on_candle(self, inst, c):
        for o in list(self.orders.values()):
            if o.status == "ACTIVE" and o.side == "BUY" and o.filled_qty == 0 and c.l <= o.price:
                o.filled_qty, o.avg_price, o.fee = 0.4, o.price, 0.4 * o.price * 0.0025
                self.usd -= 0.4 * o.price + o.fee
                self.base["BTC"] = self.base.get("BTC", 0) + 0.4
                return
        super().on_candle(inst, c)


def test_partial_entry_fill_cancels_rest_and_opens_filled_part(tmp_path):
    eng, b = fake_env(tmp_path, PartialEntry())
    t = eng.consider_signal(mk_signal(), T0)
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    assert t['state'] == 'OPEN'
    assert t['entry_qty'] == pytest.approx(0.4)
    assert b.orders[t['entry_order']].status == 'CANCELED'
    sells = [o for o in b.orders.values() if o.side == 'SELL']
    assert sum(o.qty for o in sells) == pytest.approx(0.4, abs=1e-5)


# ---------------------------------------------------------------- 9. dust
def test_dust_remainder_is_closed_not_looped(tmp_path):
    eng, b = fake_env(tmp_path)
    t = eng.consider_signal(mk_signal(), T0)
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    t['remaining'] = 0.000004                                    # below qty_tick 0.00001
    eng.stop_out(t, "Stop")
    assert t['state'] == 'CLOSED'
    assert not [o for o in b.orders.values() if o.type == 'MARKET']
    assert t['remaining'] == 0.0


def test_partial_stop_fill_with_dust_rest_closes(tmp_path):
    eng, b = fake_env(tmp_path)
    t = eng.consider_signal(mk_signal(), T0)
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    eng.stop_out(t, "Stop")
    o = b.orders[t['stop_order']]
    o.status, o.filled_qty, o.avg_price, o.fee = "CANCELED", o.qty - 0.000004, 90.0, 0.0
    eng.sync_orders()
    assert t['state'] == 'CLOSED'


# ---------------------------------------------------------------- 10. downtime replay
def test_replayed_old_signal_creates_no_entry(tmp_path):
    eng, b = fake_env(tmp_path)
    old = T0 + 2 * CANDLE_MS
    seen = []

    def strat(coin, inst, c30, c4, now_ts=None):
        if coin != "BTC":
            return []
        seen.append(now_ts)
        return [Signal('BTC', 'BTC_USD', now_ts, now_ts + 20 * CANDLE_MS, 100.0, 90.0, 110.0, 120.0, 85.0, 105.0, 110.0,
                       id=f"BTC-{now_ts}")]
    eng.strategy_fn = strat
    eng.state["cursor"]["BTC_USD"] = T0 - CANDLE_MS
    candles = [cndl(i, 101, 102, 100.5, 101) for i in range(0, 6)]
    client = Client({"BTC_USD": candles})
    now = T0 + 6 * CANDLE_MS + 60_000                            # bot was down for hours
    run_cycle(eng, client, now)
    assert len(seen) == 6
    # only the newest candle's signal (created at its close = 1 min ago) may open a trade
    assert [t['created_ts'] for t in eng.trades.values()] == [T0 + 6 * CANDLE_MS]


def test_live_stop_ignores_candles_before_opened_ts(tmp_path):
    eng, b = fake_env(tmp_path, live=True)
    t = eng.consider_signal(mk_signal(), T0)
    eng.handle_candle('BTC_USD', cndl(0, 101, 102, 99, 100))
    assert t['state'] == 'OPEN'
    t['opened_ts'] = T0 + 10 * CANDLE_MS
    eng.handle_candle('BTC_USD', cndl(3, 100, 100, 80, 99))      # old candle (replay) with a low below the stop
    assert t['state'] == 'OPEN'
    eng.handle_candle('BTC_USD', cndl(10, 100, 100, 80, 99))
    assert t['state'] == 'CLOSING'


# ---------------------------------------------------------------- 11. sync first, errors block entries
def _fresh_strat(created):
    def strat(coin, inst, c30, c4, now_ts=None):
        return [Signal(coin, inst, created, created + 20 * CANDLE_MS, 100.0, 90.0, 110.0, 120.0, 85.0, 105.0, 110.0,
                       id=f"{coin}-{created}")]
    return strat


def test_ticker_error_in_cycle_blocks_all_entries(tmp_path):
    now = T0 + 3 * CANDLE_MS + 30_000
    close = T0 + 3 * CANDLE_MS
    candles = {f"{c}_USD": [cndl(i, 101, 102, 100.5, 101) for i in range(0, 3)] for c in ("BTC", "ETH", "SOL")}
    eng, b = fake_env(tmp_path)
    eng.strategy_fn = _fresh_strat(close)
    eng.state["cursor"] = {k: T0 - CANDLE_MS for k in candles}
    run_cycle(eng, Client(candles, fail_ticker=("SOL_USD",)), now)
    assert not eng.trades                                        # SOL failed AFTER BTC/ETH were processed before
    # control: without error entries are opened
    eng2, _ = fake_env(tmp_path)
    eng2.strategy_fn = _fresh_strat(close)
    eng2.state["cursor"] = {k: T0 - CANDLE_MS for k in candles}
    run_cycle(eng2, Client(candles), now)
    assert eng2.trades


def test_sync_runs_before_any_signal(tmp_path):
    eng, b = fake_env(tmp_path)
    order = []
    orig_sync, orig_consider = eng.sync_orders, eng.consider_signal
    eng.sync_orders = lambda instrument=None: (order.append(("sync", instrument)), orig_sync(instrument))[1]
    eng.consider_signal = lambda *a, **k: (order.append(("consider",)), orig_consider(*a, **k))[1]
    close = T0 + 3 * CANDLE_MS
    candles = {f"{c}_USD": [cndl(i, 101, 102, 100.5, 101) for i in range(0, 3)] for c in ("BTC", "ETH", "SOL")}
    eng.strategy_fn = _fresh_strat(close)
    eng.state["cursor"] = {k: T0 - CANDLE_MS for k in candles}
    run_cycle(eng, Client(candles), close + 30_000)
    first_consider = order.index(("consider",))
    assert ("sync", None) in order[:first_consider]


def test_sync_api_error_blocks_entries(tmp_path):
    eng, b = fake_env(tmp_path)
    t = eng.consider_signal(mk_signal("ETH"), T0)                # an existing pending trade whose poll fails
    b.get_order = lambda oid: (_ for _ in ()).throw(RuntimeError("api"))
    close = T0 + 3 * CANDLE_MS
    candles = {f"{c}_USD": [cndl(i, 101, 102, 100.5, 101) for i in range(0, 3)] for c in ("BTC", "ETH", "SOL")}
    eng.strategy_fn = lambda coin, inst, c30, c4, now_ts=None: (
        _fresh_strat(close)(coin, inst, c30, c4) if coin == "BTC" else [])
    eng.state["cursor"] = {k: T0 - CANDLE_MS for k in candles}
    run_cycle(eng, Client(candles), close + 30_000)
    assert "BTC-%d" % close not in eng.trades
