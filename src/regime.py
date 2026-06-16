"""Market-regime classification.

Takes the latest indicator snapshot + drawdown and assigns one of six regimes.
Rules are evaluated from most-severe to least-severe so the worst applicable
regime wins. Each result carries an explanation of *why* it was chosen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RegimeResult:
    label: str
    color: str
    reasons: List[str]


REGIME_COLORS = {
    "Strong Uptrend": "#1e8e3e",
    "Uptrend but Extended": "#7cb342",
    "Neutral": "#9e9e9e",
    "Correction": "#f9a825",
    "High Risk / Downtrend": "#e64a19",
    "Crash / Extreme Risk": "#b71c1c",
    "Insufficient Data": "#607d8b",
}


def _get(snap: Dict[str, Any], key: str) -> Optional[float]:
    val = snap.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def classify(
    snapshot: Dict[str, Any],
    current_drawdown: float,
    vol_20d: Optional[float] = None,
    vol_60d: Optional[float] = None,
) -> RegimeResult:
    """Classify the regime from indicator snapshot + drawdown.

    Drawdown is a negative fraction (-0.30 == 30% below the running high).
    """
    price = _get(snapshot, "Close")
    sma20 = _get(snapshot, "sma_20")
    sma50 = _get(snapshot, "sma_50")
    sma200 = _get(snapshot, "sma_200")
    rsi = _get(snapshot, "rsi")
    dd = current_drawdown if current_drawdown == current_drawdown else None

    if price is None or rsi is None or dd is None:
        return RegimeResult("Insufficient Data", REGIME_COLORS["Insufficient Data"],
                            ["Not enough history to compute moving averages / RSI."])

    above20 = sma20 is not None and price > sma20
    above50 = sma50 is not None and price > sma50
    above200 = sma200 is not None and price > sma200
    below50 = sma50 is not None and price < sma50
    below200 = sma200 is not None and price < sma200
    ma20_gt_50 = sma20 is not None and sma50 is not None and sma20 > sma50
    ma20_lt_50 = sma20 is not None and sma50 is not None and sma20 < sma50
    vol_elevated = (
        vol_20d is not None and vol_60d is not None
        and vol_60d == vol_60d and vol_60d > 0
        and vol_20d > 1.5 * vol_60d
    )

    # ---- Crash / Extreme Risk -------------------------------------------
    if dd <= -0.50 and below200:
        reasons = [
            f"Drawdown {dd*100:.1f}% (worse than -50%).",
            "Price below 200-day MA.",
        ]
        if vol_elevated:
            reasons.append("Volatility sharply elevated (20d >> 60d).")
        return RegimeResult("Crash / Extreme Risk",
                            REGIME_COLORS["Crash / Extreme Risk"], reasons)

    # ---- High Risk / Downtrend ------------------------------------------
    if below200 and dd <= -0.25 and ma20_lt_50:
        return RegimeResult("High Risk / Downtrend",
                            REGIME_COLORS["High Risk / Downtrend"],
                            ["Price below 200-day MA.",
                             f"Drawdown {dd*100:.1f}% (worse than -25%).",
                             "20-day MA below 50-day MA."])

    # ---- Correction ------------------------------------------------------
    if below50 and dd <= -0.15:
        return RegimeResult("Correction", REGIME_COLORS["Correction"],
                            ["Price below 50-day MA.",
                             f"Drawdown {dd*100:.1f}% (worse than -15%)."])

    # ---- Strong Uptrend --------------------------------------------------
    if above20 and above50 and above200 and ma20_gt_50 and 50 <= rsi <= 75 and dd > -0.10:
        return RegimeResult("Strong Uptrend", REGIME_COLORS["Strong Uptrend"],
                            ["Price above 20/50/200-day MAs.",
                             "20-day MA above 50-day MA.",
                             f"RSI {rsi:.0f} (50-75).",
                             f"Drawdown {dd*100:.1f}% (shallower than -10%)."])

    # ---- Uptrend but Extended -------------------------------------------
    far_above_20 = sma20 is not None and price > sma20 * 1.10
    if above50 and above200 and (rsi > 75 or far_above_20):
        reasons = ["Price above major moving averages."]
        if rsi > 75:
            reasons.append(f"RSI {rsi:.0f} (>75, overbought).")
        if far_above_20:
            reasons.append("Price >10% above 20-day MA (extended).")
        return RegimeResult("Uptrend but Extended",
                            REGIME_COLORS["Uptrend but Extended"], reasons)

    # ---- Neutral (default) ----------------------------------------------
    reasons = []
    if sma50 is not None and sma200 is not None and sma200 <= price <= sma50:
        reasons.append("Price between 50-day and 200-day MAs.")
    if 40 <= rsi <= 60:
        reasons.append(f"RSI {rsi:.0f} (40-60).")
    if not reasons:
        reasons.append("No strong trend or risk signal dominates.")
    return RegimeResult("Neutral", REGIME_COLORS["Neutral"], reasons)
