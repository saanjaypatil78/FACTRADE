from factrade.regime import RegimeClassifier, RegimeConfig
from factrade.types import Regime


def test_trend_requires_persistence():
    clf = RegimeClassifier(RegimeConfig(persistence_candles=2))
    snap1 = clf.classify(
        close=25200,
        ema30=25190,
        ema95=25150,
        hma220=25100,
        hma220_slope=15,
        st_20_6_bullish=True,
        st_mixed_or_flipping=False,
    )
    assert snap1.regime == Regime.NO_TRADE

    snap2 = clf.classify(
        close=25220,
        ema30=25200,
        ema95=25160,
        hma220=25120,
        hma220_slope=18,
        st_20_6_bullish=True,
        st_mixed_or_flipping=False,
    )
    assert snap2.regime == Regime.TREND


def test_range_classification():
    clf = RegimeClassifier(RegimeConfig(persistence_candles=2, ema_compression_threshold=0.005))
    clf.classify(
        close=100,
        ema30=100.1,
        ema95=100.0,
        hma220=100,
        hma220_slope=0.01,
        st_20_6_bullish=False,
        st_mixed_or_flipping=True,
    )
    snap = clf.classify(
        close=100.02,
        ema30=100.08,
        ema95=100.03,
        hma220=100,
        hma220_slope=0.0,
        st_20_6_bullish=False,
        st_mixed_or_flipping=True,
    )
    assert snap.regime == Regime.RANGE
