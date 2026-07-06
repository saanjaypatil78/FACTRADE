"""Tests for liquidity detector (src/trading/analysis/liquidity_detector.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.trading.analysis.liquidity_detector import LiquidityDetector, LiquidityLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(
    n: int = 50,
    base_price: float = 2000.0,
    seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    closes = base_price + np.cumsum(rng.normal(0, 3, n))
    opens = np.roll(closes, 1)
    opens[0] = base_price
    highs = np.maximum(opens, closes) + rng.uniform(0, 2, n)
    lows = np.minimum(opens, closes) - rng.uniform(0, 2, n)
    vols = rng.uniform(100, 1000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=index,
    )


def _make_ranging_with_equal_highs(n: int = 20) -> pd.DataFrame:
    """Create data with 3 equal highs at 2050 within tolerance."""
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    highs = [2030.0] * n
    # Insert 3 near-equal highs
    highs[5] = 2050.0
    highs[10] = 2050.2
    highs[15] = 2049.9
    lows = [2010.0] * n
    opens = [2020.0] * n
    closes = [2025.0] * n
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [100.0] * n},
        index=index,
    )


# ---------------------------------------------------------------------------
# Basic detection
# ---------------------------------------------------------------------------


class TestLiquidityDetection:
    def test_returns_list_of_levels(self):
        df = _make_ohlcv(100)
        ld = LiquidityDetector(swing_lookback=3)
        levels = ld.detect(df, timeframe="1H")
        assert isinstance(levels, list)
        assert all(isinstance(lvl, LiquidityLevel) for lvl in levels)

    def test_empty_df_returns_empty(self):
        ld = LiquidityDetector()
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        levels = ld.detect(df)
        assert levels == []

    def test_levels_sorted_descending(self):
        df = _make_ohlcv(100)
        ld = LiquidityDetector(swing_lookback=3)
        levels = ld.detect(df)
        prices = [lvl.price for lvl in levels]
        assert prices == sorted(prices, reverse=True)

    def test_detects_swing_highs_and_lows(self):
        df = _make_ohlcv(100)
        ld = LiquidityDetector(swing_lookback=3)
        levels = ld.detect(df)
        types = {lvl.type for lvl in levels}
        assert "swing_high" in types
        assert "swing_low" in types

    def test_detects_pdh_pdl(self):
        # Need at least 2 daily bars
        df = _make_ohlcv(n=50, seed=1)
        ld = LiquidityDetector()
        levels = ld.detect(df)
        types = {lvl.type for lvl in levels}
        # PDH/PDL require 2 complete days; 50 × 1H = ~2 days
        assert "pdh" in types or "pdl" in types

    def test_detects_equal_highs(self):
        df = _make_ranging_with_equal_highs()
        ld = LiquidityDetector(equal_tolerance_pct=0.5)
        levels = ld.detect(df)
        eq_high_levels = [lvl for lvl in levels if lvl.type == "equal_high"]
        assert len(eq_high_levels) >= 1


# ---------------------------------------------------------------------------
# Sweep and break status
# ---------------------------------------------------------------------------


class TestSweepStatus:
    def _setup(self):
        ld = LiquidityDetector(swing_lookback=3)
        df = _make_ohlcv(100)
        levels = ld.detect(df)
        return ld, levels, df

    def test_sweep_triggers_on_wick_without_close(self):
        ld = LiquidityDetector(swing_lookback=3)
        # Create a specific swing high at 2100
        index = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
        data = {
            "open": [2000.0] * 20,
            "close": [2005.0] * 20,
            "volume": [100.0] * 20,
        }
        highs = [2010.0] * 20
        highs[10] = 2100.0  # isolated spike = swing high
        lows = [1995.0] * 20
        data["high"] = highs
        data["low"] = lows
        df = pd.DataFrame(data, index=index)

        levels = ld.detect(df, timeframe="1H")
        highs_only = [lvl for lvl in levels if lvl.type == "swing_high" and lvl.price >= 2090]
        assert highs_only, "Expected at least one swing high near 2100"

        lvl = highs_only[0]
        # Bar that wicks above but closes below
        sweep_bar = pd.Series(
            {"open": 2050.0, "high": 2101.0, "low": 2049.0, "close": 2060.0},
            name=pd.Timestamp("2024-01-02", tz="UTC"),
        )
        ld.update_sweep_status([lvl], sweep_bar)
        assert lvl.swept is True
        assert lvl.broken is False

    def test_break_triggers_on_close_above(self):
        ld = LiquidityDetector(swing_lookback=3)
        index = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
        highs = [2010.0] * 20
        highs[10] = 2100.0
        df = pd.DataFrame(
            {
                "open": [2000.0] * 20,
                "high": highs,
                "low": [1995.0] * 20,
                "close": [2005.0] * 20,
                "volume": [100.0] * 20,
            },
            index=index,
        )
        levels = ld.detect(df)
        highs_only = [l for l in levels if l.type == "swing_high" and l.price >= 2090]
        assert highs_only
        lvl = highs_only[0]

        break_bar = pd.Series(
            {"open": 2095.0, "high": 2110.0, "low": 2094.0, "close": 2105.0},
            name=pd.Timestamp("2024-01-02", tz="UTC"),
        )
        ld.update_sweep_status([lvl], break_bar)
        assert lvl.broken is True
        assert lvl.swept is False

    def test_already_swept_level_not_updated_again(self):
        ld = LiquidityDetector()
        lvl = LiquidityLevel(
            price=2100.0,
            type="swing_high",
            timeframe="1H",
            formed_at=pd.Timestamp("2024-01-01", tz="UTC"),
            swept=True,
        )
        original_ts = lvl.sweep_at
        bar = pd.Series(
            {"open": 2095.0, "high": 2105.0, "low": 2094.0, "close": 2098.0},
            name=pd.Timestamp("2024-01-02", tz="UTC"),
        )
        ld.update_sweep_status([lvl], bar)
        # Already swept — should not change
        assert lvl.sweep_at == original_ts


# ---------------------------------------------------------------------------
# Active / swept filters
# ---------------------------------------------------------------------------


class TestFilters:
    def test_get_active_levels_excludes_swept(self):
        ld = LiquidityDetector()
        levels = [
            LiquidityLevel(2100.0, "swing_high", "1H", pd.Timestamp("2024-01-01", tz="UTC"), swept=True),
            LiquidityLevel(2000.0, "swing_low", "1H", pd.Timestamp("2024-01-01", tz="UTC"), swept=False),
        ]
        active = ld.get_active_levels(levels)
        assert len(active) == 1
        assert active[0].price == 2000.0

    def test_get_swept_levels(self):
        ld = LiquidityDetector()
        levels = [
            LiquidityLevel(2100.0, "swing_high", "1H", pd.Timestamp("2024-01-01", tz="UTC"), swept=True),
            LiquidityLevel(2000.0, "swing_low", "1H", pd.Timestamp("2024-01-01", tz="UTC"), swept=False),
        ]
        swept = ld.get_swept_levels(levels)
        assert len(swept) == 1
        assert swept[0].price == 2100.0
