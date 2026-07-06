"""Pluggable broker / live-feed adapter interface for FACTRADE.

Architecture
------------
``LiveFeedAdapter`` is the abstract base class.  Concrete adapters implement
``connect()``, ``disconnect()``, and ``get_candles()``.

Provided implementations
------------------------
1. ``MockBrokerAdapter``   – deterministic simulated feed for testing.
2. ``FileBridgeAdapter``   – reads OHLCV CSV/Parquet files exported by a broker
   (e.g. MT4/MT5 "Export CSV" or cTrader "History Export").
3. ``WebhookBridgeAdapter`` – listens for POST requests from broker webhooks
   (e.g. TradingView alerts forwarding live OHLCV or signal data).

Usage (file bridge – minimal manual steps)
------------------------------------------
Export your broker's 1H XAUUSD history as CSV, then::

    from src.trading.data.broker_adapter import FileBridgeAdapter
    adapter = FileBridgeAdapter(path="xauusd_1h.csv", symbol="XAUUSD", timeframe="1H")
    adapter.connect()
    df = adapter.get_candles(limit=100)
    adapter.disconnect()

Usage (mock – safe default)
----------------------------
    from src.trading.data.broker_adapter import MockBrokerAdapter
    adapter = MockBrokerAdapter(symbol="XAUUSD", timeframe="1H", seed=42)
    adapter.connect()
    candle = adapter.get_latest_candle()

Safety
------
All adapters default to ``live=False`` (paper/signal mode).  Setting
``live=True`` enables the path toward order submission, but the
``AutoExecutionBridge`` still requires an explicit ``enable_live_execution``
flag before any real orders are placed.
"""

from __future__ import annotations

import abc
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LiveFeedAdapter(abc.ABC):
    """Abstract live-feed adapter.

    All concrete adapters must implement the three abstract methods below.
    """

    def __init__(self, symbol: str, timeframe: str, live: bool = False) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.live = live
        self._connected = False

    @abc.abstractmethod
    def connect(self) -> None:
        """Establish connection to the data source."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the connection."""

    @abc.abstractmethod
    def get_candles(self, limit: int = 500) -> pd.DataFrame:
        """Return the last *limit* completed OHLCV candles.

        Returns
        -------
        pd.DataFrame
            Normalised OHLCV DataFrame with UTC DatetimeIndex.
        """

    def get_latest_candle(self) -> Optional[pd.Series]:
        """Return the single most-recent completed candle."""
        df = self.get_candles(limit=1)
        if df.empty:
            return None
        return df.iloc[-1]

    def is_connected(self) -> bool:
        return self._connected

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"symbol={self.symbol!r}, "
            f"timeframe={self.timeframe!r}, "
            f"live={self.live})"
        )


# ---------------------------------------------------------------------------
# Mock adapter (safe default, deterministic)
# ---------------------------------------------------------------------------


class MockBrokerAdapter(LiveFeedAdapter):
    """Deterministic simulated broker feed for development and testing.

    Generates synthetic OHLCV data via a seeded random walk so that
    behaviour is fully reproducible across backtests and unit tests.

    Parameters
    ----------
    symbol:
        Instrument, e.g. ``"XAUUSD"``.
    timeframe:
        Bar interval, e.g. ``"1H"``.
    seed:
        Random seed (default 42) for reproducibility.
    base_price:
        Starting price for the synthetic series.
    num_candles:
        Total candles to generate in the simulated history.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        timeframe: str = "1H",
        seed: int = 42,
        base_price: float = 2000.0,
        num_candles: int = 1000,
        live: bool = False,
    ) -> None:
        super().__init__(symbol=symbol, timeframe=timeframe, live=live)
        self._seed = seed
        self._base_price = base_price
        self._num_candles = num_candles
        self._df: pd.DataFrame = pd.DataFrame()

    def connect(self) -> None:
        rng = np.random.default_rng(self._seed)

        # Map timeframe to pandas freq
        _freq_map = {
            "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
            "1H": "1h", "2H": "2h", "3H": "3h", "4H": "4h",
            "1D": "1D",
        }
        freq = _freq_map.get(self.timeframe, "1h")
        end = pd.Timestamp.utcnow().floor(freq)
        index = pd.date_range(end=end, periods=self._num_candles, freq=freq, tz="UTC")

        # Simulate OHLCV with a random walk
        returns = rng.normal(0, 0.001, self._num_candles)
        closes = self._base_price * np.cumprod(1 + returns)
        opens = np.roll(closes, 1)
        opens[0] = self._base_price
        highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.003, self._num_candles))
        lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.003, self._num_candles))
        volumes = rng.uniform(100, 10000, self._num_candles)

        self._df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
            index=index,
        )
        self._connected = True
        logger.info(
            "mock_adapter.connected",
            symbol=self.symbol,
            timeframe=self.timeframe,
            candles=len(self._df),
        )

    def disconnect(self) -> None:
        self._connected = False
        logger.info("mock_adapter.disconnected", symbol=self.symbol)

    def get_candles(self, limit: int = 500) -> pd.DataFrame:
        if not self._connected:
            raise RuntimeError("Adapter not connected. Call connect() first.")
        return self._df.iloc[-limit:]


# ---------------------------------------------------------------------------
# File-bridge adapter (broker-exported CSV/Parquet)
# ---------------------------------------------------------------------------


class FileBridgeAdapter(LiveFeedAdapter):
    """Consume broker-exported OHLCV files (CSV or Parquet).

    This is the recommended low-manual-effort path for broker live data:

    1. Export 1H (or finer) history from your broker (MT4/MT5/cTrader).
    2. Point ``FileBridgeAdapter`` at the file.
    3. The adapter loads, normalises, and serves the data to the system.

    For *rolling* updates, re-export the file and call ``reload()``.

    Parameters
    ----------
    path:
        Path to the exported CSV or Parquet file.
    symbol / timeframe:
        Metadata for the loaded data.
    date_col:
        Name of the date/datetime column in CSV files (default ``"time"``).
    csv_sep:
        CSV separator (default ``,``).
    """

    def __init__(
        self,
        path: str | Path,
        symbol: str,
        timeframe: str,
        date_col: str = "time",
        csv_sep: str = ",",
        live: bool = False,
    ) -> None:
        super().__init__(symbol=symbol, timeframe=timeframe, live=live)
        self.path = Path(path)
        self._date_col = date_col
        self._csv_sep = csv_sep
        self._df: pd.DataFrame = pd.DataFrame()

    def connect(self) -> None:
        self.reload()
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def reload(self) -> None:
        """Re-read the file (call after broker exports an updated file)."""
        if not self.path.exists():
            raise FileNotFoundError(f"Broker file not found: {self.path}")

        if self.path.suffix.lower() in (".parquet", ".pq"):
            df = pd.read_parquet(self.path)
        else:
            df = pd.read_csv(self.path, sep=self._csv_sep)
            if self._date_col in df.columns:
                df[self._date_col] = pd.to_datetime(df[self._date_col])
                df.set_index(self._date_col, inplace=True)

        df.columns = [c.lower() for c in df.columns]
        rename = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        df.rename(columns=rename, inplace=True)

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        df.sort_index(inplace=True)
        self._df = df
        logger.info(
            "file_bridge.loaded",
            path=str(self.path),
            symbol=self.symbol,
            rows=len(df),
        )

    def get_candles(self, limit: int = 500) -> pd.DataFrame:
        if not self._connected:
            raise RuntimeError("Adapter not connected. Call connect() first.")
        return self._df.iloc[-limit:]


# ---------------------------------------------------------------------------
# Webhook bridge adapter (TradingView / cTrader alerts → local HTTP server)
# ---------------------------------------------------------------------------


class WebhookBridgeAdapter(LiveFeedAdapter):
    """Receive live OHLCV candles via HTTP POST from a broker/TradingView webhook.

    This adapter starts a lightweight Flask server on ``localhost:port`` that
    accepts JSON payloads of the form::

        {
            "symbol": "XAUUSD",
            "timeframe": "1H",
            "time": "2024-01-15T09:00:00Z",
            "open": 2050.10,
            "high": 2055.40,
            "low": 2049.80,
            "close": 2053.20,
            "volume": 1234
        }

    The adapter is **receive-only** (paper/signal mode by default).

    Parameters
    ----------
    symbol / timeframe:
        Expected instrument and timeframe.
    host:
        Bind host (default ``"127.0.0.1"`` — local only).
    port:
        Listen port (default ``8765``).
    max_candles:
        Maximum candles to keep in the in-memory buffer (default 1000).

    Enable
    ------
    Set the ``FACTRADE_WEBHOOK_ENABLED=1`` environment variable or pass
    ``enabled=True`` to this constructor.  By default the server does **not**
    start automatically — call ``connect()`` explicitly.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        host: str = "127.0.0.1",
        port: int = 8765,
        max_candles: int = 1000,
        live: bool = False,
        enabled: bool = False,
    ) -> None:
        super().__init__(symbol=symbol, timeframe=timeframe, live=live)
        self.host = host
        self.port = port
        self.max_candles = max_candles
        self._enabled = enabled
        self._buffer: list[dict] = []
        self._server_thread = None

    def connect(self) -> None:
        if not self._enabled:
            logger.info(
                "webhook_bridge.disabled",
                msg="Pass enabled=True or set FACTRADE_WEBHOOK_ENABLED=1 to start.",
            )
            self._connected = False
            return

        try:
            import flask  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "flask is required for WebhookBridgeAdapter. "
                "Install with: pip install flask"
            ) from exc

        self._start_server()
        self._connected = True
        logger.info(
            "webhook_bridge.listening",
            host=self.host,
            port=self.port,
            symbol=self.symbol,
        )

    def disconnect(self) -> None:
        self._connected = False
        logger.info("webhook_bridge.disconnected")

    def get_candles(self, limit: int = 500) -> pd.DataFrame:
        if not self._buffer:
            return pd.DataFrame()
        rows = self._buffer[-limit:]
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df.set_index("time", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _start_server(self) -> None:
        """Start Flask server in a daemon thread."""
        import threading

        import flask

        app = flask.Flask(__name__)
        buffer = self._buffer
        max_c = self.max_candles
        sym = self.symbol
        tf = self.timeframe

        @app.post("/candle")
        def receive_candle():
            data = flask.request.get_json(force=True)
            if data.get("symbol") != sym or data.get("timeframe") != tf:
                return flask.jsonify({"error": "symbol/timeframe mismatch"}), 400
            buffer.append(data)
            if len(buffer) > max_c:
                del buffer[:-max_c]
            return flask.jsonify({"status": "ok"}), 200

        @app.get("/health")
        def health():
            return flask.jsonify({"status": "ok", "candles": len(buffer)})

        t = threading.Thread(
            target=lambda: app.run(host=self.host, port=self.port, use_reloader=False),
            daemon=True,
        )
        t.start()
        self._server_thread = t
        time.sleep(0.3)  # give the server a moment to bind
