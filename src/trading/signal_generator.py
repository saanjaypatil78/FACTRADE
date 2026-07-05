"""
Signal Generator — LTF (15m / 30m) entry signals based on HTF context.

Strategy flow (top-down):
  1. HTF (1H / 4H / Daily) liquidity has been *swept* (price rejected the level).
  2. On LTF (15m / 30m) a Change of Character (CHoCH) has occurred — a strong
     displacement candle breaks the most recent internal structure.
  3. Price then retraces into the OTE (Optimal Trade Entry) Fibonacci zone
     (0.618 – 0.786 of the CHoCH displacement move).
  4. An entry signal is emitted with a stop-loss below/above the swing that was
     swept plus an ATR buffer, and a take-profit at the opposing HTF liquidity.

Regime detection (for signal filtering):
  - TREND:       31/59 SMMA ribbon is aligned and separated.
  - RANGE:       Bollinger Bands (199, 1.9) are flat; price bouncing inside.
  - VOLATILE:    Price exceeded Bollinger outer band; momentum candles present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

from .liquidity_detector import LiquidityLevel, LiquidityType, SweepStatus

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

class SignalDirection(Enum):
    LONG = "long"
    SHORT = "short"


class MarketRegime(Enum):
    TREND = "trend"
    RANGE = "range"
    VOLATILE = "volatile"
    UNDEFINED = "undefined"


@dataclass
class TradeSignal:
    """A fully-defined actionable trade signal."""
    symbol: str
    direction: SignalDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float          # 80 % partial exit (first internal liquidity)
    take_profit_2: float          # 20 % runner (opposite HTF liquidity)
    timeframe: str
    timestamp: pd.Timestamp
    regime: MarketRegime = MarketRegime.UNDEFINED
    htf_level: Optional[LiquidityLevel] = None
    # Risk / reward ratio (computed, not user-provided)
    risk_pips: float = 0.0
    reward_pips: float = 0.0
    rr_ratio: float = 0.0
    # Metadata
    notes: str = ""

    def __post_init__(self) -> None:
        self.risk_pips = abs(self.entry_price - self.stop_loss)
        self.reward_pips = abs(self.take_profit_1 - self.entry_price)
        if self.risk_pips > 0:
            self.rr_ratio = round(self.reward_pips / self.risk_pips, 2)


# ---------------------------------------------------------------------------
# Signal Generator
# ---------------------------------------------------------------------------

class SignalGenerator:
    """
    Produces LTF entry signals when HTF liquidity has been swept.

    Parameters
    ----------
    ote_low : float
        Lower bound of the OTE Fibonacci zone (default 0.618).
    ote_high : float
        Upper bound of the OTE Fibonacci zone (default 0.786).
    smma_fast : int
        Period for the fast SMMA (default 31).
    smma_slow : int
        Period for the slow SMMA (default 59).
    bb_period : int
        Bollinger Bands period (default 199).
    bb_std : float
        Bollinger Bands standard-deviation multiplier (default 1.9).
    min_displacement_pct : float
        Minimum CHoCH candle body as % of recent ATR to be considered a
        "strong" displacement (default 150 %).
    max_sl_pips : float
        Skip trade if computed SL distance exceeds this value (default 50).
    """

    LTF_TIMEFRAMES = {"15m", "30m"}

    def __init__(
        self,
        ote_low: float = 0.618,
        ote_high: float = 0.786,
        smma_fast: int = 31,
        smma_slow: int = 59,
        bb_period: int = 199,
        bb_std: float = 1.9,
        min_displacement_pct: float = 150.0,
        max_sl_pips: float = 50.0,
    ) -> None:
        self.ote_low = ote_low
        self.ote_high = ote_high
        self.smma_fast = smma_fast
        self.smma_slow = smma_slow
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.min_displacement_pct = min_displacement_pct
        self.max_sl_pips = max_sl_pips

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def generate(
        self,
        ltf_ohlcv: pd.DataFrame,
        htf_levels: List[LiquidityLevel],
        symbol: str,
        timeframe: str,
        atr_value: Optional[float] = None,
    ) -> List[TradeSignal]:
        """
        Evaluate the latest LTF candles against swept HTF levels and return
        actionable signals (may be empty).

        Parameters
        ----------
        ltf_ohlcv : pd.DataFrame
            LTF OHLCV data (15m or 30m). Index: DatetimeIndex.
        htf_levels : List[LiquidityLevel]
            Levels already classified by LiquidityDetector (includes sweep status).
        symbol : str
            Instrument identifier, e.g. "XAUUSD".
        timeframe : str
            The LTF being analysed, e.g. "15m".
        atr_value : float, optional
            Current ATR value on the LTF; computed internally if not provided.

        Returns
        -------
        List[TradeSignal]
        """
        df = self._normalise_columns(ltf_ohlcv)
        if len(df) < self.bb_period:
            logger.debug("insufficient_ltf_data", rows=len(df), required=self.bb_period)
            return []

        if atr_value is None:
            atr_value = self._calculate_atr(df)

        regime = self._detect_regime(df)
        swept_htf = [
            lvl for lvl in htf_levels if lvl.sweep_status == SweepStatus.SWEPT
        ]

        signals: List[TradeSignal] = []

        for lvl in swept_htf:
            sig = self._evaluate_level(
                df, lvl, symbol, timeframe, atr_value, regime
            )
            if sig is not None:
                signals.append(sig)

        logger.info(
            "signals_generated",
            symbol=symbol,
            timeframe=timeframe,
            regime=regime.value,
            htf_swept=len(swept_htf),
            signals=len(signals),
        )
        return signals

    # ------------------------------------------------------------------
    # Regime detection
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> MarketRegime:
        """Public wrapper around the internal regime detector."""
        df = self._normalise_columns(df)
        return self._detect_regime(df)

    def _detect_regime(self, df: pd.DataFrame) -> MarketRegime:
        """Classify current market regime from LTF candles."""
        if len(df) < self.smma_slow:
            return MarketRegime.UNDEFINED

        fast = self._smma(df["close"], self.smma_fast)
        slow = self._smma(df["close"], self.smma_slow)

        mid, upper, lower = self._bollinger(df["close"], self.bb_period, self.bb_std)

        last_close = df["close"].iloc[-1]
        last_fast = fast.iloc[-1]
        last_slow = slow.iloc[-1]
        last_upper = upper.iloc[-1]
        last_lower = lower.iloc[-1]

        # Bands are "flat" when the range is small relative to recent price
        bb_width = (last_upper - last_lower) / mid.iloc[-1]

        # Volatile: price outside BB outer band
        if last_close > last_upper or last_close < last_lower:
            return MarketRegime.VOLATILE

        # Trend: SMMA ribbon clearly separated and price on correct side
        ribbon_gap = abs(last_fast - last_slow)
        price_range_20 = df["high"].rolling(20).max().iloc[-1] - df["low"].rolling(20).min().iloc[-1]
        if ribbon_gap > 0.001 * last_close and bb_width > 0.005:
            if last_fast > last_slow:
                return MarketRegime.TREND
            return MarketRegime.TREND

        # Range: flat BB bands
        if bb_width < 0.005:
            return MarketRegime.RANGE

        return MarketRegime.UNDEFINED

    # ------------------------------------------------------------------
    # CHoCH + OTE evaluation
    # ------------------------------------------------------------------

    def _evaluate_level(
        self,
        df: pd.DataFrame,
        htf_level: LiquidityLevel,
        symbol: str,
        timeframe: str,
        atr: float,
        regime: MarketRegime,
    ) -> Optional[TradeSignal]:
        """
        Check for a valid CHoCH followed by an OTE retracement.
        Returns a TradeSignal if all conditions are met, else None.
        """
        # Only look at candles after the HTF sweep
        if htf_level.sweep_timestamp is None:
            return None

        ltf_after_sweep = df[df.index >= htf_level.sweep_timestamp]
        if len(ltf_after_sweep) < 5:
            return None

        # Determine expected direction from the HTF sweep
        if htf_level.level_type in (
            LiquidityType.SWING_HIGH,
            LiquidityType.EQUAL_HIGH,
            LiquidityType.PDH,
            LiquidityType.SESSION_HIGH,
        ):
            direction = SignalDirection.SHORT  # sweep above → expect reversal down
        else:
            direction = SignalDirection.LONG   # sweep below → expect reversal up

        # Find CHoCH displacement candle
        choch = self._find_choch(ltf_after_sweep, direction, atr)
        if choch is None:
            return None

        choch_idx, swing_origin, displacement_end = choch

        # OTE zone on the CHoCH displacement
        ote_low_price, ote_high_price = self._ote_zone(
            swing_origin, displacement_end, direction
        )

        # Check whether current price is in the OTE zone
        current_close = df["close"].iloc[-1]
        current_high = df["high"].iloc[-1]
        current_low = df["low"].iloc[-1]

        in_ote = (
            (direction == SignalDirection.LONG and ote_low_price <= current_low <= ote_high_price)
            or
            (direction == SignalDirection.SHORT and ote_low_price <= current_high <= ote_high_price)
        )
        if not in_ote:
            return None

        # Entry price = current close (market order) or OTE midpoint
        entry = current_close

        # Stop-loss: beyond the HTF swept level + 1.5 × ATR buffer
        atr_buffer = 1.5 * atr
        if direction == SignalDirection.LONG:
            sl = htf_level.price - atr_buffer
        else:
            sl = htf_level.price + atr_buffer

        sl_distance = abs(entry - sl)

        # Skip rule: SL > max_sl_pips
        if sl_distance > self.max_sl_pips:
            logger.debug(
                "signal_skipped_sl_too_wide",
                sl_distance=round(sl_distance, 4),
                max_sl=self.max_sl_pips,
            )
            return None

        # TP1: first internal liquidity (1.5 × SL distance)
        tp1_distance = 1.5 * sl_distance
        # TP2: 3.0 × SL distance (opposite HTF liquidity target)
        tp2_distance = 3.0 * sl_distance

        if direction == SignalDirection.LONG:
            tp1 = entry + tp1_distance
            tp2 = entry + tp2_distance
        else:
            tp1 = entry - tp1_distance
            tp2 = entry - tp2_distance

        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry, 5),
            stop_loss=round(sl, 5),
            take_profit_1=round(tp1, 5),
            take_profit_2=round(tp2, 5),
            timeframe=timeframe,
            timestamp=df.index[-1],
            regime=regime,
            htf_level=htf_level,
            notes=(
                f"HTF {htf_level.timeframe} {htf_level.level_type.value} swept. "
                f"CHoCH on {timeframe}. OTE zone {ote_low_price:.4f}-{ote_high_price:.4f}."
            ),
        )
        logger.info(
            "signal_generated",
            symbol=symbol,
            direction=direction.value,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            rr=signal.rr_ratio,
        )
        return signal

    def _find_choch(
        self,
        df: pd.DataFrame,
        direction: SignalDirection,
        atr: float,
    ) -> Optional[Tuple[int, float, float]]:
        """
        Identify the first strong displacement candle (CHoCH) in *df*.

        Returns (index_in_df, swing_origin_price, displacement_end_price) or None.
        """
        min_body = (self.min_displacement_pct / 100.0) * atr
        for i in range(1, len(df)):
            candle = df.iloc[i]
            body = abs(candle["close"] - candle["open"])
            if body < min_body:
                continue
            if direction == SignalDirection.LONG:
                # Strong bullish candle that closes above the previous swing high
                prev_high = df["high"].iloc[:i].max()
                if candle["close"] > prev_high and candle["close"] > candle["open"]:
                    return (i, df["low"].iloc[:i].min(), candle["close"])
            else:
                # Strong bearish candle that closes below the previous swing low
                prev_low = df["low"].iloc[:i].min()
                if candle["close"] < prev_low and candle["close"] < candle["open"]:
                    return (i, df["high"].iloc[:i].max(), candle["close"])
        return None

    def _ote_zone(
        self,
        swing_origin: float,
        displacement_end: float,
        direction: SignalDirection,
    ) -> Tuple[float, float]:
        """
        Compute the OTE Fibonacci retracement zone [0.618, 0.786] of the
        displacement move (swing_origin → displacement_end).
        """
        move = displacement_end - swing_origin
        if direction == SignalDirection.LONG:
            # Retracement is *down* from the displacement top
            ote_high_price = displacement_end - self.ote_low * abs(move)
            ote_low_price = displacement_end - self.ote_high * abs(move)
        else:
            # Retracement is *up* from the displacement bottom
            ote_low_price = displacement_end + self.ote_low * abs(move)
            ote_high_price = displacement_end + self.ote_high * abs(move)
        return (min(ote_low_price, ote_high_price), max(ote_low_price, ote_high_price))

    # ------------------------------------------------------------------
    # Technical indicators
    # ------------------------------------------------------------------

    @staticmethod
    def _smma(series: pd.Series, period: int) -> pd.Series:
        """Smoothed Moving Average (SMMA / RMA)."""
        result = series.copy() * np.nan
        sma_seed = series.iloc[:period].mean()
        result.iloc[period - 1] = sma_seed
        alpha = 1.0 / period
        for i in range(period, len(series)):
            result.iloc[i] = result.iloc[i - 1] * (1 - alpha) + series.iloc[i] * alpha
        return result

    @staticmethod
    def _bollinger(
        series: pd.Series, period: int, std_mult: float
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Returns (mid, upper, lower) Bollinger Bands."""
        mid = series.rolling(period).mean()
        std = series.rolling(period).std()
        upper = mid + std_mult * std
        lower = mid - std_mult * std
        return mid, upper, lower

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Average True Range over the last *period* candles."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if not np.isnan(atr) else float(tr.iloc[-period:].mean())

    @staticmethod
    def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"OHLCV DataFrame missing columns: {missing}")
        return df
