"""Tests for CryptoComClient. No network: HTTP is replaced by a fake session."""
import json

import pytest
import requests

from ewbot.exchange import (CryptoComClient, ExchangeError, OrderStateUnknown, fmt_decimal, quantize_to_tick,
                            sign_request, _params_to_str)

KEY, SECRET = "TESTKEY", "TESTSECRET"

INSTRUMENTS = {"code": 0, "result": {"data": [
    {"symbol": "BTC_USD", "inst_type": "CCY_PAIR", "base_ccy": "BTC", "quote_ccy": "USD",
     "price_tick_size": "0.01", "qty_tick_size": "0.00001"},
    {"symbol": "SOL_USD", "inst_type": "CCY_PAIR", "base_ccy": "SOL", "quote_ccy": "USD",
     "price_tick_size": "0.01", "qty_tick_size": "0.001"},
    {"symbol": "BTCUSD-PERP", "inst_type": "PERPETUAL_SWAP", "base_ccy": "BTC", "quote_ccy": "USD",
     "price_tick_size": "0.5", "qty_tick_size": "0.0001"},
]}}


class Resp:
    def __init__(self, body, status=200):
        self._b, self.status_code = body, status

    def json(self):
        if isinstance(self._b, Exception):
            raise self._b
        return self._b


class FakeSession:
    """Scripted responses per method name; items may be dict, Resp, or an Exception to raise."""

    def __init__(self, script=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls = []  # (verb, method, params/body)

    def _next(self, method):
        q = self.script.get(method)
        if not q:
            raise AssertionError(f"unexpected call {method}")
        item = q.pop(0) if len(q) > 1 else q[0]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, Resp) else Resp(item)

    def get(self, url, params=None, timeout=None):
        m = url.split("/exchange/v1/")[1]
        self.calls.append(("GET", m, params))
        return self._next(m)

    def post(self, url, data=None, headers=None, timeout=None):
        m = url.split("/exchange/v1/")[1]
        self.calls.append(("POST", m, json.loads(data)))
        return self._next(m)


def make(script=None, **kw):
    script = dict(script or {})
    script.setdefault("public/get-instruments", [INSTRUMENTS])
    s = FakeSession(script)
    sleeps = []
    c = CryptoComClient(KEY, SECRET, session=s, sleep=sleeps.append, **kw)
    c.min_private_interval = 0
    return c, s, sleeps


def ok(result):
    return {"id": 1, "code": 0, "result": result}


def err(code, msg="X", status=400):
    return Resp({"id": 1, "code": code, "message": msg, "original": f'{{"api_key":"{KEY}","sig":"LEAKME"}}'}, status)


# ---------------------------------------------------------------- signing
def test_sign_fixed_vector_flat_params():
    params = {"instrument_name": "BTC_USD", "side": "BUY", "type": "LIMIT", "price": "85000.5",
              "quantity": "0.001", "client_oid": "abc123", "time_in_force": "GOOD_TILL_CANCEL"}
    # expected derived independently with `openssl dgst -sha256 -hmac` over
    # method+id+api_key+paramString(sorted key+value)+nonce
    assert sign_request("private/create-order", 11, KEY, params, 1700000000000, SECRET) == \
        "921f2604539202cd31dcac8640fbc5a10bcc440bab1265db2dbb3d0170de4200"


def test_sign_list_value():
    params = {"instrument_name": "BTC_USD", "side": "BUY", "quantity": "1", "exec_inst": ["POST_ONLY"]}
    assert _params_to_str(params) == "exec_instPOST_ONLYinstrument_nameBTC_USDquantity1sideBUY"
    assert sign_request("private/create-order", 12, KEY, params, 1700000000001, SECRET) == \
        "18fc00d535deff4029701d752ede3ab0943a2842b87c842daebe1365a53e3f60"


def test_sign_no_params():
    assert sign_request("private/user-balance", 13, KEY, {}, 1700000000002, SECRET) == \
        "f263e4dbcd5ffa8400d39a2d95767d71089a92b8a4f884f100053e8c2ce3db8b"


def test_sign_nested_official_docs_example():
    # params of the official docs example for private/create-order-list (list of dicts)
    params = {"contingency_type": "LIST", "order_list": [
        {"instrument_name": "ONE_USDT", "side": "BUY", "type": "LIMIT", "price": "0.24", "quantity": "1.0"},
        {"instrument_name": "ONE_USDT", "side": "BUY", "type": "STOP_LIMIT", "price": "0.27", "quantity": "1.0",
         "trigger_price": "0.26"}]}
    assert sign_request("private/create-order-list", 14, "APIKEY", params, 1700000000003, "SECRETKEY") == \
        "2460424f2b2fb4c2c7e282ed0593a34ead2cd6588b2f34f60791a91aa0d75f98"


def test_sign_none_is_null():
    assert _params_to_str({"a": None, "b": "x"}) == "anullbx"


def test_request_body_contains_valid_signature_and_no_secret():
    c, s, _ = make({"private/user-balance": [ok({"data": []})]})
    c.get_balances()
    verb, m, body = s.calls[-1]
    assert verb == "POST" and m == "private/user-balance"
    assert body["api_key"] == KEY and "secret" not in json.dumps(body).lower().replace("api_secret", "")
    assert SECRET not in json.dumps(body)
    assert body["sig"] == sign_request(m, body["id"], KEY, body["params"], body["nonce"], SECRET)
    assert body["params"] == {}


def test_repr_hides_secret():
    c, _, _ = make()
    assert SECRET not in repr(c) and KEY not in repr(c)


# ---------------------------------------------------------------- formatting
def test_fmt_decimal_no_scientific():
    assert fmt_decimal(quantize_to_tick(0.00001, "0.00001", "down")) == "0.00001"
    assert fmt_decimal(quantize_to_tick(1e-7, "1e-8", "down")) == "0.0000001"
    assert fmt_decimal(quantize_to_tick(85000.0, "0.01")) == "85000"
    assert fmt_decimal(quantize_to_tick(1.5e10, "0.5")) == "15000000000"


def test_quantize_float_noise():
    assert fmt_decimal(quantize_to_tick(0.29, "0.01", "down")) == "0.29"   # 0.29*100 = 28.999.. in float math
    assert fmt_decimal(quantize_to_tick(0.1 + 0.2, "0.1", "down")) == "0.3"
    assert fmt_decimal(quantize_to_tick(85000.005, "0.01", "nearest")) == "85000.01"
    assert fmt_decimal(quantize_to_tick(85000.019, "0.01", "down")) == "85000.01"
    assert fmt_decimal(quantize_to_tick(85000.011, "0.01", "up")) == "85000.02"


def test_round_price_qty_use_instrument_ticks():
    c, _, _ = make()
    assert c.round_qty("BTC_USD", 0.0012399) == 0.00123
    assert c.round_qty("SOL_USD", 1.23999) == 1.239
    assert c.round_price("BTC_USD", 85000.126) == 85000.13
    assert c.round_price("BTC_USD", 85000.129, "down") == 85000.12


# ---------------------------------------------------------------- public
def test_get_instrument_parses_and_caches():
    c, s, _ = make()
    i = c.get_instrument("SOL_USD")
    assert (i.base, i.quote, i.price_tick, i.qty_tick) == ("SOL", "USD", 0.01, 0.001)
    c.get_instrument("BTC_USD")
    assert [m for _, m, _ in s.calls].count("public/get-instruments") == 1
    with pytest.raises(ExchangeError):
        c.get_instrument("NOPE_USD")


def test_get_candles_sorted_dedup_and_closed_only():
    rows = [{"t": str(t), "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "3"} for t in (3_600_000, 1_800_000, 1_800_000, 5_400_000)]
    c, s, _ = make({"public/get-candlestick": [ok({"data": rows})]})
    c._clock = lambda: 5_500  # seconds -> now_ms 5_500_000: candle 5_400_000 still open
    cs = c.get_candles("BTC_USD", "30m", 3)
    assert [x.t for x in cs] == [1_800_000, 3_600_000, 5_400_000] and cs[0].h == 2.0
    assert [x.t for x in c.get_candles("BTC_USD", "30m", 3, closed_only=True)] == [1_800_000, 3_600_000]
    assert s.calls[0][2] == {"instrument_name": "BTC_USD", "timeframe": "30m", "count": 3}


def test_get_candles_bad_timeframe_and_clamp():
    c, s, _ = make({"public/get-candlestick": [ok({"data": []})]})
    with pytest.raises(ExchangeError):
        c.get_candles("BTC_USD", "3m")
    c.get_candles("BTC_USD", "4h", 5000, end_ts=123)
    assert s.calls[-1][2]["count"] == 300 and s.calls[-1][2]["end_ts"] == 123


def test_get_candles_paged():
    def page(ts):
        return ok({"data": [{"t": str(t), "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"} for t in ts]})
    pages = [page(range(600, 1000, 100)), page(range(200, 600, 100)), page([])]
    c, s, _ = make({"public/get-candlestick": pages})
    cs = c.get_candles_paged("BTC_USD", "30m", 20)
    assert [x.t for x in cs] == [200, 300, 400, 500, 600, 700, 800, 900]
    assert s.calls[1][2]["end_ts"] == 600  # second page ends at oldest t of first page


def test_get_ticker():
    c, _, _ = make({"public/get-tickers": [ok({"data": [{"i": "BTC_USD", "b": "74713.96", "k": "74713.97", "a": "74720.83", "t": 1794182388021}]})]})
    assert c.get_ticker("BTC_USD") == {"bid": 74713.96, "ask": 74713.97, "last": 74720.83, "ts": 1794182388021}
    c2, _, _ = make({"public/get-tickers": [ok({"data": []})]})
    with pytest.raises(ExchangeError):
        c2.get_ticker("BTC_USD")


# ---------------------------------------------------------------- private basics
def test_private_requires_key():
    c = CryptoComClient(session=FakeSession({"public/get-instruments": [INSTRUMENTS]}))
    with pytest.raises(ExchangeError, match="missing"):
        c.get_balances()


def test_get_balances_available_is_quantity_minus_reserved():
    res = ok({"data": [{"position_balances": [
        {"instrument_name": "USD", "quantity": "1000.5", "reserved_qty": "200.5"},
        {"instrument_name": "BTC", "quantity": "0.5", "reserved_qty": "0.0"}]}]})
    c, _, _ = make({"private/user-balance": [res]})
    assert c.get_balances() == {"USD": 800.0, "BTC": 0.5}


def test_place_limit_request_fields_and_formatting():
    c, s, _ = make({"private/create-order": [ok({"order_id": "123", "client_oid": "c1"})]})
    oid = c.place_limit("BTC_USD", "buy", 0.0012399, 85000.126, "c1")
    assert oid == "123"
    p = s.calls[-1][2]["params"]
    assert p == {"instrument_name": "BTC_USD", "side": "BUY", "type": "LIMIT", "price": "85000.13",
                 "quantity": "0.00123", "client_oid": "c1", "time_in_force": "GOOD_TILL_CANCEL"}
    assert all(isinstance(v, str) for v in p.values())  # docs: all numbers are strings


def test_place_limit_post_only_and_market():
    c, s, _ = make({"private/create-order": [ok({"order_id": "5"})]})
    c.place_limit("SOL_USD", "SELL", 3.9999, 150, "c2", post_only=True)
    p = s.calls[-1][2]["params"]
    assert p["exec_inst"] == ["POST_ONLY"] and p["quantity"] == "3.999" and p["price"] == "150"
    c.place_market("SOL_USD", "SELL", 2, "c3")
    p = s.calls[-1][2]["params"]
    assert p["type"] == "MARKET" and "price" not in p and p["quantity"] == "2"
    body = s.calls[-1][2]
    assert body["sig"] == sign_request("private/create-order", body["id"], KEY, p, body["nonce"], SECRET)


@pytest.mark.parametrize("kw", [
    dict(side="HOLD", qty=1, price=1, oid="x"), dict(side="BUY", qty=0, price=1, oid="x"),
    dict(side="BUY", qty=0.000001, price=1, oid="x"), dict(side="BUY", qty=1, price=0, oid="x"),
    dict(side="BUY", qty=1, price=1, oid=""), dict(side="BUY", qty=1, price=1, oid="x" * 37)])
def test_place_limit_validation(kw):
    c, s, _ = make({"private/create-order": [ok({"order_id": "1"})]})
    with pytest.raises(ExchangeError):
        c.place_limit("BTC_USD", kw["side"], kw["qty"], kw["price"], kw["oid"])
    assert not [x for x in s.calls if x[1] == "private/create-order"]


def test_refuses_non_spot_instrument():
    c, s, _ = make({"private/create-order": [ok({"order_id": "1"})]})
    with pytest.raises(ExchangeError, match="spot"):
        c.place_market("BTCUSD-PERP", "BUY", 1, "x")
    assert not [x for x in s.calls if x[1] == "private/create-order"]


# ---------------------------------------------------------------- retry / idempotency rules
def test_create_order_not_retried_on_timeout_recovers_by_client_oid():
    detail = ok({"order_id": "777", "client_oid": "c9", "status": "ACTIVE", "instrument_name": "BTC_USD",
                 "side": "BUY", "order_type": "LIMIT", "quantity": "0.001", "limit_price": "80000"})
    c, s, _ = make({"private/create-order": [requests.exceptions.ReadTimeout()],
                    "private/get-order-detail": [detail]})
    assert c.place_limit("BTC_USD", "BUY", 0.001, 80000, "c9") == "777"
    assert [m for _, m, _ in s.calls].count("private/create-order") == 1   # NOT repeated
    assert s.calls[-1][2]["params"] == {"client_oid": "c9"}


def test_create_order_timeout_and_not_found_raises_unknown_state():
    notfound = err(40401, "NOT_FOUND", 200)
    c, s, _ = make({"private/create-order": [requests.exceptions.ConnectionError("boom")],
                    "private/get-order-detail": [notfound], "private/advanced/get-order-detail": [notfound],
                    "private/get-open-orders": [ok({"data": []})], "private/advanced/get-open-orders": [ok({"data": []})]})
    with pytest.raises(OrderStateUnknown):
        c.place_limit("BTC_USD", "BUY", 0.001, 80000, "c9")
    assert [m for _, m, _ in s.calls].count("private/create-order") == 1


def test_create_order_http500_not_retried():
    detail = ok({"order_id": "9", "client_oid": "c1", "status": "NEW", "instrument_name": "BTC_USD", "side": "BUY", "order_type": "LIMIT"})
    c, s, _ = make({"private/create-order": [err(50001, "ERR_INTERNAL", 500)], "private/get-order-detail": [detail]})
    assert c.place_limit("BTC_USD", "BUY", 0.001, 80000, "c1") == "9"
    assert [m for _, m, _ in s.calls].count("private/create-order") == 1


def test_create_order_retried_on_explicit_rate_limit_with_fresh_signature():
    c, s, sleeps = make({"private/create-order": [err(42901, "TOO_MANY_REQUESTS", 429), ok({"order_id": "42"})]})
    clock = iter(range(1_700_000_000, 1_700_000_100))
    c._clock = lambda: next(clock)
    assert c.place_market("BTC_USD", "BUY", 0.001, "c1") == "42"
    posts = [x[2] for x in s.calls if x[1] == "private/create-order"]
    assert len(posts) == 2 and sleeps
    assert posts[0]["sig"] != posts[1]["sig"] and posts[0]["nonce"] != posts[1]["nonce"]
    assert posts[0]["params"]["client_oid"] == posts[1]["params"]["client_oid"] == "c1"


def test_duplicate_client_oid_returns_existing_order():
    detail = ok({"order_id": "55", "client_oid": "c1", "status": "ACTIVE", "instrument_name": "BTC_USD", "side": "BUY", "order_type": "LIMIT"})
    c, _, _ = make({"private/create-order": [err(204, "DUPLICATE_CLORDID", 400)], "private/get-order-detail": [detail]})
    assert c.place_limit("BTC_USD", "BUY", 0.001, 80000, "c1") == "55"


def test_api_error_message_is_clear_and_never_leaks_original():
    c, _, _ = make({"private/create-order": [err(308, "INVALID_PRICE", 400)]})
    with pytest.raises(ExchangeError) as ei:
        c.place_limit("BTC_USD", "BUY", 0.001, 80000, "c1")
    msg = str(ei.value)
    assert "308" in msg and "INVALID_PRICE" in msg and "LEAKME" not in msg and KEY not in msg
    assert ei.value.code == 308


def test_reads_retry_then_give_up():
    c, s, sleeps = make({"private/get-open-orders": [err(42901, "TOO_MANY_REQUESTS", 429)]}, max_retries=2)
    with pytest.raises(ExchangeError) as ei:
        c.open_orders("BTC_USD")
    assert ei.value.code == 42901
    assert len([x for x in s.calls if x[1] == "private/get-open-orders"]) == 3 and len(sleeps) == 2


def test_read_retries_on_timeout_then_succeeds():
    c, s, _ = make({"private/user-balance": [requests.exceptions.ReadTimeout(), ok({"data": []})]})
    assert c.get_balances() == {}


def test_auth_error_not_retried():
    c, s, _ = make({"private/user-balance": [err(40101, "UNAUTHORIZED", 401)]})
    with pytest.raises(ExchangeError, match="40101"):
        c.get_balances()
    assert len(s.calls) == 1


def test_non_json_response():
    c, _, _ = make({"private/user-balance": [Resp(ValueError("x"), 502)]}, max_retries=0)
    with pytest.raises(ExchangeError, match="not JSON"):
        c.get_balances()


# ---------------------------------------------------------------- orders: parse / cancel
def test_get_order_parses_detail():
    d = ok({"order_id": "19848525", "client_oid": "c1", "order_type": "LIMIT", "side": "BUY", "quantity": "0.0100",
            "limit_price": "50000.0", "avg_price": "49990.5", "cumulative_quantity": "0.0100",
            "cumulative_fee": "1.25", "fee_instrument_name": "USD", "status": "FILLED",
            "instrument_name": "BTC_USD", "create_time": "1613575617173", "update_time": "1613575617999"})
    c, s, _ = make({"private/get-order-detail": [d]})
    o = c.get_order(19848525)
    assert s.calls[-1][2]["params"] == {"order_id": "19848525"}   # string id (docs recommendation)
    assert (o.order_id, o.status, o.filled_qty, o.avg_price, o.fee, o.price, o.qty) == \
        ("19848525", "FILLED", 0.01, 49990.5, 1.25, 50000.0, 0.01)
    assert o.created_ts == 1613575617173 and o.updated_ts == 1613575617999


def test_get_order_fee_in_base_currency_converted():
    d = ok({"order_id": "1", "order_type": "MARKET", "side": "BUY", "quantity": "1", "avg_price": "100",
            "cumulative_quantity": "1", "cumulative_fee": "0.005", "fee_instrument_name": "SOL", "status": "FILLED",
            "instrument_name": "SOL_USD"})
    c, _, _ = make({"private/get-order-detail": [d]})
    assert c.get_order("1").fee == pytest.approx(0.5)


def test_get_order_falls_back_to_advanced_and_not_found():
    adv = ok({"order_id": "8", "order_type": "STOP_LOSS", "side": "SELL", "quantity": "1", "ref_price": "90",
              "status": "PENDING", "instrument_name": "BTC_USD"})
    c, s, _ = make({"private/get-order-detail": [err(40401, "NOT_FOUND", 200)], "private/advanced/get-order-detail": [adv]})
    o = c.get_order("8")
    assert o.type == "STOP_LOSS" and o.status == "NEW" and o.price == 90.0
    nf = err(40401, "NOT_FOUND", 200)
    c2, _, _ = make({"private/get-order-detail": [nf], "private/advanced/get-order-detail": [nf]})
    with pytest.raises(ExchangeError, match="not found"):
        c2.get_order("1")


def test_get_order_accepts_legacy_order_info_wrapper():
    d = ok({"order_info": {"order_id": "3", "order_type": "LIMIT", "side": "SELL", "quantity": "2", "status": "ACTIVE", "instrument_name": "SOL_USD"}})
    c, _, _ = make({"private/get-order-detail": [d]})
    assert c.get_order("3").status == "ACTIVE"


def test_open_orders_all_and_filtered():
    data = ok({"data": [{"order_id": "1", "client_oid": "a", "order_type": "LIMIT", "side": "BUY", "quantity": "1", "limit_price": "5", "status": "ACTIVE", "instrument_name": "SOL_USD"}]})
    c, s, _ = make({"private/get-open-orders": [data]})
    assert len(c.open_orders()) == 1 and s.calls[-1][2]["params"] == {}
    c.open_orders("SOL_USD")
    assert s.calls[-1][2]["params"] == {"instrument_name": "SOL_USD"}


def test_cancel_ok_and_idempotent_when_already_canceled():
    c, s, _ = make({"private/cancel-order": [ok({"order_id": "1", "client_oid": "c"})]})
    c.cancel("BTC_USD", "1")
    assert s.calls[-1][2]["params"] == {"order_id": "1"}
    canc = ok({"order_id": "1", "order_type": "LIMIT", "side": "BUY", "quantity": "1", "status": "CANCELED", "instrument_name": "BTC_USD"})
    c2, _, _ = make({"private/cancel-order": [err(50001, "x", 500)], "private/get-order-detail": [canc]}, max_retries=0)
    c2.cancel("BTC_USD", "1")  # failed call, but order is canceled -> fine


def test_cancel_of_filled_order_raises_with_status():
    filled = ok({"order_id": "1", "order_type": "LIMIT", "side": "BUY", "quantity": "1", "cumulative_quantity": "1", "status": "FILLED", "instrument_name": "BTC_USD"})
    c, _, _ = make({"private/cancel-order": [err(500, "x", 500)], "private/get-order-detail": [filled]}, max_retries=0)
    with pytest.raises(ExchangeError, match="already FILLED") as ei:
        c.cancel("BTC_USD", "1")
    assert ei.value.order_status == "FILLED"


# ---------------------------------------------------------------- stop (advanced) order
def test_place_stop_market_fields():
    c, s, _ = make({"private/advanced/create-order": [ok({"order_id": "5755600460443882762", "client_oid": "s1"})]})
    oid = c.place_stop_market("SOL_USD", 3.0009, 120.456, "s1")
    assert oid == "5755600460443882762"
    assert s.calls[-1][1] == "private/advanced/create-order"
    assert s.calls[-1][2]["params"] == {"instrument_name": "SOL_USD", "side": "SELL", "type": "STOP_LOSS",
                                         "quantity": "3", "ref_price": "120.46", "ref_price_type": "LAST_PRICE",
                                         "client_oid": "s1"}
    with pytest.raises(ExchangeError):
        c.place_stop_market("SOL_USD", 3, 120, "s1", ref_price_type="BOGUS")
