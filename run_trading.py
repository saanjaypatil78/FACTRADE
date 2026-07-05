#!/usr/bin/env python3
"""
FACTRADE Trading Monitor — single-command startup.

Usage
-----
    # Paper-trading mode (default, no broker required):
    python run_trading.py

    # Custom config file:
    python run_trading.py --config my_config.yaml

    # Single evaluation pass (useful for cron / testing):
    python run_trading.py --once

    # Run with live execution (requires broker adapter):
    python run_trading.py --live

The script uses a *simulated* data provider by default, which generates
synthetic OHLCV data so the system can be exercised without a live data
feed.  Replace `_make_data_provider()` with your real market-data source
(MT5, yfinance, CCXT, broker WebSocket, etc.) — see TRADING.md.
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict

import numpy as np
import pandas as pd

from src.trading.monitor import MonitorConfig, TradingMonitor
from src.trading.signal_generator import TradeSignal
from src.trading.trade_executor import Order


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("factrade.runner")


# ---------------------------------------------------------------------------
# Simulated data provider (replace with real feed in production)
# ---------------------------------------------------------------------------

_TIMEFRAME_MINUTES: Dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "3H": 180,
    "4H": 240,
    "1D": 1440,
}

_BASE_PRICES: Dict[str, float] = {
    "XAUUSD": 3200.0,
    "WTIUSD": 78.0,
}


def _simulated_provider(symbol: str, timeframe: str) -> pd.DataFrame:
    """
    Generate a realistic-looking synthetic OHLCV DataFrame.

    Replace this function with a call to your actual data source:
        - MetaTrader 5: mt5.copy_rates_from_pos(symbol, tf, 0, 500)
        - yfinance:     yf.download(symbol, period="60d", interval="1h")
        - CCXT:         exchange.fetch_ohlcv(symbol, timeframe, limit=500)
    """
    tf_min = _TIMEFRAME_MINUTES.get(timeframe, 60)
    n_candles = 500
    base = _BASE_PRICES.get(symbol, 100.0)

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
    start = end - timedelta(minutes=tf_min * n_candles)
    index = pd.date_range(start=start, end=end, freq=f"{tf_min}min")[:n_candles]

    rng = np.random.default_rng(seed=int(start.timestamp()) % (2**32))
    returns = rng.normal(0, 0.0005, n_candles).cumsum()
    closes = base * (1 + returns)

    highs = closes * (1 + rng.uniform(0.0001, 0.003, n_candles))
    lows = closes * (1 - rng.uniform(0.0001, 0.003, n_candles))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    volumes = rng.integers(100, 10000, n_candles).astype(float)

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )
    return df


# ---------------------------------------------------------------------------
# Alert callback
# ---------------------------------------------------------------------------

def _console_alert(signal: TradeSignal, order: Order) -> None:
    """Print a formatted alert to the console when a new order is opened."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  📊 NEW SIGNAL  [{order.order_id}]")
    print(f"  Symbol   : {signal.symbol}")
    print(f"  Direction: {signal.direction.value.upper()}")
    print(f"  Regime   : {signal.regime.value}")
    print(f"  Entry    : {signal.entry_price:.4f}")
    print(f"  SL       : {signal.stop_loss:.4f}  (dist {signal.risk_pips:.4f})")
    print(f"  TP1 (80%): {signal.take_profit_1:.4f}")
    print(f"  TP2 (20%): {signal.take_profit_2:.4f}")
    print(f"  R:R      : 1:{signal.rr_ratio}")
    print(f"  Lot size : {order.lot_size}")
    print(f"  Notes    : {signal.notes}")
    print(f"  Time     : {signal.timestamp}")
    print(sep)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FACTRADE Multi-Timeframe Liquidity Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="trading_config.yaml",
        help="Path to YAML config file (default: trading_config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single evaluation pass then exit",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Switch to live execution mode (requires broker adapter setup)",
    )
    args = parser.parse_args()

    # Load config
    try:
        cfg = MonitorConfig.from_yaml(args.config)
    except FileNotFoundError:
        logger.error("Config file not found: %s", args.config)
        sys.exit(1)

    # Override mode from CLI flag
    if args.live:
        cfg.paper_mode = False
        logger.warning(
            "LIVE MODE ENABLED — ensure your broker adapter is configured "
            "before allowing real order placement."
        )

    mode_label = "PAPER" if cfg.paper_mode else "LIVE ⚠️"
    logger.info("Starting FACTRADE Monitor  [mode=%s]", mode_label)

    monitor = TradingMonitor(
        config=cfg,
        data_provider=_simulated_provider,
        alert_callbacks=[_console_alert],
    )

    if args.once:
        results = monitor.run_once()
        for sym, sigs in results.items():
            logger.info("Symbol %s: %d signal(s) this cycle", sym, len(sigs))
    else:
        monitor.run()


if __name__ == "__main__":
    main()
