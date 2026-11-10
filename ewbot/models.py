"""Shared data models. Every module imports from here; do not duplicate these types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> "Side":
        return Side.SHORT if self is Side.LONG else Side.LONG


class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


class Bias(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


class SetupType(str, Enum):
    WAVE3 = "wave3"   # enter after wave-2 retracement, ride wave 3
    WAVE5 = "wave5"   # enter after wave-4 retracement, ride wave 5
    WAVEC = "waveC"   # enter after wave-B retracement, ride wave C (corrective)


class PatternType(str, Enum):
    IMPULSE = "impulse"      # 5-wave motive structure (0-1-2-3-4-5)
    ZIGZAG = "zigzag"        # 3-wave A-B-C correction


@dataclass(frozen=True)
class Candle:
    ts: int          # epoch milliseconds of candle open (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Swing:
    index: int       # bar index into the candle list the swing was computed from
    ts: int
    price: float
    kind: SwingKind


@dataclass
class WaveCount:
    """One candidate Elliott labelling over consecutive swings.

    points: pivot prices p0..pN (N=5 impulse, N=3 zigzag), swings: the Swing objects.
    direction: LONG for an upward impulse / downward correction target etc.
      - IMPULSE with direction LONG: p0 < p1, p2 < p1, p3 > p1, p4 < p3, p5 > p3
      - ZIGZAG  with direction LONG: A up, B down, C up  (p0 < p1 > p2 < p3)
    complete: True if the final wave has a confirmed terminal swing, False if the final
      wave is still "in progress" (the last point is the current price, not a swing).
    score: 0..1 fib-conformity score (higher = cleaner textbook structure).
    violations: human readable list of guideline deviations (hard rules are never violated).
    """
    pattern: PatternType
    direction: Side
    swings: list[Swing]
    points: list[float]
    complete: bool
    score: float
    ratios: dict[str, float] = field(default_factory=dict)   # e.g. {"w2/w1": 0.618, "w3/w1": 1.62}
    violations: list[str] = field(default_factory=list)

    @property
    def degree_label(self) -> str:
        return f"{self.pattern.value}-{self.direction.value}"


@dataclass
class FibLevels:
    """Retracement or extension levels for one leg."""
    start: float
    end: float
    levels: dict[float, float]   # ratio -> price, e.g. {0.382: 101.2, 0.5: 100.0}

    def nearest(self, price: float) -> tuple[float, float]:
        """Return (ratio, level_price) closest to price."""
        ratio = min(self.levels, key=lambda r: abs(self.levels[r] - price))
        return ratio, self.levels[ratio]


@dataclass
class HtfContext:
    """Higher-timeframe assist (1h / 4h) condensed into what the LTF strategy needs."""
    timeframe: str
    bias: Bias
    count: Optional[WaveCount]
    fib: Optional[FibLevels]          # retracement grid of the last HTF leg
    ema_fast: float
    ema_slow: float
    atr: float
    notes: list[str] = field(default_factory=list)


@dataclass
class Signal:
    symbol: str
    timeframe: str
    side: Side
    setup: SetupType
    entry: float
    stop: float
    tp1: float
    tp2: float
    ts: int                       # candle ts that produced the signal
    score: float                  # 0..1 composite quality
    count: WaveCount
    htf: list[HtfContext]
    reasons: list[str] = field(default_factory=list)

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr1(self) -> float:
        return abs(self.tp1 - self.entry) / self.risk_per_unit if self.risk_per_unit else 0.0

    @property
    def rr2(self) -> float:
        return abs(self.tp2 - self.entry) / self.risk_per_unit if self.risk_per_unit else 0.0


@dataclass
class Position:
    id: str
    symbol: str
    side: Side
    qty: float                 # base units, always positive
    entry: float
    stop: float
    tp1: float
    tp2: float
    opened_ts: int
    setup: SetupType
    timeframe: str
    tp1_done: bool = False
    be_moved: bool = False
    qty_open: float = 0.0      # remaining qty after partial TP (== qty at open)
    realized_pnl: float = 0.0
    fees: float = 0.0
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.qty_open == 0.0:
            self.qty_open = self.qty


@dataclass
class Fill:
    ts: int
    symbol: str
    side: Side          # side of the trade being executed (buy=LONG, sell=SHORT)
    qty: float
    price: float
    fee: float
    reason: str         # "entry" | "tp1" | "tp2" | "stop" | "manual" | "time"


@dataclass
class TradeRecord:
    position: Position
    closed_ts: int
    exit_price: float
    pnl: float          # net of fees, quote currency
    pnl_pct: float      # pnl / equity at open
    reason: str
