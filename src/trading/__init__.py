"""
FACTRADE trading system – free-only live monitoring and historical backtesting
for XAUUSD and USOIL/WTI.
"""

from .candle import Candle, Signal, TradeResult
from .adapters.base import BaseAdapter
from .adapters.csv_adapter import CSVAdapter
from .adapters.yfinance_adapter import YFinanceAdapter
from .liquidity_detector import LiquidityDetector
from .signal_generator import SignalGenerator
from .risk_manager import RiskManager
from .trade_executor import TradeExecutor
from .backtester import Backtester
from .monitor import LiveMonitor

__all__ = [
    "Candle",
    "Signal",
    "TradeResult",
    "BaseAdapter",
    "CSVAdapter",
    "YFinanceAdapter",
    "LiquidityDetector",
    "SignalGenerator",
    "RiskManager",
    "TradeExecutor",
    "Backtester",
    "LiveMonitor",
]
