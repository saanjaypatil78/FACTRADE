"""
Trade Executor — manages order lifecycle in paper-trading and live mode.

In *paper* mode (default) all orders are simulated against incoming price
data; PnL is tracked in memory without touching any broker.

In *live* mode the executor calls a user-supplied broker adapter (any object
that implements the BrokerAdapter protocol).  The actual broker integration
is outside the scope of this module — see TRADING.md for guidance on
connecting to MetaTrader 5, Alpaca, Interactive Brokers, etc.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol

import structlog

from .signal_generator import SignalDirection, TradeSignal
from .risk_manager import RiskManager, TradeParameters

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

class OrderStatus(Enum):
    PENDING = "pending"         # signal generated, awaiting entry confirmation
    OPEN = "open"               # position is live
    CLOSED_TP1 = "closed_tp1"  # 80 % booked at TP1; runner active
    CLOSED_TP2 = "closed_tp2"  # runner closed at TP2
    CLOSED_SL = "closed_sl"    # stopped out
    CANCELLED = "cancelled"    # rejected before entry


@dataclass
class Order:
    """Represents one trade throughout its lifecycle."""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    direction: SignalDirection = SignalDirection.LONG
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    lot_size: float = 0.01
    status: OrderStatus = OrderStatus.PENDING
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    open_price: float = 0.0
    close_price: float = 0.0
    realized_pnl: float = 0.0
    # Runner position (20 % remaining after TP1 partial)
    runner_lots: float = 0.0
    runner_sl: float = 0.0     # static SL moved to break-even after TP1
    notes: str = ""

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PENDING, OrderStatus.CLOSED_TP1)


# ---------------------------------------------------------------------------
# Broker adapter protocol (for live mode)
# ---------------------------------------------------------------------------

class BrokerAdapter(Protocol):
    """Minimal interface expected from any live broker adapter."""

    def place_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        entry: float,
        sl: float,
        tp: float,
    ) -> str:
        """Place an order; return broker-side order ID."""
        ...

    def close_order(self, broker_order_id: str, lot_size: float) -> float:
        """Close (or partially close) an order; return execution price."""
        ...

    def get_current_price(self, symbol: str) -> float:
        """Return latest mid price for the symbol."""
        ...


# ---------------------------------------------------------------------------
# Trade Executor
# ---------------------------------------------------------------------------

class TradeExecutor:
    """
    Manages the full trade lifecycle.

    Parameters
    ----------
    risk_manager : RiskManager
        Used to validate signals and record PnL.
    paper_mode : bool
        When True, no real orders are placed (default True).
    broker : BrokerAdapter, optional
        Required only when paper_mode=False.
    tp1_fraction : float
        Fraction of position closed at TP1 (default 0.80 — Marco's 80/20 rule).
    on_signal : Callable, optional
        Optional callback invoked with (signal, order) whenever a new order
        is created.  Useful for logging, alerting, or UI updates.
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        paper_mode: bool = True,
        broker: Optional[BrokerAdapter] = None,
        tp1_fraction: float = 0.80,
        on_signal: Optional[Callable[[TradeSignal, Order], None]] = None,
    ) -> None:
        self.risk_manager = risk_manager
        self.paper_mode = paper_mode
        self.broker = broker
        self.tp1_fraction = tp1_fraction
        self.on_signal = on_signal
        self._orders: Dict[str, Order] = {}

        if not paper_mode and broker is None:
            raise ValueError("A BrokerAdapter must be provided when paper_mode=False.")

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def process_signal(self, signal: TradeSignal) -> Optional[Order]:
        """
        Validate a signal through risk rules and open an order if approved.

        Returns the created Order or None if the signal was rejected.
        """
        params = self.risk_manager.evaluate(
            symbol=signal.symbol,
            entry=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            rr_ratio=signal.rr_ratio,
        )

        if not params.approved:
            logger.warning(
                "signal_rejected",
                symbol=signal.symbol,
                reason=params.rejection_reason,
            )
            return None

        order = Order(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            lot_size=params.lot_size,
            runner_lots=round(params.lot_size * (1 - self.tp1_fraction), 2),
        )

        if self.paper_mode:
            self._open_paper(order, params)
        else:
            self._open_live(order, params)

        self._orders[order.order_id] = order

        if self.on_signal is not None:
            self.on_signal(signal, order)

        logger.info(
            "order_opened",
            order_id=order.order_id,
            symbol=order.symbol,
            direction=order.direction.value,
            entry=order.open_price,
            sl=order.stop_loss,
            tp1=order.take_profit_1,
            tp2=order.take_profit_2,
            lots=order.lot_size,
            paper=self.paper_mode,
        )
        return order

    def update_prices(self, symbol: str, current_price: float) -> None:
        """
        Feed the latest market price; executor will auto-close orders that
        hit SL or TP levels (paper mode).

        In live mode the broker handles order triggers; call this to keep
        internal state in sync and apply the 80/20 partial booking logic.
        """
        for order in list(self._orders.values()):
            if order.symbol != symbol or not order.is_active:
                continue
            if order.status in (OrderStatus.OPEN, OrderStatus.CLOSED_TP1):
                self._check_targets(order, current_price)

    def get_open_orders(self) -> List[Order]:
        return [o for o in self._orders.values() if o.is_active]

    def get_all_orders(self) -> List[Order]:
        return list(self._orders.values())

    def cancel_order(self, order_id: str) -> None:
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CANCELLED
            logger.info("order_cancelled", order_id=order_id)

    # ------------------------------------------------------------------
    # Paper-trade helpers
    # ------------------------------------------------------------------

    def _open_paper(self, order: Order, params: TradeParameters) -> None:
        order.open_price = order.entry_price
        order.open_time = datetime.utcnow()
        order.status = OrderStatus.OPEN
        self.risk_manager.record_trade_open()

    def _check_targets(self, order: Order, price: float) -> None:
        """Evaluate SL/TP1/TP2 against *price* in paper mode."""
        if order.direction == SignalDirection.LONG:
            hit_sl = price <= order.stop_loss
            hit_tp1 = price >= order.take_profit_1
            hit_runner_sl = (
                order.status == OrderStatus.CLOSED_TP1
                and price <= order.runner_sl
            )
            hit_tp2 = price >= order.take_profit_2
        else:
            hit_sl = price >= order.stop_loss
            hit_tp1 = price <= order.take_profit_1
            hit_runner_sl = (
                order.status == OrderStatus.CLOSED_TP1
                and price >= order.runner_sl
            )
            hit_tp2 = price <= order.take_profit_2

        if hit_sl and order.status == OrderStatus.OPEN:
            pnl = self._calc_pnl(order, price, order.lot_size)
            self._close_order(order, price, OrderStatus.CLOSED_SL, pnl)
        elif hit_tp1 and order.status == OrderStatus.OPEN:
            # Partial close 80 % at TP1
            main_lots = order.lot_size - order.runner_lots
            pnl_tp1 = self._calc_pnl(order, order.take_profit_1, main_lots)
            order.realized_pnl += pnl_tp1
            order.status = OrderStatus.CLOSED_TP1
            # Set runner SL to break-even + small buffer
            if order.direction == SignalDirection.LONG:
                order.runner_sl = order.open_price + abs(order.open_price * 0.0001)
            else:
                order.runner_sl = order.open_price - abs(order.open_price * 0.0001)
            logger.info(
                "tp1_partial_close",
                order_id=order.order_id,
                pnl=pnl_tp1,
                runner_lots=order.runner_lots,
                runner_sl=order.runner_sl,
            )
        elif hit_runner_sl or (hit_tp2 and order.status == OrderStatus.CLOSED_TP1):
            target = order.take_profit_2 if hit_tp2 else order.runner_sl
            pnl_runner = self._calc_pnl(order, target, order.runner_lots)
            total_pnl = order.realized_pnl + pnl_runner
            final_status = OrderStatus.CLOSED_TP2 if hit_tp2 else OrderStatus.CLOSED_SL
            self._close_order(order, target, final_status, total_pnl)

    def _close_order(
        self,
        order: Order,
        close_price: float,
        status: OrderStatus,
        pnl: float,
    ) -> None:
        order.close_price = close_price
        order.close_time = datetime.utcnow()
        order.status = status
        order.realized_pnl = pnl
        self.risk_manager.record_trade_close(pnl)
        logger.info(
            "order_closed",
            order_id=order.order_id,
            status=status.value,
            close_price=close_price,
            pnl=pnl,
        )

    @staticmethod
    def _calc_pnl(order: Order, close_price: float, lots: float) -> float:
        """Simplified PnL: price_diff × lots × 100 (1 lot = 100 units)."""
        direction_mult = 1 if order.direction == SignalDirection.LONG else -1
        return round((close_price - order.open_price) * direction_mult * lots * 100, 2)

    # ------------------------------------------------------------------
    # Live-trade helpers
    # ------------------------------------------------------------------

    def _open_live(self, order: Order, params: TradeParameters) -> None:
        if self.broker is None:
            raise RuntimeError("Broker adapter not set.")
        broker_id = self.broker.place_order(
            symbol=order.symbol,
            direction=order.direction.value,
            lot_size=order.lot_size,
            entry=order.entry_price,
            sl=order.stop_loss,
            tp=order.take_profit_1,
        )
        order.notes += f" broker_id={broker_id}"
        order.open_price = self.broker.get_current_price(order.symbol)
        order.open_time = datetime.utcnow()
        order.status = OrderStatus.OPEN
        self.risk_manager.record_trade_open()
