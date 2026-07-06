"""Input contract helpers for long-run backtests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import pandas as pd

from src.trading.data.source_manager import DataSourceManager
from src.trading.data.store import DataStore


@dataclass
class BacktestInputItem:
    symbol: str
    timeframe: str
    rows: int
    status: str
    source: str
    detail: str = ""


def ensure_long_run_inputs(
    store: DataStore,
    source_manager: DataSourceManager,
    start: str,
    end: str,
    symbols: Optional[list[str]] = None,
    timeframes: Optional[list[str]] = None,
    min_years: int = 5,
) -> dict:
    """Require local inputs for long-run windows and auto-populate if missing."""
    symbols = symbols or ["XAUUSD", "WTIUSD"]
    timeframes = timeframes or ["4H", "15m"]
    items: list[BacktestInputItem] = []

    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    long_run = (end_ts - start_ts).days >= (min_years * 365)

    for symbol in symbols:
        for timeframe in timeframes:
            local_df = store.load(symbol, timeframe, start=start, end=end)
            if not local_df.empty:
                items.append(
                    BacktestInputItem(
                        symbol=symbol,
                        timeframe=timeframe,
                        rows=len(local_df),
                        status="available",
                        source="store",
                    )
                )
                continue

            if long_run:
                fetched = source_manager.get(symbol, timeframe, start=start, end=end)
                if not fetched.df.empty:
                    items.append(
                        BacktestInputItem(
                            symbol=symbol,
                            timeframe=timeframe,
                            rows=len(fetched.df),
                            status="populated",
                            source=fetched.source,
                        )
                    )
                else:
                    items.append(
                        BacktestInputItem(
                            symbol=symbol,
                            timeframe=timeframe,
                            rows=0,
                            status="missing",
                            source="none",
                            detail=fetched.detail,
                        )
                    )
            else:
                items.append(
                    BacktestInputItem(
                        symbol=symbol,
                        timeframe=timeframe,
                        rows=0,
                        status="missing",
                        source="none",
                        detail="short_run_local_missing",
                    )
                )

    ok = all(item.status != "missing" for item in items)
    return {
        "ok": ok,
        "long_run": long_run,
        "items": [asdict(item) for item in items],
    }
