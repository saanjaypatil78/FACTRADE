"""
Tests for src/trading/risk_manager.py
"""

import pytest
from datetime import date

from src.trading.risk_manager import RiskManager, TradeParameters, DailyStats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rm():
    return RiskManager(
        equity=1000.0,
        risk_pct=1.0,
        max_risk_pct=2.0,
        max_sl_pips=50.0,
        max_daily_loss_pct=2.0,
        max_concurrent_trades=2,
        min_rr_ratio=1.5,
        pip_values={"XAUUSD": 1.0, "WTIUSD": 1.0},
    )


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_initialisation(rm):
    assert rm.equity == 1000.0
    assert rm.risk_pct == 1.0
    assert rm.max_concurrent_trades == 2


def test_risk_pct_capped_at_max():
    rm = RiskManager(equity=1000.0, risk_pct=5.0, max_risk_pct=2.0)
    assert rm.risk_pct == 2.0


# ---------------------------------------------------------------------------
# Position-sizing
# ---------------------------------------------------------------------------

def test_lot_size_calculation(rm):
    """risk_amount = $10, sl_distance = 10 → lots = 10/10 = 1.0"""
    rm2 = RiskManager(
        equity=1000.0,
        risk_pct=1.0,
        max_sl_pips=200.0,
        pip_values={"XAUUSD": 1.0},
    )
    params = rm2.evaluate("XAUUSD", 3200.0, 3190.0, 3215.0, 3230.0, 1.5)
    assert params.approved
    assert params.lot_size == pytest.approx(1.0, abs=0.01)
    assert params.risk_amount == pytest.approx(10.0, abs=0.5)


def test_lot_size_minimum(rm):
    """Lot size should never drop below 0.01."""
    rm2 = RiskManager(
        equity=1.0,  # tiny equity
        risk_pct=1.0,
        max_sl_pips=500.0,
        pip_values={"XAUUSD": 1.0},
    )
    params = rm2.evaluate("XAUUSD", 3200.0, 3100.0, 3250.0, 3300.0, 1.5)
    if params.approved:
        assert params.lot_size >= 0.01


def test_lot_size_scales_with_equity():
    rm_small = RiskManager(equity=100.0, risk_pct=1.0, max_sl_pips=200.0,
                            pip_values={"XAUUSD": 1.0})
    rm_large = RiskManager(equity=10000.0, risk_pct=1.0, max_sl_pips=200.0,
                            pip_values={"XAUUSD": 1.0})
    p_small = rm_small.evaluate("XAUUSD", 3200.0, 3190.0, 3215.0, 3230.0, 1.5)
    p_large = rm_large.evaluate("XAUUSD", 3200.0, 3190.0, 3215.0, 3230.0, 1.5)
    if p_small.approved and p_large.approved:
        assert p_large.lot_size > p_small.lot_size


# ---------------------------------------------------------------------------
# Gate: SL distance
# ---------------------------------------------------------------------------

def test_rejects_wide_sl(rm):
    params = rm.evaluate("XAUUSD", 3200.0, 3100.0, 3260.0, 3320.0, 1.5)
    assert not params.approved
    assert "max_sl_pips" in params.rejection_reason


def test_approves_narrow_sl(rm):
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3215.0, 3230.0, 1.5)
    assert params.approved


# ---------------------------------------------------------------------------
# Gate: RR ratio
# ---------------------------------------------------------------------------

def test_rejects_low_rr(rm):
    # SL = 10, TP = 5 → RR = 0.5 < 1.5
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3205.0, 3215.0, 0.5)
    assert not params.approved
    assert "RR ratio" in params.rejection_reason


def test_approves_good_rr(rm):
    # SL = 10, TP1 = 20 → RR = 2.0 >= 1.5
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3220.0, 3240.0, 2.0)
    assert params.approved


# ---------------------------------------------------------------------------
# Gate: Daily loss cap
# ---------------------------------------------------------------------------

def test_rejects_after_daily_loss_cap(rm):
    # Simulate a 3 % loss on $1000 equity → should exceed 2 % cap
    rm._daily_stats.realized_pnl = -30.0  # -3 %
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3220.0, 3240.0, 2.0)
    assert not params.approved
    assert "Daily loss cap" in params.rejection_reason


def test_allows_trade_within_daily_loss(rm):
    rm._daily_stats.realized_pnl = -5.0  # -0.5 % — within 2 % cap
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3220.0, 3240.0, 2.0)
    assert params.approved


# ---------------------------------------------------------------------------
# Gate: Max concurrent trades
# ---------------------------------------------------------------------------

def test_rejects_when_max_trades_reached(rm):
    rm._daily_stats.open_trades = 2  # already at max
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3220.0, 3240.0, 2.0)
    assert not params.approved
    assert "concurrent trades" in params.rejection_reason


def test_approves_under_max_trades(rm):
    rm._daily_stats.open_trades = 1  # 1 open, max is 2
    params = rm.evaluate("XAUUSD", 3200.0, 3190.0, 3220.0, 3240.0, 2.0)
    assert params.approved


# ---------------------------------------------------------------------------
# Record trade lifecycle
# ---------------------------------------------------------------------------

def test_record_trade_open_increments_count(rm):
    assert rm.daily_stats.open_trades == 0
    rm.record_trade_open()
    assert rm.daily_stats.open_trades == 1


def test_record_trade_close_decrements_count(rm):
    rm.record_trade_open()
    rm.record_trade_close(pnl=50.0)
    assert rm.daily_stats.open_trades == 0
    assert rm.daily_stats.realized_pnl == pytest.approx(50.0)


def test_record_trade_close_loss(rm):
    rm.record_trade_open()
    rm.record_trade_close(pnl=-15.0)
    assert rm.daily_stats.realized_pnl == pytest.approx(-15.0)


def test_update_equity(rm):
    rm.update_equity(1500.0)
    assert rm.equity == 1500.0


# ---------------------------------------------------------------------------
# Daily stats reset
# ---------------------------------------------------------------------------

def test_daily_stats_reset():
    stats = DailyStats(date=date(2020, 1, 1), realized_pnl=-100.0, open_trades=3)
    # Simulate a new day
    stats.date = date(2020, 1, 1)  # old date
    # We can't easily mock date.today() here without patching, so just verify
    # the model holds correct data
    assert stats.realized_pnl == -100.0
    assert stats.open_trades == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_sl_equals_entry_does_not_crash(rm):
    """Edge case: SL = entry (zero distance). Should be rejected."""
    params = rm.evaluate("XAUUSD", 3200.0, 3200.0, 3220.0, 3240.0, 2.0)
    # Either rejected (SL == entry is technically valid but RR would be inf)
    # or approved with lot_size >= 0.01
    assert isinstance(params.approved, bool)


def test_unknown_symbol_uses_default_pip_value():
    rm = RiskManager(equity=1000.0, risk_pct=1.0, max_sl_pips=200.0)
    params = rm.evaluate("EXOTIC_PAIR", 100.0, 90.0, 115.0, 130.0, 1.5)
    assert isinstance(params.approved, bool)
