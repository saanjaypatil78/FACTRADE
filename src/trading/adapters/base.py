"""
Abstract base class for all FACTRADE data adapters.

Every adapter must:
  1. Accept a symbol and timeframe.
  2. Return a list of :class:`~src.trading.candle.Candle` objects normalised
     to the common schema.
  3. Be safe to call without any paid credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from src.trading.candle import Candle


class BaseAdapter(ABC):
    """Pluggable data-source adapter interface."""

    #: Human-readable name for this adapter (used in logs / reports).
    name: str = "base"

    #: Whether this adapter can deliver near-real-time candles.
    supports_live: bool = False

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        """Fetch candles and return them as a sorted (oldest-first) list."""

    def fetch_latest(self, symbol: str, timeframe: str, n: int = 500) -> List[Candle]:
        """
        Convenience method – return the *n* most-recent closed candles.

        Adapters that support streaming may override this for lower latency.
        """
        return self.fetch(symbol=symbol, timeframe=timeframe, limit=n)

    # ------------------------------------------------------------------ #
    # Normalisation helpers shared by all adapters
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_candle(candle: Candle) -> bool:
        """Basic sanity checks on a candle before it enters the pipeline."""
        if candle.high < candle.low:
            return False
        if candle.high < max(candle.open, candle.close):
            return False
        if candle.low > min(candle.open, candle.close):
            return False
        if any(v <= 0 for v in (candle.open, candle.high, candle.low, candle.close)):
            return False
        return True

    @classmethod
    def _filter_valid(cls, candles: List[Candle]) -> List[Candle]:
        return [c for c in candles if cls._validate_candle(c)]
