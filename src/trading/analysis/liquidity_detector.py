"""HTF liquidity level detector for FACTRADE.

Detects institutional liquidity pools on Higher Time Frames (HTF):
- Daily / 4H / 3H / 1H

Liquidity pools detected
------------------------
1. Swing Highs / Swing Lows (equal highs/lows are clustered)
2. Previous Day High / Low  (PDH / PDL)
3. Previous Week High / Low (PWH / PWL)
4. Equal Highs / Equal Lows (within a configurable tolerance)

Key output
----------
``LiquidityLevel`` objects tagged as:
- ``type``: "swing_high" | "swing_low" | "pdh" | "pdl" | "pwh" | "pwl" | "equal_high" | "equal_low"
- ``price``: exact price level
- ``swept``: True once price has traded through and reversed (wick sweep)
- ``broken``: True once price closed beyond (continuation breakout)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

LevelType = Literal[
    "swing_high", "swing_low",
    "pdh", "pdl",
    "pwh", "pwl",
    "equal_high", "equal_low",
]


@dataclass
class LiquidityLevel:
    """A single HTF liquidity level."""

    price: float
    type: LevelType
    timeframe: str
    formed_at: pd.Timestamp
    swept: bool = False
    broken: bool = False
    sweep_at: Optional[pd.Timestamp] = None
    break_at: Optional[pd.Timestamp] = None
    cluster_count: int = 1  # for equal highs/lows

    def __repr__(self) -> str:
        status = "swept" if self.swept else ("broken" if self.broken else "active")
        return (
            f"LiquidityLevel({self.type}@{self.price:.2f}, tf={self.timeframe}, "
            f"formed={self.formed_at.date()}, status={status})"
        )


class LiquidityDetector:
    """Detect HTF liquidity pools from OHLCV DataFrames.

    Parameters
    ----------
    swing_lookback:
        Number of bars on each side to confirm a swing high/low (default 5).
    equal_tolerance_pct:
        Percentage tolerance for clustering equal highs/lows (default 0.1%).
    min_swing_strength:
        Minimum price movement (as % of ATR) to qualify as a swing (default 0.0).
    """

    def __init__(
        self,
        swing_lookback: int = 5,
        equal_tolerance_pct: float = 0.10,
        min_swing_strength: float = 0.0,
    ) -> None:
        self.swing_lookback = swing_lookback
        self.equal_tolerance_pct = equal_tolerance_pct
        self.min_swing_strength = min_swing_strength

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, df: pd.DataFrame, timeframe: str = "1H") -> list[LiquidityLevel]:
        """Detect all liquidity levels in *df*.

        Parameters
        ----------
        df:
            OHLCV DataFrame with DatetimeIndex (UTC).
        timeframe:
            Label for the timeframe (used in level metadata).

        Returns
        -------
        list[LiquidityLevel]
            All detected levels, sorted by price descending.
        """
        if df.empty:
            return []

        levels: list[LiquidityLevel] = []
        levels.extend(self._detect_swings(df, timeframe))
        levels.extend(self._detect_previous_day(df, timeframe))
        levels.extend(self._detect_previous_week(df, timeframe))
        levels.extend(self._detect_equal_highs_lows(df, timeframe))

        # Deduplicate levels that are within equal_tolerance_pct of each other
        levels = self._deduplicate(levels)

        # Sort by price descending (highs first)
        levels.sort(key=lambda x: x.price, reverse=True)

        logger.info(
            "liquidity_detector.detected",
            timeframe=timeframe,
            count=len(levels),
            rows=len(df),
        )
        return levels

    def update_sweep_status(
        self,
        levels: list[LiquidityLevel],
        latest_bar: pd.Series,
    ) -> list[LiquidityLevel]:
        """Update swept/broken flags given the latest OHLCV bar.

        Sweep:  price wick crossed the level but candle did NOT close beyond.
        Break:  price candle CLOSED beyond the level (continuation/run).

        Parameters
        ----------
        levels:
            Current list of LiquidityLevel objects (modified in place).
        latest_bar:
            A pd.Series with open, high, low, close and a name that is the
            bar's timestamp.

        Returns
        -------
        list[LiquidityLevel]
            Updated levels (same list, modified in place).
        """
        ts = latest_bar.name
        high = latest_bar["high"]
        low = latest_bar["low"]
        close = latest_bar["close"]

        for lvl in levels:
            if lvl.swept or lvl.broken:
                continue

            if lvl.type in ("swing_high", "pdh", "pwh", "equal_high"):
                # Sweep: wick above level, close did not
                if high > lvl.price and close <= lvl.price:
                    lvl.swept = True
                    lvl.sweep_at = ts
                # Break: closed above
                elif close > lvl.price:
                    lvl.broken = True
                    lvl.break_at = ts

            elif lvl.type in ("swing_low", "pdl", "pwl", "equal_low"):
                # Sweep: wick below level, close did not
                if low < lvl.price and close >= lvl.price:
                    lvl.swept = True
                    lvl.sweep_at = ts
                # Break: closed below
                elif close < lvl.price:
                    lvl.broken = True
                    lvl.break_at = ts

        return levels

    def get_active_levels(self, levels: list[LiquidityLevel]) -> list[LiquidityLevel]:
        """Return only levels that have not yet been swept or broken."""
        return [lvl for lvl in levels if not lvl.swept and not lvl.broken]

    def get_swept_levels(self, levels: list[LiquidityLevel]) -> list[LiquidityLevel]:
        """Return levels that have been swept (reversal candidates)."""
        return [lvl for lvl in levels if lvl.swept]

    # ------------------------------------------------------------------
    # Internal detectors
    # ------------------------------------------------------------------

    def _detect_swings(
        self, df: pd.DataFrame, timeframe: str
    ) -> list[LiquidityLevel]:
        """Pivot-based swing high/low detection."""
        lb = self.swing_lookback
        levels: list[LiquidityLevel] = []

        for i in range(lb, len(df) - lb):
            window_high = df["high"].iloc[i - lb: i + lb + 1]
            window_low = df["low"].iloc[i - lb: i + lb + 1]
            bar_ts = df.index[i]

            if df["high"].iloc[i] == window_high.max():
                levels.append(
                    LiquidityLevel(
                        price=float(df["high"].iloc[i]),
                        type="swing_high",
                        timeframe=timeframe,
                        formed_at=bar_ts,
                    )
                )
            if df["low"].iloc[i] == window_low.min():
                levels.append(
                    LiquidityLevel(
                        price=float(df["low"].iloc[i]),
                        type="swing_low",
                        timeframe=timeframe,
                        formed_at=bar_ts,
                    )
                )

        return levels

    def _detect_previous_day(
        self, df: pd.DataFrame, timeframe: str
    ) -> list[LiquidityLevel]:
        """Previous day high / low."""
        if df.empty:
            return []
        daily = df.resample("1D").agg({"high": "max", "low": "min"}).dropna()
        if len(daily) < 2:
            return []

        prev = daily.iloc[-2]
        return [
            LiquidityLevel(
                price=float(prev["high"]),
                type="pdh",
                timeframe=timeframe,
                formed_at=daily.index[-2],
            ),
            LiquidityLevel(
                price=float(prev["low"]),
                type="pdl",
                timeframe=timeframe,
                formed_at=daily.index[-2],
            ),
        ]

    def _detect_previous_week(
        self, df: pd.DataFrame, timeframe: str
    ) -> list[LiquidityLevel]:
        """Previous week high / low."""
        if df.empty:
            return []
        weekly = df.resample("1W").agg({"high": "max", "low": "min"}).dropna()
        if len(weekly) < 2:
            return []

        prev = weekly.iloc[-2]
        return [
            LiquidityLevel(
                price=float(prev["high"]),
                type="pwh",
                timeframe=timeframe,
                formed_at=weekly.index[-2],
            ),
            LiquidityLevel(
                price=float(prev["low"]),
                type="pwl",
                timeframe=timeframe,
                formed_at=weekly.index[-2],
            ),
        ]

    def _detect_equal_highs_lows(
        self, df: pd.DataFrame, timeframe: str
    ) -> list[LiquidityLevel]:
        """Cluster swing highs/lows within tolerance as equal H/L."""
        if df.empty:
            return []

        tol_pct = self.equal_tolerance_pct / 100.0
        avg_price = (df["high"].mean() + df["low"].mean()) / 2
        tol = avg_price * tol_pct

        # Group highs
        highs = sorted(df["high"].values)
        eq_levels: list[LiquidityLevel] = []
        i = 0
        while i < len(highs):
            cluster = [highs[i]]
            while i + 1 < len(highs) and (highs[i + 1] - highs[i]) <= tol:
                i += 1
                cluster.append(highs[i])
            if len(cluster) >= 3:
                cluster_price = sum(cluster) / len(cluster)
                # Find formed_at from df
                mask = (df["high"] >= cluster_price - tol) & (df["high"] <= cluster_price + tol)
                formed = df.index[mask].min() if mask.any() else df.index[-1]
                eq_levels.append(
                    LiquidityLevel(
                        price=float(cluster_price),
                        type="equal_high",
                        timeframe=timeframe,
                        formed_at=formed,
                        cluster_count=len(cluster),
                    )
                )
            i += 1

        # Group lows
        lows = sorted(df["low"].values)
        i = 0
        while i < len(lows):
            cluster = [lows[i]]
            while i + 1 < len(lows) and (lows[i + 1] - lows[i]) <= tol:
                i += 1
                cluster.append(lows[i])
            if len(cluster) >= 3:
                cluster_price = sum(cluster) / len(cluster)
                mask = (df["low"] >= cluster_price - tol) & (df["low"] <= cluster_price + tol)
                formed = df.index[mask].min() if mask.any() else df.index[-1]
                eq_levels.append(
                    LiquidityLevel(
                        price=float(cluster_price),
                        type="equal_low",
                        timeframe=timeframe,
                        formed_at=formed,
                        cluster_count=len(cluster),
                    )
                )
            i += 1

        return eq_levels

    def _deduplicate(self, levels: list[LiquidityLevel]) -> list[LiquidityLevel]:
        """Remove near-duplicate levels (within equal_tolerance_pct of each other)."""
        if not levels:
            return levels

        avg_price = sum(lvl.price for lvl in levels) / len(levels)
        tol = avg_price * (self.equal_tolerance_pct / 100.0)

        kept: list[LiquidityLevel] = []
        for lvl in sorted(levels, key=lambda x: x.price):
            if not kept or abs(lvl.price - kept[-1].price) > tol:
                kept.append(lvl)
        return kept
