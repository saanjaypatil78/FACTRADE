"""Paper / signal trade executor for FACTRADE.

Default mode: paper trading (no real orders placed).
Signals are logged and optionally written to a signals file.

Modes
-----
- ``paper``  : simulate fills at signal price, track virtual P&L.
- ``signal`` : emit signal only (no fill simulation).

Both modes write a structured signal log in JSON-Lines format so that
results can be replayed or audited.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import structlog

from src.trading.analysis.signal_generator import TradeSignal
from src.trading.execution.exit_manager import ExitConfig, ExitManager, OpenTrade
from src.trading.execution.risk_manager import PositionSpec, RiskManager

logger = structlog.get_logger(__name__)


class TradeExecutor:
    """Paper/signal executor.

    Parameters
    ----------
    mode:
        ``"paper"`` or ``"signal"`` (default ``"paper"``).
    signal_log_path:
        Path for JSON-Lines signal log (default ``"data/signals.jsonl"``).
    risk_manager:
        RiskManager instance for position sizing.
    exit_config:
        ExitConfig for the exit manager.
    """

    def __init__(
        self,
        mode: str = "paper",
        signal_log_path: str = "data/signals.jsonl",
        risk_manager: Optional[RiskManager] = None,
        exit_config: Optional[ExitConfig] = None,
    ) -> None:
        if mode not in ("paper", "signal"):
            raise ValueError(f"mode must be 'paper' or 'signal', got {mode!r}")
        self.mode = mode
        self._log_path = Path(signal_log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._rm = risk_manager or RiskManager()
        self._exit_mgr = ExitManager(config=exit_config, risk_manager=self._rm)
        self._open_trades: list[OpenTrade] = []
        self._closed_trades: list[OpenTrade] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        signal: TradeSignal,
        atr: float = 0.0,
        df: Optional[pd.DataFrame] = None,
    ) -> Optional[PositionSpec]:
        """Process a TradeSignal.

        For *paper* mode: compute position spec and record a simulated fill.
        For *signal* mode: log and return the spec without fill.

        Returns the PositionSpec (or None if the trade was skipped).
        """
        spec = self._rm.calculate(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            wick_price=signal.sl_price,
            tp1_price=signal.tp1_price,
            tp2_price=signal.tp2_price,
            atr=atr,
            is_aplus=(signal.confidence >= 0.8),
            df=df,
        )

        self._log_signal(signal, spec)

        if not spec.valid:
            logger.info("executor.signal_skipped", reason=spec.skip_reason)
            return None

        if self.mode == "paper":
            trade = self._exit_mgr.open_trade(spec, open_time=signal.signal_time)
            self._open_trades.append(trade)
            logger.info(
                "executor.paper_fill",
                symbol=spec.symbol,
                direction=spec.direction,
                lots=spec.lot_size,
                entry=spec.entry_price,
            )

        return spec

    def process_bar(self, bar: pd.Series, atr: float = 0.0) -> list[dict]:
        """Update all open paper trades with a new OHLCV bar.

        Parameters
        ----------
        bar:
            Latest OHLCV bar.
        atr:
            Current ATR value.

        Returns
        -------
        list[dict]
            Exit actions triggered during this bar.
        """
        if self.mode != "paper":
            return []

        actions = []
        still_open = []
        for trade in self._open_trades:
            action = self._exit_mgr.update(trade, bar, atr=atr)
            if action:
                actions.append(action)
            if trade.closed:
                self._closed_trades.append(trade)
            else:
                still_open.append(trade)
        self._open_trades = still_open
        return actions

    def get_open_trades(self) -> list[OpenTrade]:
        return list(self._open_trades)

    def get_closed_trades(self) -> list[OpenTrade]:
        return list(self._closed_trades)

    def get_pnl_summary(self) -> dict:
        """Summarise P&L from closed paper trades."""
        if not self._closed_trades:
            return {"trades": 0, "total_pnl_pips": 0.0, "wins": 0, "losses": 0}
        pnls = [t.pnl for t in self._closed_trades]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        return {
            "trades": len(pnls),
            "total_pnl_pips": round(sum(pnls), 1),
            "avg_pnl_pips": round(sum(pnls) / len(pnls), 1),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(pnls), 3),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _log_signal(self, signal: TradeSignal, spec: PositionSpec) -> None:
        """Write signal + spec to JSON-Lines log."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.symbol,
            "direction": signal.direction,
            "signal_time": signal.signal_time.isoformat() if signal.signal_time else None,
            "entry": signal.entry_price,
            "sl": spec.sl_price,
            "tp1": spec.tp1_price,
            "tp2": spec.tp2_price,
            "lots": spec.lot_size,
            "risk_usd": spec.risk_amount,
            "valid": spec.valid,
            "skip_reason": spec.skip_reason,
            "confidence": signal.confidence,
            "regime": signal.regime,
            "mode": self.mode,
        }
        with self._log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
