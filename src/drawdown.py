"""Drawdown analysis.

drawdown_t = price_t / running_max(price)_t - 1   (<= 0)

The running max is *expanding* (uses only past + current data) so there is no
lookahead bias. Helpers return both the full series (for charting) and a
summary dict (for metric cards).
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


def drawdown_series(price: pd.Series) -> pd.Series:
    """Drawdown from the running (expanding) maximum, as a fraction <= 0."""
    running_max = price.cummax()
    return price / running_max - 1.0


def max_drawdown(price: pd.Series) -> float:
    if price is None or price.empty:
        return float("nan")
    return float(drawdown_series(price).min())


def current_drawdown(price: pd.Series) -> float:
    if price is None or price.empty:
        return float("nan")
    return float(drawdown_series(price).iloc[-1])


def drawdown_summary(
    df: pd.DataFrame, quote: Dict[str, Any]
) -> Dict[str, Any]:
    """Build the numbers shown in the drawdown section.

    Uses the *period* high from the supplied frame for the period-high metrics
    and the quote's 52-week values for the 52w / all-time figures.
    """
    summary: Dict[str, Any] = {}
    if df is None or df.empty:
        return summary
    # Guard against an all-NaN frame (e.g. mis-aligned input): nothing to summarise.
    if df["High"].dropna().empty or df["Close"].dropna().empty:
        return summary

    close = df["Close"]
    price = float(quote.get("price", close.iloc[-1]))

    # Period high (within the loaded frame).
    period_high = float(df["High"].max())
    period_high_idx = df["High"].idxmax()
    summary["period_high"] = period_high
    summary["period_high_date"] = period_high_idx.to_pydatetime()
    summary["days_since_period_high"] = int(
        (df.index[-1] - period_high_idx).days
    )
    summary["drop_from_period_high"] = price / period_high - 1.0

    # All-time high proxy = max close over the full loaded history.
    ath = float(close.max())
    ath_idx = close.idxmax()
    summary["all_time_high"] = ath
    summary["all_time_high_date"] = ath_idx.to_pydatetime()
    summary["days_since_ath"] = int((df.index[-1] - ath_idx).days)
    summary["drop_from_ath"] = price / ath - 1.0

    # 52-week high (from quote when available).
    high_52w = quote.get("high_52w", period_high)
    summary["high_52w"] = float(high_52w)
    summary["drop_from_52w_high"] = price / float(high_52w) - 1.0

    summary["current_price"] = price
    summary["current_drawdown"] = current_drawdown(close)
    summary["max_drawdown"] = max_drawdown(close)
    return summary


def classify_zone(dd: float, zones: Dict[str, float]) -> str:
    """Map a drawdown fraction to a severity label."""
    if dd is None or np.isnan(dd):
        return "unknown"
    if dd > zones.get("normal", -0.10):
        return "normal"          # 0% .. -10%
    if dd > zones.get("correction", -0.25):
        return "correction"      # -10% .. -25%
    if dd > zones.get("major", -0.50):
        return "major"           # -25% .. -50%
    return "crash"               # below -50%


ZONE_COLORS = {
    "normal": "#2ecc71",
    "correction": "#f1c40f",
    "major": "#e67e22",
    "crash": "#e74c3c",
    "unknown": "#888888",
}

ZONE_LABELS = {
    "normal": "Normal pullback (0% to -10%)",
    "correction": "Correction (-10% to -25%)",
    "major": "Major drawdown (-25% to -50%)",
    "crash": "Crash zone (below -50%)",
    "unknown": "Unknown",
}
