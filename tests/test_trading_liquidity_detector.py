"""
Tests for src/trading/liquidity_detector.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.trading.liquidity_detector import (
    LiquidityDetector,
    LiquidityLevel,
    LiquidityType,
    SweepStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 100,
    base: float = 1000.0,
    seed: int = 42,
    freq: str = "1h",
) -> pd.DataFrame:
    """Generate a simple synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(0, 1, n))
    highs = closes + rng.uniform(0.1, 2.0, n)
    lows = closes - rng.uniform(0.1, 2.0, n)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    volumes = rng.integers(100, 1000, n).astype(float)
    index = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def _make_ohlcv_with_swing_high(
    base: float = 1000.0,
    spike_idx: int = 10,
    spike_value: float = 1050.0,
) -> pd.DataFrame:
    """Returns a DataFrame with a clear swing high at spike_idx."""
    n = 50
    df = _make_ohlcv(n=n, base=base)
    # Inject spike
    df.loc[df.index[spike_idx], "high"] = spike_value
    df.loc[df.index[spike_idx], "close"] = spike_value - 1
    # Make surrounding candles clearly lower
    for offset in range(1, 4):
        for i in [spike_idx - offset, spike_idx + offset]:
            if 0 <= i < n:
                df.loc[df.index[i], "high"] = spike_value - 10 * offset
    return df


def _make_ohlcv_with_sweep(base: float = 1000.0) -> pd.DataFrame:
    """
    Returns a DataFrame where:
    - candle 10 forms a swing high at 1050
    - candle 25 wicks above 1050 but closes below (sweep / rejection)
    """
    df = _make_ohlcv_with_swing_high(base=base, spike_idx=10, spike_value=1050.0)
    # Add sweep candle
    df.loc[df.index[25], "high"] = 1055.0  # wick above swing high
    df.loc[df.index[25], "close"] = 1040.0  # close below — sweep
    return df


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def detector():
    return LiquidityDetector(swing_lookback=3, equal_tolerance_pct=0.05)


def test_detector_initialisation(detector):
    assert detector.swing_lookback == 3
    assert detector.equal_tolerance_pct == 0.05


def test_detect_returns_list(detector):
    df = _make_ohlcv()
    levels = detector.detect(df, "1H")
    assert isinstance(levels, list)


def test_detect_swing_highs_and_lows(detector):
    df = _make_ohlcv_with_swing_high(spike_idx=10, spike_value=1100.0)
    levels = detector.detect(df, "4H", include_pdh_pdl=False)
    swing_highs = [l for l in levels if l.level_type == LiquidityType.SWING_HIGH]
    assert len(swing_highs) >= 1
    # The injected spike should be the maximum swing high
    max_sh = max(swing_highs, key=lambda x: x.price)
    assert max_sh.price >= 1090.0  # close to injected spike value


def test_detect_swing_lows(detector):
    n = 60
    df = _make_ohlcv(n=n, base=1000.0)
    # Inject a clear dip at index 20
    df.loc[df.index[20], "low"] = 900.0
    df.loc[df.index[20], "close"] = 901.0
    for offset in range(1, 4):
        for i in [20 - offset, 20 + offset]:
            if 0 <= i < n:
                df.loc[df.index[i], "low"] = 900.0 + 10 * offset
    levels = detector.detect(df, "1H", include_pdh_pdl=False)
    swing_lows = [l for l in levels if l.level_type == LiquidityType.SWING_LOW]
    assert len(swing_lows) >= 1
    min_sl = min(swing_lows, key=lambda x: x.price)
    assert min_sl.price <= 910.0


def test_detect_pdh_pdl(detector):
    # Use daily frequency so PDH/PDL grouping works cleanly
    df = _make_ohlcv(n=100, freq="1d")
    levels = detector.detect(df, "1D", include_pdh_pdl=True)
    pdh_levels = [l for l in levels if l.level_type == LiquidityType.PDH]
    pdl_levels = [l for l in levels if l.level_type == LiquidityType.PDL]
    assert len(pdh_levels) >= 1
    assert len(pdl_levels) >= 1


def test_detect_session_extremes(detector):
    df = _make_ohlcv(n=200)
    levels = detector.detect(df, "1H", include_pdh_pdl=False)
    session_highs = [l for l in levels if l.level_type == LiquidityType.SESSION_HIGH]
    session_lows = [l for l in levels if l.level_type == LiquidityType.SESSION_LOW]
    assert len(session_highs) >= 1
    assert len(session_lows) >= 1


def test_sweep_classification(detector):
    df = _make_ohlcv_with_sweep()
    levels = detector.detect(df, "1H", include_pdh_pdl=False)
    highs = [l for l in levels if l.level_type == LiquidityType.SWING_HIGH]
    # At least one high should be classified as swept
    swept = [l for l in highs if l.sweep_status == SweepStatus.SWEPT]
    assert len(swept) >= 1


def test_levels_sorted_by_timestamp(detector):
    df = _make_ohlcv(n=200)
    levels = detector.detect(df, "1H")
    timestamps = [l.timestamp for l in levels]
    assert timestamps == sorted(timestamps)


def test_get_active_levels_filters_swept(detector):
    df = _make_ohlcv_with_sweep()
    active = detector.get_active_levels(df, "1H")
    for lvl in active:
        assert lvl.sweep_status == SweepStatus.UNTOUCHED


def test_missing_columns_raises():
    detector = LiquidityDetector()
    bad_df = pd.DataFrame({"open": [1.0], "high": [2.0]}, index=pd.date_range("2024-01-01", periods=1))
    with pytest.raises(ValueError, match="missing columns"):
        detector.detect(bad_df, "1H")


def test_empty_dataframe_returns_empty(detector):
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty.index = pd.DatetimeIndex([])
    levels = detector.detect(empty, "1H")
    assert levels == []


def test_equal_highs_detected(detector):
    n = 60
    df = _make_ohlcv(n=n, base=1000.0)
    # Plant two almost identical swing highs
    for idx in [10, 30]:
        df.loc[df.index[idx], "high"] = 1050.0
        df.loc[df.index[idx], "close"] = 1049.0
        for offset in range(1, 4):
            for i in [idx - offset, idx + offset]:
                if 0 <= i < n:
                    df.loc[df.index[i], "high"] = 1040.0

    levels = detector.detect(df, "1H", include_pdh_pdl=False)
    equal_highs = [l for l in levels if l.level_type == LiquidityType.EQUAL_HIGH]
    assert len(equal_highs) >= 1


def test_level_price_is_float(detector):
    df = _make_ohlcv()
    levels = detector.detect(df, "1H")
    for lvl in levels:
        assert isinstance(lvl.price, float)


def test_level_timeframe_preserved(detector):
    df = _make_ohlcv()
    for tf in ["1h", "4h", "1d"]:
        levels = detector.detect(df, tf, include_pdh_pdl=False)
        for lvl in levels:
            assert lvl.timeframe == tf
