"""
Common candle / OHLCV schema and trade data models for FACTRADE.

All adapters normalise their raw data into :class:`Candle` objects so that
strategy logic is completely source-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Literal, Optional


@dataclass
class Candle:
    """A single OHLCV candle normalised from any data source."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    timeframe: str  # e.g. "1D", "4H", "1H", "15m", "5m", "1m"

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    def __repr__(self) -> str:  # pragma: no cover
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M")
        return (
            f"Candle({self.symbol} {self.timeframe} {ts} "
            f"O={self.open:.4f} H={self.high:.4f} L={self.low:.4f} C={self.close:.4f})"
        )


@dataclass
class LiquidityLevel:
    """A price level that holds liquidity (pending stops / breakout orders)."""

    price: float
    kind: Literal["swing_high", "swing_low", "pdh", "pdl", "equal_high", "equal_low"]
    formed_at: datetime
    symbol: str
    timeframe: str
    swept: bool = False
    swept_at: Optional[datetime] = None


@dataclass
class Signal:
    """A trading signal produced by the strategy engine."""

    symbol: str
    direction: Literal["long", "short"]
    entry_price: float
    stop_loss: float
    take_profit_1: float   # 80 % partial-close target
    take_profit_2: float   # 20 % runner target (HTF opposing liquidity)
    timestamp: datetime
    setup_type: Literal[
        "ote_choch",         # Liquidity sweep + CHoCH + OTE (universal)
        "smma_ribbon",       # SMMA 31/59 trend rider
        "bb_reversion",      # Bollinger Bands 199 / 1.9 mean reversion
        "vwap_breakout",     # VWAP deviation breakout
    ]
    timeframe: str
    risk_reward: float = 0.0
    atr_at_entry: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entry_price != 0 and self.stop_loss != 0:
            sl_distance = abs(self.entry_price - self.stop_loss)
            tp1_distance = abs(self.take_profit_1 - self.entry_price)
            self.risk_reward = tp1_distance / sl_distance if sl_distance > 0 else 0.0


@dataclass
class TradeResult:
    """Outcome of a completed paper-trade / backtest trade."""

    signal: Signal
    exit_price: float
    exit_time: datetime
    exit_reason: Literal["tp1", "tp2", "sl", "manual"]
    pnl_pips: float
    pnl_dollars: float          # based on 0.01 lot for reporting
    max_adverse_excursion: float = 0.0  # pips
    max_favourable_excursion: float = 0.0  # pips

    @property
    def is_win(self) -> bool:
        return self.pnl_pips > 0
