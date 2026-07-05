"""
Liquidity Detector – identifies and tracks price levels where retail-trader
stop-losses and breakout orders congregate (Arjo's Liquidity Framework).

Detected levels
---------------
* **Swing highs / lows** – a candle whose high (or low) is the local
  extreme over *N* candles on each side.
* **Previous Day High / Low (PDH / PDL)** – the prior daily candle's
  extreme, always a magnet for liquidity sweeps.
* **Equal highs / lows** – two or more swing extremes within a tolerance
  band (institutional target for double-top / double-bottom sweeps).
* **Sweep detection** – a candle that wicks through the level but closes
  back on the original side, signalling a liquidity grab.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np
import structlog

from src.trading.candle import Candle, LiquidityLevel

logger = structlog.get_logger(__name__)

# Default look-left / look-right for swing detection
_DEFAULT_SWING_BARS = 3

# Tolerance for "equal high / equal low" detection (fraction of price)
_EQUAL_LEVEL_TOLERANCE = 0.0005   # 0.05 %


class LiquidityDetector:
    """
    Detect liquidity levels on a list of candles.

    Parameters
    ----------
    swing_bars:
        Number of bars on each side required to confirm a swing high/low.
    equal_tol:
        Fraction of price within which two highs/lows are considered equal.
    """

    def __init__(
        self,
        swing_bars: int = _DEFAULT_SWING_BARS,
        equal_tol: float = _EQUAL_LEVEL_TOLERANCE,
    ) -> None:
        self.swing_bars = swing_bars
        self.equal_tol = equal_tol

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def detect(self, candles: List[Candle]) -> List[LiquidityLevel]:
        """
        Return all liquidity levels found in *candles* (oldest-first order).
        """
        if len(candles) < self.swing_bars * 2 + 1:
            return []

        symbol = candles[0].symbol
        timeframe = candles[0].timeframe

        levels: List[LiquidityLevel] = []
        levels.extend(self._swing_levels(candles, symbol, timeframe))
        levels.extend(self._pdh_pdl_levels(candles, symbol, timeframe))
        levels.extend(self._equal_levels(levels))

        logger.debug(
            "liquidity_detector.detected",
            symbol=symbol,
            timeframe=timeframe,
            count=len(levels),
        )
        return levels

    def detect_sweeps(
        self,
        candles: List[Candle],
        levels: List[LiquidityLevel],
    ) -> List[Tuple[Candle, LiquidityLevel]]:
        """
        Return (candle, level) pairs where the candle **swept** the level.

        A sweep means:
          * For a swing-high / PDH level: the candle's high exceeds the level
            price but the **close** is back below it (wick rejection).
          * For a swing-low / PDL level: the candle's low goes under the
            level price but the **close** is back above it.
        """
        sweeps: List[Tuple[Candle, LiquidityLevel]] = []
        for candle in candles:
            for level in levels:
                if level.swept:
                    continue
                swept = self._is_sweep(candle, level)
                if swept:
                    level.swept = True
                    level.swept_at = candle.timestamp
                    sweeps.append((candle, level))
        return sweeps

    def latest_swing_high(self, candles: List[Candle]) -> Optional[LiquidityLevel]:
        """Return the most-recent un-swept swing-high level."""
        levels = self.detect(candles)
        highs = [l for l in levels if l.kind == "swing_high" and not l.swept]
        return highs[-1] if highs else None

    def latest_swing_low(self, candles: List[Candle]) -> Optional[LiquidityLevel]:
        """Return the most-recent un-swept swing-low level."""
        levels = self.detect(candles)
        lows = [l for l in levels if l.kind == "swing_low" and not l.swept]
        return lows[-1] if lows else None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _swing_levels(
        self,
        candles: List[Candle],
        symbol: str,
        timeframe: str,
    ) -> List[LiquidityLevel]:
        n = self.swing_bars
        levels: List[LiquidityLevel] = []

        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])

        for i in range(n, len(candles) - n):
            # Swing high
            if highs[i] == highs[i - n : i + n + 1].max():
                levels.append(
                    LiquidityLevel(
                        price=highs[i],
                        kind="swing_high",
                        formed_at=candles[i].timestamp,
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                )
            # Swing low
            if lows[i] == lows[i - n : i + n + 1].min():
                levels.append(
                    LiquidityLevel(
                        price=lows[i],
                        kind="swing_low",
                        formed_at=candles[i].timestamp,
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                )
        return levels

    @staticmethod
    def _pdh_pdl_levels(
        candles: List[Candle],
        symbol: str,
        timeframe: str,
    ) -> List[LiquidityLevel]:
        """PDH / PDL are only meaningful when the input candles are daily bars."""
        if timeframe not in ("1D", "1W"):
            return []

        levels: List[LiquidityLevel] = []
        for i in range(1, len(candles)):
            prev = candles[i - 1]
            curr = candles[i]
            levels.append(
                LiquidityLevel(
                    price=prev.high,
                    kind="pdh",
                    formed_at=curr.timestamp,
                    symbol=symbol,
                    timeframe=timeframe,
                )
            )
            levels.append(
                LiquidityLevel(
                    price=prev.low,
                    kind="pdl",
                    formed_at=curr.timestamp,
                    symbol=symbol,
                    timeframe=timeframe,
                )
            )
        return levels

    def _equal_levels(
        self, levels: List[LiquidityLevel]
    ) -> List[LiquidityLevel]:
        """Flag equal highs and equal lows within the tolerance band."""
        eq_levels: List[LiquidityLevel] = []
        seen_highs: List[float] = []
        seen_lows: List[float] = []

        for level in levels:
            if level.kind in ("swing_high", "pdh"):
                for prev in seen_highs:
                    if abs(level.price - prev) / prev <= self.equal_tol:
                        eq_levels.append(
                            LiquidityLevel(
                                price=level.price,
                                kind="equal_high",
                                formed_at=level.formed_at,
                                symbol=level.symbol,
                                timeframe=level.timeframe,
                            )
                        )
                        break
                seen_highs.append(level.price)
            elif level.kind in ("swing_low", "pdl"):
                for prev in seen_lows:
                    if abs(level.price - prev) / prev <= self.equal_tol:
                        eq_levels.append(
                            LiquidityLevel(
                                price=level.price,
                                kind="equal_low",
                                formed_at=level.formed_at,
                                symbol=level.symbol,
                                timeframe=level.timeframe,
                            )
                        )
                        break
                seen_lows.append(level.price)

        return eq_levels

    @staticmethod
    def _is_sweep(candle: Candle, level: LiquidityLevel) -> bool:
        """
        Determine whether *candle* swept *level* (wick through, close back).
        """
        if level.kind in ("swing_high", "pdh", "equal_high"):
            return candle.high > level.price and candle.close < level.price
        if level.kind in ("swing_low", "pdl", "equal_low"):
            return candle.low < level.price and candle.close > level.price
        return False
