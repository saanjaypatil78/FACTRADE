"""
Live Monitor – continuous free-data monitoring loop.

Runs one infinite loop per symbol, fetches the latest candles from the
configured adapter at the configured polling interval, and passes each new
candle through the signal generator.  All signals are paper-traded by
default (no real orders are ever placed unless you subclass
:class:`~src.trading.trade_executor.TradeExecutor`).

Usage (CLI – see ``main_trading.py``)::

    python main_trading.py monitor --symbols XAUUSD USOIL --timeframes 1H 15m 5m

Or programmatically::

    from src.trading.adapters.yfinance_adapter import YFinanceAdapter
    from src.trading.monitor import LiveMonitor

    monitor = LiveMonitor(adapter=YFinanceAdapter())
    monitor.run(symbols=["XAUUSD", "USOIL"], timeframes=["1H", "15m", "5m"])
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from src.trading.adapters.base import BaseAdapter
from src.trading.candle import Candle, Signal
from src.trading.signal_generator import SignalGenerator
from src.trading.trade_executor import TradeExecutor
from src.trading.risk_manager import RiskManager

logger = structlog.get_logger(__name__)

# Default polling interval (seconds) between candle refreshes
_DEFAULT_POLL_INTERVAL = 60  # 1 minute


class LiveMonitor:
    """
    Continuous live-monitoring loop.

    Parameters
    ----------
    adapter:
        A data adapter (e.g. :class:`YFinanceAdapter` or
        :class:`CSVAdapter`) used to fetch the latest candles.
    poll_interval:
        Seconds between data refreshes (default 60 s).
    candle_limit:
        Maximum number of candles fetched per timeframe per refresh.
    executor:
        Optional pre-configured :class:`TradeExecutor`.  If ``None`` a
        default paper-trade executor is created.
    signal_callback:
        Optional callable invoked with each new :class:`Signal`.
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        poll_interval: int = _DEFAULT_POLL_INTERVAL,
        candle_limit: int = 500,
        executor: Optional[TradeExecutor] = None,
        signal_callback=None,
        risk_manager: Optional[RiskManager] = None,
    ) -> None:
        self.adapter = adapter
        self.poll_interval = poll_interval
        self.candle_limit = candle_limit
        self.executor = executor or TradeExecutor(paper_trade=True)
        self.signal_callback = signal_callback
        self.sig_gen = SignalGenerator(risk_manager=risk_manager)
        self._running = False

        # Track last-seen candle timestamp per (symbol, timeframe) to
        # avoid re-processing the same candle twice.
        self._last_seen: Dict[tuple, datetime] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run(
        self,
        symbols: List[str],
        timeframes: List[str],
        max_iterations: Optional[int] = None,
    ) -> None:
        """
        Start the monitoring loop.

        Parameters
        ----------
        symbols:
            List of symbols to monitor (e.g. ``["XAUUSD", "USOIL"]``).
        timeframes:
            Timeframes to fetch per symbol (e.g. ``["1H", "15m", "5m"]``).
        max_iterations:
            Stop after *n* poll cycles (useful for testing; ``None`` = run
            forever until interrupted).
        """
        self._running = True
        iteration = 0

        logger.info(
            "monitor.start",
            symbols=symbols,
            timeframes=timeframes,
            adapter=self.adapter.name,
            poll_interval=self.poll_interval,
            paper_trade=self.executor.paper_trade,
        )

        try:
            while self._running:
                if max_iterations is not None and iteration >= max_iterations:
                    break

                self._poll_cycle(symbols, timeframes)
                iteration += 1

                if max_iterations is None or iteration < max_iterations:
                    logger.debug(
                        "monitor.sleep",
                        seconds=self.poll_interval,
                        iteration=iteration,
                    )
                    time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("monitor.interrupted")
        finally:
            self._running = False
            self._log_summary()

    def stop(self) -> None:
        """Signal the monitoring loop to stop after the current cycle."""
        self._running = False

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _poll_cycle(self, symbols: List[str], timeframes: List[str]) -> None:
        for symbol in symbols:
            candles_by_tf: Dict[str, List[Candle]] = {}

            for tf in timeframes:
                try:
                    candles = self.adapter.fetch_latest(
                        symbol=symbol, timeframe=tf, n=self.candle_limit
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "monitor.fetch_error",
                        symbol=symbol,
                        timeframe=tf,
                        error=str(exc),
                    )
                    candles = []

                if not candles:
                    continue

                # Check whether any new candle has arrived since last poll
                key = (symbol, tf)
                latest_ts = candles[-1].timestamp
                if self._last_seen.get(key) == latest_ts:
                    logger.debug(
                        "monitor.no_new_candle",
                        symbol=symbol,
                        timeframe=tf,
                    )
                else:
                    self._last_seen[key] = latest_ts
                    logger.debug(
                        "monitor.new_candle",
                        symbol=symbol,
                        timeframe=tf,
                        ts=latest_ts.isoformat(),
                        close=round(candles[-1].close, 4),
                    )

                candles_by_tf[tf] = candles

                # Update open positions against the latest candle
                for result in self.executor.update(candles[-1]):
                    logger.info(
                        "monitor.position_closed",
                        symbol=symbol,
                        reason=result.exit_reason,
                        pnl_pips=round(result.pnl_pips, 1),
                    )

            if not candles_by_tf:
                continue

            # Generate signals
            signals = self.sig_gen.scan(candles_by_tf, symbol)
            for sig in signals:
                pos_id = self.executor.execute(sig)
                if self.signal_callback:
                    try:
                        self.signal_callback(sig)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "monitor.callback_error", error=str(exc)
                        )
                logger.info(
                    "monitor.signal",
                    symbol=symbol,
                    pos_id=pos_id,
                    direction=sig.direction,
                    setup=sig.setup_type,
                    entry=round(sig.entry_price, 4),
                    sl=round(sig.stop_loss, 4),
                    tp1=round(sig.take_profit_1, 4),
                    rr=round(sig.risk_reward, 2),
                )

    def _log_summary(self) -> None:
        summary = self.executor.summary()
        logger.info("monitor.session_summary", **summary)
