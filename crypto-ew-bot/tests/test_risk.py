from ewbot.risk import RiskConfig, daily_loss_hit, floor_to_tick, position_size

CFG = RiskConfig(risk_pct=0.75, max_exposure_pct=90, daily_loss_cap_pct=2, max_capital_usd=1000, min_notional_usd=10)


def test_floor_to_tick_exact():
    assert floor_to_tick(0.123456, 0.0001) == 0.1234
    assert floor_to_tick(0.3, 0.1) == 0.3          # float trap: 0.3/0.1 = 2.999...
    assert floor_to_tick(5.999, 1) == 5
    assert floor_to_tick(1.23, 0) == 1.23


def test_size_is_risk_over_distance():
    r = position_size(1000, 73900, 72400, 0.0, CFG, qty_tick=0.00001)
    assert r.ok
    assert abs(r.qty - 0.005) < 1e-9                 # 7.5 USD / 1500
    assert abs(r.risk_usd - 7.5) < 1e-6


def test_max_capital_caps_equity():
    r = position_size(5000, 100, 90, 0.0, CFG, qty_tick=0.01)
    assert r.ok and abs(r.risk_usd - 7.5) < 0.01     # sized from 1000, not 5000


def test_exposure_cap_reduces_size():
    r = position_size(1000, 100, 99, 850.0, CFG, qty_tick=0.01)   # risk would allow 7.5 units = 750 USD
    assert r.ok and r.qty == 0.5                      # room = 900 - 850 = 50 USD
    assert "gekuerzt" in r.reason


def test_exposure_full_rejects():
    assert not position_size(1000, 100, 90, 900.0, CFG).ok


def test_min_notional_rejects():
    r = position_size(1000, 100, 50, 0.0, CFG, qty_tick=0.01)    # 7.5/50 = 0.15 units = 15 USD ok
    assert r.ok
    r = position_size(1000, 100, 90, 0.0, RiskConfig(risk_pct=0.01, min_notional_usd=10), qty_tick=0.001)
    assert not r.ok


def test_min_qty_and_bad_prices():
    assert not position_size(1000, 100, 90, 0.0, CFG, qty_tick=0.01, min_qty=5).ok
    assert not position_size(1000, 90, 100, 0.0, CFG).ok
    assert not position_size(0, 100, 90, 0.0, CFG).ok


def test_daily_loss_cap():
    assert not daily_loss_hit(1000, -19.9, CFG)
    assert daily_loss_hit(1000, -20.0, CFG)
    assert not daily_loss_hit(1000, +50, CFG)
