"""LTF entry signal generator for FACTRADE.

Strategy: HTF Liquidity Sweep + Major CHoCH + OTE (Optimal Trade Entry)

Signal generation flow
----------------------
1. Confirm HTF liquidity sweep (from LiquidityDetector).
2. Detect 15m / 30m CHoCH (Change of Character) — a strong displacement
   candle that breaks the preceding structure.
3. Measure the CHoCH range and compute Fibonacci levels.
4. Entry is triggered when price retraces to the OTE zone (0.618–0.786 Fib)
   and generates a confirming bar.

Additional signals
------------------
- SMMA 31/59 ribbon alignment (Regime 1: Trend)
- Fair Value Gap (FVG) detection for confluence
- Market regime tagging (trend / range / volatile)

Output
------
``TradeSignal`` dataclass with direction, entry, SL (preliminary), TP targets,
and confidence metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
import pandas as pd
import structlog

from src.trading.analysis.liquidity_detector import LiquidityLevel

logger = structlog.get_logger(__name__)

Direction = Literal["long", "short"]
Regime = Literal["trend", "range", "volatile", "unknown"]


@dataclass
class TradeSignal:
    """A generated trade signal."""

    direction: Direction
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    signal_time: pd.Timestamp
    regime: Regime = "unknown"
    fib_high: float = 0.0
    fib_low: float = 0.0
    ote_low: float = 0.0   # 0.618 Fib level (direction-adjusted)
    ote_high: float = 0.0  # 0.786 Fib level
    fvg_present: bool = False
    choch_confirmed: bool = False
    htf_sweep_price: float = 0.0
    confidence: float = 0.0  # 0.0 – 1.0
    symbol: str = ""
    timeframe: str = ""
    notes: list[str] = field(default_factory=list)


class SignalGenerator:
    """Generate LTF trade signals aligned with HTF liquidity sweeps.

    Parameters
    ----------
    ote_low_fib:
        Lower bound of OTE zone (default 0.618).
    ote_high_fib:
        Upper bound of OTE zone (default 0.786).
    choch_lookback:
        Bars to look back for CHoCH structure (default 20).
    smma_short:
        Short SMMA period for trend ribbon (default 31).
    smma_long:
        Long SMMA period for trend ribbon (default 59).
    """

    def __init__(
        self,
        ote_low_fib: float = 0.618,
        ote_high_fib: float = 0.786,
        choch_lookback: int = 20,
        smma_short: int = 31,
        smma_long: int = 59,
    ) -> None:
        self.ote_low_fib = ote_low_fib
        self.ote_high_fib = ote_high_fib
        self.choch_lookback = choch_lookback
        self.smma_short = smma_short
        self.smma_long = smma_long

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        ltf_df: pd.DataFrame,
        swept_levels: list[LiquidityLevel],
        symbol: str = "",
        timeframe: str = "15m",
    ) -> list[TradeSignal]:
        """Generate trade signals from LTF data and swept HTF levels.

        Parameters
        ----------
        ltf_df:
            15m or 30m OHLCV DataFrame.
        swept_levels:
            HTF liquidity levels recently swept (from LiquidityDetector).
        symbol:
            Instrument identifier.
        timeframe:
            LTF timeframe label.

        Returns
        -------
        list[TradeSignal]
            One signal per detected setup (may be empty if no setup found).
        """
        if ltf_df.empty or not swept_levels:
            return []

        signals: list[TradeSignal] = []
        regime = self._detect_regime(ltf_df)

        for level in swept_levels:
            direction = self._sweep_to_direction(level)
            if direction is None:
                continue

            choch = self._detect_choch(ltf_df, direction)
            if choch is None:
                continue

            signal = self._build_ote_signal(
                ltf_df,
                direction,
                choch,
                level,
                regime,
                symbol,
                timeframe,
            )
            if signal is not None:
                signals.append(signal)

        logger.info(
            "signal_generator.generate",
            symbol=symbol,
            timeframe=timeframe,
            swept_levels=len(swept_levels),
            signals=len(signals),
        )
        return signals

    def detect_regime(self, df: pd.DataFrame) -> Regime:
        """Public wrapper around regime detection."""
        return self._detect_regime(df)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sweep_to_direction(self, level: LiquidityLevel) -> Optional[Direction]:
        """A sweep of a high → potential short; a sweep of a low → potential long."""
        if level.type in ("swing_high", "pdh", "pwh", "equal_high"):
            return "short"
        if level.type in ("swing_low", "pdl", "pwl", "equal_low"):
            return "long"
        return None

    def _detect_choch(
        self,
        df: pd.DataFrame,
        direction: Direction,
        lookback: Optional[int] = None,
    ) -> Optional[dict]:
        """Detect a CHoCH (Change of Character) in *df*.

        A bullish CHoCH: a strong displacement candle that breaks above the
        recent swing high (after a sweep of a swing low).
        A bearish CHoCH: breaks below the recent swing low (after high sweep).

        Returns a dict with keys: high, low, bar_index, bar_ts.
        """
        lb = lookback or self.choch_lookback
        if len(df) < lb + 1:
            return None

        recent = df.iloc[-(lb + 1):]

        if direction == "long":
            # Find the displacement move upward
            swing_low = recent["low"].min()
            swing_low_idx = recent["low"].idxmin()
            # After the low, look for a strong bullish close above prior swing high
            post_low = recent.loc[swing_low_idx:]
            if len(post_low) < 2:
                return None
            swing_high = recent.loc[:swing_low_idx, "high"].max() if len(recent.loc[:swing_low_idx]) > 0 else recent["high"].max()
            for i in range(1, len(post_low)):
                bar = post_low.iloc[i]
                if bar["close"] > swing_high and (bar["close"] - bar["open"]) > 0:
                    return {
                        "high": float(post_low.loc[:post_low.index[i], "high"].max()),
                        "low": float(swing_low),
                        "bar_index": i,
                        "bar_ts": post_low.index[i],
                    }

        elif direction == "short":
            # Find the displacement move downward
            swing_high = recent["high"].max()
            swing_high_idx = recent["high"].idxmax()
            post_high = recent.loc[swing_high_idx:]
            if len(post_high) < 2:
                return None
            swing_low = recent.loc[:swing_high_idx, "low"].min() if len(recent.loc[:swing_high_idx]) > 0 else recent["low"].min()
            for i in range(1, len(post_high)):
                bar = post_high.iloc[i]
                if bar["close"] < swing_low and (bar["open"] - bar["close"]) > 0:
                    return {
                        "high": float(swing_high),
                        "low": float(post_high.loc[:post_high.index[i], "low"].min()),
                        "bar_index": i,
                        "bar_ts": post_high.index[i],
                    }

        return None

    def _build_ote_signal(
        self,
        df: pd.DataFrame,
        direction: Direction,
        choch: dict,
        sweep_level: LiquidityLevel,
        regime: Regime,
        symbol: str,
        timeframe: str,
    ) -> Optional[TradeSignal]:
        """Build a TradeSignal if price is in the OTE zone."""
        fib_high = choch["high"]
        fib_low = choch["low"]
        fib_range = fib_high - fib_low

        if fib_range <= 0:
            return None

        current_close = float(df["close"].iloc[-1])
        signal_time = df.index[-1]

        if direction == "long":
            ote_high = fib_high - self.ote_low_fib * fib_range   # 0.618 retrace
            ote_low = fib_high - self.ote_high_fib * fib_range    # 0.786 retrace
            in_ote = ote_low <= current_close <= ote_high
            if not in_ote:
                return None

            entry = current_close
            sl = fib_low - (fib_range * 0.10)  # just below CHoCH low
            tp1 = fib_high  # CHoCH high
            tp2 = float(sweep_level.price) + (fib_range * 1.5)  # HTF opposite liq proxy

        else:  # short
            ote_low = fib_low + self.ote_low_fib * fib_range    # 0.618 retrace
            ote_high = fib_low + self.ote_high_fib * fib_range   # 0.786 retrace
            in_ote = ote_low <= current_close <= ote_high
            if not in_ote:
                return None

            entry = current_close
            sl = fib_high + (fib_range * 0.10)
            tp1 = fib_low
            tp2 = float(sweep_level.price) - (fib_range * 1.5)

        # Confidence scoring
        score = 0.5  # base
        if choch.get("bar_ts") is not None:
            score += 0.1
        if regime == "trend":
            score += 0.2
        fvg = self._detect_fvg(df, direction)
        if fvg:
            score += 0.2

        signal = TradeSignal(
            direction=direction,
            entry_price=entry,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            signal_time=signal_time,
            regime=regime,
            fib_high=fib_high,
            fib_low=fib_low,
            ote_low=ote_low,
            ote_high=ote_high,
            fvg_present=fvg,
            choch_confirmed=True,
            htf_sweep_price=sweep_level.price,
            confidence=min(score, 1.0),
            symbol=symbol,
            timeframe=timeframe,
        )

        logger.info(
            "signal_generator.signal",
            direction=direction,
            entry=round(entry, 2),
            sl=round(sl, 2),
            tp1=round(tp1, 2),
            confidence=round(score, 2),
        )
        return signal

    def _detect_fvg(self, df: pd.DataFrame, direction: Direction) -> bool:
        """Detect Fair Value Gap (imbalance) in the last few candles."""
        if len(df) < 3:
            return False
        for i in range(len(df) - 3, len(df) - 1):
            c1 = df.iloc[i]
            c3 = df.iloc[i + 2] if i + 2 < len(df) else df.iloc[-1]
            if direction == "long" and c1["high"] < c3["low"]:
                return True
            if direction == "short" and c1["low"] > c3["high"]:
                return True
        return False

    def _detect_regime(self, df: pd.DataFrame) -> Regime:
        """Detect market regime using SMMA ribbon and volatility."""
        if len(df) < max(self.smma_short, self.smma_long) + 5:
            return "unknown"

        smma_s = self._smma(df["close"], self.smma_short)
        smma_l = self._smma(df["close"], self.smma_long)

        last_s = smma_s.iloc[-1]
        last_l = smma_l.iloc[-1]
        prev_s = smma_s.iloc[-5]
        prev_l = smma_l.iloc[-5]

        # Trend: ribbons have been separated and moving together
        ribbon_spread = abs(last_s - last_l) / last_l if last_l != 0 else 0
        if ribbon_spread > 0.002 and (
            (last_s > last_l and prev_s > prev_l)
            or (last_s < last_l and prev_s < prev_l)
        ):
            return "trend"

        # Volatile: large candle bodies in recent bars
        recent = df.iloc[-10:]
        avg_body = ((recent["close"] - recent["open"]).abs()).mean()
        avg_range = (recent["high"] - recent["low"]).mean()
        if avg_range > 0 and avg_body / avg_range > 0.7:
            return "volatile"

        return "range"

    @staticmethod
    def _smma(series: pd.Series, period: int) -> pd.Series:
        """Smoothed Moving Average."""
        smma = series.ewm(alpha=1 / period, adjust=False).mean()
        return smma
