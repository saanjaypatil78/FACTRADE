"""
Tests for src/trading/signal_generator.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.trading.liquidity_detector import LiquidityLevel, LiquidityType, SweepStatus
from src.trading.signal_generator import (
    SignalGenerator,
    TradeSignal,
    SignalDirection,
    MarketRegime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 500,
    base: float = 3200.0,
    trend: float = 0.0,
    noise: float = 5.0,
    seed: int = 1,
    freq: str = "15min",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(trend, noise, n))
    highs = closes + rng.uniform(0.5, 5.0, n)
    lows = closes - rng.uniform(0.5, 5.0, n)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    volumes = rng.integers(50, 500, n).astype(float)
    index = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def _make_swept_htf_level(
    price: float = 3250.0,
    level_type: LiquidityType = LiquidityType.SWING_HIGH,
    sweep_ts: pd.Timestamp = None,
) -> LiquidityLevel:
    if sweep_ts is None:
        sweep_ts = pd.Timestamp("2024-01-02")
    return LiquidityLevel(
        price=price,
        level_type=level_type,
        timeframe="1H",
        timestamp=pd.Timestamp("2024-01-01 12:00"),
        sweep_status=SweepStatus.SWEPT,
        sweep_timestamp=sweep_ts,
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def generator():
    return SignalGenerator(
        ote_low=0.618,
        ote_high=0.786,
        max_sl_pips=100.0,  # relaxed for tests
        min_displacement_pct=50.0,  # relaxed for synthetic data
    )


def test_generator_initialisation(generator):
    assert generator.ote_low == 0.618
    assert generator.ote_high == 0.786
    assert generator.max_sl_pips == 100.0


def test_generate_returns_list(generator):
    df = _make_ohlcv()
    signals = generator.generate(df, [], "XAUUSD", "15m")
    assert isinstance(signals, list)


def test_generate_no_signals_without_htf_levels(generator):
    df = _make_ohlcv()
    signals = generator.generate(df, [], "XAUUSD", "15m")
    assert signals == []


def test_generate_skips_untouched_levels(generator):
    df = _make_ohlcv()
    untouched = LiquidityLevel(
        price=3250.0,
        level_type=LiquidityType.SWING_HIGH,
        timeframe="1H",
        timestamp=pd.Timestamp("2024-01-01"),
        sweep_status=SweepStatus.UNTOUCHED,
    )
    signals = generator.generate(df, [untouched], "XAUUSD", "15m")
    assert signals == []


def test_generate_skips_run_levels(generator):
    df = _make_ohlcv()
    run_level = LiquidityLevel(
        price=3100.0,
        level_type=LiquidityType.SWING_LOW,
        timeframe="1H",
        timestamp=pd.Timestamp("2024-01-01"),
        sweep_status=SweepStatus.RUN,
        sweep_timestamp=pd.Timestamp("2024-01-01 06:00"),
    )
    signals = generator.generate(df, [run_level], "XAUUSD", "15m")
    assert signals == []


def test_trade_signal_fields():
    sig = TradeSignal(
        symbol="XAUUSD",
        direction=SignalDirection.LONG,
        entry_price=3200.0,
        stop_loss=3180.0,
        take_profit_1=3230.0,
        take_profit_2=3260.0,
        timeframe="15m",
        timestamp=pd.Timestamp("2024-01-02"),
    )
    assert sig.risk_pips == pytest.approx(20.0)
    assert sig.reward_pips == pytest.approx(30.0)
    assert sig.rr_ratio == pytest.approx(1.5)


def test_trade_signal_short_rr():
    sig = TradeSignal(
        symbol="XAUUSD",
        direction=SignalDirection.SHORT,
        entry_price=3200.0,
        stop_loss=3210.0,
        take_profit_1=3170.0,
        take_profit_2=3140.0,
        timeframe="15m",
        timestamp=pd.Timestamp("2024-01-02"),
    )
    assert sig.risk_pips == pytest.approx(10.0)
    assert sig.reward_pips == pytest.approx(30.0)
    assert sig.rr_ratio == pytest.approx(3.0)


def test_ote_zone_long(generator):
    low_p, high_p = generator._ote_zone(
        swing_origin=3180.0,
        displacement_end=3220.0,
        direction=SignalDirection.LONG,
    )
    move = 3220.0 - 3180.0  # = 40
    expected_high = 3220.0 - 0.618 * 40   # 3195.28
    expected_low = 3220.0 - 0.786 * 40    # 3188.56
    assert low_p == pytest.approx(expected_low, rel=1e-4)
    assert high_p == pytest.approx(expected_high, rel=1e-4)


def test_ote_zone_short(generator):
    low_p, high_p = generator._ote_zone(
        swing_origin=3220.0,
        displacement_end=3180.0,
        direction=SignalDirection.SHORT,
    )
    move = abs(3180.0 - 3220.0)  # = 40
    expected_low = 3180.0 + 0.618 * move   # 3204.72
    expected_high = 3180.0 + 0.786 * move  # 3211.44
    assert low_p == pytest.approx(expected_low, rel=1e-4)
    assert high_p == pytest.approx(expected_high, rel=1e-4)


def test_ote_zone_ordering(generator):
    for direction in (SignalDirection.LONG, SignalDirection.SHORT):
        lo, hi = generator._ote_zone(3100.0, 3200.0, direction)
        assert lo <= hi


def test_calculate_atr_positive():
    df = _make_ohlcv(n=50)
    atr = SignalGenerator._calculate_atr(df)
    assert atr > 0


def test_smma_length():
    series = pd.Series(range(100), dtype=float)
    result = SignalGenerator._smma(series, period=10)
    assert len(result) == 100


def test_bollinger_bands():
    series = pd.Series(np.ones(300) * 3200.0, dtype=float)
    mid, upper, lower = SignalGenerator._bollinger(series, period=20, std_mult=2.0)
    # For a constant series std = 0 → upper = lower = mid
    assert upper.iloc[-1] == pytest.approx(lower.iloc[-1], abs=1e-6)


def test_detect_regime_returns_valid(generator):
    df = _make_ohlcv(n=500)
    regime = generator.detect_regime(df)
    assert isinstance(regime, MarketRegime)


def test_detect_regime_insufficient_data(generator):
    df = _make_ohlcv(n=10)
    regime = generator.detect_regime(df)
    assert regime == MarketRegime.UNDEFINED


def test_generate_insufficient_ltf_data(generator):
    df = _make_ohlcv(n=50)  # less than bb_period (199)
    level = _make_swept_htf_level()
    signals = generator.generate(df, [level], "XAUUSD", "15m")
    assert signals == []


def test_signal_notes_contains_timeframe(generator):
    """If a signal is generated its notes should reference the HTF timeframe."""
    # Use a very small max_sl_pips=1000 and min_displacement_pct=1 to force a signal
    gen = SignalGenerator(
        ote_low=0.0,   # accept all retracements
        ote_high=1.0,
        max_sl_pips=10000.0,
        min_displacement_pct=1.0,
    )
    df = _make_ohlcv(n=500, base=3200.0, noise=10.0)
    # Mark level as swept very early
    sweep_ts = df.index[5]
    htf_level = _make_swept_htf_level(
        price=3200.0,
        level_type=LiquidityType.SWING_HIGH,
        sweep_ts=sweep_ts,
    )
    signals = gen.generate(df, [htf_level], "XAUUSD", "15m")
    # If a signal is generated, verify it has expected fields
    for sig in signals:
        assert "1H" in sig.notes
        assert sig.symbol == "XAUUSD"
        assert sig.stop_loss != sig.entry_price
        assert sig.take_profit_1 != sig.entry_price
