"""Tests for network-aware trading data source fallback."""

from __future__ import annotations

import socket

import pandas as pd
import pytest

from src.trading.backtest.input_contract import ensure_long_run_inputs
from src.trading.data.source_manager import DataSourceManager, ImportFileSpec
from src.trading.data.store import DataStore


def _make_ohlcv(periods: int = 20, freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq=freq, tz="UTC")
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


@pytest.fixture
def store(tmp_path):
    return DataStore(base_dir=tmp_path / "trading_store")


def test_check_yahoo_access_offline_dns(monkeypatch, store):
    manager = DataSourceManager(store=store)

    def _boom(_host):
        raise OSError("dns blocked")

    monkeypatch.setattr(socket, "gethostbyname", _boom)
    ok, reason = manager.check_yahoo_access()
    assert not ok
    assert reason.startswith("dns_failed:")


def test_fallback_prefers_local_store(store):
    df = _make_ohlcv()
    store.save(df, "XAUUSD", "1H", source="local_cache")

    class _Fetcher:
        called = 0

        def fetch(self, *args, **kwargs):
            self.called += 1
            return _make_ohlcv()

    fetcher = _Fetcher()
    manager = DataSourceManager(store=store, fetcher=fetcher)
    result = manager.get("XAUUSD", "1H")

    assert result.status == "ok"
    assert result.source.startswith("store:")
    assert not result.df.empty
    assert fetcher.called == 0


def test_fallback_to_imported_file_when_store_empty(tmp_path, store):
    csv_path = tmp_path / "xauusd_1h.csv"
    data = _make_ohlcv()
    data.reset_index(names="time").to_csv(csv_path, index=False)

    manager = DataSourceManager(
        store=store,
        file_sources={
            ("XAUUSD", "1H"): ImportFileSpec(path=csv_path, source="imported_csv")
        },
    )
    result = manager.get("XAUUSD", "1H", allow_yahoo=False)

    assert result.status == "ok"
    assert result.source == "imported_csv"
    assert not result.df.empty

    cached = store.load("XAUUSD", "1H", source="imported_csv")
    assert not cached.empty


def test_no_network_no_data_returns_graceful_unavailable(monkeypatch, store):
    manager = DataSourceManager(store=store)
    monkeypatch.setattr(manager, "check_yahoo_access", lambda: (False, "dns_blocked"))

    result = manager.get("WTIUSD", "15m")

    assert result.status == "unavailable"
    assert result.df.empty
    assert "store_empty" in result.detail
    assert "yfinance_skipped:dns_blocked" in result.detail
    assert "imported_file_unconfigured" in result.detail


def test_long_run_contract_auto_populates_from_fallback(tmp_path):
    store = DataStore(base_dir=tmp_path / "trading_store")
    csv_path = tmp_path / "wti_4h.csv"
    df = _make_ohlcv(freq="4h")
    df.reset_index(names="time").to_csv(csv_path, index=False)

    manager = DataSourceManager(
        store=store,
        file_sources={
            ("WTIUSD", "4H"): ImportFileSpec(path=csv_path, source="imported_csv")
        },
    )
    result = ensure_long_run_inputs(
        store=store,
        source_manager=manager,
        start="2016-01-01",
        end="2026-01-01",
        symbols=["WTIUSD"],
        timeframes=["4H"],
    )

    assert result["ok"] is True
    assert result["long_run"] is True
    assert result["items"][0]["status"] == "populated"
