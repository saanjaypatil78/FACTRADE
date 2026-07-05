"""
Tests for src/trading/trade_executor.py and src/trading/monitor.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import MagicMock

from src.trading.liquidity_detector import LiquidityLevel, LiquidityType, SweepStatus
from src.trading.signal_generator import SignalDirection, TradeSignal, MarketRegime
from src.trading.risk_manager import RiskManager
from src.trading.trade_executor import TradeExecutor, Order, OrderStatus
from src.trading.monitor import MonitorConfig, TradingMonitor, SymbolConfig, RiskConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    direction: SignalDirection = SignalDirection.LONG,
    entry: float = 3200.0,
    sl: float = 3190.0,
    tp1: float = 3220.0,
    tp2: float = 3240.0,
) -> TradeSignal:
    return TradeSignal(
        symbol="XAUUSD",
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        timeframe="15m",
        timestamp=pd.Timestamp("2024-01-02 10:00"),
        regime=MarketRegime.TREND,
    )


def _make_risk_manager(equity: float = 1000.0, max_sl: float = 200.0) -> RiskManager:
    return RiskManager(
        equity=equity,
        risk_pct=1.0,
        max_risk_pct=2.0,
        max_sl_pips=max_sl,
        max_daily_loss_pct=5.0,
        max_concurrent_trades=5,
        min_rr_ratio=1.0,
        pip_values={"XAUUSD": 1.0},
    )


def _make_executor(equity: float = 1000.0) -> TradeExecutor:
    rm = _make_risk_manager(equity=equity)
    return TradeExecutor(risk_manager=rm, paper_mode=True)


def _make_ohlcv(n: int = 500, base: float = 3200.0, freq: str = "15min") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    closes = base + np.cumsum(rng.normal(0, 5, n))
    highs = closes + rng.uniform(0.5, 5.0, n)
    lows = closes - rng.uniform(0.5, 5.0, n)
    opens = np.roll(closes, 1); opens[0] = closes[0]
    volumes = rng.integers(50, 500, n).astype(float)
    index = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


# ---------------------------------------------------------------------------
# TradeExecutor — basic lifecycle
# ---------------------------------------------------------------------------

def test_executor_initialisation():
    rm = _make_risk_manager()
    ex = TradeExecutor(risk_manager=rm, paper_mode=True)
    assert ex.paper_mode is True
    assert ex.get_open_orders() == []


def test_process_signal_returns_order():
    ex = _make_executor()
    sig = _make_signal()
    order = ex.process_signal(sig)
    assert order is not None
    assert isinstance(order, Order)


def test_order_status_open_after_signal():
    ex = _make_executor()
    order = ex.process_signal(_make_signal())
    assert order.status == OrderStatus.OPEN


def test_order_direction_matches_signal():
    ex = _make_executor()
    order_long = ex.process_signal(_make_signal(direction=SignalDirection.LONG))
    order_short = ex.process_signal(_make_signal(direction=SignalDirection.SHORT))
    assert order_long.direction == SignalDirection.LONG
    assert order_short.direction == SignalDirection.SHORT


def test_process_signal_rejected_wide_sl():
    rm = _make_risk_manager(max_sl=5.0)  # very tight SL cap
    ex = TradeExecutor(risk_manager=rm, paper_mode=True)
    sig = _make_signal(entry=3200.0, sl=3100.0)  # 100-pip SL
    order = ex.process_signal(sig)
    assert order is None


def test_get_open_orders_tracks_count():
    ex = _make_executor()
    ex.process_signal(_make_signal())
    ex.process_signal(_make_signal(entry=3205.0, sl=3195.0, tp1=3225.0, tp2=3245.0))
    assert len(ex.get_open_orders()) == 2


def test_cancel_pending_order():
    ex = _make_executor()
    order = ex.process_signal(_make_signal())
    # Manually set to PENDING to test cancel
    order.status = OrderStatus.PENDING
    ex.cancel_order(order.order_id)
    assert order.status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# TradeExecutor — price update / SL/TP hit
# ---------------------------------------------------------------------------

def test_update_prices_sl_hit_long():
    ex = _make_executor()
    order = ex.process_signal(_make_signal(
        direction=SignalDirection.LONG,
        entry=3200.0, sl=3190.0, tp1=3220.0, tp2=3240.0,
    ))
    ex.update_prices("XAUUSD", 3185.0)  # below SL
    assert order.status == OrderStatus.CLOSED_SL


def test_update_prices_sl_hit_short():
    ex = _make_executor()
    order = ex.process_signal(_make_signal(
        direction=SignalDirection.SHORT,
        entry=3200.0, sl=3210.0, tp1=3180.0, tp2=3160.0,
    ))
    ex.update_prices("XAUUSD", 3215.0)  # above SL
    assert order.status == OrderStatus.CLOSED_SL


def test_update_prices_tp1_hit_long():
    ex = _make_executor()
    order = ex.process_signal(_make_signal(
        direction=SignalDirection.LONG,
        entry=3200.0, sl=3190.0, tp1=3220.0, tp2=3240.0,
    ))
    ex.update_prices("XAUUSD", 3222.0)  # above TP1
    assert order.status == OrderStatus.CLOSED_TP1


def test_update_prices_runner_sl_after_tp1():
    ex = _make_executor()
    order = ex.process_signal(_make_signal(
        direction=SignalDirection.LONG,
        entry=3200.0, sl=3190.0, tp1=3220.0, tp2=3240.0,
    ))
    # Hit TP1
    ex.update_prices("XAUUSD", 3222.0)
    assert order.status == OrderStatus.CLOSED_TP1
    # Now price drops to runner SL (break-even ~3200)
    ex.update_prices("XAUUSD", order.runner_sl - 1.0)
    assert order.status == OrderStatus.CLOSED_SL


def test_update_prices_wrong_symbol_ignored():
    ex = _make_executor()
    order = ex.process_signal(_make_signal())
    ex.update_prices("EURUSD", 1.05)  # different symbol
    assert order.status == OrderStatus.OPEN


def test_pnl_positive_on_winning_long():
    ex = _make_executor()
    order = ex.process_signal(_make_signal(
        direction=SignalDirection.LONG,
        entry=3200.0, sl=3190.0, tp1=3220.0, tp2=3240.0,
    ))
    ex.update_prices("XAUUSD", 3225.0)  # above TP1
    assert order.realized_pnl > 0


def test_pnl_negative_on_sl():
    ex = _make_executor()
    order = ex.process_signal(_make_signal(
        direction=SignalDirection.LONG,
        entry=3200.0, sl=3190.0, tp1=3220.0, tp2=3240.0,
    ))
    ex.update_prices("XAUUSD", 3185.0)
    assert order.realized_pnl < 0


# ---------------------------------------------------------------------------
# Alert callback
# ---------------------------------------------------------------------------

def test_alert_callback_called_on_new_order():
    callback = MagicMock()
    rm = _make_risk_manager()
    ex = TradeExecutor(risk_manager=rm, paper_mode=True, on_signal=callback)
    sig = _make_signal()
    ex.process_signal(sig)
    callback.assert_called_once()


def test_alert_callback_not_called_on_rejected():
    callback = MagicMock()
    rm = _make_risk_manager(max_sl=5.0)
    ex = TradeExecutor(risk_manager=rm, paper_mode=True, on_signal=callback)
    ex.process_signal(_make_signal(entry=3200.0, sl=3100.0))
    callback.assert_not_called()


# ---------------------------------------------------------------------------
# Live mode — requires broker
# ---------------------------------------------------------------------------

def test_live_mode_requires_broker():
    rm = _make_risk_manager()
    with pytest.raises(ValueError, match="BrokerAdapter"):
        TradeExecutor(risk_manager=rm, paper_mode=False, broker=None)


# ---------------------------------------------------------------------------
# TradingMonitor
# ---------------------------------------------------------------------------

def _make_monitor_config() -> MonitorConfig:
    cfg = MonitorConfig()
    cfg.symbols = [
        SymbolConfig(
            symbol="XAUUSD",
            htf_timeframes=["1H"],
            ltf_timeframes=["15m"],
            pip_value=1.0,
        )
    ]
    cfg.risk = RiskConfig(
        equity=1000.0,
        risk_pct=1.0,
        max_risk_pct=2.0,
        max_daily_loss_pct=5.0,
        max_concurrent_trades=5,
        min_rr_ratio=1.0,
    )
    cfg.paper_mode = True
    cfg.poll_interval_seconds = 1
    cfg.max_sl_pips = 10000.0
    return cfg


def test_monitor_initialisation():
    def dummy_provider(symbol, tf):
        return _make_ohlcv()

    cfg = _make_monitor_config()
    monitor = TradingMonitor(config=cfg, data_provider=dummy_provider)
    assert monitor is not None


def test_monitor_run_once_returns_dict():
    def dummy_provider(symbol, tf):
        return _make_ohlcv()

    cfg = _make_monitor_config()
    monitor = TradingMonitor(config=cfg, data_provider=dummy_provider)
    result = monitor.run_once()
    assert isinstance(result, dict)
    assert "XAUUSD" in result


def test_monitor_run_once_no_crash_on_data_error():
    """Monitor should catch data provider errors and continue."""
    def bad_provider(symbol, tf):
        raise RuntimeError("no data")

    cfg = _make_monitor_config()
    monitor = TradingMonitor(config=cfg, data_provider=bad_provider)
    result = monitor.run_once()
    assert "XAUUSD" in result
    assert result["XAUUSD"] == []


def test_monitor_config_from_yaml(tmp_path):
    yaml_content = """
paper_mode: true
poll_interval_seconds: 30
symbols:
  - symbol: XAUUSD
    htf_timeframes: ["1H", "4H"]
    ltf_timeframes: ["15m"]
    pip_value: 1.0
    max_sl_pips: 50.0
risk:
  equity: 500.0
  risk_pct: 1.0
  max_risk_pct: 2.0
  max_daily_loss_pct: 2.0
  max_concurrent_trades: 2
  min_rr_ratio: 1.5
swing_lookback: 3
equal_tolerance_pct: 0.05
ote_low: 0.618
ote_high: 0.786
max_sl_pips: 50.0
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml_content)
    cfg = MonitorConfig.from_yaml(str(config_file))
    assert cfg.paper_mode is True
    assert cfg.risk.equity == 500.0
    assert len(cfg.symbols) == 1
    assert cfg.symbols[0].symbol == "XAUUSD"
    assert cfg.ote_low == 0.618
