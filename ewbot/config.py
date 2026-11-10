"""YAML config loading with dataclass defaults. One config file == one bot instance."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MarketCfg:
    symbol: str                    # ccxt unified symbol, e.g. "BTC/USD" (spot) or "BTC/USD:USD" (perp)
    allow_short: bool = False      # spot cannot short; perps can
    min_notional: float = 1.0      # quote currency; overridden by exchange limits when known
    weight: float = 1.0            # relative risk multiplier (1.0 = full risk_pct)


@dataclass
class SwingCfg:
    atr_period: int = 14
    atr_mult: float = 2.0          # ZigZag reversal threshold = atr_mult * ATR
    min_bars: int = 3              # minimum bars between consecutive swings
    lookback: int = 400            # candles fed into the swing detector


@dataclass
class ElliottCfg:
    max_swings: int = 14           # how many recent swings to try labelling
    w2_min: float = 0.382          # retracement bands (fraction of previous wave)
    w2_max: float = 0.786
    w4_min: float = 0.236
    w4_max: float = 0.5
    w3_min_ext: float = 1.0        # wave 3 must be >= w3_min_ext * wave 1
    wb_min: float = 0.382
    wb_max: float = 0.786
    min_score: float = 0.55        # candidate counts below this are discarded


@dataclass
class StrategyCfg:
    exec_timeframe: str = "15m"            # "15m" or "30m"
    htf_timeframes: list[str] = field(default_factory=lambda: ["1h", "4h"])
    setups: list[str] = field(default_factory=lambda: ["wave3", "wave5", "waveC"])
    require_htf_agreement: bool = True     # at least one HTF bias must agree, none strongly against
    htf_fib_confluence_atr: float = 0.5    # entry zone within x*ATR of an HTF fib level counts as confluence
    min_signal_score: float = 0.6
    min_rr1: float = 1.0                   # reject signals with worse RR to TP1
    stop_buffer_atr: float = 0.25          # SL beyond invalidation point by x*ATR
    ema_fast: int = 50
    ema_slow: int = 200
    confirm_with_close: bool = True        # entry only after a candle closes in the trade direction
    max_signal_age_bars: int = 3           # a setup older than this (bars since wave-2/4/B low) is stale


@dataclass
class RiskCfg:
    risk_pct: float = 5.0                  # % of equity risked per trade (distance to SL)
    max_positions: int = 3
    max_positions_per_symbol: int = 1
    daily_loss_cap_pct: float = 15.0       # halt new entries for the UTC day
    max_consecutive_losses: int = 4
    pause_minutes_after_losses: int = 120
    tp1_fraction: float = 0.5              # fraction closed at TP1
    move_to_be_after_tp1: bool = True
    trail_after_tp1_atr: float = 0.0       # 0 = no trailing; else trail remaining qty by x*ATR
    max_hold_bars: int = 96                # time stop (bars of exec timeframe); 0 = off
    fee_pct: float = 0.075                 # taker fee per side, percent (Crypto.com default tier)
    slippage_pct: float = 0.03             # paper fill slippage, percent
    min_stop_to_cost: float = 4.0          # stop distance (% of entry) must be >= x * round-trip cost (2*fee+2*slippage); 0 = off


@dataclass
class ExchangeCfg:
    id: str = "cryptocom"
    mode: str = "paper"                    # "paper" | "live"
    sandbox: bool = False                  # ccxt set_sandbox_mode (Crypto.com UAT needs its own keys)
    api_key_env: str = "CRYPTOCOM_API_KEY"
    api_secret_env: str = "CRYPTOCOM_API_SECRET"
    paper_start_equity: float = 20.0       # quote currency
    quote: str = "USD"
    ohlcv_limit: int = 500
    rate_limit: bool = True


@dataclass
class TelegramCfg:
    enabled: bool = False
    token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    poll_seconds: int = 5
    notify_signals: bool = True
    notify_fills: bool = True
    daily_summary_utc: str = "21:00"


@dataclass
class BotCfg:
    name: str = "ewbot-15m"
    state_file: str = "state/ewbot-15m.json"
    log_file: str = "logs/ewbot-15m.log"
    log_level: str = "INFO"
    poll_seconds: int = 20                 # how often the main loop wakes up
    markets: list[MarketCfg] = field(default_factory=lambda: [
        MarketCfg("BTC/USD"), MarketCfg("ETH/USD"), MarketCfg("SOL/USD"), MarketCfg("PAXG/USD"),
    ])
    swing: SwingCfg = field(default_factory=SwingCfg)
    elliott: ElliottCfg = field(default_factory=ElliottCfg)
    strategy: StrategyCfg = field(default_factory=StrategyCfg)
    risk: RiskCfg = field(default_factory=RiskCfg)
    exchange: ExchangeCfg = field(default_factory=ExchangeCfg)
    telegram: TelegramCfg = field(default_factory=TelegramCfg)


def _build(cls: type, data: Any) -> Any:
    """Recursively construct dataclass `cls` from a plain dict (unknown keys raise)."""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise TypeError(f"{cls.__name__}: expected mapping, got {type(data).__name__}")
    kwargs: dict[str, Any] = {}
    known = {f.name: f for f in fields(cls)}
    for key, value in data.items():
        if key not in known:
            raise KeyError(f"{cls.__name__}: unknown config key '{key}'")
        f = known[key]
        ftype = f.type if not isinstance(f.type, str) else f.type
        if key == "markets":
            kwargs[key] = [m if isinstance(m, MarketCfg) else _build(MarketCfg, m) for m in value]
        elif isinstance(f.default_factory, type) and is_dataclass(f.default_factory):  # type: ignore[arg-type]
            kwargs[key] = _build(f.default_factory, value)  # type: ignore[arg-type]
        else:
            kwargs[key] = value
    return cls(**kwargs)


def load_config(path: str | os.PathLike[str]) -> BotCfg:
    """Load a YAML file into BotCfg. Missing keys take defaults; unknown keys raise."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cfg = _build(BotCfg, raw)
    if cfg.strategy.exec_timeframe not in ("5m", "15m", "30m", "1h"):
        raise ValueError(f"exec_timeframe must be 15m or 30m (got {cfg.strategy.exec_timeframe})")
    if cfg.exchange.mode not in ("paper", "live"):
        raise ValueError("exchange.mode must be 'paper' or 'live'")
    return cfg


def env_secret(name: str) -> str | None:
    """Read a secret from the environment (never from the YAML)."""
    value = os.environ.get(name)
    return value.strip() if value else None
