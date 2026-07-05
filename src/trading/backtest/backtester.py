"""Backtesting engine for FACTRADE.

Reads from the universal DataStore, runs the full signal pipeline, and
produces a detailed trade log with P&L statistics.

Key features
------------
- Reads normalised OHLCV from DataStore (no re-download needed).
- Uses the same ExitConfig as live monitoring for deterministic behaviour.
- Walk-forward: processes bars in strict chronological order.
- HTF analysis refreshed at configurable intervals (e.g. every 4H bar).
- Outputs a structured results dict and an optional CSV trade log.

Usage
-----
    from src.trading.data.store import DataStore
    from src.trading.backtest.backtester import Backtester, BacktestConfig

    store = DataStore()
    config = BacktestConfig(symbol="XAUUSD", htf="4H", ltf="15m")
    bt = Backtester(store=store, config=config)
    results = bt.run(start="2024-01-01", end="2024-06-01")
    print(results["summary"])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import structlog

from src.trading.analysis.liquidity_detector import LiquidityDetector
from src.trading.analysis.signal_generator import SignalGenerator
from src.trading.data.store import DataStore
from src.trading.execution.exit_manager import ExitConfig, ExitManager
from src.trading.execution.risk_manager import RiskManager, _PIP_VALUE_PER_LOT

logger = structlog.get_logger(__name__)


@dataclass
class BacktestConfig:
    """Deterministic configuration for a backtest run."""

    symbol: str = "XAUUSD"
    htf: str = "4H"                 # HTF for liquidity detection
    ltf: str = "15m"                # LTF for signal generation
    account_balance: float = 1400.0
    risk_pct: float = 0.5
    atr_period: int = 14
    swing_lookback: int = 5
    htf_refresh_bars: int = 1       # re-scan HTF liquidity every N LTF bars
    exit: ExitConfig = field(default_factory=ExitConfig)
    data_source: Optional[str] = None  # None = auto-select from store


@dataclass
class BacktestTrade:
    """Record of a single backtest trade."""

    symbol: str
    direction: str
    open_time: pd.Timestamp
    close_time: Optional[pd.Timestamp]
    open_price: float
    close_price: float
    lots: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    pnl_pips: float
    exit_reason: str
    htf: str
    ltf: str
    regime: str = ""
    confidence: float = 0.0


class Backtester:
    """Walk-forward backtesting engine.

    Parameters
    ----------
    store:
        DataStore instance providing OHLCV data.
    config:
        BacktestConfig defining the strategy parameters.
    """

    def __init__(self, store: DataStore, config: Optional[BacktestConfig] = None) -> None:
        self._store = store
        self.config = config or BacktestConfig()
        self._ld = LiquidityDetector(swing_lookback=self.config.swing_lookback)
        self._sg = SignalGenerator()
        self._rm = RiskManager(
            account_balance=self.config.account_balance,
            risk_pct=self.config.risk_pct,
        )
        self._em = ExitManager(config=self.config.exit, risk_manager=self._rm)

    def run(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        htf_df: Optional[pd.DataFrame] = None,
        ltf_df: Optional[pd.DataFrame] = None,
    ) -> dict:
        """Run the backtest.

        Parameters
        ----------
        start / end:
            Date range for the backtest.
        htf_df / ltf_df:
            Optional pre-loaded DataFrames (bypass store for testing).

        Returns
        -------
        dict
            ``{"trades": list[BacktestTrade], "summary": dict, "equity_curve": pd.Series}``
        """
        cfg = self.config

        # Load data
        if htf_df is None:
            htf_df = self._store.load(cfg.symbol, cfg.htf, start=start, end=end, source=cfg.data_source)
        if ltf_df is None:
            ltf_df = self._store.load(cfg.symbol, cfg.ltf, start=start, end=end, source=cfg.data_source)

        if htf_df.empty or ltf_df.empty:
            logger.warning(
                "backtester.no_data",
                symbol=cfg.symbol,
                htf=cfg.htf,
                ltf=cfg.ltf,
            )
            return {"trades": [], "summary": {}, "equity_curve": pd.Series(dtype=float)}

        logger.info(
            "backtester.start",
            symbol=cfg.symbol,
            htf_bars=len(htf_df),
            ltf_bars=len(ltf_df),
            start=start,
            end=end,
        )

        trades: list[BacktestTrade] = []
        open_trades: list[dict] = []  # {"trade": OpenTrade, "bt_rec": BacktestTrade}
        equity = self.config.account_balance
        equity_curve: list[tuple] = []
        htf_levels = []

        htf_bar_counter = 0

        for i, (ts, ltf_bar) in enumerate(ltf_df.iterrows()):
            # Refresh HTF liquidity periodically
            if i % cfg.htf_refresh_bars == 0:
                htf_slice = htf_df[htf_df.index <= ts]
                if not htf_slice.empty:
                    htf_levels = self._ld.detect(htf_slice, timeframe=cfg.htf)

            # Update sweep status with latest HTF bar
            htf_now = htf_df[htf_df.index <= ts]
            if not htf_now.empty:
                self._ld.update_sweep_status(htf_levels, htf_now.iloc[-1])

            swept = self._ld.get_swept_levels(htf_levels)

            # ATR
            ltf_slice = ltf_df.iloc[: i + 1]
            atr = self._compute_atr(ltf_slice)

            # Update open trades
            still_open = []
            for rec in open_trades:
                action = self._em.update(rec["trade"], ltf_bar, atr=atr)
                if action and rec["trade"].closed:
                    bt_rec = rec["bt_rec"]
                    bt_rec.close_time = ts
                    bt_rec.close_price = rec["trade"].close_price
                    bt_rec.pnl_pips = rec["trade"].pnl
                    bt_rec.exit_reason = rec["trade"].close_reason.name if rec["trade"].close_reason else ""
                    trades.append(bt_rec)
                    pip_val = _PIP_VALUE_PER_LOT.get(cfg.symbol.upper(), 10.0)
                    equity += bt_rec.pnl_pips * bt_rec.lots * pip_val
                    equity_curve.append((ts, equity))
                else:
                    still_open.append(rec)
            open_trades = still_open

            # Generate new signals (only if no open trade in same direction)
            if swept:
                ltf_window = ltf_df.iloc[max(0, i - 50): i + 1]
                signals = self._sg.generate(
                    ltf_window, swept, symbol=cfg.symbol, timeframe=cfg.ltf
                )
                for sig in signals:
                    # Avoid stacking positions
                    same_dir = [r for r in open_trades if r["trade"].spec.direction == sig.direction]
                    if same_dir:
                        continue

                    spec = self._rm.calculate(
                        symbol=sig.symbol,
                        direction=sig.direction,
                        entry_price=sig.entry_price,
                        wick_price=sig.sl_price,
                        tp1_price=sig.tp1_price,
                        tp2_price=sig.tp2_price,
                        atr=atr,
                        is_aplus=(sig.confidence >= 0.8),
                    )
                    if not spec.valid:
                        continue

                    open_trade = self._em.open_trade(spec, open_time=ts)
                    bt_rec = BacktestTrade(
                        symbol=cfg.symbol,
                        direction=sig.direction,
                        open_time=ts,
                        close_time=None,
                        open_price=sig.entry_price,
                        close_price=0.0,
                        lots=spec.lot_size,
                        sl_price=spec.sl_price,
                        tp1_price=sig.tp1_price,
                        tp2_price=sig.tp2_price,
                        pnl_pips=0.0,
                        exit_reason="",
                        htf=cfg.htf,
                        ltf=cfg.ltf,
                        regime=sig.regime,
                        confidence=sig.confidence,
                    )
                    open_trades.append({"trade": open_trade, "bt_rec": bt_rec})

            if i % 500 == 0:
                equity_curve.append((ts, equity))

        # Force-close any remaining open trades at last bar price
        last_close = float(ltf_df["close"].iloc[-1])
        last_ts = ltf_df.index[-1]
        for rec in open_trades:
            action = self._em.force_close(rec["trade"], last_close, last_ts)
            bt_rec = rec["bt_rec"]
            bt_rec.close_time = last_ts
            bt_rec.close_price = last_close
            bt_rec.pnl_pips = rec["trade"].pnl
            bt_rec.exit_reason = "END_OF_DATA"
            trades.append(bt_rec)

        summary = self._summarise(trades, equity)
        eq_series = pd.Series(
            dict(equity_curve), dtype=float
        ) if equity_curve else pd.Series(dtype=float)

        logger.info(
            "backtester.complete",
            trades=len(trades),
            final_equity=round(equity, 2),
        )
        return {"trades": trades, "summary": summary, "equity_curve": eq_series}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return float((df["high"] - df["low"]).mean())
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    @staticmethod
    def _summarise(trades: list[BacktestTrade], final_equity: float) -> dict:
        if not trades:
            return {
                "total_trades": 0,
                "winners": 0,
                "losers": 0,
                "win_rate": 0.0,
                "total_pips": 0.0,
                "avg_pips": 0.0,
                "final_equity": final_equity,
            }
        pips = [t.pnl_pips for t in trades]
        winners = [p for p in pips if p > 0]
        losers = [p for p in pips if p <= 0]
        return {
            "total_trades": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(len(winners) / len(trades), 3),
            "total_pips": round(sum(pips), 1),
            "avg_pips": round(sum(pips) / len(trades), 1),
            "avg_winner_pips": round(sum(winners) / max(len(winners), 1), 1),
            "avg_loser_pips": round(sum(losers) / max(len(losers), 1), 1),
            "final_equity": round(final_equity, 2),
        }
