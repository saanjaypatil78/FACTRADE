"""
Trade Executor – signal-only / paper-trade mode.

By default **no live orders are placed**.  Every signal is logged, stored in
memory, and optionally written to a JSON file.  This keeps the system safe
when connected to free data sources whose real-time accuracy is imperfect.

To integrate real broker execution, subclass :class:`TradeExecutor` and
override :meth:`_place_order`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.trading.risk_manager import _PIP_VALUE, _PIP_SIZE, _DEFAULT_PIP_VALUE, _DEFAULT_PIP_SIZE

from src.trading.candle import Signal, TradeResult

logger = structlog.get_logger(__name__)


class TradeExecutor:
    """
    Paper-trade executor that records signals without placing real orders.

    Parameters
    ----------
    paper_trade:
        When ``True`` (default) all signals are simulated; no real order
        is ever placed.
    journal_file:
        Optional path to a JSON file where signals and results are appended.
    account_balance:
        Starting balance for P&L tracking (USD).
    """

    def __init__(
        self,
        paper_trade: bool = True,
        journal_file: Optional[str] = None,
        account_balance: float = 700.0,
    ) -> None:
        self.paper_trade = paper_trade
        self.journal_file = Path(journal_file) if journal_file else None
        self.account_balance = account_balance

        self._open_positions: Dict[str, Signal] = {}   # signal_id → Signal
        self._closed_trades: List[TradeResult] = []
        self._signal_counter = 0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def execute(self, signal: Signal) -> str:
        """
        Accept a signal and paper-execute it.

        Returns a *position_id* string.
        """
        self._signal_counter += 1
        pos_id = f"{signal.symbol}_{signal.setup_type}_{self._signal_counter}"

        logger.info(
            "trade_executor.signal_received",
            pos_id=pos_id,
            symbol=signal.symbol,
            direction=signal.direction,
            setup=signal.setup_type,
            entry=round(signal.entry_price, 4),
            sl=round(signal.stop_loss, 4),
            tp1=round(signal.take_profit_1, 4),
            tp2=round(signal.take_profit_2, 4),
            rr=round(signal.risk_reward, 2),
            paper=self.paper_trade,
        )

        if self.paper_trade:
            self._open_positions[pos_id] = signal
        else:
            self._place_order(pos_id, signal)

        self._append_journal({"event": "open", "pos_id": pos_id, "signal": _signal_to_dict(signal)})
        return pos_id

    def close(
        self,
        pos_id: str,
        exit_price: float,
        exit_time: Optional[datetime] = None,
        reason: str = "manual",
    ) -> Optional[TradeResult]:
        """Close an open position and record the result."""
        signal = self._open_positions.pop(pos_id, None)
        if signal is None:
            logger.warning("trade_executor.pos_not_found", pos_id=pos_id)
            return None

        ts = exit_time or datetime.now(tz=timezone.utc)
        pnl_pips = self._pips(signal, exit_price)
        # P&L in USD at 0.01-lot baseline using the instrument's pip value
        pip_val = _PIP_VALUE.get(signal.symbol.upper(), _DEFAULT_PIP_VALUE)
        pnl_usd = pnl_pips * pip_val

        result = TradeResult(
            signal=signal,
            exit_price=exit_price,
            exit_time=ts,
            exit_reason=reason,  # type: ignore[arg-type]
            pnl_pips=pnl_pips,
            pnl_dollars=pnl_usd,
        )
        self._closed_trades.append(result)

        logger.info(
            "trade_executor.position_closed",
            pos_id=pos_id,
            exit_price=round(exit_price, 4),
            reason=reason,
            pnl_pips=round(pnl_pips, 1),
            pnl_usd=round(pnl_usd, 2),
        )
        self._append_journal({
            "event": "close",
            "pos_id": pos_id,
            "exit_price": exit_price,
            "reason": reason,
            "pnl_pips": round(pnl_pips, 1),
        })
        return result

    def update(self, candle) -> List[TradeResult]:
        """
        Check open positions against a new candle and trigger SL / TP1.

        Returns any results that were closed on this candle.
        """
        closed: List[TradeResult] = []
        for pos_id, signal in list(self._open_positions.items()):
            result = self._check_exits(pos_id, signal, candle)
            if result:
                closed.append(result)
        return closed

    @property
    def open_positions(self) -> Dict[str, Signal]:
        return dict(self._open_positions)

    @property
    def closed_trades(self) -> List[TradeResult]:
        return list(self._closed_trades)

    def summary(self) -> dict:
        trades = self._closed_trades
        if not trades:
            return {"total": 0}
        wins = [t for t in trades if t.is_win]
        return {
            "total": len(trades),
            "wins": len(wins),
            "losses": len(trades) - len(wins),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "total_pips": round(sum(t.pnl_pips for t in trades), 1),
            "avg_pips": round(sum(t.pnl_pips for t in trades) / len(trades), 1),
        }

    # ------------------------------------------------------------------ #
    # Overridable for live execution
    # ------------------------------------------------------------------ #

    def _place_order(self, pos_id: str, signal: Signal) -> None:  # pragma: no cover
        """Override this method to connect a real broker API."""
        raise NotImplementedError(
            "Live order placement is not implemented.  "
            "Use paper_trade=True (default) or subclass TradeExecutor."
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _check_exits(self, pos_id: str, signal: Signal, candle) -> Optional[TradeResult]:
        if signal.direction == "long":
            if candle.low <= signal.stop_loss:
                return self.close(pos_id, signal.stop_loss, candle.timestamp, "sl")
            if candle.high >= signal.take_profit_1:
                return self.close(pos_id, signal.take_profit_1, candle.timestamp, "tp1")
        else:
            if candle.high >= signal.stop_loss:
                return self.close(pos_id, signal.stop_loss, candle.timestamp, "sl")
            if candle.low <= signal.take_profit_1:
                return self.close(pos_id, signal.take_profit_1, candle.timestamp, "tp1")
        return None

    @staticmethod
    def _pips(signal: Signal, exit_price: float) -> float:
        pip_size = _PIP_SIZE.get(signal.symbol.upper(), _DEFAULT_PIP_SIZE)
        if signal.direction == "long":
            return (exit_price - signal.entry_price) / pip_size
        return (signal.entry_price - exit_price) / pip_size

    def _append_journal(self, entry: dict) -> None:
        if not self.journal_file:
            return
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)
        entry["ts"] = datetime.now(tz=timezone.utc).isoformat()
        with self.journal_file.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")


def _signal_to_dict(s: Signal) -> dict:
    return {
        "symbol": s.symbol,
        "direction": s.direction,
        "entry": s.entry_price,
        "sl": s.stop_loss,
        "tp1": s.take_profit_1,
        "tp2": s.take_profit_2,
        "setup": s.setup_type,
        "timeframe": s.timeframe,
        "rr": round(s.risk_reward, 2),
        "timestamp": s.timestamp.isoformat(),
    }
