"""
YFinance Adapter – free market-data proxy for XAUUSD and USOIL/WTI.

Limitations (documented)
-------------------------
* Data is **end-of-day delayed** for intraday bars shorter than 60 minutes
  on the free yfinance tier.
* Prices are **futures prices** (GC=F for gold, CL=F for WTI crude), not
  exact spot/CFD prices.  Expect a small premium vs. broker XAUUSD/USOIL
  due to cost-of-carry and contract roll.
* Volume figures are exchange futures volume, not retail-CFD tick volume.
* No tick data or sub-minute data is available.
* 1m / 2m bars: only last 7 days available from yfinance.
* 5m – 1H bars: only last 60 days available from yfinance.

Recommended use
---------------
* Backtesting on daily / hourly bars where exact price is less critical.
* Live monitoring in *signal-only / paper-trade* mode where a small price
  offset is acceptable.
* Use :class:`~src.trading.adapters.csv_adapter.CSVAdapter` with your
  broker-exported data for exact symbol fidelity.

Symbol mapping
--------------
The adapter accepts either the canonical FACTRADE symbol names or native
yfinance tickers:

  XAUUSD  → GC=F  (CME Gold Futures, continuous front-month)
  USOIL   → CL=F  (CME WTI Crude Oil Futures, continuous front-month)
  WTI     → CL=F
  USOIL   → CL=F

Any other ticker is passed through unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from src.trading.adapters.base import BaseAdapter
from src.trading.candle import Candle

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------- #
# Symbol → yfinance ticker mapping
# ---------------------------------------------------------------------- #
_SYMBOL_MAP: Dict[str, str] = {
    "XAUUSD": "GC=F",
    "XAUUSD.": "GC=F",
    "GOLD": "GC=F",
    "USOIL": "CL=F",
    "WTI": "CL=F",
    "USOILSPOT": "CL=F",
    "CRUDE": "CL=F",
    "CRUDEOIL": "CL=F",
    "WTICOUSD": "CL=F",
}

# yfinance interval strings for each FACTRADE timeframe.
# Timeframes marked with a comment are approximations — yfinance does not
# support that exact interval, so the nearest available one is used.
_TF_MAP: Dict[str, str] = {
    "1m": "1m",
    "3m": "2m",    # ⚠ approximation: yfinance has no 3m; 2m is the nearest
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "3H": "90m",   # ⚠ approximation: yfinance has no 3H; 90m is the nearest
    "4H": "1h",   # yfinance has no 4H; use 1H and resample
    "1D": "1d",
    "1W": "1wk",
}

# Resample map: timeframes that require resampling from a finer yfinance bar
_RESAMPLE: Dict[str, str] = {
    "4H": ("1h", "4H"),
    "3H": ("1h", "3H"),
}

# Maximum days lookback supported per interval by yfinance free tier
_MAX_DAYS: Dict[str, int] = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "90m": 60,
    "1d": 10000,
    "1wk": 10000,
}


class YFinanceAdapter(BaseAdapter):
    """
    Free data adapter using *yfinance* (Yahoo Finance).

    Parameters
    ----------
    proxy:
        Optional HTTP proxy string passed to yfinance (e.g. for corporate
        networks).
    """

    name = "yfinance"
    supports_live = True   # Near-real-time for >15-min timeframes (15-min delay)

    def __init__(self, proxy: Optional[str] = None) -> None:
        self._proxy = proxy

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError(
                "yfinance is required for YFinanceAdapter.  "
                "Run: pip install yfinance"
            ) from exc

        ticker = _SYMBOL_MAP.get(symbol.upper(), symbol)

        # Handle timeframes that need resampling (e.g. 4H from 1H raw)
        if timeframe in _RESAMPLE:
            raw_tf, resample_rule = _RESAMPLE[timeframe]
            yf_interval = _TF_MAP.get(raw_tf, raw_tf)
        else:
            yf_interval = _TF_MAP.get(timeframe, timeframe)
            resample_rule = None

        # Warn when the requested timeframe is approximated by a different interval
        _APPROX_TF = {"3m", "3H"}
        if timeframe in _APPROX_TF:
            logger.warning(
                "yfinance_adapter.approx_timeframe",
                requested=timeframe,
                using=yf_interval,
                note=(
                    f"yfinance does not support {timeframe!r}; "
                    f"using {yf_interval!r} as the closest available interval. "
                    "Use a broker CSV for exact timeframe fidelity."
                ),
            )

        max_days = _MAX_DAYS.get(yf_interval, 730)

        logger.info(
            "yfinance_adapter.fetch",
            symbol=symbol,
            ticker=ticker,
            timeframe=timeframe,
            yf_interval=yf_interval,
        )

        # Build period / start-end arguments for yfinance
        download_kwargs: dict = {
            "ticker": ticker,
            "interval": yf_interval,
            "auto_adjust": True,
            "progress": False,
        }
        if self._proxy:
            download_kwargs["proxy"] = self._proxy

        if start and end:
            download_kwargs["start"] = start.strftime("%Y-%m-%d")
            download_kwargs["end"] = end.strftime("%Y-%m-%d")
        elif start:
            download_kwargs["start"] = start.strftime("%Y-%m-%d")
        elif limit:
            # Estimate date range from limit and approximate candle duration
            from datetime import timedelta

            td = _approx_timedelta(yf_interval)
            days_needed = min(int(limit * td.total_seconds() / 86400) + 2, max_days)
            from datetime import date as _date

            download_kwargs["period"] = f"{days_needed}d"
        else:
            download_kwargs["period"] = f"{max_days}d"

        try:
            t = yf.Ticker(ticker)
            df = t.history(**{
                k: v for k, v in download_kwargs.items() if k != "ticker"
            })
        except Exception as exc:  # noqa: BLE001
            logger.error("yfinance_adapter.download_error", error=str(exc), ticker=ticker)
            return []

        if df is None or df.empty:
            logger.warning("yfinance_adapter.no_data", ticker=ticker, timeframe=timeframe)
            return []

        # Resample if necessary (e.g. 1H → 4H)
        if resample_rule:
            df = _resample_ohlcv(df, resample_rule)

        candles = self._df_to_candles(df, symbol, timeframe)
        candles = self._filter_valid(candles)
        candles.sort(key=lambda c: c.timestamp)

        if limit is not None:
            candles = candles[-limit:]

        logger.info(
            "yfinance_adapter.loaded",
            count=len(candles),
            symbol=symbol,
            timeframe=timeframe,
        )
        return candles

    def fetch_latest(self, symbol: str, timeframe: str, n: int = 500) -> List[Candle]:
        return self.fetch(symbol=symbol, timeframe=timeframe, limit=n)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _df_to_candles(df, symbol: str, timeframe: str) -> List[Candle]:
        import pandas as pd

        candles: List[Candle] = []
        for ts_raw, row in df.iterrows():
            try:
                # Ensure UTC-aware datetime
                if hasattr(ts_raw, "tzinfo") and ts_raw.tzinfo is not None:
                    ts = ts_raw.to_pydatetime().astimezone(timezone.utc)
                else:
                    ts = ts_raw.to_pydatetime().replace(tzinfo=timezone.utc)

                candle = Candle(
                    timestamp=ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume", 0) or 0),
                    symbol=symbol,
                    timeframe=timeframe,
                )
                candles.append(candle)
            except Exception as exc:  # noqa: BLE001
                logger.warning("yfinance_adapter.row_skipped", reason=str(exc))
                continue
        return candles


# ------------------------------------------------------------------ #
# Resampling helper
# ------------------------------------------------------------------ #

def _resample_ohlcv(df, rule: str):
    """Resample a 1H OHLCV DataFrame to a higher timeframe (e.g. '4H')."""
    import pandas as pd

    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    existing = {k: v for k, v in agg.items() if k in df.columns}
    return df.resample(rule).agg(existing).dropna(subset=["Open", "Close"])


def _approx_timedelta(yf_interval: str):
    from datetime import timedelta

    mapping = {
        "1m": timedelta(minutes=1),
        "2m": timedelta(minutes=2),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "90m": timedelta(minutes=90),
        "1d": timedelta(days=1),
        "1wk": timedelta(weeks=1),
    }
    return mapping.get(yf_interval, timedelta(hours=1))
