"""
Risk Manager – ATR-based stop-loss and take-profit calculation.

Rules (from the FACTRADE Masterplan v7.0)
------------------------------------------
* SL = Wick extreme ± (1.5 × ATR) ± broker_spread
* Per-trade risk: 0.5 % default, 1 % for A+ setups.
* Maximum SL distance: 50 pips (configurable). Skip trade if exceeded.
* TP1 (80 % close): first 15m internal liquidity level.
* TP2 (20 % runner): HTF opposing liquidity.
* Lot size derived from account_balance × risk_pct ÷ sl_distance_in_dollars.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import structlog

from src.trading.candle import Candle

logger = structlog.get_logger(__name__)

# Instrument-specific pip values (USD per pip per 0.01 lot)
# For reporting purposes; live sizing must use broker contract specs.
_PIP_VALUE: dict = {
    "XAUUSD": 0.01,   # 1 pip = $0.01 in XAUUSD for 0.01 lot (100 oz × $0.01 × 0.01 lot)
    "USOIL":  0.10,   # 1 pip = $0.10 for 0.01 lot crude (1000 bbl × $0.01 × 0.01)
    "WTI":    0.10,
    "GC=F":   0.01,
    "CL=F":   0.10,
}
_DEFAULT_PIP_VALUE = 0.01

# Pip sizes (minimum price movement used to convert dollar distance → pips)
_PIP_SIZE: dict = {
    "XAUUSD": 0.01,
    "USOIL": 0.01,
    "WTI": 0.01,
    "GC=F": 0.10,
    "CL=F": 0.01,
}
_DEFAULT_PIP_SIZE = 0.01


class RiskManager:
    """
    Compute ATR, stop-loss, and take-profit levels.

    Parameters
    ----------
    atr_period:
        Number of bars for the ATR calculation (default 14).
    atr_multiplier:
        Multiplier applied to ATR to set the SL buffer (default 1.5).
    max_sl_pips:
        Hard cap on stop-loss distance in pips.  Signals exceeding this
        distance are marked as *skip* (default 50).
    default_risk_pct:
        Fraction of account balance to risk per trade (default 0.5 %).
    spread_pips:
        Typical broker spread added to SL buffer (default 2 pips).
    """

    def __init__(
        self,
        atr_period: int = 14,
        atr_multiplier: float = 1.5,
        max_sl_pips: int = 50,
        default_risk_pct: float = 0.005,
        spread_pips: float = 2.0,
    ) -> None:
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.max_sl_pips = max_sl_pips
        self.default_risk_pct = default_risk_pct
        self.spread_pips = spread_pips

    # ------------------------------------------------------------------ #
    # ATR
    # ------------------------------------------------------------------ #

    def atr(self, candles: List[Candle]) -> float:
        """
        Wilder's ATR over *atr_period* bars.

        Returns 0.0 if there are not enough candles.
        """
        if len(candles) < self.atr_period + 1:
            return 0.0

        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        closes = np.array([c.close for c in candles])

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        # Wilder smoothing (RMA)
        atr_vals = np.empty(len(tr))
        atr_vals[: self.atr_period - 1] = np.nan
        atr_vals[self.atr_period - 1] = tr[: self.atr_period].mean()
        alpha = 1.0 / self.atr_period
        for i in range(self.atr_period, len(tr)):
            atr_vals[i] = atr_vals[i - 1] * (1 - alpha) + tr[i] * alpha

        return float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0

    # ------------------------------------------------------------------ #
    # SL / TP calculation
    # ------------------------------------------------------------------ #

    def calculate_sl(
        self,
        direction: str,
        wick_extreme: float,
        candles: List[Candle],
        symbol: str = "XAUUSD",
    ) -> Tuple[float, float, bool]:
        """
        Compute the stop-loss price and its distance in pips.

        Parameters
        ----------
        direction:
            ``"long"`` or ``"short"``.
        wick_extreme:
            The candle's wick low (long) or wick high (short) – the raw SL
            anchor before the ATR buffer.
        candles:
            Recent candles used for ATR calculation.
        symbol:
            Used to derive pip size and value.

        Returns
        -------
        sl_price, sl_pips, skip
            ``skip`` is ``True`` when the SL distance exceeds *max_sl_pips*.
        """
        atr_value = self.atr(candles)
        pip_size = _PIP_SIZE.get(symbol.upper(), _DEFAULT_PIP_SIZE)
        spread = self.spread_pips * pip_size

        buffer = self.atr_multiplier * atr_value + spread

        if direction == "long":
            sl_price = wick_extreme - buffer
        else:
            sl_price = wick_extreme + buffer

        sl_pips = abs(wick_extreme - sl_price) / pip_size
        skip = sl_pips > self.max_sl_pips

        if skip:
            logger.debug(
                "risk_manager.sl_skip",
                symbol=symbol,
                sl_pips=round(sl_pips, 1),
                max_sl_pips=self.max_sl_pips,
            )

        return sl_price, sl_pips, skip

    def calculate_tp(
        self,
        direction: str,
        entry_price: float,
        sl_price: float,
        rr_tp1: float = 2.0,
        rr_tp2: float = 5.0,
    ) -> Tuple[float, float]:
        """
        Compute TP1 (80 % close) and TP2 (runner) prices from a fixed R:R.

        TP1 default: 2× R (first internal liquidity)
        TP2 default: 5× R (HTF opposing liquidity)
        """
        sl_dist = abs(entry_price - sl_price)
        if direction == "long":
            tp1 = entry_price + sl_dist * rr_tp1
            tp2 = entry_price + sl_dist * rr_tp2
        else:
            tp1 = entry_price - sl_dist * rr_tp1
            tp2 = entry_price - sl_dist * rr_tp2
        return tp1, tp2

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    def lot_size(
        self,
        account_balance: float,
        sl_pips: float,
        symbol: str = "XAUUSD",
        risk_pct: Optional[float] = None,
    ) -> float:
        """
        Return the recommended lot size (rounded to 0.01) for the given
        account balance and SL distance.

        This is a **guide** – always verify against your broker's contract
        spec before executing.
        """
        rp = risk_pct if risk_pct is not None else self.default_risk_pct
        risk_dollars = account_balance * rp
        pip_val = _PIP_VALUE.get(symbol.upper(), _DEFAULT_PIP_VALUE)

        if sl_pips == 0 or pip_val == 0:
            return 0.01

        lot = risk_dollars / (sl_pips * pip_val * 100)  # pip_val is per 0.01 lot
        lot = max(0.01, round(lot, 2))
        return lot
