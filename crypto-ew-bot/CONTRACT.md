# crypto-ew-bot — build contract (for the 3 build agents)

Goal: a spot-only, long-only swing bot for BTC_USD, ETH_USD, SOL_USD on the **Crypto.com Exchange**,
trading mechanised Elliott-Wave setups on the 30-min chart with 4h as trend/degree filter.
Owner: Loris (German tax specialist, knows Python basics, ran MT4 bots). Runs later on a small Linux VPS.
Starts in PAPER mode. Live needs explicit opt-in (see Safety). Python 3.11+, deps: `requests`, `pyyaml`, `pytest` only
(plus stdlib). No ccxt, no pandas in the bot (numpy allowed in backtest only if needed).

Folder: `crypto-ew-bot/` (this folder). Package: `ewbot/`. Shared types: `ewbot/models.py` (fixed — read it first).
Reference material: `reference/` (zigzag + level scripts used for the 08.11.2026 manual signals, signal page v1 HTML),
`signals/manual_2026-11-08.json` (tonight's 3 manual signals), `data/` (cached candles, rows `[t,o,h,l,c,v]`, USD pairs:
`BTC_30m.json`, `BTC_4h.json`, …).

## File ownership (only touch your own files; ask via your final report if you need a change elsewhere)
| Agent | Files |
|---|---|
| A exchange | `ewbot/exchange.py`, `ewbot/paper.py`, `tests/test_exchange.py`, `tests/test_paper.py` |
| B strategy | `ewbot/strategy.py`, `ewbot/zigzag.py`, `ewbot/backtest.py`, `ewbot/history.py`, `tests/test_strategy.py`, `BACKTEST.md` |
| C engine | `ewbot/engine.py`, `ewbot/risk.py`, `ewbot/journal.py`, `ewbot/config.py`, `ewbot/report.py`, `ewbot/__main__.py`, `config.example.yaml`, `README.md`, `VPS_SETUP.md`, `deploy/` , `tests/test_engine.py`, `tests/test_risk.py` |

## Interfaces

### A — `ewbot/exchange.py`
```python
class ExchangeError(Exception): ...
class CryptoComClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 base_url: str = "https://api.crypto.com/exchange/v1", timeout: float = 15): ...
    # public (no key)
    def get_candles(self, instrument: str, timeframe: str, count: int = 300, end_ts: int | None = None) -> list[Candle]  # sorted ascending, timeframe "30m"|"4h"|"1D"|"5m"
    def get_candles_paged(self, instrument: str, timeframe: str, total: int) -> list[Candle]   # pages backwards with end_ts, dedup
    def get_ticker(self, instrument: str) -> dict   # {"bid": float, "ask": float, "last": float, "ts": int}
    def get_instrument(self, instrument: str) -> InstrumentInfo
    # private (key required, raise ExchangeError if missing)
    def get_balances(self) -> dict[str, float]      # currency -> available amount
    def place_limit(self, instrument, side, qty, price, client_oid) -> str          # returns order_id; post-only NOT required
    def place_market(self, instrument, side, qty, client_oid) -> str
    def cancel(self, instrument, order_id) -> None
    def get_order(self, order_id) -> Order
    def open_orders(self, instrument=None) -> list[Order]
    def round_price(self, instrument, price) -> float ; def round_qty(self, instrument, qty) -> float  # floor qty to qty_tick
```
Exits (stop / take-profit) are managed **by the engine** with LIMIT and MARKET orders (synthetic stop), because the
exact trigger-order API is not verified. If you can VERIFY from official docs that `private/create-order` (or the
advanced order endpoints) supports STOP_LOSS / TAKE_PROFIT for spot, add `place_stop_market(...)` and document the exact
fields + source URL in your report; the engine will use it only as an extra exchange-side safety net.
Signing must follow the official Crypto.com Exchange v1 docs (HMAC-SHA256 over method+id+api_key+paramString+nonce,
paramString = keys sorted, nested lists/dicts flattened). Verify against the docs / official example code; write a unit
test with a fixed vector. Respect rate limits (sleep/backoff on 429 / code 10006 etc.). Never log the secret.

### A — `ewbot/paper.py`
`class PaperBroker` with the SAME private methods as the client (`get_balances, place_limit, place_market, cancel,
get_order, open_orders, round_price, round_qty`) plus `on_candle(instrument, candle: Candle)` which fills orders against
candle high/low (limit buy fills if `l <= price`; limit sell if `h >= price`; market fills at next candle open + slippage).
Fees configurable (`maker_fee`, `taker_fee`, defaults 0.0025 / 0.005 — mark as assumption). State load/save to JSON
(`to_dict()/from_dict()`), starting balance in quote currency (USD). Deterministic.

### B — `ewbot/strategy.py`
```python
@dataclass class StrategyParams: ...  # all thresholds, with defaults; documented
def find_signals(coin: str, instrument: str, c30: list[Candle], c4h: list[Candle], p: StrategyParams | None = None,
                 now_ts: int | None = None) -> list[Signal]   # 0 or 1 active signal per coin (the freshest valid one)
def describe_count(coin, c30, c4h, p=None) -> dict   # {"degree_rally": {...}, "zone": [lo, hi], "pivots": [...], "text_de": "..."}
```
Must only use candles CLOSED at `now_ts` (no look-ahead). Same function is used by backtest, scan, paper and live.

### B — `ewbot/backtest.py` + `ewbot/history.py`
`history.py`: download & cache long 30m + 4h history from the public API (paging) into `data/`.
`python -m ewbot.backtest --coins BTC ETH SOL` → walk-forward over history, simulate entries/exits exactly like the engine
(limit entry, synthetic stop on 30m low, T1 50 % + stop to break-even, T2 rest, expiry), fees included, and write
`BACKTEST.md` with honest stats per coin + total: trades, win rate, avg R, profit factor, max drawdown (in R and %),
in-sample vs out-of-sample. If the edge is weak or negative, SAY SO clearly.

### C — engine / CLI
`python -m ewbot <cmd>`:
- `scan [--json out/signals.json] [--html out/index.html]` : public data only; runs strategy for the 3 coins, writes signals + renders the signal page.
- `paper-step --state state/paper.json` : one deterministic step for the cloud routine — load state (or create with
  configured capital), fetch candles since last step, feed PaperBroker + engine logic for every closed 30m candle since
  last step, add new signals, save state, print a short JSON summary of changes (`{"new_signals":[], "fills":[], "exits":[], "equity":...}`).
- `run --mode paper|live` : long-running loop for the VPS (every 30m candle close + 1-min price checks for stops).
- `status`, `kill` (creates `state/KILL` → engine flattens nothing automatically but cancels open entries and stops opening new trades; `kill --flatten` also market-sells bot positions).
Risk (`risk.py`): risk per trade % of equity (default 0.75), max total exposure (default 90 % of equity), max 1 position per
coin, daily loss cap (default 2 % → no new entries until next UTC day), max capital the bot may use (`max_capital_usd`), min
notional check, quantities rounded down to qty_tick. Position size = risk$ / (entry − stop).
Journal (`journal.py`): append-only CSV for German tax (§ 23 EStG): date, coin, side, qty, price, fee, quote, order_id, trade_id, note.
Report (`report.py`): render the German signal page (mobile, light/dark, inline SVG candles, levels, calculator, paper-trading
status table: open positions, closed trades, equity) as ONE self-contained HTML string; follow the style of
`reference/signal_page_v1.html`; no external fetch; embed the state JSON in `<script type="application/json" id="ew-state">`.

## Safety (non-negotiable)
- Default mode paper. `live` requires: config `live_enabled: true` AND env `CDC_API_KEY`/`CDC_API_SECRET` AND CLI flag
  `--confirm-live`. Print a clear German warning on start.
- Never withdraw, never transfer, never use margin/derivatives. Spot BUY/SELL on the 3 instruments only (whitelist).
- The bot only sells quantities it bought itself (tracked in state); never touches other holdings.
- On any unknown state / API error: do not open new trades; keep managing stops; log loudly.
- Secrets only from env or a `.env` file excluded by `.gitignore`. Never print them.
- Language: code + comments English; user-facing texts (README, VPS_SETUP, page, CLI messages) German, simple words.
