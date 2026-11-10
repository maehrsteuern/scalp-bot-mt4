import json

from ewbot.models import Fill, Position, SetupType, Side, TradeRecord
from ewbot.state import (fill_from_dict, fill_to_dict, load_state, position_from_dict,
                         position_to_dict, save_state, trade_from_dict, trade_to_dict)


def make_pos():
    return Position(id="ETH/USD-1-1", symbol="ETH/USD", side=Side.LONG, qty=0.4, entry=2000.0,
                    stop=1950.0, tp1=2100.0, tp2=2200.0, opened_ts=1, setup=SetupType.WAVEC,
                    timeframe="30m", tp1_done=True, be_moved=True, qty_open=0.2, realized_pnl=19.4,
                    fees=0.6, tags={"equity_at_open": "1000.0"})


def test_state_roundtrip(tmp_path):
    pos = make_pos()
    closed = make_pos()
    closed.qty_open = 0.0
    tr = TradeRecord(closed, 99, 2150.0, 55.5, 5.55, "tp2")
    fill = Fill(5, "ETH/USD", Side.SHORT, 0.2, 2100.0, 0.3, "tp1")
    path = tmp_path / "sub" / "state.json"
    save_state(path, {"positions": [position_to_dict(pos)], "trades": [trade_to_dict(tr)],
                      "fills": [fill_to_dict(fill)], "last_seen": {"ETH/USD": 123}, "paused": False})
    raw = json.loads(path.read_text())
    assert raw["positions"][0]["side"] == "long" and raw["positions"][0]["setup"] == "waveC"
    data = load_state(path)
    assert position_from_dict(data["positions"][0]) == pos
    tr2 = trade_from_dict(data["trades"][0])
    assert tr2 == tr and tr2.position.qty_open == 0.0
    assert fill_from_dict(data["fills"][0]) == fill
    assert data["last_seen"] == {"ETH/USD": 123}
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]   # no temp files left


def test_load_missing_and_corrupt(tmp_path):
    assert load_state(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_state(bad) == {}
    assert (tmp_path / "bad.json.corrupt").exists()


def test_save_enum_values_directly(tmp_path):
    path = tmp_path / "s.json"
    save_state(path, {"side": Side.SHORT, "pos": make_pos()})
    data = load_state(path)
    assert data["side"] == "short" and data["pos"]["setup"] == "waveC"
