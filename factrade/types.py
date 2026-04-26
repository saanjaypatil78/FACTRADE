from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Regime(str, Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    NO_TRADE = "NO_TRADE"


class TrapLabel(str, Enum):
    CLEAN = "CLEAN"
    WAIT = "WAIT"
    TRAP = "TRAP"


Side = Literal["BUY", "SELL"]
OptionType = Literal["CE", "PE"]


@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class RegimeSnapshot:
    regime: Regime
    confidence: float
    reason: str


@dataclass(frozen=True)
class TrapResult:
    score: int
    label: TrapLabel
    reason: str


@dataclass(frozen=True)
class OptionQuote:
    strike: float
    option_type: OptionType
    delta: float
    bid: float
    ask: float
    ltp: float
    oi: int
    volume: int


@dataclass(frozen=True)
class StrikeDecision:
    strike: float
    option_type: OptionType
    score: float
    reason: str
