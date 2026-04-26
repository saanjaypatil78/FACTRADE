from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .types import OptionQuote, OptionType, StrikeDecision


@dataclass(frozen=True)
class StrikeSelectorConfig:
    buy_delta_min: float = 0.60
    buy_delta_max: float = 0.70
    sell_delta_max: float = 0.45
    max_spread_pct: float = 0.8
    min_oi: int = 1_000
    min_volume: int = 100


class StrikeSelector:
    def __init__(self, cfg: StrikeSelectorConfig | None = None):
        self.cfg = cfg or StrikeSelectorConfig()

    def _spread_pct(self, quote: OptionQuote) -> float:
        mid = (quote.bid + quote.ask) / 2 if quote.bid > 0 and quote.ask > 0 else quote.ltp
        if mid <= 0:
            return 999.0
        return ((quote.ask - quote.bid) / mid) * 100

    def _is_liquid(self, quote: OptionQuote) -> bool:
        return (
            quote.oi >= self.cfg.min_oi
            and quote.volume >= self.cfg.min_volume
            and self._spread_pct(quote) <= self.cfg.max_spread_pct
        )

    def pick_for_buy(self, chain: Iterable[OptionQuote], option_type: OptionType) -> StrikeDecision | None:
        candidates: list[tuple[float, OptionQuote]] = []
        for q in chain:
            if q.option_type != option_type:
                continue
            if not self._is_liquid(q):
                continue
            if not (self.cfg.buy_delta_min <= abs(q.delta) <= self.cfg.buy_delta_max):
                continue

            delta_score = 1 - abs(abs(q.delta) - 0.65) / 0.05
            spread_score = max(0.0, 1 - self._spread_pct(q) / self.cfg.max_spread_pct)
            oi_score = min(1.0, q.oi / (self.cfg.min_oi * 5))
            volume_score = min(1.0, q.volume / (self.cfg.min_volume * 10))
            total = delta_score * 0.45 + spread_score * 0.25 + oi_score * 0.2 + volume_score * 0.1
            candidates.append((total, q))

        if not candidates:
            return None
        best_score, best = max(candidates, key=lambda item: item[0])
        return StrikeDecision(
            strike=best.strike,
            option_type=best.option_type,
            score=round(best_score, 4),
            reason="buy-delta-liquidity-optimized",
        )

    def pick_for_sell(self, chain: Iterable[OptionQuote], option_type: OptionType) -> StrikeDecision | None:
        candidates: list[tuple[float, OptionQuote]] = []
        for q in chain:
            if q.option_type != option_type:
                continue
            if not self._is_liquid(q):
                continue
            if abs(q.delta) > self.cfg.sell_delta_max:
                continue

            delta_score = 1 - abs(abs(q.delta) - 0.35) / 0.35
            spread_score = max(0.0, 1 - self._spread_pct(q) / self.cfg.max_spread_pct)
            oi_score = min(1.0, q.oi / (self.cfg.min_oi * 8))
            total = delta_score * 0.5 + spread_score * 0.3 + oi_score * 0.2
            candidates.append((total, q))

        if not candidates:
            return None
        best_score, best = max(candidates, key=lambda item: item[0])
        return StrikeDecision(
            strike=best.strike,
            option_type=best.option_type,
            score=round(best_score, 4),
            reason="sell-delta-liquidity-optimized",
        )
