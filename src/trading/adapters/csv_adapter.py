"""
CSV Adapter – import broker-exported OHLCV data (MT4/MT5, cTrader, etc.)

This is the **recommended** adapter for exact-symbol fidelity (true XAUUSD
spot or exact WTI CFD prices) because it uses data you export directly from
your own broker with zero paid-data fees.

Supported column layouts (auto-detected, case-insensitive):

  1. MT4 / MT5  : DATE, TIME, OPEN, HIGH, LOW, CLOSE, TICKVOL[, VOL][, SPREAD]
  2. Standard   : TIMESTAMP (or DATE), OPEN, HIGH, LOW, CLOSE, VOLUME
  3. TradingView: time, open, high, low, close, Volume (optional)

The adapter merges DATE+TIME columns when present and falls back to a
unix-timestamp column if "timestamp" is not found.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import structlog

from src.trading.adapters.base import BaseAdapter
from src.trading.candle import Candle

logger = structlog.get_logger(__name__)

# Normalised column name mapping (raw → canonical)
_COL_ALIASES: Dict[str, str] = {
    # timestamp variants
    "date": "date",
    "time": "time",
    "datetime": "timestamp",
    "timestamp": "timestamp",
    # OHLCV
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "vol": "volume",
    "tickvol": "volume",
    "tick_vol": "volume",
    "tick volume": "volume",
    "real_volume": "volume",
}


def _normalise_col(raw: str) -> str:
    return _COL_ALIASES.get(raw.strip().lower(), raw.strip().lower())


# Timeframe aliases accepted in the symbol/timeframe argument
_TF_ALIASES: Dict[str, str] = {
    "d": "1D", "1d": "1D", "daily": "1D",
    "w": "1W", "1w": "1W", "weekly": "1W",
    "h4": "4H", "4h": "4H",
    "h3": "3H", "3h": "3H",
    "h1": "1H", "1h": "1H",
    "m30": "30m", "30m": "30m",
    "m15": "15m", "15m": "15m",
    "m5": "5m", "5m": "5m",
    "m3": "3m", "3m": "3m",
    "m1": "1m", "1m": "1m",
}


def _normalise_tf(raw: str) -> str:
    return _TF_ALIASES.get(raw.strip().lower(), raw.strip().upper())


class CSVAdapter(BaseAdapter):
    """
    Load broker-exported OHLCV CSV files.

    Parameters
    ----------
    file_path:
        Path to the CSV file.
    symbol:
        Symbol name (e.g. ``"XAUUSD"`` or ``"USOIL"``).
    timeframe:
        Timeframe string, e.g. ``"1H"`` or ``"15m"``.
    datetime_format:
        strptime format used for the timestamp column.  If ``None`` the
        adapter tries pandas ``pd.to_datetime`` with ``infer_datetime_format``.
    delimiter:
        CSV field delimiter; defaults to auto-detect.
    tz:
        Timezone for naïve timestamps (defaults to UTC).
    """

    name = "csv"
    supports_live = False

    def __init__(
        self,
        file_path: str | Path,
        symbol: str,
        timeframe: str,
        datetime_format: Optional[str] = None,
        delimiter: Optional[str] = None,
        tz: str = "UTC",
    ) -> None:
        self.file_path = Path(file_path)
        self.symbol = symbol
        self.timeframe = _normalise_tf(timeframe)
        self.datetime_format = datetime_format
        self.delimiter = delimiter
        self.tz = tz

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fetch(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        sym = symbol or self.symbol
        tf = _normalise_tf(timeframe) if timeframe else self.timeframe

        logger.info(
            "csv_adapter.fetch",
            file=str(self.file_path),
            symbol=sym,
            timeframe=tf,
        )

        df = self._load_dataframe()
        candles = self._df_to_candles(df, sym, tf)
        candles = self._filter_valid(candles)

        # Optional date filtering
        if start:
            start_utc = _to_utc(start)
            candles = [c for c in candles if _to_utc(c.timestamp) >= start_utc]
        if end:
            end_utc = _to_utc(end)
            candles = [c for c in candles if _to_utc(c.timestamp) <= end_utc]

        candles.sort(key=lambda c: c.timestamp)

        if limit is not None:
            candles = candles[-limit:]

        logger.info("csv_adapter.loaded", count=len(candles), symbol=sym, timeframe=tf)
        return candles

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_dataframe(self) -> pd.DataFrame:
        if not self.file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.file_path}")

        # Auto-detect delimiter when not specified
        sep = self.delimiter
        if sep is None:
            raw = self.file_path.read_text(encoding="utf-8-sig", errors="replace")
            sample = raw[:4096]
            sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            if sep not in (",", ";", "\t", "|"):
                sep = ","

        df = pd.read_csv(
            self.file_path,
            sep=sep,
            encoding="utf-8-sig",
            on_bad_lines="skip",
        )

        # Normalise column names
        df.columns = [_normalise_col(c) for c in df.columns]
        return df

    def _df_to_candles(
        self, df: pd.DataFrame, symbol: str, timeframe: str
    ) -> List[Candle]:
        df = df.copy()

        # -------------------------------------------------------------- #
        # Build timestamp column
        # -------------------------------------------------------------- #
        if "timestamp" in df.columns:
            ts_series = df["timestamp"]
        elif "date" in df.columns and "time" in df.columns:
            ts_series = df["date"].astype(str) + " " + df["time"].astype(str)
        elif "date" in df.columns:
            ts_series = df["date"].astype(str)
        elif "time" in df.columns:
            # TradingView exports use "time" as the sole timestamp column
            ts_series = df["time"].astype(str)
        else:
            raise ValueError(
                "CSV has no recognisable timestamp column. "
                "Expected one of: 'timestamp', 'datetime', 'date', 'time'."
            )

        if self.datetime_format:
            df["ts_parsed"] = pd.to_datetime(ts_series, format=self.datetime_format, utc=False)
        else:
            # infer_datetime_format was removed in pandas 3.x; plain to_datetime
            # still auto-detects the most common formats.
            df["ts_parsed"] = pd.to_datetime(ts_series, utc=False)

        # Localise naïve timestamps to the configured tz and convert to UTC
        if df["ts_parsed"].dt.tz is None:
            df["ts_parsed"] = df["ts_parsed"].dt.tz_localize(self.tz).dt.tz_convert("UTC")
        else:
            df["ts_parsed"] = df["ts_parsed"].dt.tz_convert("UTC")

        # -------------------------------------------------------------- #
        # Required OHLCV columns
        # -------------------------------------------------------------- #
        required = ["open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")

        if "volume" not in df.columns:
            df["volume"] = 0.0

        # -------------------------------------------------------------- #
        # Build Candle objects
        # -------------------------------------------------------------- #
        candles: List[Candle] = []
        for row in df.itertuples(index=False):
            try:
                ts = row.ts_parsed.to_pydatetime().replace(tzinfo=timezone.utc)
                candle = Candle(
                    timestamp=ts,
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                    symbol=symbol,
                    timeframe=timeframe,
                )
                candles.append(candle)
            except Exception as exc:  # noqa: BLE001
                logger.warning("csv_adapter.row_skipped", reason=str(exc))
                continue

        return candles


# ------------------------------------------------------------------ #
# Utility
# ------------------------------------------------------------------ #

def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
