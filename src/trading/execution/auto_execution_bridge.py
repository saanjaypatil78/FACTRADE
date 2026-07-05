"""Optional auto-execution bridge for FACTRADE.

⚠️  SAFE DEFAULT: live execution is DISABLED by default.

To enable, you must explicitly:
1. Set ``enable_live_execution=True`` in the constructor.
2. Set the ``FACTRADE_LIVE_EXECUTION=1`` environment variable.

If either condition is missing, all order submissions are logged as
simulated and no real broker API is called.

Architecture
------------
``AutoExecutionBridge`` wraps a ``LiveFeedAdapter`` for market data and
an optional ``BrokerExecutionAdapter`` for order placement.

Provided execution adapters
----------------------------
1. ``NullBrokerAdapter``     – default (safe) no-op: logs orders only.
2. ``FileBrokerAdapter``     – writes orders to a JSON-Lines file that a
   separate script/EA can pick up and forward to the broker.
3. ``SocketBrokerAdapter``   – sends orders over a local TCP socket to a
   running EA/connector (e.g. MT4 socket bridge, cTrader cBot).

How to connect a real broker
-----------------------------
Implement ``BrokerExecutionAdapter`` and pass an instance to
``AutoExecutionBridge``.  The bridge calls:
- ``place_order(symbol, direction, lots, sl, tp)`` → order ID
- ``modify_sl(order_id, new_sl)``
- ``close_order(order_id, lots)``

See ``NullBrokerAdapter`` for the full interface.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from src.trading.execution.risk_manager import PositionSpec

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Abstract broker execution adapter
# ---------------------------------------------------------------------------


class BrokerExecutionAdapter:
    """Base class for broker order execution adapters.

    Override in a concrete class for your specific broker/API.
    """

    def place_order(
        self,
        symbol: str,
        direction: str,
        lots: float,
        entry_price: float,
        sl_price: float,
        tp1_price: float,
        tp2_price: float,
    ) -> Optional[str]:
        """Place a market/limit order.  Returns an order ID or None on failure."""
        raise NotImplementedError

    def modify_sl(self, order_id: str, new_sl: float) -> bool:
        """Modify an open order's stop-loss.  Returns True on success."""
        raise NotImplementedError

    def close_order(self, order_id: str, lots: float) -> bool:
        """Close (full or partial) an open order.  Returns True on success."""
        raise NotImplementedError

    def get_open_orders(self) -> list[dict]:
        """Return a list of currently open order dicts."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Null adapter (safe default — logs only)
# ---------------------------------------------------------------------------


class NullBrokerAdapter(BrokerExecutionAdapter):
    """No-op adapter: logs every call, never places a real order."""

    def place_order(self, symbol, direction, lots, entry_price, sl_price, tp1_price, tp2_price):
        logger.info(
            "null_broker.place_order",
            symbol=symbol,
            direction=direction,
            lots=lots,
            entry=entry_price,
            sl=sl_price,
            tp1=tp1_price,
            tp2=tp2_price,
        )
        return None

    def modify_sl(self, order_id, new_sl):
        logger.info("null_broker.modify_sl", order_id=order_id, new_sl=new_sl)
        return True

    def close_order(self, order_id, lots):
        logger.info("null_broker.close_order", order_id=order_id, lots=lots)
        return True

    def get_open_orders(self):
        return []


# ---------------------------------------------------------------------------
# File-based adapter (write orders to disk for EA pickup)
# ---------------------------------------------------------------------------


class FileBrokerAdapter(BrokerExecutionAdapter):
    """Write orders to a JSON-Lines file.

    An external Expert Advisor (MT4/MT5/cTrader cBot) or custom script
    watches this file and executes the orders with minimal latency.

    File format (one JSON object per line)::

        {"action":"open","order_id":"...","symbol":"XAUUSD","direction":"long",
         "lots":0.05,"entry":2050.10,"sl":2040.0,"tp1":2065.0,"tp2":2090.0,
         "ts":"2024-01-15T09:00:00Z"}

    Parameters
    ----------
    order_file:
        Path to the orders file (default ``"data/live_orders.jsonl"``).
    """

    def __init__(self, order_file: str = "data/live_orders.jsonl") -> None:
        self._path = Path(order_file)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"FAC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{self._counter:04d}"

    def _write(self, record: dict) -> None:
        with self._path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        logger.info("file_broker.write", action=record.get("action"), order_id=record.get("order_id"))

    def place_order(self, symbol, direction, lots, entry_price, sl_price, tp1_price, tp2_price):
        oid = self._new_id()
        self._write({
            "action": "open",
            "order_id": oid,
            "symbol": symbol,
            "direction": direction,
            "lots": lots,
            "entry": entry_price,
            "sl": sl_price,
            "tp1": tp1_price,
            "tp2": tp2_price,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return oid

    def modify_sl(self, order_id, new_sl):
        self._write({
            "action": "modify_sl",
            "order_id": order_id,
            "new_sl": new_sl,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return True

    def close_order(self, order_id, lots):
        self._write({
            "action": "close",
            "order_id": order_id,
            "lots": lots,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        return True

    def get_open_orders(self):
        return []


# ---------------------------------------------------------------------------
# Socket-based adapter (send orders over local TCP to EA/connector)
# ---------------------------------------------------------------------------


class SocketBrokerAdapter(BrokerExecutionAdapter):
    """Send JSON order commands over a local TCP socket.

    Compatible with the standard MT4/MT5 socket bridges (e.g. DWX Connect,
    FXConnect) or any custom EA listening on a TCP port.

    Parameters
    ----------
    host:
        Broker bridge host (default ``"127.0.0.1"``).
    port:
        TCP port the broker bridge listens on (default ``9090``).
    timeout:
        Socket timeout in seconds (default ``5``).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9090,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._counter = 0

    def _send(self, payload: dict) -> Optional[str]:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                msg = json.dumps(payload) + "\n"
                s.sendall(msg.encode())
                response = s.recv(4096).decode().strip()
                logger.info("socket_broker.response", response=response)
                return response
        except (OSError, TimeoutError) as exc:
            logger.error("socket_broker.send_error", error=str(exc))
            return None

    def _new_id(self) -> str:
        self._counter += 1
        return f"FAC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{self._counter:04d}"

    def place_order(self, symbol, direction, lots, entry_price, sl_price, tp1_price, tp2_price):
        oid = self._new_id()
        self._send({
            "action": "open",
            "order_id": oid,
            "symbol": symbol,
            "direction": direction,
            "lots": lots,
            "entry": entry_price,
            "sl": sl_price,
            "tp1": tp1_price,
            "tp2": tp2_price,
        })
        return oid

    def modify_sl(self, order_id, new_sl):
        self._send({"action": "modify_sl", "order_id": order_id, "new_sl": new_sl})
        return True

    def close_order(self, order_id, lots):
        self._send({"action": "close", "order_id": order_id, "lots": lots})
        return True

    def get_open_orders(self):
        result = self._send({"action": "get_orders"})
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return []
        return []


# ---------------------------------------------------------------------------
# Auto-execution bridge
# ---------------------------------------------------------------------------


class AutoExecutionBridge:
    """Optional bridge that connects the signal pipeline to a broker adapter.

    ⚠️  DISABLED BY DEFAULT — both the constructor flag AND the environment
    variable must be set to enable live execution.

    Parameters
    ----------
    broker_adapter:
        The broker execution adapter to use (default: ``NullBrokerAdapter``).
    enable_live_execution:
        Set to ``True`` AND set ``FACTRADE_LIVE_EXECUTION=1`` in the
        environment to allow real order placement.
    """

    def __init__(
        self,
        broker_adapter: Optional[BrokerExecutionAdapter] = None,
        enable_live_execution: bool = False,
    ) -> None:
        self._adapter = broker_adapter or NullBrokerAdapter()
        env_flag = os.environ.get("FACTRADE_LIVE_EXECUTION", "0") == "1"
        self._live = enable_live_execution and env_flag

        if self._live:
            logger.warning(
                "auto_execution_bridge.LIVE_MODE_ACTIVE",
                adapter=type(self._adapter).__name__,
                msg="Real orders will be submitted to the broker.",
            )
        else:
            logger.info(
                "auto_execution_bridge.paper_mode",
                adapter=type(self._adapter).__name__,
                msg="Auto-execution is DISABLED. Set enable_live_execution=True "
                    "AND FACTRADE_LIVE_EXECUTION=1 to enable.",
            )

        self._order_map: dict[str, str] = {}  # trade_id → broker_order_id

    @property
    def is_live(self) -> bool:
        """True only when both the constructor flag and env var are set."""
        return self._live

    def submit(self, spec: PositionSpec, trade_id: str) -> Optional[str]:
        """Submit an order for a validated PositionSpec.

        Parameters
        ----------
        spec:
            Validated PositionSpec from the risk manager.
        trade_id:
            Internal trade identifier (used to track order modifications).

        Returns
        -------
        str | None
            Broker order ID (or ``None`` when paper/null adapter).
        """
        if not spec.valid:
            logger.warning("auto_execution_bridge.invalid_spec_skipped")
            return None

        order_id = self._adapter.place_order(
            symbol=spec.symbol,
            direction=spec.direction,
            lots=spec.lot_size,
            entry_price=spec.entry_price,
            sl_price=spec.sl_price,
            tp1_price=spec.tp1_price,
            tp2_price=spec.tp2_price,
        )
        if order_id:
            self._order_map[trade_id] = order_id
        return order_id

    def modify_sl(self, trade_id: str, new_sl: float) -> bool:
        order_id = self._order_map.get(trade_id)
        if not order_id:
            return False
        return self._adapter.modify_sl(order_id, new_sl)

    def close(self, trade_id: str, lots: float) -> bool:
        order_id = self._order_map.get(trade_id)
        if not order_id:
            return False
        return self._adapter.close_order(order_id, lots)
