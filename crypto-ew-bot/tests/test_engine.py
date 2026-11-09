import json
import os

import pytest

from ewbot.config import Config
from ewbot.engine import CANDLE_MS, Engine, StateStore, new_state, run_paper_step
from ewbot.journal import Journal
from ewbot.models import Candle, InstrumentInfo, Order, Signal

T0 = 1_762_641_000_000          # arbitrary 30m-aligned start (ms)
assert T0 % CANDLE_MS == 0


# ---------------------------------------------------------------- fakes
class FakeBroker:
    """Minimal stand-in with the CONTRACT interface. Limit buy fills if l<=price, limit sell if h>=price,
    market fills at the open of the next candle."""

    def __init__(self, usd=1000.0):
        self.usd = usd
        self.base = {}
        self.orders = {}
        self.n = 0

    def to_dict(self):
        return {"usd": self.usd, "base": self.base, "n": self.n,
                "orders": {k: o.__dict__ for k, o in self.orders.items()}}

    def round_price(self, i, p):
        return round(p, 2)

    def round_qty(self, i, q):
        return int(q * 1e5 + 1e-9) / 1e5

    def get_balances(self):
        return {"USD": self.usd, **self.base}

    def _new(self, inst, side, typ, qty, price, oid):
        self.n += 1
        o = Order(f"O{self.n}", oid, inst, side, typ, qty, price, "ACTIVE")
        self.orders[o.order_id] = o
        return o.order_id

    def place_limit(self, inst, side, qty, price, oid):
        return self._new(inst, side, "LIMIT", qty, price, oid)

    def place_market(self, inst, side, qty, oid):
        return self._new(inst, side, "MARKET", qty, None, oid)

    def cancel(self, inst, oid):
        o = self.orders[oid]
        if o.status == "ACTIVE":
            o.status = "CANCELED"

    def get_order(self, oid):
        return self.orders[oid]

    def open_orders(self, instrument=None):
        return [o for o in self.orders.values() if o.status == "ACTIVE"]

    def _fill(self, o, px, fee_rate):
        o.status, o.filled_qty, o.avg_price = "FILLED", o.qty, px
        o.fee = o.qty * px * fee_rate
        base = o.instrument.split("_")[0]
        if o.side == "BUY":
            self.usd -= o.qty * px + o.fee
            self.base[base] = self.base.get(base, 0) + o.qty
        else:
            self.usd += o.qty * px - o.fee
            self.base[base] = self.base.get(base, 0) - o.qty

    def on_candle(self, inst, c):
        for o in list(self.orders.values()):
            if o.instrument != inst or o.status != "ACTIVE":
                continue
            if o.type == "MARKET":
                self._fill(o, c.o, 0.005)
            elif o.side == "BUY" and c.l <= o.price:
                self._fill(o, o.price, 0.0025)
            elif o.side == "SELL" and c.h >= o.price:
                self._fill(o, o.price, 0.0025)


def cndl(i, o, h, l, c):
    return Candle(T0 + i * CANDLE_MS, o, h, l, c, 1.0)


def mk_signal(coin="BTC", entry=100.0, stop=90.0, t1=110.0, t2=120.0, valid_candles=20, created_i=0):
    created = T0 + created_i * CANDLE_MS
    return Signal(coin=coin, instrument=f"{coin}_USD", created_ts=created,
                  valid_until_ts=created + valid_candles * CANDLE_MS, entry=entry, stop=stop, t1=t1, t2=t2,
                  wave_low=85.0, wave1_high=105.0, cancel_above=t1, id=f"{coin}-{created}")


@pytest.fixture
def env(tmp_path):
    cfg = Config(kill_path=str(tmp_path / "KILL"), journal_path=str(tmp_path / "j.csv"),
                 state_path=str(tmp_path / "paper.json"))
    infos = {f"{c}_USD": InstrumentInfo(f"{c}_USD", c, "USD", 0.01, 0.00001, 0.0001, 1.0) for c in ("BTC", "ETH", "SOL")}
    broker = FakeBroker()
    state = new_state("paper", 1000.0, T0)
    store = StateStore(cfg.state_path)
    eng = Engine(cfg, broker, state, store, Journal(cfg.journal_path), infos, strategy_fn=None)
    eng.now_ts = T0
    return eng, broker, cfg


def feed(eng, inst, candles):
    for c in candles:
        eng.handle_candle(inst, c)


def only_trade(eng):
    return next(iter(eng.trades.values()))


# ---------------------------------------------------------------- tests
def test_full_win_t1_then_t2(env):
    eng, broker, _ = env
    sig = mk_signal()
    t = eng.consider_signal(sig, T0)
    assert t["state"] == "ENTRY_PENDING"
    assert t["qty"] == pytest.approx(0.75, abs=1e-4)           # 7.5 USD risk / 10
    feed(eng, "BTC_USD", [cndl(0, 102, 103, 99.5, 101)])
    assert t["state"] == "OPEN" and t["entry_price"] == 100.0
    feed(eng, "BTC_USD", [cndl(1, 101, 111, 100.5, 110)])      # T1
    assert t["state"] == "OPEN_BE" and t["stop"] == 100.0
    assert t["remaining"] == pytest.approx(t["entry_qty"] / 2, abs=1e-4)
    feed(eng, "BTC_USD", [cndl(2, 110, 121, 109, 120)])        # T2
    assert t["state"] == "CLOSED" and t["close_reason"] == "Ziel 2"
    assert t["realized"] > 0
    assert t["r_multiple"] > 1.0
    # journal: BUY, SELL, SELL
    rows = open(env[2].journal_path).read().strip().splitlines()
    assert len(rows) == 4 and rows[0].startswith("date,coin,side")


def test_stop_out_loss_close_to_risk(env):
    eng, broker, _ = env
    t = eng.consider_signal(mk_signal(), T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100)])          # fill
    feed(eng, "BTC_USD", [cndl(1, 100, 100.5, 89, 91)])         # low <= stop -> CLOSING
    assert t["state"] == "CLOSING"
    feed(eng, "BTC_USD", [cndl(2, 90, 92, 88, 89)])             # market fills at open 90
    assert t["state"] == "CLOSED" and t["close_reason"] == "Stop"
    assert -t["risk_usd"] * 1.6 < t["realized"] < 0
    assert t["remaining"] == 0.0
    assert broker.base["BTC"] == pytest.approx(0, abs=1e-9)    # sold exactly what was bought


def test_stop_wins_over_t1_in_same_candle(env):
    eng, _, _ = env
    t = eng.consider_signal(mk_signal(), T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100)])
    feed(eng, "BTC_USD", [cndl(1, 100, 115, 88, 100)])          # touches T1 AND stop: pessimistic -> stop
    assert t["state"] == "CLOSING" and not t["t1_done"]


def test_break_even_stop_after_t1(env):
    eng, _, _ = env
    t = eng.consider_signal(mk_signal(), T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100), cndl(1, 100, 111, 100.2, 110)])
    assert t["state"] == "OPEN_BE"
    feed(eng, "BTC_USD", [cndl(2, 108, 109, 99.9, 101), cndl(3, 101, 102, 100, 101)])
    assert t["state"] == "CLOSED" and t["close_reason"].startswith("Stop")
    assert t["realized"] > 0                                    # T1 profit outweighs fees on the rest


def test_cancel_on_expiry_and_cancel_above(env):
    eng, broker, _ = env
    t = eng.consider_signal(mk_signal(valid_candles=3), T0)
    feed(eng, "BTC_USD", [cndl(0, 105, 106, 103, 104), cndl(1, 104, 106, 103, 105)])
    assert t["state"] == "ENTRY_PENDING"
    feed(eng, "BTC_USD", [cndl(2, 105, 106, 103, 105)])         # candle closes at valid_until
    assert t["state"] == "CANCELED"
    assert broker.orders[t["entry_order"]].status == "CANCELED"

    t2 = eng.consider_signal(mk_signal(created_i=3, valid_candles=50), T0 + 3 * CANDLE_MS)
    feed(eng, "BTC_USD", [cndl(3, 108, 111, 105, 109)])         # never touched entry, reached T1
    assert t2["state"] == "CANCELED" and "Ziel" in t2["close_reason"]


def test_one_position_per_coin(env):
    eng, _, _ = env
    assert eng.consider_signal(mk_signal(), T0)
    assert eng.consider_signal(mk_signal(created_i=1), T0) is None
    assert len(eng.trades) == 1
    # another coin is fine
    assert eng.consider_signal(mk_signal("ETH"), T0)


def test_seen_signal_not_reopened_after_close(env):
    eng, _, _ = env
    sig = mk_signal()
    eng.consider_signal(sig, T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100), cndl(1, 100, 100, 89, 90), cndl(2, 90, 91, 88, 89)])
    assert only_trade(eng)["state"] == "CLOSED"
    assert eng.consider_signal(sig, T0 + 3 * CANDLE_MS) is None


def test_daily_loss_cap_blocks_entry(env):
    eng, _, _ = env
    eng.consider_signal(mk_signal(), T0)
    # big gap down: loss > 2 %
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100), cndl(1, 100, 100, 70, 71), cndl(2, 60, 61, 58, 59)])
    assert eng.realized_today(eng.now_ts) < -20
    assert eng.consider_signal(mk_signal("ETH", created_i=3), eng.now_ts) is None
    assert "ETH-%d" % (T0 + 3 * CANDLE_MS) not in eng.trades


def test_exposure_cap_reduces_second_position(env):
    eng, _, _ = env
    a = eng.consider_signal(mk_signal("BTC", entry=100, stop=99), T0)          # wants 750 USD
    b = eng.consider_signal(mk_signal("ETH", entry=100, stop=99), T0)          # room only 150 USD
    assert a["qty"] == pytest.approx(7.5) and b["qty"] == pytest.approx(1.5)


def test_kill_cancels_entries_and_blocks(env):
    eng, broker, cfg = env
    t = eng.consider_signal(mk_signal(), T0)
    open(cfg.kill_path, "w").write("cancel\n")
    eng.apply_kill()
    assert t["state"] == "CANCELED"
    assert eng.consider_signal(mk_signal("ETH"), T0) is None


def test_kill_flatten_sells_bot_position(env):
    eng, broker, cfg = env
    t = eng.consider_signal(mk_signal(), T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100)])
    open(cfg.kill_path, "w").write("flatten\n")
    eng.apply_kill()
    assert t["state"] == "CLOSING"
    feed(eng, "BTC_USD", [cndl(1, 100, 101, 99.5, 100)])
    assert t["state"] == "CLOSED" and "KILL" in t["close_reason"]


def test_check_price_triggers_synthetic_stop(env):
    eng, _, _ = env
    t = eng.consider_signal(mk_signal(), T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100)])
    eng.check_price("BTC_USD", 91.0, 91.0, T0 + 99)
    assert t["state"] == "OPEN"
    eng.check_price("BTC_USD", 89.9, 90.0, T0 + 100)
    assert t["state"] == "CLOSING"


def test_api_error_blocks_new_entries_but_keeps_state(env):
    eng, broker, _ = env
    broker.get_balances = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    assert eng.consider_signal(mk_signal(), T0) is None
    assert eng.safe_mode and not eng.trades


def test_state_roundtrip_and_resume(env, tmp_path):
    eng, broker, cfg = env
    eng.consider_signal(mk_signal(), T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100)])
    saved = json.load(open(cfg.state_path))
    assert saved["trades"][next(iter(saved["trades"]))]["state"] == "OPEN"
    assert saved["cursor"]["BTC_USD"] == T0
    assert "broker" in saved


def test_journal_is_append_only_and_dedups(tmp_path):
    j = Journal(str(tmp_path / "j.csv"))
    assert j.append(T0, "BTC", "BUY", 0.1, 100.0, 0.01, "O1", "BTC-1", "x")
    assert not j.append(T0, "BTC", "BUY", 0.1, 100.0, 0.01, "O1", "BTC-1", "x")
    j2 = Journal(str(tmp_path / "j.csv"))
    assert not j2.append(T0, "BTC", "BUY", 0.1, 100.0, 0.01, "O1", "BTC-1", "x")
    assert len(open(str(tmp_path / "j.csv")).read().strip().splitlines()) == 2


# ---------------------------------------------------------------- paper-step idempotency
class FakeClient:
    def __init__(self, series):
        self.series = series

    def get_candles(self, inst, tf, count=300, end_ts=None):
        if tf == "30m":
            return list(self.series[inst][-count:])
        return []

    def get_candles_paged(self, inst, tf, total):
        return self.get_candles(inst, tf, total)

    def get_ticker(self, inst):
        c = self.series[inst][-1]
        return {"bid": c.c, "ask": c.c, "last": c.c, "ts": c.t}


def test_paper_step_idempotent_and_seeded(tmp_path):
    cfg = Config(kill_path=str(tmp_path / "KILL"), journal_path=str(tmp_path / "j.csv"))
    seed = tmp_path / "seed.json"
    created = T0
    seed.write_text(json.dumps({"created_ts": created, "valid_until_ts": created + 40 * CANDLE_MS, "coins": {
        "BTC": {"entry": 100, "stop": 90, "t1": 110, "t2": 120, "low": 85, "bounce": 105}}}))
    series = {"BTC_USD": [cndl(0, 102, 103, 99.5, 101), cndl(1, 101, 111, 100.5, 110), cndl(2, 110, 112, 105, 108)],
              "ETH_USD": [cndl(i, 50, 51, 49, 50) for i in range(3)], "SOL_USD": [cndl(i, 5, 5.1, 4.9, 5) for i in range(3)]}
    client = FakeClient(series)
    infos = {f"{c}_USD": InstrumentInfo(f"{c}_USD", c, "USD", 0.01, 0.00001, 0.0001, 1.0) for c in ("BTC", "ETH", "SOL")}
    store = StateStore(str(tmp_path / "s.json"))
    now = T0 + 3 * CANDLE_MS + 5000

    def step():
        state = store.load() if store.exists() else new_state("paper", 1000.0, now)
        broker = FakeBroker()
        if state.get("broker"):
            b = state["broker"]
            broker.usd, broker.base, broker.n = b["usd"], b["base"], b["n"]
            broker.orders = {k: Order(**v) for k, v in b["orders"].items()}
        eng = Engine(cfg, broker, state, store, Journal(cfg.journal_path), infos)
        return run_paper_step(eng, client, now, str(seed))

    s1 = step()
    assert s1["candles_processed"] == 9 and s1["seeded"] == [f"BTC-{created}"]
    assert s1["fills"] and s1["open"] == ["BTC-%d" % created]
    snapshot = open(store.path).read()
    journal_snap = open(cfg.journal_path).read()
    s2 = step()
    assert s2["candles_processed"] == 0 and not s2["fills"] and not s2["exits"]
    assert open(store.path).read() == snapshot          # nothing changed
    assert open(cfg.journal_path).read() == journal_snap


# ---------------------------------------------------------------- report / CLI gate
def test_report_self_contained(env):
    from ewbot import report
    eng, _, cfg = env
    sig = mk_signal()
    eng.consider_signal(sig, T0)
    feed(eng, "BTC_USD", [cndl(0, 101, 102, 99, 100), cndl(1, 100, 100, 89, 90), cndl(2, 90, 91, 88, 89)])
    rows = [cndl(i, 100 + i % 3, 103, 98, 101) for i in range(40)]
    per = {"BTC": {"signal": sig.to_dict(), "candles": rows, "last": 101.0, "count": None},
           "ETH": {"signal": None, "candles": rows, "last": 50.0, "count": {"text_de": "Noch kein Muster."}},
           "SOL": {"signal": None, "candles": [], "last": None, "count": None}}
    data = report.build_page_data(cfg, T0 + 5 * CANDLE_MS, 0.9, per, eng.state, eng.equity())
    page = report.render_page(data)
    assert 'id="ew-state"' in page and "Keine Anlageberatung" in page and "<svg" in page
    assert "http://" not in page and "https://" not in page and "src=" not in page
    blob = page.split('id="ew-state">')[1].split("</script>")[0]
    assert json.loads(blob.replace("<\\/", "</"))["coins"]["BTC"]["signal"]["entry"] == 100.0
    assert "MEZ" in page or "MESZ" in page


def test_live_gate(monkeypatch):
    from ewbot.__main__ import check_live_gate
    monkeypatch.delenv("CDC_API_KEY", raising=False)
    monkeypatch.delenv("CDC_API_SECRET", raising=False)
    cfg = Config()
    msg = check_live_gate(cfg, False)
    assert msg and "live_enabled" in msg and "CDC_API_KEY" in msg and "--confirm-live" in msg
    monkeypatch.setenv("CDC_API_KEY", "k")
    monkeypatch.setenv("CDC_API_SECRET", "s")
    cfg.live_enabled = True
    assert check_live_gate(cfg, True) is None
    assert check_live_gate(cfg, False) is not None


def test_config_rejects_bad_coin():
    from ewbot.config import ConfigError, from_dict
    with pytest.raises(ConfigError):
        from_dict({"coins": ["BTC", "DOGE"]})
    assert from_dict({"fees": {"maker": 0.001}, "paths": {"out_dir": "x"}}).out_dir == "x"
