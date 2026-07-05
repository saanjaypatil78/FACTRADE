"""
Tests for signal generation, risk management, and liquidity detection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np
import pytest

from src.trading.candle import Candle, Signal
from src.trading.liquidity_detector import LiquidityDetector
from src.trading.risk_manager import RiskManager
from src.trading.signal_generator import SignalGenerator, _smma, _bollinger, _calc_vwap


# ================================================================== #
# Helpers
# ================================================================== #

def _make_candles(
    n: int,
    base_price: float = 2000.0,
    symbol: str = "XAUUSD",
    timeframe: str = "1H",
    trend: float = 0.0,       # price drift per bar
    noise: float = 2.0,       # random ± noise
    volume: float = 1000.0,
    seed: int = 42,
) -> List[Candle]:
    rng = np.random.default_rng(seed)
    candles = []
    price = base_price
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        ts = start + timedelta(hours=i)
        o = price
        price += trend + rng.uniform(-noise, noise)
        c = price
        h = max(o, c) + rng.uniform(0, noise)
        l = min(o, c) - rng.uniform(0, noise)
        candles.append(Candle(ts, o, h, l, c, volume, symbol, timeframe))
    return candles


def _make_trending_candles(n: int, direction: str = "up", base: float = 2000.0) -> List[Candle]:
    """Make candles with a clear trend for SMMA ribbon tests."""
    drift = 1.0 if direction == "up" else -1.0
    return _make_candles(n, base_price=base, trend=drift, noise=0.3, seed=7)


# ================================================================== #
# RiskManager tests
# ================================================================== #

class TestRiskManager:
    def test_atr_zero_for_too_few_candles(self):
        rm = RiskManager(atr_period=14)
        candles = _make_candles(5)
        assert rm.atr(candles) == 0.0

    def test_atr_positive_for_enough_candles(self):
        rm = RiskManager(atr_period=14)
        candles = _make_candles(50)
        atr = rm.atr(candles)
        assert atr > 0

    def test_atr_increases_with_volatility(self):
        rm = RiskManager(atr_period=14)
        low_vol = _make_candles(50, noise=0.5)
        high_vol = _make_candles(50, noise=10.0)
        assert rm.atr(high_vol) > rm.atr(low_vol)

    def test_calculate_sl_long(self):
        # Use very low noise so ATR stays small and sl_pips stays well under 200
        rm = RiskManager(atr_period=14, atr_multiplier=1.5, max_sl_pips=200)
        candles = _make_candles(50, noise=0.5)
        wick_low = 1990.0
        sl_price, sl_pips, skip = rm.calculate_sl("long", wick_low, candles, "XAUUSD")
        assert sl_price < wick_low
        assert sl_pips > 0
        assert not skip  # max_sl_pips set high, noise is tiny → always passes

    def test_calculate_sl_short(self):
        rm = RiskManager(atr_period=14, atr_multiplier=1.5, max_sl_pips=200)
        candles = _make_candles(50)
        wick_high = 2010.0
        sl_price, sl_pips, skip = rm.calculate_sl("short", wick_high, candles, "XAUUSD")
        assert sl_price > wick_high
        assert sl_pips > 0

    def test_sl_skip_when_too_large(self):
        rm = RiskManager(atr_period=14, atr_multiplier=50.0, max_sl_pips=5)
        candles = _make_candles(50, noise=5.0)
        sl_price, sl_pips, skip = rm.calculate_sl("long", 1990.0, candles, "XAUUSD")
        assert skip is True

    def test_calculate_tp_long(self):
        rm = RiskManager()
        tp1, tp2 = rm.calculate_tp("long", 2000.0, 1980.0, rr_tp1=2.0, rr_tp2=5.0)
        assert tp1 == pytest.approx(2040.0)
        assert tp2 == pytest.approx(2100.0)

    def test_calculate_tp_short(self):
        rm = RiskManager()
        tp1, tp2 = rm.calculate_tp("short", 2000.0, 2020.0, rr_tp1=2.0, rr_tp2=5.0)
        assert tp1 == pytest.approx(1960.0)
        assert tp2 == pytest.approx(1900.0)

    def test_lot_size_basic(self):
        rm = RiskManager(default_risk_pct=0.005)
        lot = rm.lot_size(account_balance=700.0, sl_pips=20.0, symbol="XAUUSD")
        assert lot >= 0.01

    def test_lot_size_zero_sl_returns_minimum(self):
        rm = RiskManager()
        lot = rm.lot_size(700.0, sl_pips=0.0, symbol="XAUUSD")
        assert lot == 0.01


# ================================================================== #
# LiquidityDetector tests
# ================================================================== #

class TestLiquidityDetector:
    def test_detect_returns_empty_for_too_few_candles(self):
        ld = LiquidityDetector(swing_bars=3)
        candles = _make_candles(5)
        levels = ld.detect(candles)
        assert levels == []

    def test_detects_swing_highs_and_lows(self):
        ld = LiquidityDetector(swing_bars=3)
        candles = _make_candles(50)
        levels = ld.detect(candles)
        kinds = {l.kind for l in levels}
        assert "swing_high" in kinds
        assert "swing_low" in kinds

    def test_sweep_detection_bullish(self):
        """A candle that wicks below a swing low then closes above = sweep."""
        ld = LiquidityDetector()
        from src.trading.candle import LiquidityLevel

        ts = datetime(2024, 1, 5, tzinfo=timezone.utc)
        level = LiquidityLevel(
            price=1990.0,
            kind="swing_low",
            formed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            symbol="XAUUSD",
            timeframe="1H",
        )
        # Wick below 1990, close above 1990
        sweep_candle = Candle(ts, 1995.0, 2000.0, 1985.0, 1998.0, 100.0, "XAUUSD", "1H")
        # No sweep – close stays below
        no_sweep_candle = Candle(ts, 1995.0, 1998.0, 1985.0, 1988.0, 100.0, "XAUUSD", "1H")

        assert ld._is_sweep(sweep_candle, level) is True
        assert ld._is_sweep(no_sweep_candle, level) is False

    def test_sweep_detection_bearish(self):
        """A candle wicking above a swing high then closing below = sweep."""
        ld = LiquidityDetector()
        from src.trading.candle import LiquidityLevel

        ts = datetime(2024, 1, 5, tzinfo=timezone.utc)
        level = LiquidityLevel(
            price=2010.0,
            kind="swing_high",
            formed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            symbol="XAUUSD",
            timeframe="1H",
        )
        sweep_candle = Candle(ts, 2005.0, 2015.0, 2000.0, 2002.0, 100.0, "XAUUSD", "1H")
        assert ld._is_sweep(sweep_candle, level) is True

    def test_pdh_pdl_only_for_daily_tf(self):
        ld = LiquidityDetector()
        daily = _make_candles(10, timeframe="1D")
        hourly = _make_candles(10, timeframe="1H")
        daily_levels = ld._pdh_pdl_levels(daily, "XAUUSD", "1D")
        hourly_levels = ld._pdh_pdl_levels(hourly, "XAUUSD", "1H")
        assert len(daily_levels) > 0
        assert len(hourly_levels) == 0

    def test_level_symbol_and_timeframe_set(self):
        ld = LiquidityDetector(swing_bars=3)
        candles = _make_candles(30, symbol="USOIL", timeframe="4H")
        levels = ld.detect(candles)
        for l in levels:
            assert l.symbol == "USOIL"
            # Timeframe may differ for PDH/PDL-derived; just check non-empty
            assert l.timeframe != ""


# ================================================================== #
# Indicator helper tests
# ================================================================== #

class TestIndicators:
    def test_smma_returns_nan_prefix(self):
        data = np.arange(1.0, 51.0)
        result = _smma(data, period=14)
        assert np.isnan(result[0])
        assert not np.isnan(result[-1])

    def test_smma_too_few_bars_all_nan(self):
        data = np.arange(1.0, 5.0)
        result = _smma(data, period=14)
        assert np.all(np.isnan(result))

    def test_bollinger_mid_equals_rolling_mean(self):
        data = np.array([float(i) for i in range(210)])
        mid, upper, lower = _bollinger(data, period=20, num_std=2.0)
        idx = 209
        expected_mid = np.mean(data[idx - 19 : idx + 1])
        assert mid[idx] == pytest.approx(expected_mid)

    def test_bollinger_upper_above_lower(self):
        data = np.array([float(i) + 0.1 * (i % 3) for i in range(210)])
        mid, upper, lower = _bollinger(data, period=20, num_std=2.0)
        valid = ~np.isnan(upper)
        assert np.all(upper[valid] >= lower[valid])

    def test_vwap_zero_volume_returns_none(self):
        candles = _make_candles(10, volume=0.0)
        result = _calc_vwap(candles)
        assert result is None

    def test_vwap_positive_for_nonzero_volume(self):
        candles = _make_candles(10, volume=1000.0)
        result = _calc_vwap(candles)
        assert result is not None
        assert result > 0


# ================================================================== #
# SignalGenerator – setup-level smoke tests
# ================================================================== #

class TestSignalGenerator:
    def _gen(self) -> SignalGenerator:
        rm = RiskManager(atr_period=14, atr_multiplier=1.5, max_sl_pips=500)
        return SignalGenerator(risk_manager=rm, swing_bars=3)

    def test_signal_has_sl_and_tp(self):
        """Any emitted signal must have deterministic SL and TP values."""
        gen = self._gen()
        candles = _make_candles(400, timeframe="15m")
        candles_by_tf = {
            "1H": _make_candles(400, timeframe="1H"),
            "15m": candles,
            "5m": _make_candles(400, timeframe="5m"),
        }
        signals = gen.scan(candles_by_tf, symbol="XAUUSD")
        for sig in signals:
            assert sig.stop_loss != 0
            assert sig.take_profit_1 != 0
            assert sig.take_profit_2 != 0
            assert sig.entry_price != 0
            assert sig.direction in ("long", "short")

    def test_signal_direction_consistent_with_sl(self):
        """For a long signal, SL must be below entry; for short, above."""
        gen = self._gen()
        candles_by_tf = {
            "1H": _make_candles(400, timeframe="1H"),
            "15m": _make_candles(400, timeframe="15m"),
            "5m": _make_candles(400, timeframe="5m"),
        }
        signals = gen.scan(candles_by_tf, symbol="XAUUSD")
        for sig in signals:
            if sig.direction == "long":
                assert sig.stop_loss < sig.entry_price, f"Long SL above entry: {sig}"
            else:
                assert sig.stop_loss > sig.entry_price, f"Short SL below entry: {sig}"

    def test_smma_ribbon_requires_enough_candles(self):
        gen = self._gen()
        too_few = _make_candles(10)
        assert gen.smma_ribbon_signal(too_few) is None

    def test_bb_reversion_requires_enough_candles(self):
        gen = self._gen()
        too_few = _make_candles(10)
        assert gen.bb_reversion_signal(too_few) is None

    def test_vwap_breakout_requires_enough_candles(self):
        gen = self._gen()
        too_few = _make_candles(5)
        assert gen.vwap_breakout_signal(too_few) is None

    def test_scan_returns_list(self):
        gen = self._gen()
        result = gen.scan({}, symbol="XAUUSD")
        assert isinstance(result, list)

    def test_signal_risk_reward_auto_computed(self):
        gen = self._gen()
        candles_by_tf = {
            "1H": _make_candles(400, timeframe="1H"),
            "15m": _make_candles(400, timeframe="15m"),
            "5m": _make_candles(400, timeframe="5m"),
        }
        signals = gen.scan(candles_by_tf, symbol="XAUUSD")
        for sig in signals:
            assert sig.risk_reward >= 0.0

    def test_ote_entry_long(self):
        in_ote, entry = SignalGenerator._ote_entry(
            "long", choch_high=2100.0, choch_low=2000.0, candle=_make_candles(1)[0]
        )
        # entry should be in the middle of the 0.618–0.786 retracement zone
        ote_low = 2100.0 - 100.0 * 0.786
        ote_high = 2100.0 - 100.0 * 0.618
        assert ote_low <= entry <= ote_high

    def test_ote_entry_short(self):
        in_ote, entry = SignalGenerator._ote_entry(
            "short", choch_high=2100.0, choch_low=2000.0,
            candle=_make_candles(1)[0]
        )
        ote_low = 2000.0 + 100.0 * 0.618
        ote_high = 2000.0 + 100.0 * 0.786
        assert ote_low <= entry <= ote_high
