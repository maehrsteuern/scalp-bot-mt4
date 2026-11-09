import json

import pytest

from ewbot.exchange import ExchangeError
from ewbot.models import Candle
from ewbot.paper import PaperBroker


def cd(t, o, h, l, c):
    return Candle(t=t, o=o, h=h, l=l, c=c, v=1.0)


def broker(**kw):
    kw.setdefault("starting_balance", 10_000.0)
    return PaperBroker(**kw)


def test_limit_buy_fills_on_low_touch_with_maker_fee():
    b = broker()
    oid = b.place_limit("BTC_USD", "BUY", 0.1, 80_000, "e1")
    assert b.get_balances()["USD"] == pytest.approx(10_000 - 0.1 * 80_000 * 1.005)  # reserved incl. fee reserve (taker)
    assert b.on_candle("BTC_USD", cd(1000, 81_000, 82_000, 80_001, 81_500)) == []     # low above price: no fill
    filled = b.on_candle("BTC_USD", cd(2000, 81_000, 82_000, 80_000, 81_500))         # low == price: fill
    assert [o.order_id for o in filled] == [oid]
    o = b.get_order(oid)
    assert (o.status, o.filled_qty, o.avg_price) == ("FILLED", 0.1, 80_000) and o.fee == pytest.approx(8000 * 0.0025)
    tot = b.get_total_balances()
    assert tot["BTC"] == 0.1 and tot["USD"] == pytest.approx(10_000 - 8000 - 20)
    assert b.reserved.get("USD", 0) == pytest.approx(0)


def test_limit_sell_fills_on_high_and_fee_deducted():
    b = broker()
    b.total["BTC"] = 0.5
    oid = b.place_limit("BTC_USD", "SELL", 0.5, 90_000, "x1")
    assert b.get_balances()["BTC"] == 0
    b.on_candle("BTC_USD", cd(1, 85_000, 89_999.99, 84_000, 88_000))
    assert b.get_order(oid).status == "ACTIVE"
    b.on_candle("BTC_USD", cd(2, 88_000, 90_000, 87_000, 89_000))
    assert b.get_order(oid).status == "FILLED"
    assert b.get_total_balances()["USD"] == pytest.approx(10_000 + 45_000 - 45_000 * 0.0025)
    assert b.get_total_balances()["BTC"] == 0


def test_market_fills_next_candle_open_with_slippage_and_taker_fee():
    b = broker(slippage=0.001)
    b.on_candle("BTC_USD", cd(1, 100, 101, 99, 100))   # establishes "now"
    oid = b.place_market("BTC_USD", "BUY", 0.01, "m1")
    assert b.get_order(oid).status == "ACTIVE"
    b.on_candle("BTC_USD", cd(2, 50_000, 51_000, 49_000, 50_500))
    o = b.get_order(oid)
    assert o.status == "FILLED" and o.avg_price == pytest.approx(50_050.0)
    assert o.fee == pytest.approx(0.01 * 50_050 * 0.005)


def test_market_sell_slippage_down():
    b = broker(slippage=0.001)
    b.total["SOL"] = 10
    oid = b.place_market("SOL_USD", "SELL", 10, "m2")
    b.on_candle("SOL_USD", cd(5, 100, 110, 90, 105))
    assert b.get_order(oid).avg_price == pytest.approx(99.9)


def test_order_never_fills_on_candle_before_or_same_as_placement():
    b = broker()
    b.on_candle("BTC_USD", cd(1000, 100, 100, 100, 100))
    oid = b.place_limit("BTC_USD", "BUY", 0.01, 100.0, "late")
    b.on_candle("BTC_USD", cd(1000, 100, 100, 1, 100))   # same candle re-fed: ignored
    assert b.get_order(oid).status == "ACTIVE"
    b.on_candle("BTC_USD", cd(2000, 100, 100, 99, 100))
    assert b.get_order(oid).status == "FILLED"


def test_insufficient_funds_and_duplicate_client_oid_rejected():
    b = broker(starting_balance=100)
    with pytest.raises(ExchangeError, match="insufficient"):
        b.place_limit("BTC_USD", "BUY", 1, 80_000, "a")
    with pytest.raises(ExchangeError, match="insufficient"):
        b.place_limit("BTC_USD", "SELL", 1, 80_000, "b")
    b.place_limit("SOL_USD", "BUY", 0.5, 100, "dup")
    with pytest.raises(ExchangeError) as ei:
        b.place_limit("SOL_USD", "BUY", 0.5, 100, "dup")
    assert ei.value.code == 204
    # reserved cash cannot be spent twice
    with pytest.raises(ExchangeError, match="insufficient"):
        b.place_limit("SOL_USD", "BUY", 0.5, 100, "dup2")


def test_cancel_releases_reserve_and_is_final():
    b = broker()
    oid = b.place_limit("BTC_USD", "BUY", 0.1, 80_000, "c1")
    assert b.get_balances()["USD"] < 10_000
    b.cancel("BTC_USD", oid)
    assert b.get_balances()["USD"] == pytest.approx(10_000) and b.get_order(oid).status == "CANCELED"
    assert b.open_orders() == []
    b.on_candle("BTC_USD", cd(9, 1, 100_000, 1, 1))
    assert b.get_order(oid).status == "CANCELED"
    with pytest.raises(ExchangeError):
        b.cancel("BTC_USD", oid)
    with pytest.raises(ExchangeError):
        b.get_order("nope")


def test_rounding_and_min_qty():
    b = broker()
    assert b.round_qty("SOL_USD", 1.23999) == 1.239 and b.round_qty("BTC_USD", 0.0012399) == 0.00123
    assert b.round_price("ETH_USD", 3000.126) == 3000.13
    with pytest.raises(ExchangeError, match="quantity"):
        b.place_limit("BTC_USD", "BUY", 0.000001, 80_000, "tiny")
    oid = b.place_limit("SOL_USD", "BUY", 1.23999, 100.004, "r1")
    o = b.get_order(oid)
    assert o.qty == 1.239 and o.price == 100.0


def test_open_orders_filter_and_copies():
    b = broker()
    b.place_limit("BTC_USD", "BUY", 0.01, 50_000, "o1")
    b.place_limit("SOL_USD", "BUY", 1, 10, "o2")
    assert len(b.open_orders()) == 2 and len(b.open_orders("SOL_USD")) == 1
    b.get_order(b.open_orders()[0].order_id).status = "FILLED"   # mutating a copy must not matter
    assert len(b.open_orders()) == 2


def test_json_roundtrip_and_determinism():
    def run(b, candles):
        for inst, c in candles:
            b.on_candle(inst, c)

    seq1 = [("BTC_USD", cd(1, 100_000, 100_100, 99_900, 100_000))]
    seq2 = [("BTC_USD", cd(2, 100_000, 101_000, 79_000, 90_000)), ("BTC_USD", cd(3, 90_000, 95_000, 89_000, 94_000))]

    def build():
        b = broker(maker_fee=0.001, taker_fee=0.002, slippage=0.0003)
        run(b, seq1)
        b.place_limit("BTC_USD", "BUY", 0.0777, 80_000, "e1")
        b.place_market("BTC_USD", "BUY", 0.01, "m1")
        b.place_limit("SOL_USD", "BUY", 3, 50, "s1")
        return b

    a, c = build(), build()
    mid = PaperBroker.from_dict(json.loads(json.dumps(c.to_dict())))   # restore half-way through
    assert mid.to_dict() == c.to_dict()
    run(a, seq2)
    run(mid, seq2)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(mid.to_dict(), sort_keys=True)
    assert a.get_total_balances()["BTC"] == pytest.approx(0.0877)
    # ids keep counting after restore
    nid = mid.place_limit("BTC_USD", "BUY", 0.01, 10_000, "after")
    assert nid == "P000004"


def test_equity_marks_to_market():
    b = broker()
    b.on_candle("BTC_USD", cd(1, 100, 100, 100, 100))
    b.place_limit("BTC_USD", "BUY", 10, 100, "q")
    b.on_candle("BTC_USD", cd(2, 100, 100, 99, 120))
    assert b.equity() == pytest.approx(10_000 - 1000 * 0.0025 + 10 * (120 - 100))
    assert b.equity({"BTC_USD": 90}) == pytest.approx(10_000 - 2.5 - 100)
