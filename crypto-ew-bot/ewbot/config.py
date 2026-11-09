"""Configuration loading. YAML file + defaults + .env helper. No secrets are ever stored in the YAML."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ALLOWED_COINS = ("BTC", "ETH", "SOL")


class ConfigError(Exception):
    pass


@dataclass
class Config:
    mode: str = "paper"                    # "paper" | "live" (live also needs live_enabled + keys + --confirm-live)
    live_enabled: bool = False
    capital_usd: float = 1000.0            # paper start capital / reference capital
    max_capital_usd: float = 1000.0        # hard cap of capital the bot may use (sizing base)
    risk_pct: float = 0.75                 # risk per trade, % of equity
    max_exposure_pct: float = 90.0         # max sum of position values, % of equity
    daily_loss_cap_pct: float = 2.0        # no new entries after this loss (UTC day), % of day-start equity
    min_notional_usd: float = 10.0         # fallback if the exchange does not report min notional
    coins: List[str] = field(default_factory=lambda: list(ALLOWED_COINS))
    quote: str = "USD"
    # ASSUMPTIONS (not verified for your fee tier) - check your real fees on Crypto.com
    maker_fee: float = 0.0025
    taker_fee: float = 0.005
    slippage_pct: float = 0.0005           # paper market-order slippage (0.05 %)
    eur_per_usd_fallback: float = 0.8974
    state_path: str = "state/paper.json"
    live_state_path: str = "state/live.json"
    kill_path: str = "state/KILL"
    journal_path: str = "state/journal_paper.csv"
    live_journal_path: str = "state/journal_live.csv"
    out_dir: str = "out"
    log_path: str = "logs/ewbot.log"
    strategy: Dict[str, Any] = field(default_factory=dict)   # overrides for StrategyParams

    def instrument(self, coin: str) -> str:
        return f"{coin}_{self.quote}"

    @property
    def instruments(self) -> Dict[str, str]:
        return {c: self.instrument(c) for c in self.coins}


def validate(cfg: Config) -> Config:
    if cfg.mode not in ("paper", "live"):
        raise ConfigError("mode muss 'paper' oder 'live' sein")
    bad = [c for c in cfg.coins if c not in ALLOWED_COINS]
    if bad or not cfg.coins:
        raise ConfigError(f"Nur diese Coins sind erlaubt: {', '.join(ALLOWED_COINS)} (falsch: {bad})")
    if cfg.quote != "USD":
        raise ConfigError("Nur USD-Paare sind erlaubt")
    if not (0 < cfg.risk_pct <= 2):
        raise ConfigError("risk_pct muss zwischen 0 und 2 liegen")
    if not (0 < cfg.max_exposure_pct <= 100):
        raise ConfigError("max_exposure_pct muss zwischen 0 und 100 liegen")
    if cfg.daily_loss_cap_pct <= 0 or cfg.capital_usd <= 0 or cfg.max_capital_usd <= 0:
        raise ConfigError("capital_usd, max_capital_usd und daily_loss_cap_pct muessen > 0 sein")
    return cfg


def from_dict(d: Dict[str, Any]) -> Config:
    """Accepts a flat dict or the nested layout of config.example.yaml (fees:/paths:)."""
    d = dict(d or {})
    flat: Dict[str, Any] = {}
    fees = d.pop("fees", None) or {}
    for k_src, k_dst in (("maker", "maker_fee"), ("taker", "taker_fee"), ("slippage_pct", "slippage_pct")):
        if k_src in fees:
            flat[k_dst] = fees[k_src]
    paths = d.pop("paths", None) or {}
    for k_src, k_dst in (("state", "state_path"), ("live_state", "live_state_path"), ("kill", "kill_path"),
                         ("journal", "journal_path"), ("live_journal", "live_journal_path"),
                         ("out_dir", "out_dir"), ("log", "log_path")):
        if k_src in paths:
            flat[k_dst] = paths[k_src]
    names = {f.name for f in fields(Config)}
    for k, v in d.items():
        if k not in names:
            raise ConfigError(f"Unbekannte Einstellung in der Config: {k}")
        flat[k] = v
    cfg = Config(**flat)
    cfg.coins = [str(c).upper() for c in cfg.coins]
    return validate(cfg)


def load_config(path: str | None = None) -> Config:
    """Load YAML (if path exists) over the defaults. Missing file -> defaults (paper)."""
    if path and os.path.exists(path):
        if yaml is None:
            raise ConfigError("PyYAML fehlt: pip install pyyaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return from_dict(data)
    return validate(Config())


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env reader (KEY=VALUE). Does not override existing env vars. Never prints values."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def api_keys() -> tuple[str | None, str | None]:
    return os.environ.get("CDC_API_KEY") or None, os.environ.get("CDC_API_SECRET") or None
