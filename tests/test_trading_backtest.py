"""
Tests for the backtest engine and trade executor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from src.trading.candle import Candle, Signal
from src.trading.backtester import Backtester, BacktestReport
from src.trading.trade_executor import TradeExecutor
from src.trading.risk_manager import RiskManager


# ================================================================== #
# Helpers
# ================================================================== #

def _ts(h: int) -> datetime:
    return datetime(2024, 1, 1, h, 0, tzinfo=timezone.utc)


def _candle(
    ts: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    symbol: str = "XAUUSD",
    tf: str = "1H",
) -> Candle:
    return Candle(ts, o, h, l, c, 1000.0, symbol, tf)


def _make_signal(
    direction: str = "long",
    entry: float = 2000.0,
    sl: float = 1980.0,
    tp1: float = 2040.0,
    tp2: float = 2100.0,
    symbol: str = "XAUUSD",
) -> Signal:
    return Signal(
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        timestamp=_ts(0),
        setup_type="ote_choch",
        timeframe="1H",
    )


def _make_candles_for_backtest(
    n: int, symbol: str = "XAUUSD", timeframe: str = "1H", base: float = 2000.0
) -> List[Candle]:
    import numpy as np
    rng = np.random.default_rng(42)
    candles = []
    price = base
    for i in range(n):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
        o = price
        price += rng.uniform(-5, 5)
        c = price
        h = max(o, c) + rng.uniform(0, 3)
        l = min(o, c) - rng.uniform(0, 3)
        candles.append(Candle(ts, o, h, l, c, 1000.0, symbol, timeframe))
    return candles


# ================================================================== #
# TradeExecutor tests
# ================================================================== #

class TestTradeExecutor:

    def test_execute_returns_pos_id(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal()
        pos_id = exec_.execute(sig)
        assert isinstance(pos_id, str)
        assert len(pos_id) > 0

    def test_open_position_tracked(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal()
        pos_id = exec_.execute(sig)
        assert pos_id in exec_.open_positions

    def test_close_removes_from_open(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal()
        pos_id = exec_.execute(sig)
        result = exec_.close(pos_id, 2030.0, _ts(5), "manual")
        assert pos_id not in exec_.open_positions
        assert result is not None

    def test_close_unknown_pos_returns_none(self):
        exec_ = TradeExecutor(paper_trade=True)
        result = exec_.close("nonexistent", 2000.0, _ts(1), "manual")
        assert result is None

    def test_sl_hit_long(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal(direction="long", entry=2000.0, sl=1980.0, tp1=2040.0)
        pos_id = exec_.execute(sig)
        # Candle that hits SL
        sl_candle = _candle(_ts(1), 2000.0, 2010.0, 1975.0, 1985.0)
        results = exec_.update(sl_candle)
        assert len(results) == 1
        assert results[0].exit_reason == "sl"
        assert results[0].pnl_pips < 0

    def test_tp1_hit_long(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal(direction="long", entry=2000.0, sl=1980.0, tp1=2040.0)
        pos_id = exec_.execute(sig)
        # Candle that hits TP1
        tp_candle = _candle(_ts(1), 2030.0, 2050.0, 2025.0, 2045.0)
        results = exec_.update(tp_candle)
        assert len(results) == 1
        assert results[0].exit_reason == "tp1"
        assert results[0].pnl_pips > 0

    def test_sl_hit_short(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal(direction="short", entry=2000.0, sl=2020.0, tp1=1960.0)
        exec_.execute(sig)
        sl_candle = _candle(_ts(1), 2005.0, 2025.0, 2000.0, 2022.0)
        results = exec_.update(sl_candle)
        assert results[0].exit_reason == "sl"
        assert results[0].pnl_pips < 0

    def test_tp1_hit_short(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal(direction="short", entry=2000.0, sl=2020.0, tp1=1960.0)
        exec_.execute(sig)
        tp_candle = _candle(_ts(1), 1980.0, 1985.0, 1955.0, 1958.0)
        results = exec_.update(tp_candle)
        assert results[0].exit_reason == "tp1"
        assert results[0].pnl_pips > 0

    def test_pnl_pips_long(self):
        exec_ = TradeExecutor(paper_trade=True)
        sig = _make_signal(direction="long", entry=2000.0, tp1=2010.0, sl=1990.0)
        exec_.execute(sig)
        tp_candle = _candle(_ts(1), 2005.0, 2015.0, 2002.0, 2012.0)
        results = exec_.update(tp_candle)
        # TP1=2010, entry=2000 → 10 pips (pip size 0.01 for XAUUSD)
        assert results[0].pnl_pips == pytest.approx(
            (2010.0 - 2000.0) / 0.01, rel=1e-3
        )

    def test_summary_metrics(self):
        exec_ = TradeExecutor(paper_trade=True)
        # Manually close one win and one loss
        sig1 = _make_signal("long", entry=2000.0, sl=1990.0, tp1=2020.0)
        sig2 = _make_signal("long", entry=2000.0, sl=1990.0, tp1=2020.0)
        p1 = exec_.execute(sig1)
        p2 = exec_.execute(sig2)
        exec_.close(p1, 2020.0, _ts(1), "tp1")   # win
        exec_.close(p2, 1990.0, _ts(2), "sl")    # loss
        s = exec_.summary()
        assert s["total"] == 2
        assert s["wins"] == 1
        assert s["losses"] == 1
        assert s["win_rate"] == pytest.approx(50.0)

    def test_journal_file_written(self, tmp_path):
        journal = tmp_path / "journal.jsonl"
        exec_ = TradeExecutor(paper_trade=True, journal_file=str(journal))
        sig = _make_signal()
        pos_id = exec_.execute(sig)
        exec_.close(pos_id, 2030.0, _ts(5), "manual")
        assert journal.exists()
        lines = journal.read_text().strip().split("\n")
        assert len(lines) >= 2  # open + close events


# ================================================================== #
# BacktestReport tests
# ================================================================== #

class TestBacktestReport:

    def _make_result(self, pnl_pips: float, direction: str = "long") -> object:
        from src.trading.candle import TradeResult
        sig = _make_signal(direction=direction)
        reason = "tp1" if pnl_pips > 0 else "sl"
        exit_price = sig.entry_price + (pnl_pips * 0.01 * (1 if direction == "long" else -1))
        return TradeResult(
            signal=sig,
            exit_price=exit_price,
            exit_time=_ts(1),
            exit_reason=reason,
            pnl_pips=pnl_pips,
            pnl_dollars=pnl_pips * 0.01,
        )

    def test_empty_report(self):
        report = BacktestReport([], [], "XAUUSD", None, None)
        assert report.total_trades == 0
        assert report.win_rate == 0.0
        assert report.total_pips == 0.0
        assert report.profit_factor == float("inf")
        assert report.max_drawdown_pips == 0.0

    def test_win_rate_calculation(self):
        results = [
            self._make_result(100.0),
            self._make_result(50.0),
            self._make_result(-30.0),
        ]
        report = BacktestReport(results, [], "XAUUSD", _ts(0), _ts(3))
        assert report.total_trades == 3
        assert report.wins == 2
        assert report.losses == 1
        assert report.win_rate == pytest.approx(66.67, rel=0.01)

    def test_profit_factor(self):
        results = [
            self._make_result(100.0),
            self._make_result(-50.0),
        ]
        report = BacktestReport(results, [], "XAUUSD", _ts(0), _ts(2))
        assert report.profit_factor == pytest.approx(2.0)

    def test_max_drawdown(self):
        results = [
            self._make_result(50.0),
            self._make_result(50.0),
            self._make_result(-80.0),
            self._make_result(10.0),
        ]
        report = BacktestReport(results, [], "XAUUSD", _ts(0), _ts(4))
        # Peak at 100 pips, drops to 20 → drawdown = 80
        assert report.max_drawdown_pips == pytest.approx(80.0)

    def test_to_dict_keys(self):
        report = BacktestReport([], [], "XAUUSD", _ts(0), _ts(1))
        d = report.to_dict()
        for key in ("total_trades", "win_rate_pct", "total_pips", "profit_factor"):
            assert key in d

    def test_by_setup_grouping(self):
        results = [self._make_result(100.0), self._make_result(-30.0)]
        results[0].signal.setup_type = "ote_choch"
        results[1].signal.setup_type = "smma_ribbon"
        report = BacktestReport(results, [], "XAUUSD", _ts(0), _ts(2))
        by_setup = report.by_setup
        assert "ote_choch" in by_setup
        assert "smma_ribbon" in by_setup


# ================================================================== #
# Backtester integration test
# ================================================================== #

class TestBacktester:

    def test_run_returns_report(self):
        bt = Backtester(warmup_bars=50)
        candles_by_tf = {
            "1H": _make_candles_for_backtest(300, timeframe="1H"),
            "15m": _make_candles_for_backtest(1200, timeframe="15m"),
            "5m": _make_candles_for_backtest(1500, timeframe="5m"),
        }
        report = bt.run(candles_by_tf, symbol="XAUUSD")
        assert isinstance(report, BacktestReport)
        assert report.symbol == "XAUUSD"

    def test_run_insufficient_data_returns_empty_report(self):
        bt = Backtester(warmup_bars=300)
        candles_by_tf = {"1H": _make_candles_for_backtest(10, timeframe="1H")}
        report = bt.run(candles_by_tf, symbol="XAUUSD")
        assert report.total_trades == 0

    def test_report_start_end_set(self):
        bt = Backtester(warmup_bars=50)
        candles = _make_candles_for_backtest(300, timeframe="1H")
        report = bt.run({"1H": candles, "15m": _make_candles_for_backtest(1200, timeframe="15m")}, "XAUUSD")
        if report.start:
            assert isinstance(report.start, datetime)
        if report.end:
            assert isinstance(report.end, datetime)

    def test_usoil_symbol_supported(self):
        bt = Backtester(warmup_bars=50)
        candles_by_tf = {
            "1H": _make_candles_for_backtest(300, symbol="USOIL", timeframe="1H", base=70.0),
            "15m": _make_candles_for_backtest(1200, symbol="USOIL", timeframe="15m", base=70.0),
        }
        report = bt.run(candles_by_tf, symbol="USOIL")
        assert report.symbol == "USOIL"
