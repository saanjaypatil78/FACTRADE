"""Tests for the advanced exit manager (src/trading/execution/exit_manager.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.trading.execution.exit_manager import (
    ExitConfig,
    ExitManager,
    ExitReason,
    OpenTrade,
)
from src.trading.execution.risk_manager import PositionSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    direction: str = "long",
    entry: float = 2000.0,
    sl: float = 1980.0,
    tp1: float = 2030.0,
    tp2: float = 2060.0,
    lots: float = 0.05,
    symbol: str = "XAUUSD",
) -> PositionSpec:
    return PositionSpec(
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        sl_price=sl,
        tp1_price=tp1,
        tp2_price=tp2,
        lot_size=lots,
        sl_pips=abs(entry - sl) / 0.01,
        risk_amount=7.0,
        risk_pct=0.5,
        atr=5.0,
        valid=True,
    )


def _bar(
    o: float, h: float, l: float, c: float, ts: str = "2024-01-01 10:00"
) -> pd.Series:
    return pd.Series(
        {"open": o, "high": h, "low": l, "close": c, "volume": 100.0},
        name=pd.Timestamp(ts, tz="UTC"),
    )


def _make_manager(config: ExitConfig | None = None) -> ExitManager:
    return ExitManager(config=config)


# ---------------------------------------------------------------------------
# SL hit
# ---------------------------------------------------------------------------


class TestSLHit:
    def test_long_sl_triggered_on_low(self):
        mgr = _make_manager()
        trade = mgr.open_trade(_spec("long", sl=1980.0), pd.Timestamp("2024-01-01", tz="UTC"))
        bar = _bar(1985, 1986, 1979, 1981)  # low below SL
        result = mgr.update(trade, bar)
        assert result is not None
        assert result["reason"] == ExitReason.SL_HIT
        assert trade.closed

    def test_short_sl_triggered_on_high(self):
        mgr = _make_manager()
        sp = _spec("short", entry=2000.0, sl=2020.0, tp1=1970.0, tp2=1940.0)
        trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))
        bar = _bar(2010, 2021, 2009, 2011)  # high above SL
        result = mgr.update(trade, bar)
        assert result is not None
        assert result["reason"] == ExitReason.SL_HIT

    def test_sl_not_triggered_when_low_above_sl(self):
        mgr = _make_manager()
        trade = mgr.open_trade(_spec("long", sl=1980.0), pd.Timestamp("2024-01-01", tz="UTC"))
        bar = _bar(1990, 1995, 1982, 1993)  # low > SL
        result = mgr.update(trade, bar)
        assert result is None
        assert not trade.closed


# ---------------------------------------------------------------------------
# TP1 partial close and break-even
# ---------------------------------------------------------------------------


class TestTP1Partial:
    def test_tp1_triggered_partial_close(self):
        config = ExitConfig(partial_pct=0.80, breakeven_buffer_pips=10.0, pip_size=0.01)
        mgr = _make_manager(config)
        trade = mgr.open_trade(
            _spec("long", entry=2000.0, tp1=2030.0, lots=0.05),
            pd.Timestamp("2024-01-01", tz="UTC"),
        )
        bar = _bar(2025, 2035, 2024, 2032)  # high above tp1
        result = mgr.update(trade, bar)
        assert result is not None
        assert result["action"] == "partial"
        assert result["reason"] == ExitReason.TP1

    def test_tp1_partial_lots_correct(self):
        config = ExitConfig(partial_pct=0.80, pip_size=0.01)
        mgr = _make_manager(config)
        trade = mgr.open_trade(
            _spec("long", entry=2000.0, tp1=2030.0, lots=0.10),
            pd.Timestamp("2024-01-01", tz="UTC"),
        )
        bar = _bar(2025, 2035, 2024, 2032)
        result = mgr.update(trade, bar)
        # 80% of 0.10 = 0.08 lots closed
        assert result["lots"] == pytest.approx(0.08)
        # Remaining should be 0.02
        assert trade.remaining_lots == pytest.approx(0.02)

    def test_breakeven_sl_set_after_tp1(self):
        config = ExitConfig(
            partial_pct=0.80,
            breakeven_buffer_pips=10.0,
            brokerage_pips=3.0,
            pip_size=0.01,
        )
        mgr = _make_manager(config)
        sp = _spec("long", entry=2000.0, tp1=2030.0, lots=0.10)
        trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))
        bar = _bar(2025, 2035, 2024, 2032)
        mgr.update(trade, bar)
        # BE = entry + (buffer + brokerage) * pip_size = 2000 + 0.13 = 2000.13
        expected_be = 2000.0 + (10.0 + 3.0) * 0.01
        assert trade.current_sl == pytest.approx(expected_be)
        assert trade.be_active is True

    def test_short_tp1_partial(self):
        config = ExitConfig(partial_pct=0.80, pip_size=0.01)
        mgr = _make_manager(config)
        sp = _spec("short", entry=2000.0, sl=2020.0, tp1=1970.0, tp2=1940.0, lots=0.10)
        trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))
        bar = _bar(1975, 1976, 1968, 1972)  # low below tp1
        result = mgr.update(trade, bar)
        assert result is not None
        assert result["action"] == "partial"


# ---------------------------------------------------------------------------
# TP2 (runner full exit)
# ---------------------------------------------------------------------------


class TestTP2:
    def test_tp2_full_close(self):
        config = ExitConfig(partial_pct=0.80)
        mgr = _make_manager(config)
        sp = _spec("long", entry=2000.0, tp1=2030.0, tp2=2060.0, lots=0.10)
        trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))
        # Simulate tp1 hit first
        bar_tp1 = _bar(2025, 2035, 2024, 2032)
        mgr.update(trade, bar_tp1)
        assert trade.tp1_hit

        # Then tp2
        bar_tp2 = _bar(2055, 2065, 2054, 2063)
        result = mgr.update(trade, bar_tp2)
        assert result is not None
        assert result["action"] == "full"
        assert result["reason"] == ExitReason.TP2
        assert trade.closed


# ---------------------------------------------------------------------------
# Trailing stop
# ---------------------------------------------------------------------------


class TestTrailingStop:
    def test_trailing_stop_activates_after_tp1(self):
        config = ExitConfig(
            partial_pct=0.80,
            trailing_stop=True,
            trail_atr_mult=1.0,
            pip_size=0.01,
        )
        mgr = _make_manager(config)
        sp = _spec("long", entry=2000.0, tp1=2030.0, tp2=2100.0, lots=0.10)
        trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))

        # Hit TP1
        mgr.update(trade, _bar(2025, 2035, 2024, 2032), atr=5.0)
        assert trade.tp1_hit

        # Price moves higher — trailing SL should advance
        mgr.update(trade, _bar(2040, 2050, 2039, 2048), atr=5.0)
        sl_after_trail = trade.current_sl
        # trailing_high = 2050, trail_dist = 1 * 5.0 = 5.0, so new_sl = 2045.0
        assert sl_after_trail == pytest.approx(2045.0)

    def test_trailing_stop_does_not_move_back(self):
        config = ExitConfig(
            partial_pct=0.80,
            trailing_stop=True,
            trail_atr_mult=1.0,
            pip_size=0.01,
        )
        mgr = _make_manager(config)
        sp = _spec("long", entry=2000.0, tp1=2030.0, tp2=2100.0, lots=0.10)
        trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))

        # Hit TP1 and move higher
        mgr.update(trade, _bar(2025, 2035, 2024, 2032), atr=5.0)
        mgr.update(trade, _bar(2040, 2060, 2039, 2058), atr=5.0)
        sl_high = trade.current_sl

        # Price retreats but does not close below SL yet
        mgr.update(trade, _bar(2045, 2048, 2044, 2046), atr=5.0)
        # SL must not decrease (trailing stop never moves back)
        assert trade.current_sl >= sl_high


# ---------------------------------------------------------------------------
# Time stop
# ---------------------------------------------------------------------------


class TestTimeStop:
    def test_time_stop_exits_after_n_bars(self):
        config = ExitConfig(max_hold_bars=3, pip_size=0.01)
        mgr = _make_manager(config)
        trade = mgr.open_trade(_spec("long"), pd.Timestamp("2024-01-01", tz="UTC"))

        # First 2 bars must NOT trigger the time stop
        for i in range(2):
            result = mgr.update(trade, _bar(2005, 2010, 2001, 2008, f"2024-01-01 0{i}:00"))
            assert result is None, f"Expected no exit on bar {i + 1}"

        # 3rd bar (bars_held == max_hold_bars == 3) triggers the time stop
        result = mgr.update(trade, _bar(2005, 2010, 2001, 2008, "2024-01-01 02:00"))
        assert result is not None
        assert result["reason"] == ExitReason.TIME_STOP
        assert trade.closed


# ---------------------------------------------------------------------------
# Force close
# ---------------------------------------------------------------------------


class TestForceClose:
    def test_force_close(self):
        mgr = _make_manager()
        trade = mgr.open_trade(_spec("long"), pd.Timestamp("2024-01-01", tz="UTC"))
        ts = pd.Timestamp("2024-01-01 12:00", tz="UTC")
        result = mgr.force_close(trade, price=2010.0, ts=ts)
        assert result["reason"] == ExitReason.MANUAL
        assert trade.closed
        assert trade.close_price == pytest.approx(2010.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_config_produces_same_exits(self):
        """Identical inputs must produce identical exit events."""
        config = ExitConfig(partial_pct=0.80, trailing_stop=True, trail_atr_mult=1.5)
        bars = [
            _bar(2000, 2010, 1998, 2008, "2024-01-01 01:00"),
            _bar(2008, 2035, 2007, 2032, "2024-01-01 02:00"),
            _bar(2032, 2060, 2030, 2058, "2024-01-01 03:00"),
            _bar(2058, 2062, 2035, 2040, "2024-01-01 04:00"),
        ]

        def _run():
            mgr = ExitManager(config=config)
            sp = _spec("long", tp1=2030.0, tp2=2055.0)
            trade = mgr.open_trade(sp, pd.Timestamp("2024-01-01", tz="UTC"))
            results = []
            for bar in bars:
                r = mgr.update(trade, bar, atr=5.0)
                if r:
                    results.append((r["action"], r["reason"].name))
            return results

        assert _run() == _run()
