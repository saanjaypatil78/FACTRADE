"""
Signal Generator – FACTRADE Tri-Regime strategy logic.

Implements four setups from the FACTRADE Masterplan v7.0:

1. **OTE + CHoCH** (universal – works in any regime)
   Liquidity sweep on HTF → CHoCH on 15m → OTE Fibonacci entry (0.618–0.786).

2. **SMMA Ribbon** (Regime 1: trending market)
   SMMA(31) crosses SMMA(59); price pulls back to ribbon → hammer/wick entry.

3. **Bollinger Bands** (Regime 2: consolidation)
   BB(199, 1.9) on 5m; price touches outer band with flat bands → mean reversion.

4. **VWAP Breakout** (Regime 3: high-volatility / session open)
   Price returns from VWAP deviation band; 2 consecutive closes above/below
   VWAP midline; third candle triggers.

All setups produce :class:`~src.trading.candle.Signal` objects with
deterministic SL and TP via :class:`~src.trading.risk_manager.RiskManager`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
import structlog

from src.trading.candle import Candle, Signal
from src.trading.liquidity_detector import LiquidityDetector
from src.trading.risk_manager import RiskManager

logger = structlog.get_logger(__name__)

# OTE Fibonacci retracement zone (inclusive)
_OTE_LOW = 0.618
_OTE_HIGH = 0.786

# Bollinger Band parameters
_BB_PERIOD = 199
_BB_STD = 1.9

# SMMA periods
_SMMA_FAST = 31
_SMMA_SLOW = 59

# VWAP reset frequency (daily)
_VWAP_RESET = "1D"


class SignalGenerator:
    """
    Generate trading signals using FACTRADE's four-setup strategy model.

    Parameters
    ----------
    risk_manager:
        Pre-configured :class:`RiskManager`.  If *None*, one is created with
        default settings.
    swing_bars:
        Passed to :class:`LiquidityDetector` for swing detection.
    """

    def __init__(
        self,
        risk_manager: Optional[RiskManager] = None,
        swing_bars: int = 3,
    ) -> None:
        self.risk = risk_manager or RiskManager()
        self.liq = LiquidityDetector(swing_bars=swing_bars)

    # ================================================================== #
    # Setup 1: OTE + CHoCH
    # ================================================================== #

    def ote_choch_signal(
        self,
        htf_candles: List[Candle],   # 1H or 4H candles (liquidity context)
        ltf_candles: List[Candle],   # 15m candles (CHoCH + OTE entry)
    ) -> Optional[Signal]:
        """
        Universal Liquidity Sweep + CHoCH + OTE setup.

        Returns a ``Signal`` if all conditions align, else ``None``.
        """
        if len(htf_candles) < 20 or len(ltf_candles) < 30:
            return None

        # ---- Step 1: detect a recent HTF liquidity sweep ----
        htf_levels = self.liq.detect(htf_candles)
        sweeps = self.liq.detect_sweeps(htf_candles[-20:], htf_levels)
        if not sweeps:
            return None

        sweep_candle, sweep_level = sweeps[-1]
        direction = (
            "long" if sweep_level.kind in ("swing_low", "pdl", "equal_low") else "short"
        )

        # ---- Step 2: CHoCH on 15m ----
        choch_result = self._detect_choch(ltf_candles, direction)
        if choch_result is None:
            return None
        choch_high, choch_low, choch_candle = choch_result

        # ---- Step 3: OTE zone on the latest 15m candle ----
        latest = ltf_candles[-1]
        in_ote, ote_entry = self._ote_entry(
            direction, choch_high, choch_low, latest
        )
        if not in_ote:
            return None

        # ---- Step 4: SL / TP ----
        wick_extreme = latest.low if direction == "long" else latest.high
        sl_price, sl_pips, skip = self.risk.calculate_sl(
            direction=direction,
            wick_extreme=wick_extreme,
            candles=ltf_candles,
            symbol=latest.symbol,
        )
        if skip:
            return None

        tp1, tp2 = self.risk.calculate_tp(direction, ote_entry, sl_price)
        atr = self.risk.atr(ltf_candles)

        signal = Signal(
            symbol=latest.symbol,
            direction=direction,
            entry_price=ote_entry,
            stop_loss=sl_price,
            take_profit_1=tp1,
            take_profit_2=tp2,
            timestamp=latest.timestamp,
            setup_type="ote_choch",
            timeframe=latest.timeframe,
            atr_at_entry=atr,
            metadata={
                "sweep_level_price": sweep_level.price,
                "sweep_level_kind": sweep_level.kind,
                "choch_high": choch_high,
                "choch_low": choch_low,
                "ote_low": _OTE_LOW,
                "ote_high": _OTE_HIGH,
                "sl_pips": round(sl_pips, 1),
            },
        )
        logger.info(
            "signal_generator.ote_choch",
            symbol=latest.symbol,
            direction=direction,
            entry=round(ote_entry, 4),
            sl=round(sl_price, 4),
            tp1=round(tp1, 4),
            rr=round(signal.risk_reward, 2),
        )
        return signal

    # ================================================================== #
    # Setup 2: SMMA Ribbon
    # ================================================================== #

    def smma_ribbon_signal(self, candles: List[Candle]) -> Optional[Signal]:
        """
        SMMA(31) / SMMA(59) trend-rider setup.

        Returns a ``Signal`` when:
        - SMMA(31) is clearly above/below SMMA(59) (trend confirmed).
        - Price has pulled back to touch or pierce the fast ribbon.
        - A hammer / long-wick candle forms at the ribbon (close confirmed).
        """
        n = max(_SMMA_FAST, _SMMA_SLOW) + 10
        if len(candles) < n:
            return None

        closes = np.array([c.close for c in candles])
        smma_fast = _smma(closes, _SMMA_FAST)
        smma_slow = _smma(closes, _SMMA_SLOW)

        fast = smma_fast[-1]
        slow = smma_slow[-1]
        diff = fast - slow

        # Trend must be clear (at least 0.1 % separation)
        sep_pct = abs(diff) / slow
        if sep_pct < 0.001:
            return None

        direction = "long" if diff > 0 else "short"
        latest = candles[-1]
        prev = candles[-2]

        # Price must have touched the fast SMMA on the current or previous bar
        ribbon_touched = (
            (direction == "long" and latest.low <= fast <= latest.high)
            or (direction == "short" and latest.low <= fast <= latest.high)
        )
        if not ribbon_touched:
            return None

        # Wick-rejection / hammer confirmation
        if direction == "long":
            wick_ok = latest.lower_wick > latest.body_size * 1.5
        else:
            wick_ok = latest.upper_wick > latest.body_size * 1.5

        if not wick_ok:
            return None

        wick_extreme = latest.low if direction == "long" else latest.high
        sl_price, sl_pips, skip = self.risk.calculate_sl(
            direction, wick_extreme, candles, latest.symbol
        )
        if skip:
            return None

        entry = latest.close
        tp1, tp2 = self.risk.calculate_tp(direction, entry, sl_price)
        atr = self.risk.atr(candles)

        signal = Signal(
            symbol=latest.symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=sl_price,
            take_profit_1=tp1,
            take_profit_2=tp2,
            timestamp=latest.timestamp,
            setup_type="smma_ribbon",
            timeframe=latest.timeframe,
            atr_at_entry=atr,
            metadata={
                "smma_fast": round(fast, 4),
                "smma_slow": round(slow, 4),
                "ribbon_sep_pct": round(sep_pct * 100, 3),
                "sl_pips": round(sl_pips, 1),
            },
        )
        logger.info(
            "signal_generator.smma_ribbon",
            symbol=latest.symbol,
            direction=direction,
            entry=round(entry, 4),
        )
        return signal

    # ================================================================== #
    # Setup 3: Bollinger Bands mean reversion
    # ================================================================== #

    def bb_reversion_signal(self, candles: List[Candle]) -> Optional[Signal]:
        """
        Bollinger Bands (199, 1.9) mean-reversion on 5m candles.

        Returns a ``Signal`` when:
        - Bands are flat (σ of the midline < threshold → consolidation).
        - Price touched the outer band but closed inside (sell-side sweep done).
        - Entry is at the close of the confirming candle.
        """
        if len(candles) < _BB_PERIOD + 5:
            return None

        closes = np.array([c.close for c in candles])
        mid, upper, lower = _bollinger(closes, _BB_PERIOD, _BB_STD)

        # Bands must be flat (range of the last 20 midline values < 0.3 %)
        mid_range = (mid[-20:].max() - mid[-20:].min()) / mid[-1]
        if mid_range > 0.003:
            return None

        latest = candles[-1]
        prev = candles[-2]

        # Lower band touch → long
        if prev.low <= lower[-2] and latest.close > lower[-1]:
            direction = "long"
        # Upper band touch → short
        elif prev.high >= upper[-2] and latest.close < upper[-1]:
            direction = "short"
        else:
            return None

        wick_extreme = prev.low if direction == "long" else prev.high
        sl_price, sl_pips, skip = self.risk.calculate_sl(
            direction, wick_extreme, candles, latest.symbol
        )
        if skip:
            return None

        entry = latest.close
        # TP1: midline; TP2: opposite band
        if direction == "long":
            tp1 = float(mid[-1])
            tp2 = float(upper[-1])
        else:
            tp1 = float(mid[-1])
            tp2 = float(lower[-1])

        atr = self.risk.atr(candles)

        signal = Signal(
            symbol=latest.symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=sl_price,
            take_profit_1=tp1,
            take_profit_2=tp2,
            timestamp=latest.timestamp,
            setup_type="bb_reversion",
            timeframe=latest.timeframe,
            atr_at_entry=atr,
            metadata={
                "bb_mid": round(float(mid[-1]), 4),
                "bb_upper": round(float(upper[-1]), 4),
                "bb_lower": round(float(lower[-1]), 4),
                "mid_range_pct": round(mid_range * 100, 3),
                "sl_pips": round(sl_pips, 1),
            },
        )
        logger.info(
            "signal_generator.bb_reversion",
            symbol=latest.symbol,
            direction=direction,
            entry=round(entry, 4),
        )
        return signal

    # ================================================================== #
    # Setup 4: VWAP breakout
    # ================================================================== #

    def vwap_breakout_signal(self, candles: List[Candle]) -> Optional[Signal]:
        """
        VWAP Deviation Breakout for high-volatility / session-open conditions.

        Returns a ``Signal`` when:
        - Price has returned from the VWAP deviation band.
        - Two consecutive candles close on the same side of VWAP.
        - The third candle breaks the high/low of the previous two.
        """
        if len(candles) < 30:
            return None

        vwap = _calc_vwap(candles)
        if vwap is None:
            return None

        c0, c1, c2 = candles[-3], candles[-2], candles[-1]
        v = vwap

        # Two consecutive closes above VWAP → long bias
        if c0.close > v and c1.close > v:
            # Third candle breaks the 2-bar high
            if c2.close > max(c0.high, c1.high):
                direction = "long"
            else:
                return None
        # Two consecutive closes below VWAP → short bias
        elif c0.close < v and c1.close < v:
            if c2.close < min(c0.low, c1.low):
                direction = "short"
            else:
                return None
        else:
            return None

        wick_extreme = c2.low if direction == "long" else c2.high
        sl_price, sl_pips, skip = self.risk.calculate_sl(
            direction, wick_extreme, candles, c2.symbol
        )
        if skip:
            return None

        entry = c2.close
        tp1, tp2 = self.risk.calculate_tp(direction, entry, sl_price)
        atr = self.risk.atr(candles)

        signal = Signal(
            symbol=c2.symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=sl_price,
            take_profit_1=tp1,
            take_profit_2=tp2,
            timestamp=c2.timestamp,
            setup_type="vwap_breakout",
            timeframe=c2.timeframe,
            atr_at_entry=atr,
            metadata={
                "vwap": round(v, 4),
                "sl_pips": round(sl_pips, 1),
            },
        )
        logger.info(
            "signal_generator.vwap_breakout",
            symbol=c2.symbol,
            direction=direction,
            entry=round(entry, 4),
        )
        return signal

    # ================================================================== #
    # Combined scanner
    # ================================================================== #

    def scan(
        self,
        candles_by_tf: dict,   # {"1H": [...], "15m": [...], "5m": [...]}
        symbol: str,
    ) -> List[Signal]:
        """
        Run all four setups and return all generated signals.

        Parameters
        ----------
        candles_by_tf:
            A mapping of ``timeframe → list[Candle]`` (at least 15m and 5m).
        symbol:
            Asset symbol (used for logging).
        """
        signals: List[Signal] = []

        htf_candles = candles_by_tf.get("1H") or candles_by_tf.get("4H") or []
        ltf_candles = candles_by_tf.get("15m") or []
        m5_candles = candles_by_tf.get("5m") or []

        # Setup 1
        if htf_candles and ltf_candles:
            sig = self.ote_choch_signal(htf_candles, ltf_candles)
            if sig:
                signals.append(sig)

        # Setup 2 – SMMA on 15m or 1H
        for tf_key in ("15m", "30m", "1H"):
            ribbon_candles = candles_by_tf.get(tf_key) or []
            if ribbon_candles:
                sig = self.smma_ribbon_signal(ribbon_candles)
                if sig:
                    signals.append(sig)
                    break

        # Setup 3 – BB on 5m
        if m5_candles:
            sig = self.bb_reversion_signal(m5_candles)
            if sig:
                signals.append(sig)

        # Setup 4 – VWAP on 5m or 15m
        for tf_key in ("5m", "15m"):
            vwap_candles = candles_by_tf.get(tf_key) or []
            if vwap_candles:
                sig = self.vwap_breakout_signal(vwap_candles)
                if sig:
                    signals.append(sig)
                    break

        return signals

    # ================================================================== #
    # Private helpers
    # ================================================================== #

    @staticmethod
    def _detect_choch(
        candles: List[Candle],
        direction: str,
    ) -> Optional[Tuple[float, float, Candle]]:
        """
        Detect a Major CHoCH (Change of Character) after a liquidity sweep.

        For a bullish CHoCH: price breaks above the most recent swing high
        (strong displacement candle).
        For a bearish CHoCH: price breaks below the most recent swing low.

        Returns (choch_high, choch_low, trigger_candle) or None.
        """
        if len(candles) < 10:
            return None

        recent = candles[-30:]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]

        swing_high = max(highs[:-1])
        swing_low = min(lows[:-1])

        latest = recent[-1]
        if direction == "long" and latest.close > swing_high:
            return swing_high, swing_low, latest
        if direction == "short" and latest.close < swing_low:
            return swing_high, swing_low, latest
        return None

    @staticmethod
    def _ote_entry(
        direction: str,
        choch_high: float,
        choch_low: float,
        candle: Candle,
    ) -> Tuple[bool, float]:
        """
        Determine whether *candle* is in the OTE zone (0.618 – 0.786 Fib).

        Returns (in_ote, suggested_entry_price).
        """
        fib_range = choch_high - choch_low

        if direction == "long":
            ote_low_price = choch_high - fib_range * _OTE_HIGH
            ote_high_price = choch_high - fib_range * _OTE_LOW
            in_ote = ote_low_price <= candle.low <= ote_high_price
            entry = ote_low_price + (ote_high_price - ote_low_price) * 0.5
        else:
            ote_low_price = choch_low + fib_range * _OTE_LOW
            ote_high_price = choch_low + fib_range * _OTE_HIGH
            in_ote = ote_low_price <= candle.high <= ote_high_price
            entry = ote_low_price + (ote_high_price - ote_low_price) * 0.5

        return in_ote, entry


# ================================================================== #
# Indicator helpers
# ================================================================== #

def _smma(data: np.ndarray, period: int) -> np.ndarray:
    """Smoothed Moving Average (Wilder / RMA)."""
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
    result[period - 1] = data[:period].mean()
    alpha = 1.0 / period
    for i in range(period, len(data)):
        result[i] = result[i - 1] * (1 - alpha) + data[i] * alpha
    return result


def _bollinger(
    data: np.ndarray, period: int, num_std: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Standard Bollinger Bands."""
    mid = np.full(len(data), np.nan)
    upper = np.full(len(data), np.nan)
    lower = np.full(len(data), np.nan)
    for i in range(period - 1, len(data)):
        window = data[i - period + 1 : i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        mid[i] = m
        upper[i] = m + num_std * s
        lower[i] = m - num_std * s
    return mid, upper, lower


def _calc_vwap(candles: List[Candle]) -> Optional[float]:
    """
    Intraday VWAP (cumulative from the first candle of the session).

    Returns the current VWAP value, or None if volume data is missing.
    """
    total_vol = sum(c.volume for c in candles)
    if total_vol == 0:
        return None
    typical_price_vol = sum(
        ((c.high + c.low + c.close) / 3) * c.volume for c in candles
    )
    return typical_price_vol / total_vol
