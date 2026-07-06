"""Live monitoring loop for FACTRADE.

Continuously fetches the latest candles from a ``LiveFeedAdapter`` (or the
DataStore for paper-mode replay), runs the full analysis pipeline, and
dispatches to the ``TradeExecutor`` and optional ``AutoExecutionBridge``.

Design
------
- Default: paper / signal mode — no real orders.
- The monitor is a simple polling loop; for production use, run it in a
  dedicated thread or process.
- News filter: skip signals if a news event is flagged (extendable).

Usage (paper mode)
------------------
    from src.trading.data.broker_adapter import MockBrokerAdapter
    from src.trading.monitor import LiveMonitor

    adapter = MockBrokerAdapter(symbol="XAUUSD", timeframe="1H")
    monitor = LiveMonitor(feed_adapter=adapter, mode="paper")
    monitor.start(max_iterations=10)  # run 10 bars then stop
"""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd
import structlog

from src.trading.analysis.liquidity_detector import LiquidityDetector
from src.trading.analysis.signal_generator import SignalGenerator
from src.trading.data.broker_adapter import LiveFeedAdapter, MockBrokerAdapter
from src.trading.execution.auto_execution_bridge import AutoExecutionBridge, NullBrokerAdapter
from src.trading.execution.exit_manager import ExitConfig
from src.trading.execution.risk_manager import RiskManager
from src.trading.execution.trade_executor import TradeExecutor

logger = structlog.get_logger(__name__)


class LiveMonitor:
    """Live / paper monitoring loop.

    Parameters
    ----------
    feed_adapter:
        ``LiveFeedAdapter`` providing OHLCV candles.
    mode:
        ``"paper"`` or ``"signal"`` (default ``"paper"``).
    poll_interval_seconds:
        Seconds between feed polls (default 60).
    swing_lookback:
        Swing high/low detection lookback (default 5).
    ltf_window:
        Number of LTF candles to keep in memory for signal generation (default 100).
    risk_manager:
        Optional RiskManager instance.
    exit_config:
        Optional ExitConfig for the exit manager.
    auto_execution_bridge:
        Optional AutoExecutionBridge.  Defaults to the null (paper) bridge.
    news_events:
        Optional list of ISO timestamp strings marking high-impact news.
        Signals are suppressed within ±15 minutes of each event.
    """

    def __init__(
        self,
        feed_adapter: Optional[LiveFeedAdapter] = None,
        mode: str = "paper",
        poll_interval_seconds: int = 60,
        swing_lookback: int = 5,
        ltf_window: int = 100,
        risk_manager: Optional[RiskManager] = None,
        exit_config: Optional[ExitConfig] = None,
        auto_execution_bridge: Optional[AutoExecutionBridge] = None,
        news_events: Optional[list[str]] = None,
    ) -> None:
        self._feed = feed_adapter or MockBrokerAdapter()
        self.mode = mode
        self._poll_interval = poll_interval_seconds
        self._ltf_window = ltf_window

        self._ld = LiquidityDetector(swing_lookback=swing_lookback)
        self._sg = SignalGenerator()
        self._rm = risk_manager or RiskManager()
        self._executor = TradeExecutor(mode=mode, risk_manager=self._rm, exit_config=exit_config)
        self._bridge = auto_execution_bridge or AutoExecutionBridge(
            broker_adapter=NullBrokerAdapter(), enable_live_execution=False
        )
        self._news_events: list[pd.Timestamp] = []
        if news_events:
            self._news_events = [pd.Timestamp(e, tz="UTC") for e in news_events]

        self._running = False
        self._iteration = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, max_iterations: int = 0) -> None:
        """Start the monitoring loop.

        Parameters
        ----------
        max_iterations:
            Stop after this many poll cycles (0 = run indefinitely).
        """
        if not self._feed.is_connected():
            self._feed.connect()

        self._running = True
        logger.info(
            "monitor.start",
            symbol=self._feed.symbol,
            timeframe=self._feed.timeframe,
            mode=self.mode,
            live=self._bridge.is_live,
        )

        htf_levels = []

        try:
            while self._running:
                self._iteration += 1

                df = self._feed.get_candles(limit=self._ltf_window)
                if df.empty:
                    logger.warning("monitor.empty_feed")
                    self._sleep()
                    continue

                latest_bar = df.iloc[-1]
                ts = latest_bar.name

                # Skip if near news event
                if self._near_news(ts):
                    logger.info("monitor.news_filter_active", ts=str(ts))
                    self._sleep()
                    continue

                # Update sweep status
                htf_levels = self._ld.detect(df, timeframe=self._feed.timeframe)
                self._ld.update_sweep_status(htf_levels, latest_bar)
                swept = self._ld.get_swept_levels(htf_levels)

                # ATR
                atr = self._compute_atr(df)

                # Update open paper trades
                self._executor.process_bar(latest_bar, atr=atr)

                # Generate signals
                if swept:
                    signals = self._sg.generate(
                        df, swept, symbol=self._feed.symbol, timeframe=self._feed.timeframe
                    )
                    for sig in signals:
                        spec = self._executor.execute_signal(sig, atr=atr, df=df)
                        if spec and self._bridge.is_live:
                            trade_id = f"{sig.symbol}-{ts}"
                            self._bridge.submit(spec, trade_id)

                logger.info(
                    "monitor.iteration",
                    iteration=self._iteration,
                    ts=str(ts),
                    open_trades=len(self._executor.get_open_trades()),
                    swept_levels=len(swept),
                )

                if max_iterations > 0 and self._iteration >= max_iterations:
                    logger.info("monitor.max_iterations_reached")
                    break

                self._sleep()

        except KeyboardInterrupt:
            logger.info("monitor.interrupted")
        finally:
            self._running = False
            if self._feed.is_connected():
                self._feed.disconnect()

    def stop(self) -> None:
        """Signal the loop to stop after the current iteration."""
        self._running = False

    def get_summary(self) -> dict:
        """Return current P&L summary from the executor."""
        return self._executor.get_pnl_summary()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sleep(self) -> None:
        time.sleep(self._poll_interval)

    def _near_news(self, ts: pd.Timestamp, window_minutes: int = 15) -> bool:
        """Return True if *ts* is within *window_minutes* of a news event."""
        if not self._news_events:
            return False
        window = pd.Timedelta(minutes=window_minutes)
        return any(abs(ts - evt) <= window for evt in self._news_events)

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return float((df["high"] - df["low"]).mean())
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        val = tr.rolling(period).mean().iloc[-1]
        return float(val) if pd.notna(val) else float((high - low).mean())
