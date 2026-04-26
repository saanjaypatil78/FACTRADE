from factrade.risk import RiskConfig, RiskGovernor, RiskState


def test_rejects_when_daily_loss_breached():
    governor = RiskGovernor(RiskConfig(max_daily_loss=1000))
    state = RiskState(trades_today=1, realized_pnl=-1000)
    ok, reason = governor.can_enter(state, regime_clear=True, est_slippage_pct=0.1)
    assert not ok
    assert "max-daily-loss" in reason


def test_on_entry_increments_trade_count():
    governor = RiskGovernor()
    state = RiskState(trades_today=0, realized_pnl=0)
    updated = governor.on_entry(state)
    assert updated.trades_today == 1


def test_recovery_trade_requires_active_chain():
    governor = RiskGovernor()
    state = RiskState(recovery_chain_active=False)
    ok, reason = governor.can_enter(
        state,
        regime_clear=True,
        est_slippage_pct=0.1,
        wants_recovery_trade=True,
    )
    assert not ok
    assert "no-active-recovery-chain" in reason
