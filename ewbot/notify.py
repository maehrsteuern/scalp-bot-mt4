"""Telegram notifications and command polling (Bot API via requests). Never raises."""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .config import TelegramCfg, env_secret
from .models import Fill, Position, Signal, TradeRecord

log = logging.getLogger("ewbot.notify")

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 10
MAX_LEN = 4096


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _fmt_price(x: float) -> str:
    if x == 0:
        return "0"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.2f}"
    if ax >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.6g}"


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class Telegram:
    """Sends HTML messages and polls commands from the configured chat only.

    Disabled silently (send() -> False, poll_commands() -> []) when cfg.enabled is False or the
    token / chat id env vars are missing. Commands are returned as ("/status", "args").
    """

    def __init__(self, cfg: TelegramCfg, session: Any = None) -> None:
        self.cfg = cfg
        self.token = env_secret(cfg.token_env)
        self.chat_id = env_secret(cfg.chat_id_env)
        self.enabled = bool(cfg.enabled and self.token and self.chat_id)
        if cfg.enabled and not self.enabled:
            log.warning("telegram enabled in config but %s / %s not set; notifications off",
                        cfg.token_env, cfg.chat_id_env)
        self.session = session or requests.Session()
        self._offset: int | None = None
        self._started = time.time()

    def _url(self, method: str) -> str:
        return API.format(token=self.token, method=method)

    def send(self, text: str) -> bool:
        if not self.enabled or not text:
            return False
        if len(text) > MAX_LEN:
            text = text[: MAX_LEN - 20] + "\n…(truncated)"
        try:
            resp = self.session.post(self._url("sendMessage"), data={
                "chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }, timeout=TIMEOUT)
            ok = bool(resp.ok and (resp.json() or {}).get("ok"))
            if not ok:
                log.warning("telegram send failed: %s %s", getattr(resp, "status_code", "?"),
                            str(getattr(resp, "text", ""))[:200])
            return ok
        except Exception as exc:
            log.warning("telegram send error: %s", exc)
            return False

    def poll_commands(self) -> list[tuple[str, str]]:
        """Non-blocking getUpdates; returns [(command, args)] from the configured chat only.
        Messages sent before this process started (minus 60 s) are skipped on the first poll."""
        if not self.enabled:
            return []
        params: dict[str, Any] = {"timeout": 0, "allowed_updates": '["message"]'}
        if self._offset is not None:
            params["offset"] = self._offset
        try:
            resp = self.session.get(self._url("getUpdates"), params=params, timeout=TIMEOUT)
            data = resp.json() or {}
        except Exception as exc:
            log.warning("telegram poll error: %s", exc)
            return []
        if not data.get("ok"):
            return []
        out: list[tuple[str, str]] = []
        for upd in data.get("result") or []:
            try:
                uid = int(upd.get("update_id"))
                self._offset = max(self._offset or 0, uid + 1)
                msg = upd.get("message") or upd.get("edited_message") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                if chat != str(self.chat_id):
                    continue
                if float(msg.get("date", 0)) < self._started - 60:
                    continue   # stale backlog (e.g. an old /close_all) – ignore
                text = (msg.get("text") or "").strip()
                if not text.startswith("/"):
                    continue
                head, _, args = text.partition(" ")
                cmd = head.split("@", 1)[0].lower()
                out.append((cmd, args.strip()))
            except Exception:
                log.debug("bad telegram update skipped: %r", upd)
        return out

    # ----------------------------------------------------------- formatting
    @staticmethod
    def format_signal(signal: Signal) -> str:
        arrow = "🟢 LONG" if signal.side.value == "long" else "🔴 SHORT"
        lines = [
            f"<b>{arrow} {_esc(signal.symbol)}</b> {_esc(signal.timeframe)} · {_esc(signal.setup.value)}",
            f"Entry <code>{_fmt_price(signal.entry)}</code>  SL <code>{_fmt_price(signal.stop)}</code>",
            f"TP1 <code>{_fmt_price(signal.tp1)}</code> (RR {signal.rr1:.2f})  "
            f"TP2 <code>{_fmt_price(signal.tp2)}</code> (RR {signal.rr2:.2f})",
            f"Score {signal.score:.2f} · {_esc(signal.count.degree_label)}",
        ]
        if signal.htf:
            lines.append("HTF: " + ", ".join(f"{_esc(h.timeframe)} {_esc(h.bias.value)}" for h in signal.htf))
        if signal.reasons:
            lines.append("<i>" + _esc("; ".join(signal.reasons)) + "</i>")
        return "\n".join(lines)

    @staticmethod
    def format_fill(fill: Fill, position: Position | None = None) -> str:
        action = "BUY" if fill.side.value == "long" else "SELL"
        lines = [
            f"<b>{action} {_esc(fill.symbol)}</b> · {_esc(fill.reason)}",
            f"Qty <code>{fill.qty:.8g}</code> @ <code>{_fmt_price(fill.price)}</code> "
            f"(fee {fill.fee:.4f})",
        ]
        if position is not None:
            if fill.reason == "entry":
                lines.append(f"SL <code>{_fmt_price(position.stop)}</code> · "
                             f"TP1 <code>{_fmt_price(position.tp1)}</code> · "
                             f"TP2 <code>{_fmt_price(position.tp2)}</code>")
            else:
                lines.append(f"Realised {position.realized_pnl:+.4f} · open qty {position.qty_open:.8g}")
        lines.append(_esc(_fmt_ts(fill.ts)))
        return "\n".join(lines)

    @staticmethod
    def format_trade(trade: TradeRecord) -> str:
        p = trade.position
        icon = "✅" if trade.pnl >= 0 else "❌"
        return (f"{icon} <b>{_esc(p.symbol)}</b> {_esc(p.side.value)} closed ({_esc(trade.reason)})\n"
                f"Entry <code>{_fmt_price(p.entry)}</code> → Exit <code>{_fmt_price(trade.exit_price)}</code>\n"
                f"PnL <b>{trade.pnl:+.4f}</b> ({trade.pnl_pct:+.2f}%) · fees {p.fees:.4f}")

    @staticmethod
    def format_summary(equity: float, day_pnl: float, trades: list[TradeRecord]) -> str:
        wins = sum(1 for t in trades if t.pnl > 0)
        n = len(trades)
        lines = [
            "<b>📊 Daily summary</b>",
            f"Equity <code>{equity:.2f}</code> · Day PnL <b>{day_pnl:+.2f}</b>",
            f"Trades {n} · wins {wins} · losses {n - wins}" + (f" · win rate {wins / n * 100:.0f}%" if n else ""),
        ]
        for t in trades[-10:]:
            lines.append(f"• {_esc(t.position.symbol)} {_esc(t.position.setup.value)} "
                         f"{t.pnl:+.4f} ({_esc(t.reason)})")
        return "\n".join(lines)
