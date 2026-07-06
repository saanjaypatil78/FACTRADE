"""Free public data fetcher for FACTRADE.

Uses ``yfinance`` as the primary free data source for XAUUSD and USOIL.

Symbol mapping
--------------
FACTRADE symbol  →  yfinance ticker
XAUUSD           →  GC=F   (Gold Futures, ~spot proxy)
USOIL            →  CL=F   (WTI Crude Oil Futures)

Note: yfinance does not provide native 3H or 4H bars.  The fetcher
transparently fetches 1H data and resamples to 3H/4H using the exact
resampler when those timeframes are requested.

Timeframe mapping
-----------------
For direct yfinance download:
  1m, 5m, 15m, 30m, 1H → directly available
  3H, 4H               → fetched as 1H then resampled
  1D                   → directly available

Usage
-----
    from src.trading.data.fetcher import FreeFetcher
    from src.trading.data.store import DataStore

    store = DataStore()
    fetcher = FreeFetcher(store=store)
    df = fetcher.fetch("XAUUSD", "3H", start="2024-01-01", end="2024-06-01")
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import structlog

from src.trading.data.resampler import resample

logger = structlog.get_logger(__name__)

# FACTRADE internal symbol → yfinance ticker
_SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "GC=F",
    "USOIL": "CL=F",
    "WTIUSD": "CL=F",
}

# yfinance valid interval strings
_YF_INTERVALS: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "1D": "1d",
    "1W": "1wk",
}

# Timeframes that must be resampled from 1H
_RESAMPLE_FROM_1H: set[str] = {"2H", "3H", "4H", "6H", "8H", "12H"}


class FreeFetcher:
    """Fetch OHLCV data from free public sources (yfinance).

    Parameters
    ----------
    store:
        Optional DataStore.  If provided, fetched data is automatically
        saved for future retrieval.
    """

    def __init__(self, store=None) -> None:
        self._store = store

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str | datetime] = None,
        end: Optional[str | datetime] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles.

        Parameters
        ----------
        symbol:
            ``"XAUUSD"`` or ``"USOIL"``.
        timeframe:
            e.g. ``"1H"``, ``"3H"``, ``"4H"``, ``"15m"``, ``"1D"``.
        start / end:
            Date range.  Defaults to last 365 days.

        Returns
        -------
        pd.DataFrame
            Normalised OHLCV DataFrame with UTC DatetimeIndex.
        """
        try:
            import yfinance as yf  # lazy import – not always installed
        except ImportError as exc:
            raise ImportError(
                "yfinance is required for the free fetcher. "
                "Install it with: pip install yfinance"
            ) from exc

        ticker = _SYMBOL_MAP.get(symbol.upper(), symbol)

        if end is None:
            end = datetime.now(timezone.utc)
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=365)

        # If target timeframe must be resampled from 1H, fetch 1H first
        if timeframe in _RESAMPLE_FROM_1H:
            logger.info(
                "fetcher.resampling_path",
                symbol=symbol,
                target_tf=timeframe,
                source_tf="1H",
            )
            raw = self._download(yf, ticker, "1h", start, end)
            if raw.empty:
                return raw
            df = resample(raw, timeframe)
            source_label = "yfinance"
        else:
            yf_interval = _YF_INTERVALS.get(timeframe)
            if yf_interval is None:
                raise ValueError(
                    f"Unsupported timeframe '{timeframe}'. "
                    f"Supported: {sorted(_YF_INTERVALS.keys()) + sorted(_RESAMPLE_FROM_1H)}"
                )
            df = self._download(yf, ticker, yf_interval, start, end)
            source_label = "yfinance"

        if self._store is not None and not df.empty:
            resample_from = "1H" if timeframe in _RESAMPLE_FROM_1H else None
            self._store.save(df, symbol, timeframe, source=source_label, resample_from=resample_from)

        return df

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _download(
        yf,
        ticker: str,
        interval: str,
        start,
        end,
    ) -> pd.DataFrame:
        """Download from yfinance and normalise."""
        logger.info("fetcher.download", ticker=ticker, interval=interval)
        raw = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            progress=False,
            multi_level_index=False,
        )
        if raw is None or raw.empty:
            logger.warning("fetcher.empty_response", ticker=ticker, interval=interval)
            return pd.DataFrame()

        raw.columns = [c.lower() for c in raw.columns]
        for col in ("open", "high", "low", "close"):
            if col not in raw.columns:
                logger.error("fetcher.missing_column", col=col)
                return pd.DataFrame()
        if "volume" not in raw.columns:
            raw["volume"] = 0.0

        raw = raw[["open", "high", "low", "close", "volume"]].copy()

        # Ensure UTC DatetimeIndex
        if not isinstance(raw.index, pd.DatetimeIndex):
            raw.index = pd.to_datetime(raw.index)
        if raw.index.tz is None:
            raw.index = raw.index.tz_localize("UTC")
        else:
            raw.index = raw.index.tz_convert("UTC")

        raw.sort_index(inplace=True)
        raw.dropna(subset=["open", "high", "low", "close"], inplace=True)
        return raw
