"""
Risk Manager — position sizing, SL/TP validation, and session-level caps.

Rules implemented (from FACTRADE Masterplan):
  - Fixed % equity risk per trade (default 1 %, max 2 %).
  - ATR + spread buffer on stop-loss (1.5 × ATR already baked into signal).
  - Skip trade if SL distance > max_sl_pips (50 by default).
  - Daily loss cap: stop trading for the day after -2 % equity drawdown.
  - Max concurrent open trades (default 2).
  - Min risk/reward ratio check (default 1.5).

Position sizing formula (forex / CFD):
    risk_amount   = equity × risk_pct / 100
    lot_size      = risk_amount / (sl_distance × pip_value)

where pip_value is instrument-specific (provided via config or overrides).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

@dataclass
class TradeParameters:
    """Fully resolved trade parameters after risk checks."""
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    lot_size: float
    risk_amount: float        # in account currency
    risk_pct: float           # as a percentage of equity
    sl_distance: float        # in price units
    rr_ratio: float
    approved: bool = True
    rejection_reason: str = ""


@dataclass
class DailyStats:
    """Tracks intraday PnL and trade counts."""
    date: date = field(default_factory=date.today)
    realized_pnl: float = 0.0
    open_trades: int = 0
    total_trades: int = 0

    def reset_if_new_day(self) -> None:
        today = date.today()
        if self.date != today:
            self.date = today
            self.realized_pnl = 0.0
            self.open_trades = 0
            self.total_trades = 0


# ---------------------------------------------------------------------------
# Risk Manager
# ---------------------------------------------------------------------------

class RiskManager:
    """
    Validates trade signals and computes safe position parameters.

    Parameters
    ----------
    equity : float
        Current account equity in account currency (e.g. USD).
    risk_pct : float
        Default risk per trade as a percentage of equity (default 1.0).
    max_risk_pct : float
        Hard cap on risk per trade (default 2.0).
    max_sl_pips : float
        Skip trade if computed SL distance (in price units) exceeds this.
    max_daily_loss_pct : float
        Halt new trades for the day if daily loss exceeds this % (default 2.0).
    max_concurrent_trades : int
        Maximum number of simultaneously open positions (default 2).
    min_rr_ratio : float
        Minimum risk/reward ratio required to approve a trade (default 1.5).
    pip_values : dict
        Maps symbol → pip value per 0.01 lot in account currency.
        Used for lot-size calculation.  Example: {"XAUUSD": 1.0, "WTIUSD": 10.0}.
    """

    DEFAULT_PIP_VALUES: Dict[str, float] = {
        "XAUUSD": 1.0,    # $1 per pip per 0.01 lot (1 lot = 100 oz)
        "WTIUSD": 1.0,    # $1 per $1 move per 0.01 lot
        "XTIUSD": 1.0,
    }

    def __init__(
        self,
        equity: float,
        risk_pct: float = 1.0,
        max_risk_pct: float = 2.0,
        max_sl_pips: float = 50.0,
        max_daily_loss_pct: float = 2.0,
        max_concurrent_trades: int = 2,
        min_rr_ratio: float = 1.5,
        pip_values: Optional[Dict[str, float]] = None,
    ) -> None:
        self.equity = equity
        self.risk_pct = min(risk_pct, max_risk_pct)
        self.max_risk_pct = max_risk_pct
        self.max_sl_pips = max_sl_pips
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_concurrent_trades = max_concurrent_trades
        self.min_rr_ratio = min_rr_ratio
        self.pip_values: Dict[str, float] = {
            **self.DEFAULT_PIP_VALUES,
            **(pip_values or {}),
        }
        self._daily_stats = DailyStats()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        entry: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        rr_ratio: float,
        atr_value: Optional[float] = None,
    ) -> TradeParameters:
        """
        Check all risk rules and return fully-resolved TradeParameters.

        If any rule is violated the returned object has approved=False and a
        human-readable rejection_reason.
        """
        self._daily_stats.reset_if_new_day()

        sl_distance = abs(entry - stop_loss)
        reward_distance = abs(take_profit_1 - entry)
        actual_rr = (reward_distance / sl_distance) if sl_distance > 0 else 0.0

        params = TradeParameters(
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            lot_size=0.0,
            risk_amount=0.0,
            risk_pct=self.risk_pct,
            sl_distance=sl_distance,
            rr_ratio=round(actual_rr, 2),
        )

        # --- Gate 1: Daily loss cap ---
        if self._daily_loss_exceeded():
            return self._reject(
                params,
                f"Daily loss cap reached ({self.max_daily_loss_pct}% equity). "
                "No new trades until tomorrow.",
            )

        # --- Gate 2: Max concurrent trades ---
        if self._daily_stats.open_trades >= self.max_concurrent_trades:
            return self._reject(
                params,
                f"Max concurrent trades ({self.max_concurrent_trades}) already open.",
            )

        # --- Gate 3: SL distance check ---
        if sl_distance > self.max_sl_pips:
            return self._reject(
                params,
                f"SL distance {sl_distance:.2f} exceeds max_sl_pips {self.max_sl_pips}. "
                "Trade skipped.",
            )

        # --- Gate 4: RR ratio ---
        if actual_rr < self.min_rr_ratio:
            return self._reject(
                params,
                f"RR ratio {actual_rr:.2f} below minimum {self.min_rr_ratio}.",
            )

        # --- Compute position size ---
        lot_size = self._calculate_lot_size(symbol, sl_distance)
        risk_amount = self.equity * self.risk_pct / 100.0

        params.lot_size = lot_size
        params.risk_amount = round(risk_amount, 2)
        params.approved = True

        logger.info(
            "trade_approved",
            symbol=symbol,
            entry=entry,
            sl=stop_loss,
            lot_size=lot_size,
            risk_usd=risk_amount,
            rr=actual_rr,
        )
        return params

    def record_trade_open(self) -> None:
        """Call when a new trade is opened."""
        self._daily_stats.open_trades += 1
        self._daily_stats.total_trades += 1

    def record_trade_close(self, pnl: float) -> None:
        """Call when a trade is closed; *pnl* in account currency."""
        self._daily_stats.open_trades = max(0, self._daily_stats.open_trades - 1)
        self._daily_stats.realized_pnl += pnl
        logger.info(
            "trade_closed",
            pnl=pnl,
            daily_pnl=self._daily_stats.realized_pnl,
        )

    def update_equity(self, new_equity: float) -> None:
        """Update the current account equity (call after each PnL change)."""
        self.equity = new_equity

    @property
    def daily_stats(self) -> DailyStats:
        self._daily_stats.reset_if_new_day()
        return self._daily_stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _daily_loss_exceeded(self) -> bool:
        max_loss = self.equity * self.max_daily_loss_pct / 100.0
        return self._daily_stats.realized_pnl < -max_loss

    def _calculate_lot_size(self, symbol: str, sl_distance: float) -> float:
        """
        lot_size = risk_amount / (sl_distance × pip_value_per_0.01_lot / 0.01)

        We round down to the nearest 0.01 lot to avoid over-risking.
        """
        risk_amount = self.equity * self.risk_pct / 100.0
        pip_value_per_lot = self.pip_values.get(symbol.upper(), 1.0)

        if sl_distance <= 0 or pip_value_per_lot <= 0:
            return 0.01

        raw_lots = risk_amount / (sl_distance * pip_value_per_lot)
        # Round down to 2 decimal places (minimum 0.01 lot)
        lot_size = max(0.01, round(int(raw_lots * 100) / 100, 2))
        return lot_size

    @staticmethod
    def _reject(params: TradeParameters, reason: str) -> TradeParameters:
        params.approved = False
        params.rejection_reason = reason
        logger.warning("trade_rejected", reason=reason)
        return params
