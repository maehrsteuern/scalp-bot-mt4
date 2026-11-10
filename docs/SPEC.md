# ewbot – Interface Spec (binding for all modules)

Package `ewbot/`. Python 3.11+. Dependencies: ccxt, numpy, pandas (optional), pyyaml, requests, pytest.
Shared types live in `ewbot/models.py` (Candle, Swing, WaveCount, FibLevels, HtfContext, Signal,
Position, Fill, TradeRecord, enums Side/SwingKind/Bias/SetupType/PatternType). Config dataclasses in
`ewbot/config.py` (`load_config(path) -> BotCfg`). Never redefine these; import them.

All prices are floats, timestamps are epoch **milliseconds** (ccxt convention). Candle lists are ascending
by ts and contain only **closed** candles unless stated otherwise.

## Module A – analysis core (`swings.py`, `fib.py`, `elliott.py`, `strategy.py`)

```python
# swings.py
def atr(candles: list[Candle], period: int) -> list[float]          # same length, NaN-free (first values seeded with TR)
def ema(values: list[float], period: int) -> list[float]
def detect_swings(candles: list[Candle], cfg: SwingCfg) -> list[Swing]
    # ATR-based ZigZag: a reversal is confirmed once price moves atr_mult*ATR against the current leg
    # and at least min_bars elapsed. Alternates HIGH/LOW strictly. The last swing is the last *confirmed*
    # pivot; the in-progress leg is NOT a swing.
def last_leg(candles, swings) -> tuple[Swing, float]                  # (last confirmed swing, current close)

# fib.py
RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTEND  = (1.0, 1.272, 1.618, 2.0, 2.618)
def retracement(start: float, end: float) -> FibLevels     # levels between end and start, keyed by ratio
def extension(start: float, end: float, from_price: float, ratios=EXTEND) -> FibLevels
    # projection of |end-start| * ratio from from_price in direction of (end-start)
def ratio_of(move: float, base: float) -> float            # abs(move)/abs(base), 0 if base==0
def in_band(ratio: float, lo: float, hi: float) -> bool

# elliott.py
def find_counts(swings: list[Swing], current_price: float, cfg: ElliottCfg) -> list[WaveCount]
    # Enumerate windows over the last cfg.max_swings swings and return all valid IMPULSE (6 points) and
    # ZIGZAG (4 points) candidates, complete and in-progress (last point = current_price), sorted by score desc.
    # HARD rules (impulse, upward; mirror for downward):
    #   p0<p1, p2>p0 (wave 2 never retraces >100% of wave 1), p3>p1, p4>p1 (no overlap), p5>p3,
    #   wave 3 is not the shortest of waves 1,3,5 (for in-progress counts, compare only completed waves)
    # HARD rules (zigzag, A down / B up / C down for a correction of an up-move):
    #   B retraces < 100% of A ; C exceeds end of A
    # SCORE (0..1): mean of per-ratio closeness to ideal with cfg bands:
    #   w2/w1 ideal 0.618 band [w2_min,w2_max]; w3/w1 ideal 1.618 (>= w3_min_ext);
    #   w4/w3 ideal 0.382 band [w4_min,w4_max]; w5/w1 ideal 0.618..1.0; B/A ideal 0.618; C/A ideal 1.0..1.618
    #   plus alternation bonus (w2 sharp vs w4 shallow or vice versa). Fill WaveCount.ratios and violations.
def best_count(counts, pattern: PatternType | None = None) -> WaveCount | None
def bias_from_counts(counts: list[WaveCount], current_price: float) -> Bias
    # BULL if the best in-progress/complete structure implies upside next (e.g. impulse up in wave 3 or 5,
    # or completed zigzag down ending), BEAR mirror, else NEUTRAL.

# strategy.py
class ElliottStrategy:
    def __init__(self, cfg: BotCfg): ...
    def analyse_htf(self, timeframe: str, candles: list[Candle]) -> HtfContext
        # swings -> counts -> bias (combine bias_from_counts with EMA fast/slow; EMA decides only when
        # counts are NEUTRAL). fib = retracement grid of the last completed HTF leg (last two swings).
    def evaluate(self, symbol: str, candles: list[Candle], htf: list[HtfContext]) -> Signal | None
        # candles = exec timeframe (closed candles). Returns at most one signal for the just-closed candle.
        # Setups (long shown; short is the mirror and only produced when the caller allows it – the
        # strategy does not know about allow_short, the bot filters):
        #  WAVE3: impulse-up count in progress with waves 0,1,2 confirmed (p2 is the last confirmed swing LOW),
        #         w2/w1 in [w2_min,w2_max], last close > p2 and (confirm_with_close) close > previous close,
        #         bars since p2 <= max_signal_age_bars. entry=close, stop=p0 - stop_buffer_atr*ATR,
        #         tp1 = p2 + 1.0*(p1-p0), tp2 = p2 + 1.618*(p1-p0).
        #  WAVE5: waves 0..4 confirmed (p4 last swing LOW), w4/w3 in band, no overlap, close > p4.
        #         stop = p4 - buffer, tp1 = p4 + 0.618*(p1-p0), tp2 = p4 + 1.0*(p1-p0)
        #         (if tp1 does not exceed p3 use p3 + 0.1*(p3-p2) as tp1).
        #  WAVEC: completed impulse DOWN followed by A up and B down (zigzag up in progress, p2 last swing LOW),
        #         B/A in [wb_min,wb_max], close > p2. stop = p2 - buffer (if B retraced <100% of A),
        #         tp1 = p2 + 1.0*(p1-p0), tp2 = p2 + 1.618*(p1-p0).
        # HTF gate (require_htf_agreement): no HtfContext.bias may be opposite to the trade side; at least one
        # must agree (NEUTRAL counts as neither). HTF fib confluence: if the retracement zone end (p2/p4) is
        # within htf_fib_confluence_atr * HTF.atr of any HTF fib level, add +0.15 to score and a reason.
        # Final score = 0.6*count.score + 0.25*htf_agreement(0/0.5/1) + confluence bonus, clipped 0..1.
        # Reject if score < min_signal_score or rr1 < min_rr1. Fill Signal.reasons with short strings.
```
Tests (`tests/test_swings.py`, `tests/test_elliott.py`, `tests/test_strategy.py`) must build synthetic
candle series (e.g. a clean 5-wave impulse with noise) and assert: swings alternate, impulse is found with
score > 0.7, hard-rule violators are rejected, WAVE3 signal is produced with stop below p0 and rr1 >= 1.

## Module B – infrastructure (`data.py`, `broker.py`, `risk.py`, `state.py`, `notify.py`)

```python
# data.py
class MarketData:
    def __init__(self, cfg: ExchangeCfg): ...        # builds ccxt exchange (public, no keys needed)
    def fetch(self, symbol: str, timeframe: str, limit: int | None = None) -> list[Candle]
        # closed candles only (drop the last candle if its close time > now). Retries 3x with backoff on
        # NetworkError. Caches by (symbol, timeframe); only refetches when a new candle could have closed.
    def fetch_history(self, symbol, timeframe, since_ms: int, until_ms: int | None = None) -> list[Candle]
        # paginates with `since` for backtests.
    @staticmethod
    def timeframe_ms(timeframe: str) -> int
    @staticmethod
    def from_csv(path) -> list[Candle]   # columns ts,open,high,low,close,volume
    @staticmethod
    def to_csv(candles, path) -> None

# broker.py
class Broker(ABC):
    equity() -> float ; cash() -> float
    positions() -> list[Position]
    open(signal: Signal, qty: float, ts: int) -> Position | None       # market entry
    close(position: Position, qty: float, price_hint: float, ts: int, reason: str) -> Fill | None
    update_stop(position, new_stop: float) -> None
    on_candle(symbol: str, candle: Candle) -> list[TradeRecord]        # paper: simulate SL/TP hits inside candle
    trades() -> list[TradeRecord]
    last_price(symbol) -> float
class PaperBroker(Broker):
    # start equity from cfg.exchange.paper_start_equity; fee_pct & slippage_pct from RiskCfg.
    # Fill order inside a candle: if both stop and tp are touched in one candle assume STOP first (pessimistic).
    # Partial TP1 closes risk.tp1_fraction, then stop -> entry if move_to_be_after_tp1.
    # TradeRecord per closed (fully) position; realized pnl accumulates in cash.
class CcxtBroker(Broker):
    # ccxt cryptocom with keys from env (cfg.exchange.api_key_env/...). Spot: long only -> market buy/sell.
    # Perp symbols ("BTC/USD:USD"): createOrder with reduceOnly for exits. Equity = total quote balance +
    # unrealized. Stops are managed locally by the bot (on_candle checks price vs stop/tp and sends market
    # exits) AND, best effort, a stop-loss order is placed on the exchange if the market supports it
    # (try/except, log and continue). Round qty/price to market precision; refuse orders below min cost.
    # Keep the exchange object injectable for tests (constructor arg `exchange=None`).

# risk.py
class RiskManager:
    def __init__(self, cfg: RiskCfg): ...
    def position_size(self, equity: float, signal: Signal, market: MarketCfg, min_notional: float) -> float
        # qty = equity * risk_pct/100 * market.weight / risk_per_unit; fee-adjusted; 0 if notional < min_notional.
    def can_open(self, now_ts: int, equity: float, open_positions: list[Position], trades: list[TradeRecord],
                 symbol: str) -> tuple[bool, str]
        # max_positions, per-symbol cap, daily loss cap (UTC day, based on day-start equity which the caller
        # supplies via set_day_start(equity, ts)), consecutive-loss pause (pause_minutes_after_losses).
    def set_day_start(self, equity: float, ts: int) -> None
    def manage(self, position: Position, candle: Candle, atr: float) -> list[tuple[str, float]]
        # returns actions: ("tp1", qty) / ("close", qty) / ("stop", new_stop) for BE move, trailing, time stop
        # (max_hold_bars uses bars elapsed = (candle.ts - opened_ts)/tf_ms; caller passes tf via position.timeframe).

# state.py
def save_state(path, data: dict) -> None    # atomic write (tmp + rename), creates parent dirs
def load_state(path) -> dict                # {} if missing
def position_to_dict / position_from_dict, trade_to_dict / trade_from_dict (Enums as values)

# notify.py
class Telegram:
    def __init__(self, cfg: TelegramCfg): ...  # disabled silently if not enabled or env missing
    def send(self, text: str) -> bool          # HTML parse mode, never raises
    def poll_commands(self) -> list[tuple[str, str]]   # [(command, args)] since last update_id; non-blocking
    def format_signal(signal) / format_fill(fill, position) / format_summary(equity, day_pnl, trades) -> str
```
Tests: paper broker fills, partial TP + BE, pessimistic stop-first, risk sizing with 20 USD equity / 5 %,
daily loss cap halts, state round trip. No network in tests (inject a fake exchange object for CcxtBroker).

## Module C – orchestration (`bot.py`, `backtest.py`, `__main__.py`, `config/`, `deploy/`, README)

```python
# bot.py
class Bot:
    def __init__(self, cfg: BotCfg, data: MarketData, broker: Broker, strategy: ElliottStrategy,
                 risk: RiskManager, notifier: Telegram, logger): ...
    def step(self, now_ms: int) -> None
        # for each market: fetch exec candles; if newest closed candle ts > last_seen[symbol]:
        #   broker.on_candle -> records -> notify; risk.manage for open positions -> execute actions;
        #   htf = [strategy.analyse_htf(tf, data.fetch(symbol, tf)) for tf in htf_timeframes]
        #   signal = strategy.evaluate(...); filter allow_short; risk.can_open; qty = risk.position_size;
        #   broker.open; notify; persist state.
        # Handle telegram commands: /status /pause /resume /close_all /equity /positions.
        # Day rollover -> risk.set_day_start, daily summary at telegram.daily_summary_utc.
    def run_forever(self) -> None       # sleep cfg.poll_seconds between steps; catches and logs exceptions
    def restore(self) / persist(self)   # positions, last_seen, day start, paused flag via state.py

# backtest.py
def run_backtest(cfg: BotCfg, candles_by_tf: dict[str, dict[str, list[Candle]]], start_equity: float) -> BacktestResult
    # candles_by_tf[symbol][timeframe]. Walk the exec timeframe bar by bar; HTF context uses only HTF candles
    # closed at or before the exec candle close (no look-ahead!). Uses PaperBroker + RiskManager + Bot.step-like
    # logic (factor shared logic into bot.py so backtest and live use the SAME decision path).
    # BacktestResult: trades, equity_curve [(ts, equity)], metrics: net_pnl, return_pct, win_rate,
    # profit_factor, max_drawdown_pct, avg_rr, trades_per_setup. to_markdown(), save_csv(dir).
# __main__.py  (python -m ewbot ...)
#   run --config config/ewbot-15m.yaml
#   backtest --config ... --days 90 [--csv-dir data/]   (fetches via MarketData.fetch_history or reads CSVs)
#   fetch --config ... --days 90 --out data/              (download OHLCV to CSV for offline backtests)
#   status --config ...                                   (prints state file summary)
#   check --config ...                                    (validates config, env keys, exchange connectivity)
```
Config files: `config/ewbot-15m.yaml`, `config/ewbot-30m.yaml` (same markets, different exec timeframe,
state/log names, Telegram off by default, mode paper). `config/.env.example` with the 4 env var names.
Deploy (`deploy/`): `install_oracle.sh` (Ubuntu 22.04/24.04 ARM or x86: apt python3-venv git, clone/pull, venv,
pip install -r requirements.txt, copy systemd unit, enable), `ewbot@.service` (systemd template, instance name =
config basename, EnvironmentFile=/opt/ewbot/.env, Restart=always, WorkingDirectory=/opt/ewbot), `update.sh`.
Root files: `requirements.txt`, `pyproject.toml` (package `ewbot`, console script `ewbot = ewbot.__main__:main`),
`.gitignore` (state/, logs/, data/, .env, *.ex4, __pycache__), `README.md` in GERMAN (Kernaussage zuerst,
kein Jargon; Abschnitte: Was der Bot macht, Elliott-Wave-Logik in einfachen Worten, Risiko, Installation Oracle
VPS Schritt für Schritt, Paper -> Live umschalten, Telegram, Backtest, Befehle, Risikohinweise).
