from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .types import Regime, RegimeSnapshot


@dataclass(frozen=True)
class RegimeConfig:
    ema_compression_threshold: float = 0.0015
    hma_distance_threshold: float = 0.0008
    hma_flat_slope_threshold: float = 0.00025
    persistence_candles: int = 2


class RegimeClassifier:
    """3-minute candle regime classifier with persistence gating."""

    def __init__(self, cfg: RegimeConfig | None = None):
        self.cfg = cfg or RegimeConfig()
        self._history: deque[Regime] = deque(maxlen=self.cfg.persistence_candles)

    def classify(
        self,
        *,
        close: float,
        ema30: float,
        ema95: float,
        hma220: float,
        hma220_slope: float,
        st_20_6_bullish: bool,
        st_mixed_or_flipping: bool,
    ) -> RegimeSnapshot:
        if close <= 0 or hma220 <= 0:
            candidate = Regime.NO_TRADE
            confidence = 0.0
            reason = "invalid-price-input"
        else:
            ema_spread_ratio = abs(ema30 - ema95) / close
            hma_distance_ratio = abs(close - hma220) / close
            slope_ratio = abs(hma220_slope) / close

            trend_candidate = (
                close > hma220
                and ema30 > ema95
                and st_20_6_bullish
                and hma220_slope > 0
                and hma_distance_ratio >= self.cfg.hma_distance_threshold
            )

            range_candidate = (
                hma_distance_ratio <= self.cfg.hma_distance_threshold
                and ema_spread_ratio <= self.cfg.ema_compression_threshold
                and st_mixed_or_flipping
                and slope_ratio <= self.cfg.hma_flat_slope_threshold
            )

            if trend_candidate and not range_candidate:
                candidate = Regime.TREND
                confidence = min(1.0, 0.6 + hma_distance_ratio * 20)
                reason = "trend-conditions-met"
            elif range_candidate and not trend_candidate:
                candidate = Regime.RANGE
                confidence = min(1.0, 0.6 + (self.cfg.ema_compression_threshold - ema_spread_ratio) * 300)
                reason = "range-conditions-met"
            else:
                candidate = Regime.NO_TRADE
                confidence = 0.25
                reason = "mixed-or-transition"

        self._history.append(candidate)

        if len(self._history) < self.cfg.persistence_candles:
            return RegimeSnapshot(Regime.NO_TRADE, 0.1, "awaiting-persistence")

        if all(r == Regime.TREND for r in self._history):
            return RegimeSnapshot(Regime.TREND, confidence, reason)
        if all(r == Regime.RANGE for r in self._history):
            return RegimeSnapshot(Regime.RANGE, confidence, reason)
        return RegimeSnapshot(Regime.NO_TRADE, 0.2, "persistence-not-met")
