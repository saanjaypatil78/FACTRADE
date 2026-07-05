"""ATR-based risk manager for FACTRADE.

Rules implemented
-----------------
- SL = Wick Low/High ± (1.5 × ATR) ± spread buffer
- Risk per trade: 0.5 % (default), 1 % (A+ setups only)
- Max SL: configurable pip limit (default 50 pips; skip trade if exceeded)
- Position sizing: lots = risk_amount / (sl_pips × pip_value)
- Daily stop: -2R or -2 % (whichever hits first)
- Weekly stop: -5R hard lock

All calculations are deterministic given the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# Pip values per instrument per standard lot (approximate; always verify with broker)
_PIP_VALUE_PER_LOT: dict[str, float] = {
    "XAUUSD": 10.0,   # $10 per pip (0.01 move) per 0.1 lot → $1 per pip per 0.01 lot
    "USOIL": 10.0,    # $10 per pip ($0.01 move) per 0.1 lot
    "WTIUSD": 10.0,
}

# Pip size (minimum price increment that counts as 1 pip)
_PIP_SIZE: dict[str, float] = {
    "XAUUSD": 0.01,
    "USOIL": 0.01,
    "WTIUSD": 0.01,
}


@dataclass
class PositionSpec:
    """Output of the risk manager: everything needed to place or simulate a trade."""

    symbol: str
    direction: str          # "long" | "short"
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    lot_size: float
    sl_pips: float
    risk_amount: float      # in account currency ($)
    risk_pct: float         # e.g. 0.5 or 1.0
    atr: float
    valid: bool = True
    skip_reason: str = ""

    def __repr__(self) -> str:
        if not self.valid:
            return f"PositionSpec(SKIP: {self.skip_reason})"
        return (
            f"PositionSpec({self.symbol} {self.direction} "
            f"entry={self.entry_price:.2f} sl={self.sl_price:.2f} "
            f"tp1={self.tp1_price:.2f} lots={self.lot_size:.2f} "
            f"risk=${self.risk_amount:.2f})"
        )


class RiskManager:
    """Calculate position sizing and validate trade risk.

    Parameters
    ----------
    account_balance:
        Current account balance in USD.
    risk_pct:
        Default risk per trade as percentage (default 0.5).
    aplus_risk_pct:
        Risk for A+ setups (default 1.0).
    max_sl_pips:
        Maximum allowable SL in pips (default 50).  Trade is skipped if SL
        exceeds this.
    atr_multiplier:
        SL buffer = ATR × atr_multiplier beyond the wick (default 1.5).
    spread_pips:
        Broker spread in pips added to SL buffer (default 3).
    min_lot:
        Minimum lot size (default 0.01).
    max_lot:
        Maximum lot size (default 0.10 — safety cap).
    daily_stop_r:
        Daily drawdown hard limit in R multiples (default -2).
    weekly_stop_r:
        Weekly drawdown hard limit in R multiples (default -5).
    """

    def __init__(
        self,
        account_balance: float = 1400.0,
        risk_pct: float = 0.5,
        aplus_risk_pct: float = 1.0,
        max_sl_pips: float = 50.0,
        atr_multiplier: float = 1.5,
        spread_pips: float = 3.0,
        min_lot: float = 0.01,
        max_lot: float = 0.10,
        daily_stop_r: float = -2.0,
        weekly_stop_r: float = -5.0,
    ) -> None:
        self.account_balance = account_balance
        self.risk_pct = risk_pct
        self.aplus_risk_pct = aplus_risk_pct
        self.max_sl_pips = max_sl_pips
        self.atr_multiplier = atr_multiplier
        self.spread_pips = spread_pips
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.daily_stop_r = daily_stop_r
        self.weekly_stop_r = weekly_stop_r

        # Session tracking
        self._daily_r_used: float = 0.0
        self._weekly_r_used: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        wick_price: float,      # swing wick low (long) or high (short)
        tp1_price: float,
        tp2_price: float,
        atr: float,
        is_aplus: bool = False,
        df: Optional[pd.DataFrame] = None,
    ) -> PositionSpec:
        """Compute a PositionSpec for a proposed trade.

        Parameters
        ----------
        symbol:
            Instrument, e.g. ``"XAUUSD"``.
        direction:
            ``"long"`` or ``"short"``.
        entry_price:
            Proposed entry.
        wick_price:
            Extreme wick that defines the raw SL anchor.
        tp1_price:
            First profit target.
        tp2_price:
            HTF runner profit target.
        atr:
            Current ATR value (same timeframe as entry).
        is_aplus:
            If True, use ``aplus_risk_pct`` instead of ``risk_pct``.
        df:
            Optional source OHLCV DataFrame (used for ATR if ``atr`` is 0).
        """
        if atr <= 0 and df is not None:
            atr = self._compute_atr(df)

        pip_size = _PIP_SIZE.get(symbol.upper(), 0.01)
        pip_val = _PIP_VALUE_PER_LOT.get(symbol.upper(), 10.0)

        # SL with ATR buffer
        if direction == "long":
            sl = wick_price - (self.atr_multiplier * atr) - (self.spread_pips * pip_size)
        else:
            sl = wick_price + (self.atr_multiplier * atr) + (self.spread_pips * pip_size)

        sl_pips = abs(entry_price - sl) / pip_size
        risk_pct = self.aplus_risk_pct if is_aplus else self.risk_pct
        risk_amount = self.account_balance * (risk_pct / 100.0)

        # Validate SL size
        if sl_pips > self.max_sl_pips:
            logger.warning(
                "risk_manager.sl_too_large",
                sl_pips=round(sl_pips, 1),
                max_sl_pips=self.max_sl_pips,
                symbol=symbol,
            )
            return PositionSpec(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                sl_price=sl,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                lot_size=0.0,
                sl_pips=sl_pips,
                risk_amount=risk_amount,
                risk_pct=risk_pct,
                atr=atr,
                valid=False,
                skip_reason=f"SL {sl_pips:.1f} pips exceeds max {self.max_sl_pips} pips",
            )

        # Position sizing: risk_amount = lots × sl_pips × pip_val_per_lot
        # pip_val_per_lot is for 1 standard lot (1.0)
        if sl_pips < 0.01:
            # SL is effectively at entry — trade is structurally invalid
            return PositionSpec(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                sl_price=sl,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                lot_size=0.0,
                sl_pips=sl_pips,
                risk_amount=risk_amount,
                risk_pct=risk_pct,
                atr=atr,
                valid=False,
                skip_reason="SL pips too small (< 0.01) — entry and SL are at the same price",
            )
        raw_lots = risk_amount / (sl_pips * pip_val)
        lot_size = max(self.min_lot, min(self.max_lot, round(raw_lots, 2)))

        # Session risk check
        if not self._session_allows_trade(risk_amount):
            return PositionSpec(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                sl_price=sl,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                lot_size=0.0,
                sl_pips=sl_pips,
                risk_amount=risk_amount,
                risk_pct=risk_pct,
                atr=atr,
                valid=False,
                skip_reason="Daily or weekly drawdown limit reached",
            )

        spec = PositionSpec(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            lot_size=lot_size,
            sl_pips=sl_pips,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
            atr=atr,
            valid=True,
        )
        logger.info(
            "risk_manager.spec",
            symbol=symbol,
            direction=direction,
            lots=lot_size,
            sl_pips=round(sl_pips, 1),
            risk_usd=round(risk_amount, 2),
        )
        return spec

    def record_trade_result(self, result_r: float) -> None:
        """Record a trade result in R multiples for session tracking."""
        self._daily_r_used += result_r
        self._weekly_r_used += result_r

    def reset_daily(self) -> None:
        """Reset daily R tracker (call at session start)."""
        self._daily_r_used = 0.0

    def reset_weekly(self) -> None:
        """Reset weekly R tracker."""
        self._weekly_r_used = 0.0

    def session_status(self) -> dict:
        """Return current session risk consumption."""
        return {
            "daily_r_used": self._daily_r_used,
            "weekly_r_used": self._weekly_r_used,
            "daily_stop": self.daily_stop_r,
            "weekly_stop": self.weekly_stop_r,
            "daily_ok": self._daily_r_used > self.daily_stop_r,
            "weekly_ok": self._weekly_r_used > self.weekly_stop_r,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _session_allows_trade(self, risk_amount: float) -> bool:
        """Return False if daily or weekly stop has been hit."""
        if self._daily_r_used <= self.daily_stop_r:
            logger.warning("risk_manager.daily_stop_hit", r=self._daily_r_used)
            return False
        if self._weekly_r_used <= self.weekly_stop_r:
            logger.warning("risk_manager.weekly_stop_hit", r=self._weekly_r_used)
            return False
        return True

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Compute ATR from OHLCV DataFrame."""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        tr = pd.concat(
            [high - low, (high - close).abs(), (low - close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if pd.notna(atr) else float((high - low).mean())
