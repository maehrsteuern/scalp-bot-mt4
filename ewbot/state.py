"""Atomic JSON state persistence and (de)serialisation of Position / TradeRecord."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from .models import Fill, Position, SetupType, Side, TradeRecord

log = logging.getLogger("ewbot.state")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _plain(dataclasses.asdict(obj))
    if isinstance(obj, (set, tuple)):
        return list(obj)
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def _plain(value: Any) -> Any:
    """Recursively convert Enums to their values (dataclasses.asdict keeps Enum objects)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def save_state(path: str | os.PathLike[str], data: dict) -> None:
    """Write `data` as JSON atomically (temp file in the same dir + os.replace)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True, default=_json_default)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_state(path: str | os.PathLike[str]) -> dict:
    """Load JSON state; {} if the file is missing. A corrupt file is moved aside and {} returned."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        backup = p.with_name(p.name + ".corrupt")
        log.error("state file %s unreadable (%s); moved to %s", p, exc, backup)
        try:
            os.replace(p, backup)
        except OSError:
            pass
        return {}
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------------- Position
_POSITION_FIELDS = {f.name for f in dataclasses.fields(Position)}


def position_to_dict(position: Position) -> dict:
    return _plain(dataclasses.asdict(position))


def position_from_dict(data: dict) -> Position:
    kwargs = {k: v for k, v in data.items() if k in _POSITION_FIELDS}
    kwargs["side"] = Side(kwargs["side"])
    kwargs["setup"] = SetupType(kwargs["setup"])
    kwargs["tags"] = {str(k): str(v) for k, v in (kwargs.get("tags") or {}).items()}
    for key in ("qty", "entry", "stop", "tp1", "tp2", "qty_open", "realized_pnl", "fees"):
        if key in kwargs and kwargs[key] is not None:
            kwargs[key] = float(kwargs[key])
    kwargs["opened_ts"] = int(kwargs["opened_ts"])
    qty_open = kwargs.pop("qty_open", None)
    pos = Position(**kwargs)
    if qty_open is not None:
        pos.qty_open = float(qty_open)   # may legitimately be 0.0 for closed positions
    return pos


# ---------------------------------------------------------------- TradeRecord
def trade_to_dict(trade: TradeRecord) -> dict:
    return _plain(dataclasses.asdict(trade))


def trade_from_dict(data: dict) -> TradeRecord:
    return TradeRecord(
        position=position_from_dict(data["position"]),
        closed_ts=int(data["closed_ts"]),
        exit_price=float(data["exit_price"]),
        pnl=float(data["pnl"]),
        pnl_pct=float(data["pnl_pct"]),
        reason=str(data["reason"]),
    )


# ----------------------------------------------------------------------- Fill
def fill_to_dict(fill: Fill) -> dict:
    return _plain(dataclasses.asdict(fill))


def fill_from_dict(data: dict) -> Fill:
    return Fill(ts=int(data["ts"]), symbol=str(data["symbol"]), side=Side(data["side"]),
                qty=float(data["qty"]), price=float(data["price"]), fee=float(data["fee"]),
                reason=str(data["reason"]))
