"""
TradingMonitor — continuous multi-timeframe monitoring and signal loop.

Architecture
------------
The monitor ingests OHLCV data from a *DataProvider* (any callable that
returns a pandas DataFrame for a given symbol + timeframe), then:

  1. Evaluates HTF context (Daily, 1H, 3H, 4H) via LiquidityDetector.
  2. Evaluates LTF entry conditions (15m, 30m) via SignalGenerator.
  3. Passes approved signals to TradeExecutor (paper or live).
  4. Calls optional user-supplied alert callbacks (e.g. Telegram, email).

Usage (single-command startup)
-------------------------------
    from src.trading.monitor import TradingMonitor, MonitorConfig
    config = MonitorConfig.from_yaml("trading_config.yaml")
    monitor = TradingMonitor(config)
    monitor.run()        # blocking loop
    # or:
    monitor.run_once()   # single evaluation pass (useful for testing / cron)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import structlog
import yaml

from .liquidity_detector import LiquidityDetector, LiquidityLevel
from .signal_generator import SignalGenerator, TradeSignal
from .risk_manager import RiskManager
from .trade_executor import TradeExecutor, Order

logger = structlog.get_logger(__name__)

# Type alias for a data-provider callable
DataProvider = Callable[[str, str], pd.DataFrame]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SymbolConfig:
    symbol: str
    htf_timeframes: List[str] = field(default_factory=lambda: ["1D", "4H", "3H", "1H"])
    ltf_timeframes: List[str] = field(default_factory=lambda: ["30m", "15m"])
    pip_value: float = 1.0          # account-currency value per pip per 0.01 lot
    max_sl_pips: float = 50.0


@dataclass
class RiskConfig:
    equity: float = 700.0           # session capital
    risk_pct: float = 1.0           # % risk per trade
    max_risk_pct: float = 2.0
    max_daily_loss_pct: float = 2.0
    max_concurrent_trades: int = 2
    min_rr_ratio: float = 1.5


@dataclass
class MonitorConfig:
    symbols: List[SymbolConfig] = field(default_factory=list)
    risk: RiskConfig = field(default_factory=RiskConfig)
    paper_mode: bool = True
    poll_interval_seconds: int = 60
    # LiquidityDetector params
    swing_lookback: int = 3
    equal_tolerance_pct: float = 0.05
    # SignalGenerator params
    ote_low: float = 0.618
    ote_high: float = 0.786
    max_sl_pips: float = 50.0       # global default (per-symbol can override)

    @classmethod
    def from_yaml(cls, path: str) -> "MonitorConfig":
        """Load configuration from a YAML file (see trading_config.yaml)."""
        with open(path, "r") as fh:
            raw = yaml.safe_load(fh)

        cfg = cls()

        risk_raw = raw.get("risk", {})
        cfg.risk = RiskConfig(
            equity=risk_raw.get("equity", 700.0),
            risk_pct=risk_raw.get("risk_pct", 1.0),
            max_risk_pct=risk_raw.get("max_risk_pct", 2.0),
            max_daily_loss_pct=risk_raw.get("max_daily_loss_pct", 2.0),
            max_concurrent_trades=risk_raw.get("max_concurrent_trades", 2),
            min_rr_ratio=risk_raw.get("min_rr_ratio", 1.5),
        )

        cfg.paper_mode = raw.get("paper_mode", True)
        cfg.poll_interval_seconds = raw.get("poll_interval_seconds", 60)
        cfg.swing_lookback = raw.get("swing_lookback", 3)
        cfg.equal_tolerance_pct = raw.get("equal_tolerance_pct", 0.05)
        cfg.ote_low = raw.get("ote_low", 0.618)
        cfg.ote_high = raw.get("ote_high", 0.786)
        cfg.max_sl_pips = raw.get("max_sl_pips", 50.0)

        for sym_raw in raw.get("symbols", []):
            cfg.symbols.append(
                SymbolConfig(
                    symbol=sym_raw["symbol"],
                    htf_timeframes=sym_raw.get("htf_timeframes", ["1D", "4H", "3H", "1H"]),
                    ltf_timeframes=sym_raw.get("ltf_timeframes", ["30m", "15m"]),
                    pip_value=sym_raw.get("pip_value", 1.0),
                    max_sl_pips=sym_raw.get("max_sl_pips", cfg.max_sl_pips),
                )
            )

        return cfg


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class TradingMonitor:
    """
    Orchestrates the full signal-detection and execution loop.

    Parameters
    ----------
    config : MonitorConfig
        All strategy and risk parameters.
    data_provider : DataProvider
        Callable(symbol, timeframe) → pd.DataFrame (OHLCV, DatetimeIndex).
    alert_callbacks : list of callables
        Optional list of functions called with (TradeSignal, Order) when a
        new trade is opened.  Useful for Telegram / email alerts.
    """

    def __init__(
        self,
        config: MonitorConfig,
        data_provider: DataProvider,
        alert_callbacks: Optional[List[Callable[[TradeSignal, Order], None]]] = None,
    ) -> None:
        self.config = config
        self.data_provider = data_provider
        self._alert_callbacks = alert_callbacks or []
        self._running = False

        # Per-symbol risk managers (each symbol shares the same equity pool)
        pip_values = {sc.symbol: sc.pip_value for sc in config.symbols}
        self._risk_manager = RiskManager(
            equity=config.risk.equity,
            risk_pct=config.risk.risk_pct,
            max_risk_pct=config.risk.max_risk_pct,
            max_sl_pips=config.max_sl_pips,
            max_daily_loss_pct=config.risk.max_daily_loss_pct,
            max_concurrent_trades=config.risk.max_concurrent_trades,
            min_rr_ratio=config.risk.min_rr_ratio,
            pip_values=pip_values,
        )

        self._executor = TradeExecutor(
            risk_manager=self._risk_manager,
            paper_mode=config.paper_mode,
            on_signal=self._handle_new_order,
        )

        self._detector = LiquidityDetector(
            swing_lookback=config.swing_lookback,
            equal_tolerance_pct=config.equal_tolerance_pct,
        )

        self._signal_generator = SignalGenerator(
            ote_low=config.ote_low,
            ote_high=config.ote_high,
            max_sl_pips=config.max_sl_pips,
        )

        # Cache of latest HTF levels per symbol
        self._htf_cache: Dict[str, List[LiquidityLevel]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Blocking monitoring loop.  Press Ctrl-C to stop."""
        mode = "PAPER" if self.config.paper_mode else "LIVE"
        logger.info("monitor_starting", mode=mode, symbols=[s.symbol for s in self.config.symbols])
        self._running = True
        try:
            while self._running:
                self.run_once()
                logger.debug("sleeping", seconds=self.config.poll_interval_seconds)
                time.sleep(self.config.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("monitor_stopped_by_user")
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the monitoring loop to exit after the current iteration."""
        self._running = False

    def run_once(self) -> Dict[str, List[TradeSignal]]:
        """
        Execute one full evaluation cycle across all configured symbols.

        Returns
        -------
        dict
            symbol → list of new TradeSignals generated this cycle.
        """
        all_signals: Dict[str, List[TradeSignal]] = {}

        for sym_cfg in self.config.symbols:
            symbol = sym_cfg.symbol
            try:
                signals = self._evaluate_symbol(sym_cfg)
                all_signals[symbol] = signals
            except Exception as exc:
                logger.error("symbol_evaluation_error", symbol=symbol, error=str(exc))
                all_signals[symbol] = []

        open_orders = self._executor.get_open_orders()
        logger.info(
            "cycle_complete",
            open_orders=len(open_orders),
            total_signals=sum(len(v) for v in all_signals.values()),
        )
        return all_signals

    def get_open_orders(self) -> List[Order]:
        return self._executor.get_open_orders()

    def get_all_orders(self) -> List[Order]:
        return self._executor.get_all_orders()

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate_symbol(self, sym_cfg: SymbolConfig) -> List[TradeSignal]:
        symbol = sym_cfg.symbol

        # 1. Build / refresh HTF context
        htf_levels: List[LiquidityLevel] = []
        for tf in sym_cfg.htf_timeframes:
            try:
                ohlcv = self.data_provider(symbol, tf)
                levels = self._detector.detect(ohlcv, tf)
                htf_levels.extend(levels)
            except Exception as exc:
                logger.warning("htf_data_error", symbol=symbol, tf=tf, error=str(exc))

        self._htf_cache[symbol] = htf_levels

        # 2. Generate LTF signals
        new_signals: List[TradeSignal] = []
        for ltf in sym_cfg.ltf_timeframes:
            try:
                ltf_ohlcv = self.data_provider(symbol, ltf)
                signals = self._signal_generator.generate(
                    ltf_ohlcv=ltf_ohlcv,
                    htf_levels=htf_levels,
                    symbol=symbol,
                    timeframe=ltf,
                )
                for sig in signals:
                    order = self._executor.process_signal(sig)
                    if order is not None:
                        new_signals.append(sig)
            except Exception as exc:
                logger.warning("ltf_signal_error", symbol=symbol, tf=ltf, error=str(exc))

        return new_signals

    def _handle_new_order(self, signal: TradeSignal, order: Order) -> None:
        """Internal callback: fan-out to user-supplied alert callbacks."""
        for cb in self._alert_callbacks:
            try:
                cb(signal, order)
            except Exception as exc:
                logger.warning("alert_callback_error", error=str(exc))
