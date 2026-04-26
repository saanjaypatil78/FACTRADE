from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RiskConfig:
    max_trades_per_day: int = 8
    max_daily_loss: float = 5_000.0
    max_slippage_pct: float = 0.8
    allow_single_recovery_chain: bool = True


@dataclass(frozen=True)
class RiskState:
    trades_today: int = 0
    realized_pnl: float = 0.0
    recovery_chain_active: bool = False


class RiskGovernor:
    def __init__(self, cfg: RiskConfig | None = None):
        self.cfg = cfg or RiskConfig()

    def can_enter(
        self,
        state: RiskState,
        *,
        regime_clear: bool,
        est_slippage_pct: float,
        wants_recovery_trade: bool = False,
    ) -> tuple[bool, str]:
        if not regime_clear:
            return False, "blocked:no-trade-regime"

        if state.trades_today >= self.cfg.max_trades_per_day:
            return False, "blocked:max-trades-reached"

        if state.realized_pnl <= -abs(self.cfg.max_daily_loss):
            return False, "blocked:max-daily-loss-reached"

        if est_slippage_pct > self.cfg.max_slippage_pct:
            return False, "blocked:slippage-too-high"

        if self.cfg.allow_single_recovery_chain and wants_recovery_trade and not state.recovery_chain_active:
            return False, "blocked:no-active-recovery-chain"

        return True, "approved"

    def on_entry(self, state: RiskState, *, recovery_chain_active: bool | None = None) -> RiskState:
        return replace(
            state,
            trades_today=state.trades_today + 1,
            recovery_chain_active=state.recovery_chain_active if recovery_chain_active is None else recovery_chain_active,
        )

    def on_trade_close(self, state: RiskState, *, pnl: float, recovery_chain_active: bool | None = None) -> RiskState:
        return replace(
            state,
            realized_pnl=state.realized_pnl + pnl,
            recovery_chain_active=state.recovery_chain_active if recovery_chain_active is None else recovery_chain_active,
        )
