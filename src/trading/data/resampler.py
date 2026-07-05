"""Exact timeframe resampler for FACTRADE.

Key principle
-------------
3H and 4H candles are computed by exact resampling from 1H (or finer) source
data, **not** approximated by requesting those intervals directly from a public
API that may use arbitrary alignment.

Resampling rules
----------------
- open  : first bar
- high  : maximum
- low   : minimum
- close : last bar
- volume: sum

Alignment
---------
By default bars are *left-closed* and *left-labelled* (standard OHLCV
convention):
- 3H bars start at 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 UTC
- 4H bars start at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC

Only complete bars (where the last 1H close is available) are returned.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# Mapping from friendly alias → pandas offset alias
_TF_MAP: dict[str, str] = {
    # exact multi-hour offsets
    "3H": "3h",
    "4H": "4h",
    "2H": "2h",
    "6H": "6h",
    "8H": "8h",
    "12H": "12h",
    "1D": "1D",
    "1W": "1W",
    # pass-through for source data
    "1H": "1h",
    "30m": "30min",
    "30M": "30min",
    "15m": "15min",
    "15M": "15min",
    "5m": "5min",
    "5M": "5min",
    "1m": "1min",
    "1M": "1min",
}

_OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def resample(
    df: pd.DataFrame,
    target_tf: str,
    closed: str = "left",
    label: str = "left",
    drop_incomplete: bool = True,
    anchor: Optional[str] = None,
) -> pd.DataFrame:
    """Resample an OHLCV DataFrame to *target_tf*.

    Parameters
    ----------
    df:
        Source OHLCV DataFrame.  Must have a ``DatetimeIndex`` (UTC).
    target_tf:
        Target timeframe, e.g. ``"3H"``, ``"4H"``, ``"1D"``.
    closed:
        Which side of each interval is closed (default ``"left"``).
    label:
        Which side is used as the interval label (default ``"left"``).
    drop_incomplete:
        If ``True`` (default), the last bar is dropped when it may not be
        complete yet (i.e. when ``df`` ends before the bar's close).
    anchor:
        Optional pandas-compatible origin string (e.g. ``"epoch"``,
        ``"start_day"``).  Defaults to ``"epoch"`` which aligns 3H/4H bars
        on clean UTC boundaries.

    Returns
    -------
    pd.DataFrame
        Resampled OHLCV DataFrame.

    Raises
    ------
    ValueError
        If *target_tf* is not recognised or *df* does not have the required
        OHLCV columns.
    """
    if target_tf not in _TF_MAP:
        raise ValueError(
            f"Unknown timeframe '{target_tf}'. "
            f"Supported: {sorted(_TF_MAP.keys())}"
        )

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    if df.empty:
        return df.copy()

    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame must have a DatetimeIndex.")
    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    agg_cols = {k: v for k, v in _OHLCV_AGG.items() if k in df.columns}
    offset = _TF_MAP[target_tf]

    # Use 'epoch' origin so 3H bars align at 00:00/03:00/06:00 UTC etc.
    resample_kwargs: dict = dict(
        rule=offset,
        closed=closed,
        label=label,
        origin=anchor or "epoch",
    )

    resampled = df.resample(**resample_kwargs).agg(agg_cols).dropna(how="all")

    if drop_incomplete and not resampled.empty:
        resampled = resampled.iloc[:-1]

    logger.info(
        "resampler.done",
        target_tf=target_tf,
        input_rows=len(df),
        output_rows=len(resampled),
    )
    return resampled


def validate_resampling(
    source_df: pd.DataFrame,
    resampled_df: pd.DataFrame,
    target_tf: str,
    tolerance_ticks: int = 0,
) -> dict:
    """Validate a resampled DataFrame against the source data.

    Checks:
    1. Every resampled bar's high == max of constituent source highs.
    2. Every resampled bar's low  == min of constituent source lows.
    3. Every resampled bar's open == first constituent open.
    4. Every resampled bar's close == last constituent close.
    5. Bar spacing is consistent (uniform period).

    Parameters
    ----------
    source_df:
        Original finer-timeframe OHLCV data.
    resampled_df:
        Resampled data to validate.
    target_tf:
        Target timeframe string (used for period inference).
    tolerance_ticks:
        Allowed floating-point tolerance in ticks (0 = exact match).

    Returns
    -------
    dict
        ``{"valid": bool, "errors": list[str]}``
    """
    errors: list[str] = []
    offset = _TF_MAP.get(target_tf)

    # Check bar spacing
    if len(resampled_df) > 1:
        diffs = resampled_df.index.to_series().diff().dropna()
        unique_diffs = diffs.unique()
        if len(unique_diffs) > 1:
            errors.append(
                f"Non-uniform bar spacing detected: {unique_diffs}"
            )

    # Validate OHLC values bar-by-bar
    for bar_ts, bar in resampled_df.iterrows():
        # Find constituent source candles
        if offset is not None:
            bar_end = bar_ts + pd.tseries.frequencies.to_offset(offset)
            mask = (source_df.index >= bar_ts) & (source_df.index < bar_end)
        else:
            mask = source_df.index == bar_ts

        chunk = source_df.loc[mask]
        if chunk.empty:
            errors.append(f"No source candles found for bar {bar_ts}")
            continue

        expected_high = chunk["high"].max()
        expected_low = chunk["low"].min()
        expected_open = chunk["open"].iloc[0]
        expected_close = chunk["close"].iloc[-1]

        tol = tolerance_ticks * 0.01  # treat ticks as cents

        if abs(bar["high"] - expected_high) > tol:
            errors.append(
                f"{bar_ts}: high mismatch "
                f"(got {bar['high']}, expected {expected_high})"
            )
        if abs(bar["low"] - expected_low) > tol:
            errors.append(
                f"{bar_ts}: low mismatch "
                f"(got {bar['low']}, expected {expected_low})"
            )
        if abs(bar["open"] - expected_open) > tol:
            errors.append(
                f"{bar_ts}: open mismatch "
                f"(got {bar['open']}, expected {expected_open})"
            )
        if abs(bar["close"] - expected_close) > tol:
            errors.append(
                f"{bar_ts}: close mismatch "
                f"(got {bar['close']}, expected {expected_close})"
            )

    result = {"valid": len(errors) == 0, "errors": errors}
    if result["valid"]:
        logger.info("resampler.validation_passed", target_tf=target_tf, bars=len(resampled_df))
    else:
        logger.warning(
            "resampler.validation_failed",
            target_tf=target_tf,
            error_count=len(errors),
        )
    return result
