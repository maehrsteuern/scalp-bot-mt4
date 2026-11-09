"""Command line: python -m ewbot <scan|paper-step|run|status|kill> ..."""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal as os_signal
import sys
import time
from typing import Any, Dict, List, Optional

from . import report
from .config import Config, ConfigError, api_keys, load_config, load_dotenv
from .engine import (CANDLE_MS, Engine, StateStore, new_state, run_cycle, run_loop, run_paper_step, utc_date)
from .journal import Journal

log = logging.getLogger("ewbot")

LIVE_WARNING = """
==================================================================
  ACHTUNG: LIVE-MODUS - ECHTES GELD
  Der Bot kauft und verkauft jetzt wirklich auf Crypto.com.
  - Der Stop-Loss liegt NICHT bei der Boerse, sondern wird vom Bot
    geprueft. Laeuft der Bot nicht, gibt es keinen Stop.
  - Verluste sind moeglich, auch bis zum kompletten Einsatz.
  - Not-Aus: python -m ewbot kill   (bzw. kill --flatten)
==================================================================
"""


# ----------------------------------------------------------------- setup helpers
def setup_logging(cfg: Config, verbose: bool = False) -> None:
    root = logging.getLogger("ewbot")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    if root.handlers:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if cfg.log_path:
        try:
            os.makedirs(os.path.dirname(cfg.log_path) or ".", exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(cfg.log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            pass


def make_client(private: bool = False):
    from .exchange import CryptoComClient
    if private:
        k, s = api_keys()
        return CryptoComClient(k, s)
    return CryptoComClient()


def load_infos(client, cfg: Config) -> Dict[str, Any]:
    infos = {}
    for inst in cfg.instruments.values():
        try:
            infos[inst] = client.get_instrument(inst)
        except Exception as e:  # noqa: BLE001
            log.warning("Instrument-Infos %s nicht abrufbar: %s", inst, e)
    return infos


def make_paper_broker(cfg: Config, state: Dict[str, Any], infos: Dict[str, Any]):
    from .paper import PaperBroker
    if state.get("broker"):
        b = PaperBroker.from_dict(state["broker"])
    else:
        b = PaperBroker(starting_balance=state.get("start_capital", cfg.capital_usd), quote=cfg.quote,
                        maker_fee=cfg.maker_fee, taker_fee=cfg.taker_fee, slippage=cfg.slippage_pct)
    for inst, info in (infos or {}).items():    # real tick sizes / minimums from the exchange when available
        b.instruments[inst] = info
    return b


def strategy_fn_for(cfg: Config):
    from . import strategy
    params = strategy.StrategyParams(**cfg.strategy) if cfg.strategy else None

    def fn(coin, instrument, c30, c4h, now_ts=None):
        return strategy.find_signals(coin, instrument, c30, c4h, params, now_ts=now_ts)
    return fn


def get_eurusd(client, cfg: Config) -> float:
    try:
        eur = client.get_ticker("BTC_EUR")["last"]
        usd = client.get_ticker("BTC_USD")["last"]
        if eur > 0 and usd > 0:
            return eur / usd
    except Exception as e:  # noqa: BLE001
        log.warning("EUR-Kurs nicht abrufbar, nehme Ersatzwert: %s", e)
    return cfg.eur_per_usd_fallback


def write_out(path: str, text: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def page_for(cfg: Config, client, now_ts: int, state: Optional[Dict[str, Any]] = None,
             prefer: Optional[Dict[str, Any]] = None) -> tuple[str, Dict[str, Any]]:
    """Fetch public data, run the strategy, render the page. Returns (html, signals_json)."""
    from . import strategy
    fx = get_eurusd(client, cfg)
    sfn = strategy_fn_for(cfg)
    per: Dict[str, Dict[str, Any]] = {}
    sigs_json: Dict[str, Any] = {"generated_ts": now_ts, "eurusd": fx, "signals": []}
    for coin, inst in cfg.instruments.items():
        pc: Dict[str, Any] = {"signal": None, "count": None, "candles": [], "last": None}
        try:
            c30 = [c for c in sorted(client.get_candles(inst, "30m", 300), key=lambda x: x.t) if c.t + CANDLE_MS <= now_ts]
            c4 = sorted(client.get_candles(inst, "4h", 300), key=lambda x: x.t)
            pc["candles"], pc["last"] = c30, (c30[-1].c if c30 else None)
            sigs = sfn(coin, inst, c30, [c for c in c4 if c.t + 4 * 3600_000 <= now_ts], now_ts=now_ts)
            if sigs:
                pc["signal"] = sigs[0].to_dict()
                sigs_json["signals"].append(pc["signal"])
            try:
                pc["count"] = strategy.describe_count(coin, c30, c4)
            except Exception as e:  # noqa: BLE001
                log.warning("describe_count %s: %s", coin, e)
        except Exception as e:  # noqa: BLE001
            log.error("Daten fuer %s nicht abrufbar: %s", coin, e)
        # an active paper trade keeps showing ITS levels
        if state:
            for t in state.get("trades", {}).values():
                if t["coin"] == coin and t["state"] in ("ENTRY_PENDING", "OPEN", "OPEN_BE", "CLOSING"):
                    pc["signal"] = t["signal"]
        per[coin] = pc
    equity = Engine(cfg, None, state).equity() if state else None
    data = report.build_page_data(cfg, now_ts, fx, per, state, equity)
    return report.render_page(data), sigs_json


# ----------------------------------------------------------------- commands
def cmd_scan(args, cfg: Config) -> int:
    client = make_client()
    now_ts = args.now_ts or int(time.time() * 1000)
    state = None
    if os.path.exists(cfg.state_path):
        state = StateStore(cfg.state_path).load()
    page, sigs = page_for(cfg, client, now_ts, state)
    out_json = args.json or os.path.join(cfg.out_dir, "signals.json")
    out_html = args.html or os.path.join(cfg.out_dir, "index.html")
    write_out(out_json, json.dumps(sigs, indent=1, ensure_ascii=False))
    write_out(out_html, page)
    print(f"Signale gefunden: {len(sigs['signals'])} ({', '.join(s['coin'] for s in sigs['signals']) or 'keine'})")
    print(f"JSON: {out_json}\nSeite: {out_html}")
    return 0


def open_paper(cfg: Config, state_path: str, client, now_ts: int):
    store = StateStore(state_path)
    state = store.load() if store.exists() else new_state("paper", cfg.capital_usd, now_ts)
    infos = load_infos(client, cfg)
    broker = make_paper_broker(cfg, state, infos)
    infos = {**broker.instruments, **infos}
    jpath = cfg.journal_path
    if os.path.abspath(state_path) != os.path.abspath(cfg.state_path):
        jpath = os.path.join(os.path.dirname(state_path) or ".", "journal_paper.csv")   # journal travels with the state
    eng = Engine(cfg, broker, state, store, Journal(jpath), infos, strategy_fn_for(cfg), live=False)
    return eng


def cmd_paper_step(args, cfg: Config) -> int:
    client = make_client()
    now_ts = args.now_ts or int(time.time() * 1000)
    state_path = args.state or cfg.state_path
    eng = open_paper(cfg, state_path, client, now_ts)
    summary = run_paper_step(eng, client, now_ts, args.seed_manual)
    if not args.no_html:
        page, _ = page_for(cfg, client, now_ts, eng.state)
        write_out(args.html or os.path.join(cfg.out_dir, "index.html"), page)
    print(json.dumps(summary, indent=1, sort_keys=True, ensure_ascii=False))
    return 0


def check_live_gate(cfg: Config, confirm: bool) -> Optional[str]:
    """Returns None if live trading is allowed, otherwise a German error message."""
    missing = []
    if not cfg.live_enabled:
        missing.append("in der Config fehlt 'live_enabled: true'")
    k, s = api_keys()
    if not (k and s):
        missing.append("die Umgebungsvariablen CDC_API_KEY und CDC_API_SECRET fehlen")
    if not confirm:
        missing.append("der Schalter --confirm-live fehlt")
    if missing:
        return "Live-Modus nicht gestartet, weil: " + "; ".join(missing) + "."
    return None


def cmd_run(args, cfg: Config) -> int:
    mode = args.mode
    stop = {"flag": False}

    def handler(signum, frame):  # noqa: ARG001
        stop["flag"] = True
        log.info("Stop-Signal erhalten, beende nach dem aktuellen Durchlauf")
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        try:
            os_signal.signal(sig, handler)
        except (ValueError, OSError):
            pass
    now_ts = int(time.time() * 1000)
    if mode == "live":
        err = check_live_gate(cfg, args.confirm_live)
        if err:
            print(err, file=sys.stderr)
            return 2
        print(LIVE_WARNING, file=sys.stderr)
        client = make_client(private=True)
        store = StateStore(cfg.live_state_path)
        state = store.load() if store.exists() else new_state("live", min(cfg.capital_usd, cfg.max_capital_usd), now_ts)
        infos = load_infos(client, cfg)
        eng = Engine(cfg, client, state, store, Journal(cfg.live_journal_path), infos, strategy_fn_for(cfg), live=True)
        pub = client
    else:
        client = make_client()
        eng = open_paper(cfg, args.state or cfg.state_path, client, now_ts)
        pub = client
        log.info("Paper-Modus: es wird kein echtes Geld bewegt.")

    class Both:
        """Public data from the client; orders from the engine's broker."""
        def __getattr__(self, name):
            return getattr(pub, name)
    run_loop(eng, Both(), lambda: stop["flag"], poll_s=60)
    eng.persist()
    log.info("Bot beendet.")
    return 0


def cmd_status(args, cfg: Config) -> int:
    path = args.state or (cfg.live_state_path if args.mode == "live" else cfg.state_path)
    store = StateStore(path)
    if not store.exists():
        print(f"Kein Zustand gefunden ({path}). Noch nichts passiert.")
        return 0
    state = store.load()
    if args.clear_halt:
        state["halt_new"] = False
        store.save(state)
        print("Sperre fuer neue Trades aufgehoben.")
    eng = Engine(cfg, None, state)
    s = eng.summary()
    print(f"Modus: {state.get('mode')} | Eigenkapital: {s['equity']:.2f} USD (Start {s['start_capital']:.2f}) | "
          f"realisiert: {s['realized']:+.2f} USD")
    print(f"Offene Positionen: {', '.join(s['open']) or 'keine'} | wartende Einstiege: {', '.join(s['pending']) or 'keine'}")
    print(f"Geschlossen: {s['closed']} (davon Gewinner: {s['wins']})")
    print(f"Kill-Schalter: {s['kill'] or 'aus'} | Sperre neue Trades: {'JA' if s['halt_new'] else 'nein'}")
    for line in state.get("log", [])[-5:]:
        print("  " + line)
    return 0


def cmd_kill(args, cfg: Config) -> int:
    p = cfg.kill_path
    if args.clear:
        if os.path.exists(p):
            os.remove(p)
        print("Kill-Schalter entfernt. Neue Trades sind wieder erlaubt.")
        return 0
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("flatten\n" if args.flatten else "cancel\n")
    print(f"Kill-Schalter gesetzt ({p}): keine neuen Trades, offene Einstiege werden storniert"
          + (", Positionen werden zum Marktpreis verkauft." if args.flatten else "."))
    # apply right away where we can (paper state or live with keys); a running bot also reacts within a minute
    try:
        if args.mode == "live":
            k, s = api_keys()
            store = StateStore(cfg.live_state_path)
            if not (k and s and store.exists()):
                print("Hinweis: Ein laufender Bot beachtet die Datei innerhalb einer Minute.")
                return 0
            client = make_client(private=True)
            state = store.load()
            eng = Engine(cfg, client, state, store, Journal(cfg.live_journal_path), load_infos(client, cfg), live=True)
        else:
            store = StateStore(cfg.state_path)
            if not store.exists():
                return 0
            client = make_client()
            eng = open_paper(cfg, cfg.state_path, client, int(time.time() * 1000))
        eng.now_ts = int(time.time() * 1000)
        eng.apply_kill()
        eng.persist()
        print("Sofort ausgefuehrt. Stand: " + json.dumps(eng.summary(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"Hinweis: Sofort-Ausfuehrung nicht moeglich ({e}). Ein laufender Bot beachtet die Datei innerhalb einer Minute.")
    return 0


# ----------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m ewbot", description="Elliott-Wave Swing-Bot (Spot, Long-only, Crypto.com)")
    p.add_argument("--config", default=None, help="Pfad zur config.yaml (Standard: config.yaml, falls vorhanden)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="Signale suchen und Seite erzeugen (nur oeffentliche Daten)")
    s.add_argument("--json"), s.add_argument("--html"), s.add_argument("--now-ts", type=int, help=argparse.SUPPRESS)
    s = sub.add_parser("paper-step", help="Ein deterministischer Paper-Schritt (z. B. alle 4 Stunden)")
    s.add_argument("--state"), s.add_argument("--html"), s.add_argument("--no-html", action="store_true")
    s.add_argument("--seed-manual", help="JSON mit manuellen Signalen, z. B. signals/manual_2026-11-08.json")
    s.add_argument("--now-ts", type=int, help=argparse.SUPPRESS)
    s = sub.add_parser("run", help="Dauerlauf (VPS)")
    s.add_argument("--mode", choices=["paper", "live"], default="paper")
    s.add_argument("--confirm-live", action="store_true", help="Bestaetigung fuer echtes Geld")
    s.add_argument("--state")
    s = sub.add_parser("status", help="Zustand anzeigen")
    s.add_argument("--mode", choices=["paper", "live"], default="paper")
    s.add_argument("--state"), s.add_argument("--clear-halt", action="store_true")
    s = sub.add_parser("kill", help="Not-Aus: keine neuen Trades, Einstiege stornieren")
    s.add_argument("--flatten", action="store_true", help="zusaetzlich Bot-Positionen zum Marktpreis verkaufen")
    s.add_argument("--clear", action="store_true", help="Kill-Schalter wieder entfernen")
    s.add_argument("--mode", choices=["paper", "live"], default="paper")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(".env")
    cfg_path = args.config or ("config.yaml" if os.path.exists("config.yaml") else None)
    try:
        cfg = load_config(cfg_path)
    except ConfigError as e:
        print(f"Config-Fehler: {e}", file=sys.stderr)
        return 2
    setup_logging(cfg, args.verbose)
    cmds = {"scan": cmd_scan, "paper-step": cmd_paper_step, "run": cmd_run, "status": cmd_status, "kill": cmd_kill}
    return cmds[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
