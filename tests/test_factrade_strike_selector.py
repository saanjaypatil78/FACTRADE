from factrade.strike_selector import StrikeSelector
from factrade.types import OptionQuote


def test_pick_buy_prefers_target_delta_with_liquidity():
    selector = StrikeSelector()
    chain = [
        OptionQuote(strike=25000, option_type="CE", delta=0.58, bid=100, ask=101, ltp=100.5, oi=5000, volume=2000),
        OptionQuote(strike=25100, option_type="CE", delta=0.65, bid=80, ask=80.4, ltp=80.2, oi=10000, volume=4000),
        OptionQuote(strike=25200, option_type="CE", delta=0.70, bid=60, ask=61.2, ltp=60.6, oi=1500, volume=150),
    ]
    decision = selector.pick_for_buy(chain, option_type="CE")
    assert decision is not None
    assert decision.strike == 25100


def test_pick_sell_filters_high_delta():
    selector = StrikeSelector()
    chain = [
        OptionQuote(strike=25000, option_type="PE", delta=-0.55, bid=120, ask=120.5, ltp=120.2, oi=10000, volume=4000),
        OptionQuote(strike=24800, option_type="PE", delta=-0.33, bid=70, ask=70.3, ltp=70.1, oi=9000, volume=2200),
    ]
    decision = selector.pick_for_sell(chain, option_type="PE")
    assert decision is not None
    assert decision.strike == 24800
