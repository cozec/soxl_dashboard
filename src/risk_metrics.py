"""Risk metrics tailored to a 3x leveraged ETF.

All return-based metrics use simple daily (or per-bar) returns derived from
Close. VaR is historical (non-parametric). Multi-day "moves" use the latest
N-bar return; worst N-day losses scan the rolling N-bar return history.

No lookahead bias: every value is computed from past/current observations only.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from . import drawdown


def simple_returns(price: pd.Series) -> pd.Series:
    return price.pct_change()


def period_move(price: pd.Series, bars: int) -> float:
    """Return over the last *bars* bars (fraction)."""
    if price is None or len(price) <= bars:
        return float("nan")
    return float(price.iloc[-1] / price.iloc[-1 - bars] - 1.0)


def annualized_vol(price: pd.Series, window: int, trading_days: int = 252) -> float:
    rets = np.log(price / price.shift(1)).dropna()
    if len(rets) < window:
        return float("nan")
    return float(rets.tail(window).std() * np.sqrt(trading_days))


def historical_var(price: pd.Series, confidence: float = 0.95) -> float:
    """1-bar historical VaR as a *positive* loss fraction.

    e.g. 0.08 means a 5% chance of losing >= 8% in one bar.
    """
    rets = simple_returns(price).dropna()
    if rets.empty:
        return float("nan")
    q = np.quantile(rets, 1.0 - confidence)
    return float(-q)


def worst_n_day_loss(price: pd.Series, bars: int) -> float:
    """Most negative rolling *bars*-bar return in the series (fraction)."""
    if price is None or len(price) <= bars:
        return float("nan")
    rolling_ret = price / price.shift(bars) - 1.0
    return float(rolling_ret.min())


def gap_from_prev_close(quote: Dict[str, Any]) -> float:
    prev = quote.get("prev_close")
    op = quote.get("open")
    if not prev or op is None:
        return float("nan")
    return op / prev - 1.0


def compute_risk(
    df: pd.DataFrame, quote: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    """Assemble the full risk dashboard payload."""
    out: Dict[str, Any] = {}
    if df is None or df.empty:
        return out

    price = df["Close"].dropna()
    td = config["risk"]["trading_days_per_year"]
    conf = config["risk"]["var_confidence"]

    out["move_1d"] = period_move(price, 1)
    out["move_5d"] = period_move(price, 5)
    out["move_20d"] = period_move(price, 20)
    out["move_60d"] = period_move(price, 60)

    out["vol_20d"] = annualized_vol(price, 20, td)
    out["vol_60d"] = annualized_vol(price, 60, td)

    out["max_drawdown"] = drawdown.max_drawdown(price)
    out["current_drawdown"] = drawdown.current_drawdown(price)

    out["var_95_1d"] = historical_var(price, conf)
    out["var_confidence"] = conf

    rets = simple_returns(price).dropna()
    out["worst_1d"] = float(rets.min()) if not rets.empty else float("nan")
    out["worst_5d"] = worst_n_day_loss(price, 5)
    out["worst_20d"] = worst_n_day_loss(price, 20)

    out["daily_realized_vol"] = float(rets.tail(20).std()) if len(rets) >= 2 else float("nan")
    out["gap_from_prev_close"] = gap_from_prev_close(quote)
    return out


LEVERAGE_WARNING = (
    "SOXL is a 3x leveraged ETF. It is designed for daily leveraged exposure "
    "and can suffer from volatility decay over longer holding periods."
)
