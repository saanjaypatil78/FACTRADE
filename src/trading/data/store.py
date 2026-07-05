"""Universal historical data store for FACTRADE.

Architecture
------------
- SQLite  : metadata catalogue (symbol, timeframe, source, date ranges,
            resampling provenance, fetch timestamps).
- Parquet : columnar OHLCV data files, partitioned by symbol and timeframe.

This store is the single source of truth for backtesting and live monitoring.
Subsequent backtests and reference queries **never** re-download data already
present in the store; they call ``load()`` instead of the fetcher.

Workflow
--------
1. ``store.save(df, symbol, timeframe, source)``   – persist downloaded candles.
2. ``store.load(symbol, timeframe, start, end)``   – retrieve from local store.
3. ``store.refresh(symbol, timeframe, fetcher)``   – append/update from fetcher.
4. ``store.list_entries()``                        – inspect what is cached.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS candle_catalogue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,
    timeframe     TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    start_dt      TEXT    NOT NULL,
    end_dt        TEXT    NOT NULL,
    rows          INTEGER NOT NULL,
    resample_from TEXT,          -- e.g. "1H" when 3H was resampled from 1H
    fetched_at    TEXT    NOT NULL,
    parquet_path  TEXT    NOT NULL,
    UNIQUE (symbol, timeframe, source)
);
"""

_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime(_DATE_FMT)


class DataStore:
    """Persistent, reusable local data store for normalised OHLCV candles.

    Parameters
    ----------
    base_dir:
        Root directory for all store files (default: ``data/trading_store``).
    """

    def __init__(self, base_dir: str | Path = "data/trading_store") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.base_dir / "catalogue.db"
        self._con: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._con is None:
            self._con = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._con.row_factory = sqlite3.Row
        return self._con

    def _init_db(self) -> None:
        con = self._connect()
        con.executescript(_SCHEMA_SQL)
        con.commit()
        logger.info("data_store.init", db=str(self._db_path))

    def _parquet_path(self, symbol: str, timeframe: str, source: str) -> Path:
        """Return canonical parquet path for a (symbol, timeframe, source) triple."""
        safe = lambda s: s.replace("/", "_").replace(" ", "_").lower()
        fname = f"{safe(symbol)}__{safe(timeframe)}__{safe(source)}.parquet"
        return self.base_dir / fname

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        source: str,
        resample_from: Optional[str] = None,
    ) -> Path:
        """Persist a normalised OHLCV DataFrame to the store.

        Parameters
        ----------
        df:
            DataFrame with DatetimeIndex (UTC) and columns
            [open, high, low, close, volume].
        symbol:
            Instrument ticker, e.g. ``"XAUUSD"`` or ``"USOIL"``.
        timeframe:
            Timeframe string, e.g. ``"1H"``, ``"3H"``, ``"4H"``, ``"1D"``.
        source:
            Data source identifier, e.g. ``"yfinance"``, ``"broker_csv"``.
        resample_from:
            If this data was resampled from a finer timeframe, note it here
            (e.g. ``"1H"`` meaning 3H data was resampled from 1H candles).

        Returns
        -------
        Path
            Path to the written Parquet file.
        """
        df = self._normalise(df)
        path = self._parquet_path(symbol, timeframe, source)
        df.to_parquet(path, engine="pyarrow", index=True)

        con = self._connect()
        con.execute(
            """
            INSERT INTO candle_catalogue
                (symbol, timeframe, source, start_dt, end_dt, rows,
                 resample_from, fetched_at, parquet_path)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, timeframe, source) DO UPDATE SET
                start_dt     = excluded.start_dt,
                end_dt       = excluded.end_dt,
                rows         = excluded.rows,
                resample_from= excluded.resample_from,
                fetched_at   = excluded.fetched_at,
                parquet_path = excluded.parquet_path
            """,
            (
                symbol,
                timeframe,
                source,
                df.index.min().strftime(_DATE_FMT),
                df.index.max().strftime(_DATE_FMT),
                len(df),
                resample_from,
                _utcnow(),
                str(path),
            ),
        )
        con.commit()
        logger.info(
            "data_store.saved",
            symbol=symbol,
            timeframe=timeframe,
            source=source,
            rows=len(df),
            path=str(path),
        )
        return path

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str | datetime] = None,
        end: Optional[str | datetime] = None,
        source: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load OHLCV data from the local store.

        Parameters
        ----------
        symbol:
            e.g. ``"XAUUSD"``.
        timeframe:
            e.g. ``"3H"``.
        start / end:
            Optional date range filter (inclusive).  Accepts ISO strings or
            ``datetime`` objects.
        source:
            Prefer a specific source; if ``None`` the most recently fetched
            entry for this (symbol, timeframe) is used.

        Returns
        -------
        pd.DataFrame
            OHLCV DataFrame with UTC DatetimeIndex, or empty DataFrame if not
            found.
        """
        con = self._connect()
        if source:
            row = con.execute(
                "SELECT parquet_path FROM candle_catalogue "
                "WHERE symbol=? AND timeframe=? AND source=?",
                (symbol, timeframe, source),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT parquet_path FROM candle_catalogue "
                "WHERE symbol=? AND timeframe=? "
                "ORDER BY fetched_at DESC LIMIT 1",
                (symbol, timeframe),
            ).fetchone()

        if row is None:
            logger.warning(
                "data_store.not_found",
                symbol=symbol,
                timeframe=timeframe,
                source=source,
            )
            return pd.DataFrame()

        df = pd.read_parquet(row["parquet_path"], engine="pyarrow")
        df.index = pd.to_datetime(df.index, utc=True)

        if start is not None:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]

        logger.info(
            "data_store.loaded",
            symbol=symbol,
            timeframe=timeframe,
            rows=len(df),
        )
        return df

    def refresh(
        self,
        symbol: str,
        timeframe: str,
        fetcher,
        source: str = "yfinance",
        resample_from: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch new candles from *fetcher* and append them to the store.

        Only candles newer than the last stored candle are fetched, making
        incremental updates efficient.

        Parameters
        ----------
        fetcher:
            An object with a ``fetch(symbol, timeframe, start, end)`` method.
        source:
            Source tag to record in metadata.
        resample_from:
            If the fetcher returns raw finer-timeframe data that is then
            resampled, set this to the raw timeframe (e.g. ``"1H"``).
        """
        existing = self.load(symbol, timeframe, source=source)
        start: Optional[str] = None
        if not existing.empty:
            last = existing.index.max()
            start = last.strftime("%Y-%m-%d")
            logger.info(
                "data_store.refresh_incremental",
                symbol=symbol,
                timeframe=timeframe,
                from_date=start,
            )

        new_df = fetcher.fetch(symbol, timeframe, start=start)
        if new_df.empty:
            logger.info("data_store.refresh_no_new_data", symbol=symbol, timeframe=timeframe)
            return existing

        if not existing.empty:
            combined = pd.concat([existing, new_df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
        else:
            combined = new_df

        self.save(combined, symbol, timeframe, source=source, resample_from=resample_from)
        return combined

    def list_entries(self) -> pd.DataFrame:
        """Return the catalogue as a DataFrame for inspection."""
        con = self._connect()
        rows = con.execute("SELECT * FROM candle_catalogue ORDER BY fetched_at DESC").fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    # ------------------------------------------------------------------
    # Internal normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure consistent column names and UTC DatetimeIndex."""
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        rename = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        df.rename(columns=rename, inplace=True)
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' missing from DataFrame.")
        if "volume" not in df.columns:
            df["volume"] = 0.0

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        df.sort_index(inplace=True)
        return df[["open", "high", "low", "close", "volume"]]
