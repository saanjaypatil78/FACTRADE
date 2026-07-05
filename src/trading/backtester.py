"""
Backtester – historical backtest engine for FACTRADE strategies.

Usage
-----
::

    from src.trading.adapters.csv_adapter import CSVAdapter
    from src.trading.backtester import Backtester

    adapter = CSVAdapter("data/XAUUSD_H1.csv", symbol="XAUUSD", timeframe="1H")
    bt = Backtester()
    report = bt.run(
        candles_1h=adapter.fetch(),
        candles_15m=CSVAdapter("data/XAUUSD_M15.csv", "XAUUSD", "15m").fetch(),
        candles_5m=CSVAdapter("data/XAUUSD_M5.csv", "XAUUSD", "5m").fetch(),
        symbol="XAUUSD",
    )
    bt.print_report(report)

The engine replays candles chronologically and checks all four setups on
each new bar.  Open positions are marked to market on every subsequent bar.
The 80/20 partial-close rule is applied: TP1 closes 80 % of the position,
TP2 closes the remaining 20 %.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import structlog

from src.trading.candle import Candle, Signal, TradeResult
from src.trading.signal_generator import SignalGenerator
from src.trading.risk_manager import RiskManager
from src.trading.trade_executor import TradeExecutor

logger = structlog.get_logger(__name__)

# Minimum warm-up bars before strategy can fire
_WARMUP_BARS = 250


class BacktestReport:
    """Container for backtest results."""

    def __init__(
        self,
        trades: List[TradeResult],
        signals: List[Signal],
        symbol: str,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> None:
        self.trades = trades
        self.signals = signals
        self.symbol = symbol
        self.start = start
        self.end = end

    # ------------------------------------------------------------------ #
    # Metrics
    # ------------------------------------------------------------------ #

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.is_win)

    @property
    def losses(self) -> int:
        return self.total_trades - self.wins

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades else 0.0

    @property
    def total_pips(self) -> float:
        return sum(t.pnl_pips for t in self.trades)

    @property
    def avg_win_pips(self) -> float:
        wins = [t.pnl_pips for t in self.trades if t.is_win]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss_pips(self) -> float:
        losses = [t.pnl_pips for t in self.trades if not t.is_win]
        return sum(losses) / len(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pips for t in self.trades if t.is_win)
        gross_loss = abs(sum(t.pnl_pips for t in self.trades if not t.is_win))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def max_drawdown_pips(self) -> float:
        """Maximum peak-to-trough drawdown in pips."""
        if not self.trades:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.pnl_pips
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def by_setup(self) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        for trade in self.trades:
            setup = trade.signal.setup_type
            if setup not in result:
                result[setup] = {"count": 0, "wins": 0, "pips": 0.0}
            result[setup]["count"] += 1
            if trade.is_win:
                result[setup]["wins"] += 1
            result[setup]["pips"] += trade.pnl_pips
        return result

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": round(self.win_rate, 1),
            "total_pips": round(self.total_pips, 1),
            "avg_win_pips": round(self.avg_win_pips, 1),
            "avg_loss_pips": round(self.avg_loss_pips, 1),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown_pips": round(self.max_drawdown_pips, 1),
            "by_setup": self.by_setup,
        }


class Backtester:
    """
    Walk-forward backtest engine.

    Parameters
    ----------
    warmup_bars:
        Number of bars consumed as indicator warm-up (no trades during
        this period).  Defaults to 250.
    risk_manager:
        Pre-configured :class:`RiskManager`.
    """

    def __init__(
        self,
        warmup_bars: int = _WARMUP_BARS,
        risk_manager: Optional[RiskManager] = None,
    ) -> None:
        self.warmup_bars = warmup_bars
        self.risk = risk_manager or RiskManager()
        self.sig_gen = SignalGenerator(risk_manager=self.risk)

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def run(
        self,
        candles_by_tf: Dict[str, List[Candle]],
        symbol: str,
    ) -> BacktestReport:
        """
        Run a multi-timeframe backtest.

        Parameters
        ----------
        candles_by_tf:
            Dict mapping timeframe strings to sorted (oldest-first) candle
            lists.  At minimum supply one of ``"1H"`` / ``"4H"`` plus
            ``"15m"`` for the OTE+CHoCH setup.
        symbol:
            Asset symbol for reporting.

        Returns
        -------
        BacktestReport
        """
        # Determine the primary (lowest) timeframe for the replay loop
        priority = ["1m", "5m", "15m", "30m", "1H", "4H", "1D"]
        primary_tf = next(
            (tf for tf in priority if tf in candles_by_tf),
            next(iter(candles_by_tf)),
        )
        primary = candles_by_tf[primary_tf]

        if len(primary) < self.warmup_bars + 10:
            logger.warning(
                "backtester.insufficient_data",
                tf=primary_tf,
                count=len(primary),
            )
            return BacktestReport([], [], symbol, None, None)

        executor = TradeExecutor(paper_trade=True)
        all_signals: List[Signal] = []

        # Pre-sort all timeframe candle lists and build an index map
        # so we can look up "candles up to timestamp T" in O(log n).
        import bisect

        sorted_tfs: dict = {}
        ts_arrays: dict = {}
        for tf, tf_candles in candles_by_tf.items():
            srt = sorted(tf_candles, key=lambda c: c.timestamp)
            sorted_tfs[tf] = srt
            ts_arrays[tf] = [c.timestamp for c in srt]

        # Use the sorted primary list for the replay loop
        primary = sorted_tfs[primary_tf]
        start_ts = primary[self.warmup_bars].timestamp
        end_ts = primary[-1].timestamp

        logger.info(
            "backtester.start",
            symbol=symbol,
            primary_tf=primary_tf,
            candles=len(primary),
            start=start_ts.isoformat(),
            end=end_ts.isoformat(),
        )

        for i in range(self.warmup_bars, len(primary)):
            current_candle = primary[i]
            current_ts = current_candle.timestamp

            # Update any open positions with the current candle
            executor.update(current_candle)

            # Build the per-timeframe window up to (and including) the current bar
            window: Dict[str, List[Candle]] = {}
            for tf, srt in sorted_tfs.items():
                # Binary-search for the insertion point of current_ts
                idx = bisect.bisect_right(ts_arrays[tf], current_ts)
                window[tf] = srt[:idx]

            # Run strategy
            signals = self.sig_gen.scan(window, symbol)
            for sig in signals:
                all_signals.append(sig)
                executor.execute(sig)

        logger.info(
            "backtester.complete",
            symbol=symbol,
            signals=len(all_signals),
            trades=len(executor.closed_trades),
        )

        report = BacktestReport(
            trades=executor.closed_trades,
            signals=all_signals,
            symbol=symbol,
            start=start_ts,
            end=end_ts,
        )
        return report

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #

    @staticmethod
    def print_report(report: BacktestReport) -> None:  # pragma: no cover
        d = report.to_dict()
        sep = "-" * 52
        print(f"\n{'='*52}")
        print(f"  FACTRADE Backtest Report – {d['symbol']}")
        print(f"  Period: {d['start']} → {d['end']}")
        print(f"{'='*52}")
        print(f"  Total trades      : {d['total_trades']}")
        print(f"  Wins / Losses     : {d['wins']} / {d['losses']}")
        print(f"  Win rate          : {d['win_rate_pct']} %")
        print(f"  Total pips        : {d['total_pips']}")
        print(f"  Avg win pips      : {d['avg_win_pips']}")
        print(f"  Avg loss pips     : {d['avg_loss_pips']}")
        print(f"  Profit factor     : {d['profit_factor']}")
        print(f"  Max drawdown pips : {d['max_drawdown_pips']}")
        if d["by_setup"]:
            print(sep)
            print("  By setup:")
            for setup, stats in d["by_setup"].items():
                wr = round(stats["wins"] / stats["count"] * 100, 1) if stats["count"] else 0
                print(
                    f"    {setup:<20} "
                    f"n={stats['count']:>4}  wr={wr:>5.1f}%  "
                    f"pips={round(stats['pips'],1):>8}"
                )
        print(f"{'='*52}\n")
