"""Network-aware data source fallback manager for trading candles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import socket
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd
import structlog

from src.trading.data.broker_adapter import FileBridgeAdapter
from src.trading.data.fetcher import FreeFetcher
from src.trading.data.store import DataStore

logger = structlog.get_logger(__name__)

_YAHOO_HOSTS = (
    "finance.yahoo.com",
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "guce.yahoo.com",
)

_YAHOO_PROBE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d"


@dataclass
class ImportFileSpec:
    """Configuration for optional imported CSV/Parquet fallback."""

    path: str | Path
    source: str = "imported_file"
    date_col: str = "time"
    csv_sep: str = ","


@dataclass
class LoadResult:
    """Result of data loading via fallback sequence."""

    df: pd.DataFrame
    source: str
    status: str
    detail: str = ""


class DataSourceManager:
    """Resolve candles from local store, yfinance, then imported files."""

    def __init__(
        self,
        store: DataStore,
        fetcher: Optional[FreeFetcher] = None,
        file_sources: Optional[dict[tuple[str, str], ImportFileSpec]] = None,
        probe_url: str = _YAHOO_PROBE_URL,
    ) -> None:
        self.store = store
        self.fetcher = fetcher or FreeFetcher(store=store)
        self.file_sources = {
            (sym.upper(), tf): spec for (sym, tf), spec in (file_sources or {}).items()
        }
        self.probe_url = probe_url

    @staticmethod
    def _key(symbol: str, timeframe: str) -> tuple[str, str]:
        return symbol.upper(), timeframe

    @staticmethod
    def _empty() -> pd.DataFrame:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def check_yahoo_access(self, timeout: int = 5) -> tuple[bool, str]:
        """Check DNS + HTTPS access needed by yfinance Yahoo endpoints."""
        try:
            for host in _YAHOO_HOSTS:
                socket.gethostbyname(host)
        except OSError as exc:
            return False, f"dns_failed:{exc}"

        req = Request(self.probe_url, method="GET")
        try:
            with urlopen(req, timeout=timeout) as resp:
                if int(resp.status) >= 400:
                    return False, f"http_status:{resp.status}@{self.probe_url}"
        except URLError as exc:
            return False, f"http_failed:{exc}"
        except TimeoutError:
            return False, "timeout"

        return True, "ok"

    def get(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        source: Optional[str] = None,
        allow_yahoo: bool = True,
    ) -> LoadResult:
        """Load candles with fallback: local store -> yfinance -> imported file."""
        reasons: list[str] = []
        key = self._key(symbol, timeframe)

        # 1) Local DataStore first
        local_df = self.store.load(symbol, timeframe, start=start, end=end, source=source)
        if not local_df.empty:
            used_source = source or "latest"
            logger.info(
                "source_manager.used",
                symbol=symbol,
                timeframe=timeframe,
                source=f"store:{used_source}",
                rows=len(local_df),
            )
            return LoadResult(local_df, source=f"store:{used_source}", status="ok")
        reasons.append("store_empty")

        # 2) yfinance only when Yahoo is reachable
        if allow_yahoo:
            reachable, reason = self.check_yahoo_access()
            if reachable:
                yf_df = self.fetcher.fetch(symbol, timeframe, start=start, end=end)
                if not yf_df.empty:
                    logger.info(
                        "source_manager.used",
                        symbol=symbol,
                        timeframe=timeframe,
                        source="yfinance",
                        rows=len(yf_df),
                    )
                    return LoadResult(yf_df, source="yfinance", status="ok")
                reasons.append("yfinance_empty")
            else:
                logger.warning(
                    "source_manager.yahoo_offline",
                    symbol=symbol,
                    timeframe=timeframe,
                    reason=reason,
                )
                reasons.append(f"yfinance_skipped:{reason}")
        else:
            reasons.append("yfinance_disabled")

        # 3) Optional imported file provider
        spec = self.file_sources.get(key)
        if spec is not None:
            try:
                adapter = FileBridgeAdapter(
                    path=spec.path,
                    symbol=symbol,
                    timeframe=timeframe,
                    date_col=spec.date_col,
                    csv_sep=spec.csv_sep,
                )
                adapter.connect()
                imported_df = adapter.get_candles(limit=1_000_000)
                adapter.disconnect()
                if not imported_df.empty:
                    self.store.save(imported_df, symbol, timeframe, source=spec.source)
                    imported_df = self.store.load(
                        symbol,
                        timeframe,
                        start=start,
                        end=end,
                        source=spec.source,
                    )
                    logger.info(
                        "source_manager.used",
                        symbol=symbol,
                        timeframe=timeframe,
                        source=spec.source,
                        rows=len(imported_df),
                    )
                    return LoadResult(imported_df, source=spec.source, status="ok")
                reasons.append("imported_file_empty")
            except Exception as exc:
                reasons.append(f"imported_file_failed:{exc}")
        else:
            reasons.append("imported_file_unconfigured")

        detail = " | ".join(reasons)
        logger.warning(
            "source_manager.unavailable",
            symbol=symbol,
            timeframe=timeframe,
            reason=detail,
        )
        return LoadResult(self._empty(), source="none", status="unavailable", detail=detail)
