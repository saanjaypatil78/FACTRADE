"""
Liquidity Detector — HTF swing-high/low and liquidity-pool detection.

Supported timeframes: Daily, 1H, 3H, 4H (HTF context providers).

A "liquidity level" is any price area where a significant number of retail
stop-losses or breakout orders are likely to be resting:
  - Swing Highs / Swing Lows (local pivot extremes)
  - Equal Highs / Equal Lows   (within configurable tolerance)
  - Previous Day High / Low    (PDH / PDL)
  - Session High / Low         (within a rolling window)

The detector also classifies whether each level has been *swept* (price
pierced it and closed back on the other side — reversal signal) or *run*
(price broke through and held — continuation signal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

class LiquidityType(Enum):
    """Classification of a detected liquidity level."""
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    EQUAL_HIGH = "equal_high"
    EQUAL_LOW = "equal_low"
    PDH = "previous_day_high"
    PDL = "previous_day_low"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"


class SweepStatus(Enum):
    """Whether a liquidity level has been interacted with."""
    UNTOUCHED = "untouched"
    SWEPT = "swept"          # price pierced and rejected — reversal signal
    RUN = "run"              # price broke and held — continuation signal


@dataclass
class LiquidityLevel:
    """A single detected liquidity level on a specific timeframe."""
    price: float
    level_type: LiquidityType
    timeframe: str
    timestamp: pd.Timestamp
    sweep_status: SweepStatus = SweepStatus.UNTOUCHED
    sweep_timestamp: Optional[pd.Timestamp] = None
    # Candle index (row number) where the level was formed
    candle_index: int = 0


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class LiquidityDetector:
    """
    Detects liquidity levels from OHLCV data.

    Parameters
    ----------
    swing_lookback : int
        Number of candles on each side required to confirm a swing pivot.
    equal_tolerance_pct : float
        Two highs/lows are considered "equal" when within this percentage.
    session_window : int
        Number of candles used to define a rolling session for session H/L.
    """

    HTF_TIMEFRAMES = {"1D", "1H", "3H", "4H"}

    def __init__(
        self,
        swing_lookback: int = 3,
        equal_tolerance_pct: float = 0.05,
        session_window: int = 20,
    ) -> None:
        self.swing_lookback = swing_lookback
        self.equal_tolerance_pct = equal_tolerance_pct
        self.session_window = session_window

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def detect(
        self,
        ohlcv: pd.DataFrame,
        timeframe: str,
        include_pdh_pdl: bool = True,
    ) -> List[LiquidityLevel]:
        """
        Return all active liquidity levels found in *ohlcv*.

        Parameters
        ----------
        ohlcv : pd.DataFrame
            Columns: open, high, low, close, volume (case-insensitive).
            Index:   DatetimeIndex.
        timeframe : str
            e.g. "1H", "4H", "1D".
        include_pdh_pdl : bool
            Whether to include Previous Day High/Low levels.

        Returns
        -------
        List[LiquidityLevel]
            Levels ordered by timestamp ascending.
        """
        df = self._normalise_columns(ohlcv)
        if df.empty:
            return []

        levels: List[LiquidityLevel] = []
        levels.extend(self._find_swing_pivots(df, timeframe))
        levels.extend(self._find_equal_levels(df, timeframe))
        if include_pdh_pdl:
            levels.extend(self._find_pdh_pdl(df, timeframe))
        levels.extend(self._find_session_extremes(df, timeframe))

        # Classify sweep/run status against the most recent candle
        levels = self._classify_sweep_status(levels, df)

        levels.sort(key=lambda lvl: lvl.timestamp)
        logger.debug(
            "liquidity_levels_detected",
            timeframe=timeframe,
            count=len(levels),
        )
        return levels

    def get_active_levels(
        self,
        ohlcv: pd.DataFrame,
        timeframe: str,
    ) -> List[LiquidityLevel]:
        """Return only UNTOUCHED (still-valid) liquidity levels."""
        return [
            lvl
            for lvl in self.detect(ohlcv, timeframe)
            if lvl.sweep_status == SweepStatus.UNTOUCHED
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure lower-case column names; validate required columns."""
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"OHLCV DataFrame missing columns: {missing}")
        return df

    def _find_swing_pivots(
        self, df: pd.DataFrame, timeframe: str
    ) -> List[LiquidityLevel]:
        """
        Identify swing highs and lows using a rolling lookback window.
        A swing high at index *i* requires:
            df.high[i] > df.high[i-k] and df.high[i] > df.high[i+k]
            for all k in 1..swing_lookback.
        """
        levels: List[LiquidityLevel] = []
        n = len(df)
        lb = self.swing_lookback

        highs = df["high"].values
        lows = df["low"].values
        timestamps = df.index

        for i in range(lb, n - lb):
            # Swing high
            if all(highs[i] > highs[i - k] for k in range(1, lb + 1)) and all(
                highs[i] > highs[i + k] for k in range(1, lb + 1)
            ):
                levels.append(
                    LiquidityLevel(
                        price=float(highs[i]),
                        level_type=LiquidityType.SWING_HIGH,
                        timeframe=timeframe,
                        timestamp=timestamps[i],
                        candle_index=i,
                    )
                )
            # Swing low
            if all(lows[i] < lows[i - k] for k in range(1, lb + 1)) and all(
                lows[i] < lows[i + k] for k in range(1, lb + 1)
            ):
                levels.append(
                    LiquidityLevel(
                        price=float(lows[i]),
                        level_type=LiquidityType.SWING_LOW,
                        timeframe=timeframe,
                        timestamp=timestamps[i],
                        candle_index=i,
                    )
                )

        return levels

    def _find_equal_levels(
        self, df: pd.DataFrame, timeframe: str
    ) -> List[LiquidityLevel]:
        """
        Find clusters of swing highs/lows that are within tolerance of each other
        (equal highs / equal lows).  Only the cluster representative (highest of
        highs / lowest of lows) is returned.
        """
        swings = self._find_swing_pivots(df, timeframe)
        sh = [s for s in swings if s.level_type == LiquidityType.SWING_HIGH]
        sl = [s for s in swings if s.level_type == LiquidityType.SWING_LOW]
        levels: List[LiquidityLevel] = []

        def _cluster(points: List[LiquidityLevel], eq_type: LiquidityType) -> None:
            visited = [False] * len(points)
            for i, a in enumerate(points):
                if visited[i]:
                    continue
                cluster = [a]
                for j, b in enumerate(points[i + 1 :], start=i + 1):
                    tol = self.equal_tolerance_pct / 100 * a.price
                    if abs(a.price - b.price) <= tol:
                        cluster.append(b)
                        visited[j] = True
                if len(cluster) >= 2:
                    # Representative: most recent timestamp
                    rep = max(cluster, key=lambda x: x.timestamp)
                    if eq_type == LiquidityType.EQUAL_HIGH:
                        rep_price = max(c.price for c in cluster)
                    else:
                        rep_price = min(c.price for c in cluster)
                    levels.append(
                        LiquidityLevel(
                            price=rep_price,
                            level_type=eq_type,
                            timeframe=timeframe,
                            timestamp=rep.timestamp,
                            candle_index=rep.candle_index,
                        )
                    )

        _cluster(sh, LiquidityType.EQUAL_HIGH)
        _cluster(sl, LiquidityType.EQUAL_LOW)
        return levels

    def _find_pdh_pdl(
        self, df: pd.DataFrame, timeframe: str
    ) -> List[LiquidityLevel]:
        """Return Previous Day High and Low based on date grouping."""
        levels: List[LiquidityLevel] = []
        df_copy = df.copy()
        if not hasattr(df_copy.index, "date"):
            return levels

        df_copy["_date"] = df_copy.index.date  # type: ignore[attr-defined]
        daily_groups = df_copy.groupby("_date")
        dates = sorted(daily_groups.groups.keys())

        for idx, d in enumerate(dates[1:], start=1):
            prev_d = dates[idx - 1]
            prev_group = daily_groups.get_group(prev_d)

            pdh = float(prev_group["high"].max())
            pdl = float(prev_group["low"].min())
            ts = prev_group.index[-1]

            levels.append(
                LiquidityLevel(
                    price=pdh,
                    level_type=LiquidityType.PDH,
                    timeframe=timeframe,
                    timestamp=ts,
                )
            )
            levels.append(
                LiquidityLevel(
                    price=pdl,
                    level_type=LiquidityType.PDL,
                    timeframe=timeframe,
                    timestamp=ts,
                )
            )

        return levels

    def _find_session_extremes(
        self, df: pd.DataFrame, timeframe: str
    ) -> List[LiquidityLevel]:
        """Rolling window session high/low over *session_window* candles."""
        levels: List[LiquidityLevel] = []
        if len(df) < self.session_window:
            return levels

        highs = df["high"].rolling(self.session_window).max()
        lows = df["low"].rolling(self.session_window).min()

        # Only emit at new rolling extremes (where value changes)
        prev_h = prev_l = None
        for i in range(self.session_window - 1, len(df)):
            h = float(highs.iloc[i])
            l = float(lows.iloc[i])
            ts = df.index[i]
            if h != prev_h:
                levels.append(
                    LiquidityLevel(
                        price=h,
                        level_type=LiquidityType.SESSION_HIGH,
                        timeframe=timeframe,
                        timestamp=ts,
                        candle_index=i,
                    )
                )
                prev_h = h
            if l != prev_l:
                levels.append(
                    LiquidityLevel(
                        price=l,
                        level_type=LiquidityType.SESSION_LOW,
                        timeframe=timeframe,
                        timestamp=ts,
                        candle_index=i,
                    )
                )
                prev_l = l

        return levels

    def _classify_sweep_status(
        self,
        levels: List[LiquidityLevel],
        df: pd.DataFrame,
    ) -> List[LiquidityLevel]:
        """
        Update each level's sweep_status by checking all candles that appear
        *after* the level's formation timestamp.

        Sweep (reversal): wick pierces the level but the candle closes back on
        the opposite side.
        Run (continuation): candle closes beyond the level and holds.
        """
        if df.empty:
            return levels

        last_ts = df.index[-1]

        for lvl in levels:
            # Only look at candles after the level was formed
            future = df[df.index > lvl.timestamp]
            if future.empty:
                continue

            if lvl.level_type in (
                LiquidityType.SWING_HIGH,
                LiquidityType.EQUAL_HIGH,
                LiquidityType.PDH,
                LiquidityType.SESSION_HIGH,
            ):
                # Bullish level — look for price reaching above it
                above_mask = future["high"] > lvl.price
                if above_mask.any():
                    first_touch = future[above_mask].iloc[0]
                    if first_touch["close"] < lvl.price:
                        lvl.sweep_status = SweepStatus.SWEPT
                    else:
                        lvl.sweep_status = SweepStatus.RUN
                    lvl.sweep_timestamp = first_touch.name  # type: ignore[assignment]
            else:
                # Bearish level — look for price reaching below it
                below_mask = future["low"] < lvl.price
                if below_mask.any():
                    first_touch = future[below_mask].iloc[0]
                    if first_touch["close"] > lvl.price:
                        lvl.sweep_status = SweepStatus.SWEPT
                    else:
                        lvl.sweep_status = SweepStatus.RUN
                    lvl.sweep_timestamp = first_touch.name  # type: ignore[assignment]

        return levels
