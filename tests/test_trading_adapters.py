"""
Tests for data adapters and candle normalization.
"""

from __future__ import annotations

import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.trading.candle import Candle
from src.trading.adapters.base import BaseAdapter
from src.trading.adapters.csv_adapter import CSVAdapter
from src.trading.adapters.yfinance_adapter import YFinanceAdapter


# ================================================================== #
# Fixtures / helpers
# ================================================================== #

def _make_candle(**kwargs) -> Candle:
    defaults = dict(
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        open=2000.0,
        high=2010.0,
        low=1990.0,
        close=2005.0,
        volume=1000.0,
        symbol="XAUUSD",
        timeframe="1H",
    )
    defaults.update(kwargs)
    return Candle(**defaults)


MT4_CSV = """\
DATE,TIME,OPEN,HIGH,LOW,CLOSE,TICKVOL
2024.01.01,00:00,2000.00,2010.00,1990.00,2005.00,1234
2024.01.01,01:00,2005.00,2015.00,1995.00,2010.00,2345
2024.01.01,02:00,2010.00,2020.00,2000.00,2015.00,3456
"""

STANDARD_CSV = """\
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,2000.00,2010.00,1990.00,2005.00,1234
2024-01-01 01:00:00,2005.00,2015.00,1995.00,2010.00,2345
2024-01-01 02:00:00,2010.00,2020.00,2000.00,2015.00,3456
"""

TV_CSV = """\
time,open,high,low,close,Volume
2024-01-01 00:00:00,2000.00,2010.00,1990.00,2005.00,1234
2024-01-01 01:00:00,2005.00,2015.00,1995.00,2010.00,2345
"""


# ================================================================== #
# Candle schema tests
# ================================================================== #

class TestCandleSchema:
    def test_basic_properties(self):
        c = _make_candle(open=2000.0, close=2010.0, high=2020.0, low=1990.0)
        assert c.is_bullish
        assert not c.is_bearish
        assert c.body_size == pytest.approx(10.0)
        assert c.range == pytest.approx(30.0)
        assert c.upper_wick == pytest.approx(10.0)
        assert c.lower_wick == pytest.approx(10.0)

    def test_bearish_candle(self):
        c = _make_candle(open=2010.0, close=2000.0, high=2020.0, low=1990.0)
        assert c.is_bearish
        assert not c.is_bullish

    def test_doji(self):
        c = _make_candle(open=2000.0, close=2000.0)
        assert c.body_size == 0.0

    def test_repr_does_not_raise(self):
        c = _make_candle()
        assert "XAUUSD" in repr(c)


# ================================================================== #
# BaseAdapter validation tests
# ================================================================== #

class TestBaseAdapterValidation:
    def test_valid_candle_passes(self):
        c = _make_candle()
        assert BaseAdapter._validate_candle(c) is True

    def test_high_below_low_fails(self):
        c = _make_candle(high=1980.0, low=1990.0)
        assert BaseAdapter._validate_candle(c) is False

    def test_high_below_close_fails(self):
        c = _make_candle(close=2020.0, high=2010.0)
        assert BaseAdapter._validate_candle(c) is False

    def test_zero_price_fails(self):
        c = _make_candle(open=0.0)
        assert BaseAdapter._validate_candle(c) is False

    def test_filter_valid_removes_bad(self):
        good = _make_candle()
        bad = _make_candle(high=1980.0, low=1990.0)
        result = BaseAdapter._filter_valid([good, bad])
        assert result == [good]


# ================================================================== #
# CSV Adapter tests
# ================================================================== #

class TestCSVAdapter:

    def _write_tmp(self, content: str, suffix: str = ".csv") -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    def test_load_mt4_format(self):
        path = self._write_tmp(MT4_CSV)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        candles = adapter.fetch()
        assert len(candles) == 3
        assert candles[0].open == pytest.approx(2000.0)
        assert candles[0].symbol == "XAUUSD"
        assert candles[0].timeframe == "1H"

    def test_load_standard_format(self):
        path = self._write_tmp(STANDARD_CSV)
        adapter = CSVAdapter(path, symbol="USOIL", timeframe="15m")
        candles = adapter.fetch()
        assert len(candles) == 3
        assert candles[0].symbol == "USOIL"
        assert candles[0].timeframe == "15m"

    def test_load_tradingview_format(self):
        path = self._write_tmp(TV_CSV)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        candles = adapter.fetch()
        assert len(candles) == 2

    def test_timestamps_are_utc(self):
        path = self._write_tmp(STANDARD_CSV)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        candles = adapter.fetch()
        for c in candles:
            assert c.timestamp.tzinfo is not None
            assert c.timestamp.utcoffset().total_seconds() == 0

    def test_date_range_filter(self):
        path = self._write_tmp(STANDARD_CSV)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        start = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
        candles = adapter.fetch(start=start)
        assert len(candles) == 2
        assert all(c.timestamp >= start for c in candles)

    def test_limit_parameter(self):
        path = self._write_tmp(STANDARD_CSV)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        candles = adapter.fetch(limit=2)
        assert len(candles) == 2

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            adapter = CSVAdapter("/nonexistent/path.csv", "XAUUSD", "1H")
            adapter.fetch()

    def test_missing_required_columns_raises(self):
        bad_csv = "timestamp,open\n2024-01-01,2000\n"
        path = self._write_tmp(bad_csv)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        with pytest.raises(ValueError, match="missing required columns"):
            adapter.fetch()
    def test_sorted_oldest_first(self):
        reversed_csv = """\
timestamp,open,high,low,close,volume
2024-01-01 02:00:00,2010.00,2020.00,2000.00,2015.00,3456
2024-01-01 00:00:00,2000.00,2010.00,1990.00,2005.00,1234
2024-01-01 01:00:00,2005.00,2015.00,1995.00,2010.00,2345
"""
        path = self._write_tmp(reversed_csv)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H")
        candles = adapter.fetch()
        timestamps = [c.timestamp for c in candles]
        assert timestamps == sorted(timestamps)

    def test_timeframe_alias_normalisation(self):
        path = self._write_tmp(STANDARD_CSV)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="h1")
        candles = adapter.fetch()
        assert candles[0].timeframe == "1H"

    def test_semicolon_delimiter(self):
        semi_csv = "timestamp;open;high;low;close;volume\n"
        semi_csv += "2024-01-01 00:00:00;2000;2010;1990;2005;100\n"
        path = self._write_tmp(semi_csv)
        adapter = CSVAdapter(path, symbol="XAUUSD", timeframe="1H", delimiter=";")
        candles = adapter.fetch()
        assert len(candles) == 1


# ================================================================== #
# YFinance Adapter symbol mapping tests (no network calls)
# ================================================================== #

class TestYFinanceAdapterMapping:
    def test_symbol_map_gold(self):
        from src.trading.adapters.yfinance_adapter import _SYMBOL_MAP
        assert _SYMBOL_MAP["XAUUSD"] == "GC=F"
        assert _SYMBOL_MAP["GOLD"] == "GC=F"

    def test_symbol_map_oil(self):
        from src.trading.adapters.yfinance_adapter import _SYMBOL_MAP
        assert _SYMBOL_MAP["USOIL"] == "CL=F"
        assert _SYMBOL_MAP["WTI"] == "CL=F"
        assert _SYMBOL_MAP["CRUDE"] == "CL=F"

    def test_tf_map_coverage(self):
        from src.trading.adapters.yfinance_adapter import _TF_MAP
        for tf in ["1m", "5m", "15m", "30m", "1H", "4H", "1D"]:
            assert tf in _TF_MAP

    def test_adapter_instantiation(self):
        adapter = YFinanceAdapter()
        assert adapter.name == "yfinance"
        assert adapter.supports_live is True
