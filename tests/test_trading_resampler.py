"""Tests for exact 3H/4H resampling (src/trading/data/resampler.py).

Validates that:
1. 3H bars align at 00:00/03:00/06:00/09:00/12:00/15:00/18:00/21:00 UTC.
2. 4H bars align at 00:00/04:00/08:00/12:00/16:00/20:00 UTC.
3. OHLCV aggregation is mathematically exact (high=max, low=min,
   open=first, close=last, volume=sum).
4. The ``validate_resampling`` helper passes on correct data and fails on
   corrupted data.
5. Incomplete (current) bar is dropped by default.
6. Unsupported timeframes raise ValueError.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.trading.data.resampler import resample, validate_resampling


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_1h_df(
    start: str = "2024-01-01",
    periods: int = 72,
    base_price: float = 2000.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Create a deterministic 1H OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    closes = base_price + np.cumsum(rng.normal(0, 2, periods))
    opens = np.roll(closes, 1)
    opens[0] = base_price
    highs = np.maximum(opens, closes) + rng.uniform(0, 1, periods)
    lows = np.minimum(opens, closes) - rng.uniform(0, 1, periods)
    volumes = rng.uniform(100, 1000, periods)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


# ---------------------------------------------------------------------------
# 3H alignment tests
# ---------------------------------------------------------------------------


class TestResample3H:
    """Validate exact 3H resampling."""

    def setup_method(self) -> None:
        # 73 × 1H bars starting at 00:00: bars 0–71 fill 24 complete 3H periods,
        # bar 72 (at 72:00) starts the 25th period (incomplete → dropped).
        # After drop_incomplete=True: exactly 24 complete 3H bars remain.
        self.df_1h = _make_1h_df(start="2024-01-01 00:00", periods=73)

    def test_3h_bar_count(self) -> None:
        result = resample(self.df_1h, "3H")
        # 73 hours from 00:00 → last bar at 72:00 is incomplete; expect 24 bars
        assert len(result) == 24, f"Expected 24 bars, got {len(result)}"

    def test_3h_alignment(self) -> None:
        result = resample(self.df_1h, "3H")
        # All bar timestamps must be divisible by 3 hours
        for ts in result.index:
            assert ts.hour % 3 == 0, f"Bar at {ts} not aligned to 3H boundary"
            assert ts.minute == 0
            assert ts.second == 0

    def test_3h_high_is_max(self) -> None:
        result = resample(self.df_1h, "3H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=3)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            expected_high = constituent["high"].max()
            assert result.loc[ts, "high"] == pytest.approx(expected_high), (
                f"High mismatch at {ts}"
            )

    def test_3h_low_is_min(self) -> None:
        result = resample(self.df_1h, "3H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=3)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            expected_low = constituent["low"].min()
            assert result.loc[ts, "low"] == pytest.approx(expected_low), (
                f"Low mismatch at {ts}"
            )

    def test_3h_open_is_first(self) -> None:
        result = resample(self.df_1h, "3H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=3)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            expected_open = constituent["open"].iloc[0]
            assert result.loc[ts, "open"] == pytest.approx(expected_open), (
                f"Open mismatch at {ts}"
            )

    def test_3h_close_is_last(self) -> None:
        result = resample(self.df_1h, "3H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=3)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            expected_close = constituent["close"].iloc[-1]
            assert result.loc[ts, "close"] == pytest.approx(expected_close), (
                f"Close mismatch at {ts}"
            )

    def test_3h_volume_is_sum(self) -> None:
        result = resample(self.df_1h, "3H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=3)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            expected_vol = constituent["volume"].sum()
            assert result.loc[ts, "volume"] == pytest.approx(expected_vol), (
                f"Volume mismatch at {ts}"
            )


# ---------------------------------------------------------------------------
# 4H alignment tests
# ---------------------------------------------------------------------------


class TestResample4H:
    """Validate exact 4H resampling."""

    def setup_method(self) -> None:
        # 96 × 1H bars = 24 complete 4H bars
        self.df_1h = _make_1h_df(start="2024-01-01 00:00", periods=97)

    def test_4h_bar_count(self) -> None:
        result = resample(self.df_1h, "4H")
        assert len(result) == 24, f"Expected 24 bars, got {len(result)}"

    def test_4h_alignment(self) -> None:
        result = resample(self.df_1h, "4H")
        for ts in result.index:
            assert ts.hour % 4 == 0, f"Bar at {ts} not aligned to 4H boundary"
            assert ts.minute == 0

    def test_4h_high_is_max(self) -> None:
        result = resample(self.df_1h, "4H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=4)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            assert result.loc[ts, "high"] == pytest.approx(constituent["high"].max())

    def test_4h_low_is_min(self) -> None:
        result = resample(self.df_1h, "4H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=4)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            assert result.loc[ts, "low"] == pytest.approx(constituent["low"].min())

    def test_4h_volume_is_sum(self) -> None:
        result = resample(self.df_1h, "4H")
        for ts in result.index:
            bar_end = ts + pd.Timedelta(hours=4)
            constituent = self.df_1h[
                (self.df_1h.index >= ts) & (self.df_1h.index < bar_end)
            ]
            assert result.loc[ts, "volume"] == pytest.approx(constituent["volume"].sum())


# ---------------------------------------------------------------------------
# validate_resampling helper
# ---------------------------------------------------------------------------


class TestValidateResampling:
    """Tests for the validate_resampling correctness checker."""

    def setup_method(self) -> None:
        self.df_1h = _make_1h_df(start="2024-01-01 00:00", periods=48)
        self.df_3h = resample(self.df_1h, "3H")

    def test_valid_resampling_passes(self) -> None:
        result = validate_resampling(self.df_1h, self.df_3h, "3H")
        assert result["valid"] is True, f"Errors: {result['errors']}"

    def test_corrupted_high_fails(self) -> None:
        corrupted = self.df_3h.copy()
        corrupted.iloc[0, corrupted.columns.get_loc("high")] -= 999.0  # absurdly low
        result = validate_resampling(self.df_1h, corrupted, "3H")
        assert result["valid"] is False
        assert any("high mismatch" in e for e in result["errors"])

    def test_corrupted_low_fails(self) -> None:
        corrupted = self.df_3h.copy()
        corrupted.iloc[0, corrupted.columns.get_loc("low")] += 999.0
        result = validate_resampling(self.df_1h, corrupted, "3H")
        assert result["valid"] is False
        assert any("low mismatch" in e for e in result["errors"])

    def test_valid_4h_resampling_passes(self) -> None:
        df_4h = resample(self.df_1h, "4H")
        result = validate_resampling(self.df_1h, df_4h, "4H")
        assert result["valid"] is True, f"Errors: {result['errors']}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestResampleEdgeCases:
    """Edge case tests."""

    def test_unsupported_timeframe_raises(self) -> None:
        df = _make_1h_df()
        with pytest.raises(ValueError, match="Unknown timeframe"):
            resample(df, "7H")

    def test_empty_df_returns_empty(self) -> None:
        df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        result = resample(df, "3H")
        assert result.empty

    def test_missing_column_raises(self) -> None:
        df = _make_1h_df()
        df = df.drop(columns=["high"])
        with pytest.raises(ValueError, match="missing required columns"):
            resample(df, "3H")

    def test_naive_datetime_index_localised(self) -> None:
        """Naive DatetimeIndex should be treated as UTC without error."""
        df = _make_1h_df(periods=24)
        df.index = df.index.tz_localize(None)  # strip timezone
        result = resample(df, "3H")
        assert not result.empty
        assert result.index.tz is not None  # should be UTC after resampling

    def test_drop_incomplete_false(self) -> None:
        """With drop_incomplete=False, last (partial) bar is included."""
        # 7 x 1H bars → 2 complete 3H bars + 1 partial bar (1H)
        df = _make_1h_df(start="2024-01-01 00:00", periods=7)
        result_drop = resample(df, "3H", drop_incomplete=True)
        result_keep = resample(df, "3H", drop_incomplete=False)
        assert len(result_keep) == len(result_drop) + 1

    def test_1d_resampling_from_1h(self) -> None:
        """Daily resampling from 1H data.

        73 × 1H bars = 3 complete days (00:00–23:00 each) + 1 partial bar
        at day-4 00:00.  With drop_incomplete=True the partial bar is dropped,
        leaving exactly 3 complete daily bars.
        """
        df = _make_1h_df(start="2024-01-01 00:00", periods=73)
        result = resample(df, "1D")
        assert len(result) == 3, f"Expected 3 bars, got {len(result)}"
        for ts in result.index:
            assert ts.hour == 0

    def test_reproducibility(self) -> None:
        """Same input always produces identical output (deterministic)."""
        df = _make_1h_df(seed=42)
        r1 = resample(df, "4H")
        r2 = resample(df, "4H")
        pd.testing.assert_frame_equal(r1, r2)

    def test_non_midnight_start_alignment(self) -> None:
        """Resampling should align to epoch, not start of data."""
        # Start at 01:00 UTC — 3H bars should still be at 00:00/03:00/06:00
        df = _make_1h_df(start="2024-01-01 01:00", periods=24)
        result = resample(df, "3H")
        for ts in result.index:
            assert ts.hour % 3 == 0, f"Bar at {ts} not on 3H boundary"
