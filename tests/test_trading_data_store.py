"""Tests for the universal DataStore (src/trading/data/store.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.trading.data.store import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(periods: int = 50, base_price: float = 2000.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=periods, freq="1h", tz="UTC")
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


@pytest.fixture
def store(tmp_path):
    """Fresh DataStore in a temporary directory."""
    return DataStore(base_dir=tmp_path / "trading_store")


# ---------------------------------------------------------------------------
# Save and load
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_save_returns_path(self, store):
        df = _make_ohlcv()
        path = store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        assert Path(path).exists()

    def test_load_roundtrip(self, store):
        df = _make_ohlcv(50)
        store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        loaded = store.load("XAUUSD", "1H", source="test")
        assert len(loaded) == len(df)
        pd.testing.assert_frame_equal(loaded.reset_index(drop=True), df.reset_index(drop=True))

    def test_load_date_filter(self, store):
        df = _make_ohlcv(100)
        store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        start = "2024-01-02"
        loaded = store.load("XAUUSD", "1H", start=start, source="test")
        assert all(loaded.index >= pd.Timestamp(start, tz="UTC"))

    def test_load_end_filter(self, store):
        df = _make_ohlcv(100)
        store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        end = "2024-01-03"
        loaded = store.load("XAUUSD", "1H", end=end, source="test")
        assert all(loaded.index <= pd.Timestamp(end, tz="UTC"))

    def test_load_not_found_returns_empty(self, store):
        result = store.load("XAUUSD", "5m")
        assert result.empty

    def test_save_upserts_metadata(self, store):
        df1 = _make_ohlcv(10)
        df2 = _make_ohlcv(20)
        store.save(df1, symbol="USOIL", timeframe="1H", source="test")
        store.save(df2, symbol="USOIL", timeframe="1H", source="test")
        catalogue = store.list_entries()
        # Only one entry for same (symbol, timeframe, source)
        entries = catalogue[
            (catalogue["symbol"] == "USOIL") & (catalogue["timeframe"] == "1H")
        ]
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------


class TestNormalisation:
    def test_uppercase_columns_normalised(self, store):
        df = _make_ohlcv(10)
        df.columns = [c.upper() for c in df.columns]
        path = store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        loaded = store.load("XAUUSD", "1H", source="test")
        assert "open" in loaded.columns

    def test_missing_volume_filled_with_zero(self, store):
        df = _make_ohlcv(10).drop(columns=["volume"])
        store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        loaded = store.load("XAUUSD", "1H", source="test")
        assert "volume" in loaded.columns
        assert (loaded["volume"] == 0.0).all()

    def test_missing_required_column_raises(self, store):
        df = _make_ohlcv(10).drop(columns=["close"])
        with pytest.raises(ValueError, match="close"):
            store.save(df, symbol="XAUUSD", timeframe="1H", source="test")

    def test_naive_index_localised_to_utc(self, store):
        df = _make_ohlcv(10)
        df.index = df.index.tz_localize(None)
        store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        loaded = store.load("XAUUSD", "1H", source="test")
        assert loaded.index.tz is not None


# ---------------------------------------------------------------------------
# Catalogue metadata
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_list_entries_empty_on_fresh_store(self, store):
        result = store.list_entries()
        assert result.empty

    def test_resample_from_recorded(self, store):
        df = _make_ohlcv(50)
        store.save(df, symbol="XAUUSD", timeframe="3H", source="yfinance", resample_from="1H")
        cat = store.list_entries()
        row = cat[(cat["symbol"] == "XAUUSD") & (cat["timeframe"] == "3H")].iloc[0]
        assert row["resample_from"] == "1H"

    def test_rows_count_correct(self, store):
        n = 37
        df = _make_ohlcv(n)
        store.save(df, symbol="XAUUSD", timeframe="1H", source="test")
        cat = store.list_entries()
        assert cat.iloc[0]["rows"] == n


# ---------------------------------------------------------------------------
# Refresh / incremental update
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_with_mock_fetcher(self, store):
        """refresh() merges new data from a mock fetcher."""

        class _MockFetcher:
            call_count = 0

            def fetch(self, symbol, timeframe, start=None, end=None):
                self.call_count += 1
                periods = 20
                index = pd.date_range(
                    "2024-02-01" if start is None else start,
                    periods=periods,
                    freq="1h",
                    tz="UTC",
                )
                return pd.DataFrame(
                    {
                        "open": [2000.0] * periods,
                        "high": [2010.0] * periods,
                        "low": [1990.0] * periods,
                        "close": [2005.0] * periods,
                        "volume": [100.0] * periods,
                    },
                    index=index,
                )

        fetcher = _MockFetcher()
        # First refresh (no existing data)
        df = store.refresh("XAUUSD", "1H", fetcher, source="mock")
        assert len(df) == 20

        # Second refresh (incremental — should still call fetcher)
        df2 = store.refresh("XAUUSD", "1H", fetcher, source="mock")
        assert fetcher.call_count == 2
