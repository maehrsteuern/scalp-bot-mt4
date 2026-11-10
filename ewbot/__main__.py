"""Command line: python -m ewbot {run|backtest|fetch|status|check} --config config/ewbot-15m.yaml"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .bot import iso, safe_symbol, timeframe_ms
from .config import BotCfg, load_config

DAY_MS = 86_400_000
HTF_WARMUP_BARS = 70   # fetched before the backtest window so the HTF context is ready at the start


def load_dotenv(path: str | os.PathLike[str] = ".env") -> int:
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win. Returns count loaded."""
    p = Path(path)
    if not p.is_file():
        return 0
    n = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            n += 1
    return n


# -------------------------------------------------------------------------------------- commands

def cmd_run(cfg: BotCfg, args: argparse.Namespace) -> int:
    from .bot import build_bot, setup_logging

    logger = setup_logging(cfg)
    bot = build_bot(cfg, logger)
    bot.restore()
    bot.run_forever()
    return 0


def _symbols(cfg: BotCfg, args: argparse.Namespace) -> list[str]:
    syms = [m.symbol for m in cfg.markets]
    if getattr(args, "symbols", None):
        wanted = [s.strip() for s in args.symbols.split(",") if s.strip()]
        syms = [s for s in syms if s in wanted]
    return syms


def _timeframes(cfg: BotCfg) -> list[str]:
    return [cfg.strategy.exec_timeframe] + [tf for tf in cfg.strategy.htf_timeframes
                                            if tf != cfg.strategy.exec_timeframe]


def _download(cfg: BotCfg, symbols: list[str], days: int) -> dict:
    """Fetch history for exec + HTF timeframes, including warm-up bars before the window."""
    from .data import MarketData

    md = MarketData(cfg.exchange)
    now = int(time.time() * 1000)
    start = now - int(days) * DAY_MS
    out: dict = {}
    for sym in symbols:
        out[sym] = {}
        for tf in _timeframes(cfg):
            tf_ms = timeframe_ms(tf)
            warm = (cfg.swing.lookback if tf == cfg.strategy.exec_timeframe else HTF_WARMUP_BARS) * tf_ms
            print(f"  lade {sym} {tf} ...", flush=True)
            out[sym][tf] = md.fetch_history(sym, tf, start - warm, now)
            print(f"    {len(out[sym][tf])} Kerzen", flush=True)
    return out


def _read_csvs(cfg: BotCfg, symbols: list[str], csv_dir: str) -> dict:
    from .data import MarketData

    out: dict = {}
    for sym in symbols:
        frames = {}
        for tf in _timeframes(cfg):
            path = Path(csv_dir) / f"{safe_symbol(sym)}_{tf}.csv"
            if not path.is_file():
                print(f"  fehlt: {path} – {sym} wird übersprungen", file=sys.stderr)
                frames = {}
                break
            frames[tf] = MarketData.from_csv(path)
        if frames:
            out[sym] = frames
    return out


def cmd_backtest(cfg: BotCfg, args: argparse.Namespace) -> int:
    from .backtest import run_backtest
    from .bot import setup_logging

    logger = setup_logging(cfg, to_file=False)
    logger.setLevel(str(args.log_level).upper())
    symbols = _symbols(cfg, args)
    if args.csv_dir:
        candles = _read_csvs(cfg, symbols, args.csv_dir)
    else:
        print(f"Lade {args.days} Tage Historie von {cfg.exchange.id} ...")
        candles = _download(cfg, symbols, args.days)
    if not candles:
        print("Keine Kursdaten – Abbruch.", file=sys.stderr)
        return 1
    equity = args.equity if args.equity is not None else cfg.exchange.paper_start_equity
    result = run_backtest(cfg, candles, equity, logger=logger)
    print(result.to_markdown())
    out_dir = Path(args.out) / f"{cfg.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    eq, tr = result.save_csv(out_dir)
    (out_dir / "report.md").write_text(result.to_markdown() + "\n", encoding="utf-8")
    print(f"\nCSV: {eq}\n     {tr}")
    return 0


def cmd_fetch(cfg: BotCfg, args: argparse.Namespace) -> int:
    from .data import MarketData

    symbols = _symbols(cfg, args)
    print(f"Lade {args.days} Tage Historie nach {args.out}/ ...")
    data = _download(cfg, symbols, args.days)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    for sym, frames in data.items():
        for tf, candles in frames.items():
            path = Path(args.out) / f"{safe_symbol(sym)}_{tf}.csv"
            MarketData.to_csv(candles, path)
            print(f"  {path}: {len(candles)} Kerzen")
    return 0


def cmd_status(cfg: BotCfg, args: argparse.Namespace) -> int:
    path = Path(cfg.state_file)
    if not path.is_file():
        print(f"Keine Statusdatei unter {path} (Bot noch nie gelaufen?)")
        return 1
    st = json.loads(path.read_text(encoding="utf-8") or "{}")
    q = cfg.exchange.quote
    print(f"Instanz:      {st.get('name', cfg.name)} ({st.get('mode', cfg.exchange.mode)})")
    if st.get("updated_ts"):
        print(f"Gespeichert:  {iso(int(st['updated_ts']))} UTC")
    eq = st.get("equity")
    print(f"Equity:       {eq:.2f} {q}" if isinstance(eq, (int, float)) else "Equity:       ?")
    day = st.get("day_start") or {}
    if day:
        print(f"Tagesstart:   {day.get('date')} mit {float(day.get('equity', 0)):.2f} {q}")
    print(f"Pausiert:     {'ja' if st.get('paused') else 'nein'}")
    print(f"Trades:       {st.get('trades_count', 0)} (seit Start dieser Statusdatei)")
    positions = st.get("positions") or []
    print(f"Positionen:   {len(positions)}")
    for p in positions:
        print(f"  {p.get('symbol')} {p.get('side')} {p.get('setup')} qty={p.get('qty_open')} entry={p.get('entry')} "
              f"stop={p.get('stop')} tp1={p.get('tp1')} tp2={p.get('tp2')}")
    for sym, ts in sorted((st.get("last_seen") or {}).items()):
        print(f"  letzte Kerze {sym}: {iso(int(ts))} UTC")
    trades = st.get("trades") or []
    if trades:
        print("Letzte Trades:")
        for t in trades[-10:]:
            pos = t.get("position", {})
            print(f"  {iso(int(t.get('closed_ts', 0)))} {pos.get('symbol')} {pos.get('side')} {pos.get('setup')} "
                  f"pnl={float(t.get('pnl', 0)):+.4f} ({t.get('reason')})")
    return 0


def cmd_check(cfg: BotCfg, args: argparse.Namespace) -> int:
    ok = True
    print(f"Konfiguration OK: {args.config}")
    print(f"  Instanz {cfg.name} | Modus {cfg.exchange.mode} | Börse {cfg.exchange.id} | "
          f"Zeitebene {cfg.strategy.exec_timeframe} + {','.join(cfg.strategy.htf_timeframes)}")
    print(f"  Risiko {cfg.risk.risk_pct}% je Trade | max {cfg.risk.max_positions} Positionen | "
          f"Tagesverlustgrenze {cfg.risk.daily_loss_cap_pct}%")
    print(f"  Märkte: {', '.join(m.symbol + (' (short)' if m.allow_short else '') for m in cfg.markets)}")
    print("Umgebungsvariablen (Werte werden nie angezeigt):")
    needed = {cfg.exchange.api_key_env: cfg.exchange.mode == "live",
              cfg.exchange.api_secret_env: cfg.exchange.mode == "live",
              cfg.telegram.token_env: cfg.telegram.enabled,
              cfg.telegram.chat_id_env: cfg.telegram.enabled}
    for name, required in needed.items():
        present = bool(os.environ.get(name, "").strip())
        tag = "gesetzt" if present else ("FEHLT (benötigt)" if required else "nicht gesetzt")
        print(f"  {name:<24} {tag}")
        ok &= present or not required
    print(f"Verbindung zu {cfg.exchange.id} ...")
    try:
        import ccxt  # noqa: WPS433

        ex = getattr(ccxt, cfg.exchange.id)({"enableRateLimit": True})
        if cfg.exchange.sandbox:
            ex.set_sandbox_mode(True)
        markets = ex.load_markets()
        print(f"  {len(markets)} Märkte geladen")
        for m in cfg.markets:
            info = markets.get(m.symbol)
            if info is None:
                print(f"  {m.symbol:<14} NICHT GEFUNDEN")
                ok = False
                continue
            min_cost = ((info.get("limits") or {}).get("cost") or {}).get("min")
            min_amt = ((info.get("limits") or {}).get("amount") or {}).get("min")
            print(f"  {m.symbol:<14} ok (Typ {info.get('type')}, min. Menge {min_amt}, min. Wert {min_cost})")
        if cfg.exchange.mode == "live" and all(os.environ.get(k) for k in
                                               (cfg.exchange.api_key_env, cfg.exchange.api_secret_env)):
            ex.apiKey = os.environ[cfg.exchange.api_key_env].strip()
            ex.secret = os.environ[cfg.exchange.api_secret_env].strip()
            bal = ex.fetch_balance()
            total = (bal.get("total") or {}).get(cfg.exchange.quote)
            print(f"  API-Key ok, Guthaben {cfg.exchange.quote}: {total}")
    except Exception as exc:  # network, auth, unknown exchange id ...
        print(f"  FEHLER: {type(exc).__name__}: {str(exc)[:300]}")
        return 2
    print("Alles in Ordnung." if ok else "Es gibt Probleme (siehe oben).")
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ewbot", description="Elliott-Wave Trading Bot (Crypto.com Exchange)")
    p.add_argument("--env-file", default=".env", help="optional .env file to load (default: ./.env)")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--config", "-c", default="config/ewbot-15m.yaml", help="YAML config file")
        return sp

    add("run", "start the bot (endless loop)")
    bt = add("backtest", "backtest on history (download or CSV)")
    bt.add_argument("--days", type=int, default=90, help="days of history to fetch (ignored with --csv-dir)")
    bt.add_argument("--csv-dir", default=None, help="read CSVs (e.g. BTC-USD_15m.csv) instead of downloading")
    bt.add_argument("--out", default="reports", help="output directory for report + CSV")
    bt.add_argument("--equity", type=float, default=None, help="start equity (default paper_start_equity)")
    bt.add_argument("--symbols", default=None, help="comma separated subset, e.g. BTC/USD,ETH/USD")
    bt.add_argument("--log-level", default="WARNING", help="log level during the backtest")
    fe = add("fetch", "download OHLCV history to CSV")
    fe.add_argument("--days", type=int, default=90)
    fe.add_argument("--out", default="data")
    fe.add_argument("--symbols", default=None)
    add("status", "print the state file summary")
    add("check", "validate config, env vars and exchange connectivity")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env_file)
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"Konfigurationsfehler in {args.config}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    handlers = {"run": cmd_run, "backtest": cmd_backtest, "fetch": cmd_fetch, "status": cmd_status,
                "check": cmd_check}
    return int(handlers[args.command](cfg, args) or 0)


if __name__ == "__main__":
    sys.exit(main())
