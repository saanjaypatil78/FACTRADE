"""Advanced exit manager for FACTRADE.

Implements the Marco 80/20 Institutional Exit Rule and extensions:

Default exit logic
------------------
1. **TP1 (80 % partial book):** When price hits the first internal liquidity
   target, close 80 % of the position and lock the runner's SL to break-even.
2. **Static runner SL:** Entry + brokerage + 10 pips (direction-adjusted).
3. **TP2 (HTF runner):** The remaining 20 % rides toward HTF opposite liquidity.

Configurable extensions
-----------------------
- ``partial_pct``       : fraction to book at TP1 (default 0.80).
- ``breakeven_buffer``  : pips added to entry when moving SL to BE (default 10).
- ``trailing_stop``     : enable ATR-based trailing stop on the runner.
- ``trail_atr_mult``    : ATR multiplier for the trailing stop (default 1.5).
- ``max_hold_bars``     : time-stop — exit runner if still open after N bars.
- ``risk_adjust``       : enable risk-aware SL tightening after BE.

All parameters can be supplied via a dict so the same config is used in
both backtests and live monitoring, ensuring deterministic behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import pandas as pd
import structlog

from src.trading.execution.risk_manager import PositionSpec, RiskManager

logger = structlog.get_logger(__name__)


class ExitReason(Enum):
    TP1 = auto()
    TP2 = auto()
    SL_HIT = auto()
    BREAKEVEN = auto()
    TRAILING_STOP = auto()
    TIME_STOP = auto()
    MANUAL = auto()


@dataclass
class OpenTrade:
    """Tracks the live state of a single trade position."""

    spec: PositionSpec
    open_time: pd.Timestamp
    open_price: float
    full_lots: float

    # Mutable state
    remaining_lots: float = 0.0
    current_sl: float = 0.0
    tp1_hit: bool = False
    be_active: bool = False
    trailing_high: float = 0.0   # for long trailing: track best high
    trailing_low: float = float("inf")  # for short trailing: track best low
    bars_held: int = 0
    partial_exits: list[dict] = field(default_factory=list)
    closed: bool = False
    close_price: float = 0.0
    close_time: Optional[pd.Timestamp] = None
    close_reason: Optional[ExitReason] = None
    pnl: float = 0.0

    def __post_init__(self) -> None:
        if self.remaining_lots == 0.0:
            self.remaining_lots = self.full_lots
        if self.current_sl == 0.0:
            self.current_sl = self.spec.sl_price
        if self.spec.direction == "long":
            self.trailing_high = self.open_price
        else:
            self.trailing_low = self.open_price


@dataclass
class ExitConfig:
    """Deterministic configuration for the exit manager.

    Pass this same config to both the backtester and live monitor to ensure
    identical exit behaviour.
    """

    partial_pct: float = 0.80          # fraction closed at TP1
    breakeven_buffer_pips: float = 10.0  # pips above/below entry for BE SL
    trailing_stop: bool = False         # enable ATR trailing on runner
    trail_atr_mult: float = 1.5         # ATR × this = trailing distance
    max_hold_bars: int = 0              # 0 = disabled
    risk_adjust: bool = False           # tighten SL as profit grows
    brokerage_pips: float = 3.0         # brokerage cost in pips (for BE calc)
    pip_size: float = 0.01              # instrument pip size


class ExitManager:
    """Advanced exit manager with partial TP, BE, trailing stop, and runner.

    Parameters
    ----------
    config:
        ``ExitConfig`` instance.  If ``None``, defaults are used.
    risk_manager:
        Optional RiskManager reference for ATR calculation.
    """

    def __init__(
        self,
        config: Optional[ExitConfig] = None,
        risk_manager: Optional[RiskManager] = None,
    ) -> None:
        self.config = config or ExitConfig()
        self._rm = risk_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_trade(self, spec: PositionSpec, open_time: pd.Timestamp) -> OpenTrade:
        """Create and register an OpenTrade from a PositionSpec."""
        trade = OpenTrade(
            spec=spec,
            open_time=open_time,
            open_price=spec.entry_price,
            full_lots=spec.lot_size,
        )
        logger.info(
            "exit_manager.trade_opened",
            symbol=spec.symbol,
            direction=spec.direction,
            lots=spec.lot_size,
            entry=spec.entry_price,
            sl=spec.sl_price,
        )
        return trade

    def update(
        self,
        trade: OpenTrade,
        bar: pd.Series,
        atr: float = 0.0,
    ) -> Optional[dict]:
        """Process one new OHLCV bar against an open trade.

        Returns a dict describing an exit action (partial or full close), or
        ``None`` if no exit triggered.

        Parameters
        ----------
        trade:
            The current open position state (modified in place).
        bar:
            OHLCV bar (pd.Series with open/high/low/close and a timestamp name).
        atr:
            Current ATR value for trailing stop calculations.

        Returns
        -------
        dict | None
            ``{"action": "partial"|"full", "lots": float, "price": float,
               "reason": ExitReason}`` or ``None``.
        """
        if trade.closed:
            return None

        trade.bars_held += 1
        direction = trade.spec.direction
        cfg = self.config
        pip = cfg.pip_size

        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        ts = bar.name

        # ── Time stop ───────────────────────────────────────────────────
        # bars_held is incremented at the top of this method, so when
        # bars_held == max_hold_bars the *current* bar is the Nth bar held
        # (e.g. max_hold_bars=3 exits on the 3rd processed bar, inclusive).
        if cfg.max_hold_bars > 0 and trade.bars_held >= cfg.max_hold_bars:
            return self._close_trade(trade, close, ts, ExitReason.TIME_STOP)

        # ── SL check ────────────────────────────────────────────────────
        sl = trade.current_sl
        if direction == "long" and low <= sl:
            return self._close_trade(trade, sl, ts, ExitReason.SL_HIT)
        if direction == "short" and high >= sl:
            return self._close_trade(trade, sl, ts, ExitReason.SL_HIT)

        # ── TP1: partial profit-taking ───────────────────────────────────
        if not trade.tp1_hit:
            tp1 = trade.spec.tp1_price
            if (direction == "long" and high >= tp1) or (
                direction == "short" and low <= tp1
            ):
                partial_lots = round(trade.remaining_lots * cfg.partial_pct, 2)
                if partial_lots >= 0.01:
                    trade.remaining_lots = round(
                        trade.remaining_lots - partial_lots, 2
                    )
                    trade.tp1_hit = True
                    trade.partial_exits.append(
                        {"lots": partial_lots, "price": tp1, "reason": ExitReason.TP1, "ts": ts}
                    )
                    # Move SL to break-even
                    be_buffer = (cfg.breakeven_buffer_pips + cfg.brokerage_pips) * pip
                    if direction == "long":
                        trade.current_sl = trade.open_price + be_buffer
                    else:
                        trade.current_sl = trade.open_price - be_buffer
                    trade.be_active = True
                    logger.info(
                        "exit_manager.tp1_partial",
                        symbol=trade.spec.symbol,
                        lots_closed=partial_lots,
                        lots_remaining=trade.remaining_lots,
                        new_sl=round(trade.current_sl, 3),
                    )
                    return {
                        "action": "partial",
                        "lots": partial_lots,
                        "price": tp1,
                        "reason": ExitReason.TP1,
                        "new_sl": trade.current_sl,
                    }

        # ── TP2: runner full exit ────────────────────────────────────────
        tp2 = trade.spec.tp2_price
        if (direction == "long" and high >= tp2) or (
            direction == "short" and low <= tp2
        ):
            return self._close_trade(trade, tp2, ts, ExitReason.TP2)

        # ── Trailing stop (runner only, after TP1) ───────────────────────
        if cfg.trailing_stop and trade.tp1_hit and atr > 0:
            trail_dist = atr * cfg.trail_atr_mult
            if direction == "long":
                trade.trailing_high = max(trade.trailing_high, high)
                new_trail_sl = trade.trailing_high - trail_dist
                if new_trail_sl > trade.current_sl:
                    trade.current_sl = new_trail_sl
                    logger.debug(
                        "exit_manager.trailing_sl_updated",
                        new_sl=round(new_trail_sl, 3),
                    )
            else:
                trade.trailing_low = min(trade.trailing_low, low)
                new_trail_sl = trade.trailing_low + trail_dist
                if new_trail_sl < trade.current_sl:
                    trade.current_sl = new_trail_sl

        return None

    def force_close(
        self,
        trade: OpenTrade,
        price: float,
        ts: pd.Timestamp,
    ) -> dict:
        """Force-close a trade (e.g. news filter triggered)."""
        return self._close_trade(trade, price, ts, ExitReason.MANUAL)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _close_trade(
        self,
        trade: OpenTrade,
        exit_price: float,
        ts: pd.Timestamp,
        reason: ExitReason,
    ) -> dict:
        direction = trade.spec.direction
        lots = trade.remaining_lots
        pnl_pips = (
            (exit_price - trade.open_price) / self.config.pip_size
            if direction == "long"
            else (trade.open_price - exit_price) / self.config.pip_size
        )
        trade.pnl = pnl_pips
        trade.closed = True
        trade.close_price = exit_price
        trade.close_time = ts
        trade.close_reason = reason
        trade.remaining_lots = 0.0

        logger.info(
            "exit_manager.trade_closed",
            symbol=trade.spec.symbol,
            reason=reason.name,
            lots=lots,
            exit_price=exit_price,
            pnl_pips=round(pnl_pips, 1),
        )
        return {
            "action": "full",
            "lots": lots,
            "price": exit_price,
            "reason": reason,
            "pnl_pips": pnl_pips,
        }
