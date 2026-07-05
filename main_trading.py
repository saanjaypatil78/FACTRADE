#!/usr/bin/env python3
"""
FACTRADE Trading CLI – free-only live monitoring and historical backtesting.

Commands
--------
::

    # Live monitoring (paper-trade, no paid credits required)
    python main_trading.py monitor --symbols XAUUSD USOIL

    # Live monitoring with custom timeframes and poll interval
    python main_trading.py monitor --symbols XAUUSD --timeframes 1H 15m 5m --interval 60

    # Backtest using free yfinance proxy data
    python main_trading.py backtest --symbols XAUUSD --timeframes 1H 15m --source yfinance

    # Backtest using broker-exported CSV files
    python main_trading.py backtest \\
        --symbols XAUUSD \\
        --csv-1h  data/XAUUSD_H1.csv \\
        --csv-15m data/XAUUSD_M15.csv \\
        --csv-5m  data/XAUUSD_M5.csv

    # Show help
    python main_trading.py --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the repo root is on the Python path when called directly.
sys.path.insert(0, str(Path(__file__).parent))

from src.trading.adapters.yfinance_adapter import YFinanceAdapter
from src.trading.adapters.csv_adapter import CSVAdapter
from src.trading.backtester import Backtester
from src.trading.monitor import LiveMonitor
from src.trading.risk_manager import RiskManager

# ------------------------------------------------------------------ #
# Defaults
# ------------------------------------------------------------------ #
DEFAULT_SYMBOLS = ["XAUUSD", "USOIL"]
DEFAULT_TIMEFRAMES = ["1H", "15m", "5m"]
DEFAULT_POLL_INTERVAL = 60  # seconds
DEFAULT_CANDLE_LIMIT = 500


# ================================================================== #
# Monitor command
# ================================================================== #

def cmd_monitor(args: argparse.Namespace) -> None:
    adapter = YFinanceAdapter()
    risk = RiskManager(
        atr_multiplier=args.atr_mult,
        max_sl_pips=args.max_sl_pips,
        default_risk_pct=args.risk_pct / 100.0,
    )
    monitor = LiveMonitor(
        adapter=adapter,
        poll_interval=args.interval,
        candle_limit=DEFAULT_CANDLE_LIMIT,
        risk_manager=risk,
    )
    print(
        f"\n🟢 FACTRADE Live Monitor (paper-trade)\n"
        f"   Symbols   : {', '.join(args.symbols)}\n"
        f"   Timeframes: {', '.join(args.timeframes)}\n"
        f"   Source    : yfinance (free — GC=F / CL=F proxies)\n"
        f"   Interval  : {args.interval}s\n"
        f"   Press Ctrl-C to stop.\n"
    )
    monitor.run(symbols=args.symbols, timeframes=args.timeframes)


# ================================================================== #
# Backtest command
# ================================================================== #

def cmd_backtest(args: argparse.Namespace) -> None:
    risk = RiskManager(
        atr_multiplier=args.atr_mult,
        max_sl_pips=args.max_sl_pips,
        default_risk_pct=args.risk_pct / 100.0,
    )
    bt = Backtester(risk_manager=risk)

    for symbol in args.symbols:
        print(f"\n⏳ Backtesting {symbol} …")
        candles_by_tf = _load_candles(args, symbol)

        if not candles_by_tf:
            print(f"  ❌ No candle data available for {symbol}. Skipping.")
            continue

        report = bt.run(candles_by_tf=candles_by_tf, symbol=symbol)
        bt.print_report(report)

        if args.json_out:
            import json
            out_path = Path(args.json_out) / f"backtest_{symbol}.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report.to_dict(), indent=2))
            print(f"  📄 Report saved to {out_path}")


def _load_candles(args: argparse.Namespace, symbol: str) -> dict:
    """Build candles_by_tf dict from CLI args (CSV or yfinance)."""
    candles_by_tf: dict = {}

    # CSV paths take priority (exact-symbol fidelity)
    csv_map = {
        "1D": getattr(args, "csv_1d", None),
        "4H": getattr(args, "csv_4h", None),
        "1H": getattr(args, "csv_1h", None),
        "15m": getattr(args, "csv_15m", None),
        "5m": getattr(args, "csv_5m", None),
    }

    for tf, csv_path in csv_map.items():
        if csv_path:
            try:
                adapter = CSVAdapter(csv_path, symbol=symbol, timeframe=tf)
                candles = adapter.fetch()
                if candles:
                    candles_by_tf[tf] = candles
                    print(f"  📂 Loaded {len(candles)} {tf} candles from {csv_path}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠️  Could not load {csv_path}: {exc}")

    # Fall back to yfinance if no CSV data loaded for this timeframe
    if not candles_by_tf or getattr(args, "source", "yfinance") == "yfinance":
        yfadapter = YFinanceAdapter()
        for tf in args.timeframes:
            if tf in candles_by_tf:
                continue
            try:
                candles = yfadapter.fetch(symbol=symbol, timeframe=tf)
                if candles:
                    candles_by_tf[tf] = candles
                    print(
                        f"  🌐 Fetched {len(candles)} {tf} candles "
                        f"from yfinance (proxy symbol)"
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠️  yfinance fetch failed for {symbol}/{tf}: {exc}")

    return candles_by_tf


# ================================================================== #
# Argument parser
# ================================================================== #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main_trading.py",
        description="FACTRADE – free-only trading monitor and backtester",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- monitor ----
    mon = sub.add_parser("monitor", help="Live monitoring loop (paper-trade)")
    mon.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        metavar="SYM",
        help="Symbols to monitor (default: XAUUSD USOIL)",
    )
    mon.add_argument(
        "--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES,
        metavar="TF",
        help="Timeframes to fetch (default: 1H 15m 5m)",
    )
    mon.add_argument(
        "--interval", type=int, default=DEFAULT_POLL_INTERVAL,
        metavar="SEC",
        help="Poll interval in seconds (default: 60)",
    )
    _add_risk_args(mon)

    # ---- backtest ----
    bkt = sub.add_parser("backtest", help="Historical backtest")
    bkt.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        metavar="SYM",
    )
    bkt.add_argument(
        "--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES,
        metavar="TF",
    )
    bkt.add_argument(
        "--source", choices=["yfinance", "csv"], default="yfinance",
        help="Data source (default: yfinance)",
    )
    # CSV overrides
    bkt.add_argument("--csv-1d",  metavar="FILE", help="Daily CSV file path")
    bkt.add_argument("--csv-4h",  metavar="FILE", help="4H CSV file path")
    bkt.add_argument("--csv-1h",  metavar="FILE", help="1H CSV file path")
    bkt.add_argument("--csv-15m", metavar="FILE", help="15m CSV file path")
    bkt.add_argument("--csv-5m",  metavar="FILE", help="5m CSV file path")
    bkt.add_argument(
        "--json-out", metavar="DIR",
        help="Directory to write JSON backtest reports",
    )
    _add_risk_args(bkt)

    return parser


def _add_risk_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--atr-mult", type=float, default=1.5,
        metavar="X",
        help="ATR multiplier for SL buffer (default: 1.5)",
    )
    p.add_argument(
        "--max-sl-pips", type=int, default=50,
        metavar="N",
        help="Maximum SL distance in pips (default: 50)",
    )
    p.add_argument(
        "--risk-pct", type=float, default=0.5,
        metavar="PCT",
        help="Percent of balance to risk per trade (default: 0.5)",
    )


# ================================================================== #
# Entry point
# ================================================================== #

if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "monitor":
        cmd_monitor(args)
    elif args.command == "backtest":
        cmd_backtest(args)
