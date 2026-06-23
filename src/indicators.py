"""Technical indicators.

Every function takes a price/OHLCV frame or series and returns aligned output
(same index). Calculations are causal -- each value uses only data up to and
including its own timestamp -- so there is **no lookahead bias**. We rely on
pandas rolling/ewm which are backward-looking by construction.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------
def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def ma_slope(series: pd.Series, lookback: int = 5) -> pd.Series:
    """Per-bar slope of a moving average as a fraction (rise/run normalised).

    Positive => rising MA. Expressed relative to price level so it is unit-free.
    """
    return series.diff(lookback) / (series.shift(lookback).abs() * lookback)


# --------------------------------------------------------------------------
# Momentum
# --------------------------------------------------------------------------
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing == EWM with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss == 0 -> RSI 100; when avg_gain == 0 -> RSI 0.
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(avg_gain != 0, 0.0)
    return out


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": hist}, index=series.index
    )


def roc(series: pd.Series, period: int) -> pd.Series:
    """Rate of change as a fraction over *period* bars."""
    return series / series.shift(period) - 1.0


# --------------------------------------------------------------------------
# Volatility
# --------------------------------------------------------------------------
def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def historical_volatility(
    series: pd.Series, window: int, trading_days: int = 252
) -> pd.Series:
    """Annualised rolling volatility of log returns."""
    log_ret = np.log(series / series.shift(1))
    return log_ret.rolling(window, min_periods=window).std() * np.sqrt(trading_days)


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    mid = sma(series, period)
    std = series.rolling(period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid
    return pd.DataFrame(
        {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width},
        index=series.index,
    )


# --------------------------------------------------------------------------
# Volume
# --------------------------------------------------------------------------
def volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(period, min_periods=period).mean()


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume / volume_ma(volume, period)


def on_balance_volume(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["Close"].diff()).fillna(0.0)
    return (direction * df["Volume"]).cumsum()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP, reset each session (per calendar date).

    Only meaningful for intraday data. Daily/weekly callers should skip this.
    """
    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    tpv = typical * df["Volume"]
    day = pd.Series(df.index.date, index=df.index)
    cum_tpv = tpv.groupby(day).cumsum()
    cum_vol = df["Volume"].groupby(day).cumsum()
    return cum_tpv / cum_vol.replace(0, np.nan)


# --------------------------------------------------------------------------
# Aggregator
# --------------------------------------------------------------------------
def compute_all(
    df: pd.DataFrame, config: Dict, intraday: bool
) -> pd.DataFrame:
    """Return *df* augmented with every indicator column the app needs."""
    if df is None or df.empty:
        return df
    out = df.copy()
    close = out["Close"]
    ind = config["indicators"]

    for period in config["moving_averages"]:
        out[f"sma_{period}"] = sma(close, period)
        out[f"sma_{period}_slope"] = ma_slope(out[f"sma_{period}"])

    out["rsi"] = rsi(close, ind["rsi_period"])

    macd_df = macd(close, ind["macd_fast"], ind["macd_slow"], ind["macd_signal"])
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]

    out["atr"] = atr(out, ind["atr_period"])
    for w in ind["hist_vol_windows"]:
        out[f"hv_{w}"] = historical_volatility(
            close, w, config["risk"]["trading_days_per_year"]
        )

    bb = bollinger_bands(close, ind["bb_period"], ind["bb_std"])
    for col in bb.columns:
        out[col] = bb[col]

    out["vol_ma"] = volume_ma(out["Volume"], ind["vol_ma_period"])
    out["rel_volume"] = relative_volume(out["Volume"], ind["vol_ma_period"])
    out["obv"] = on_balance_volume(out)

    for period in (5, 20, 60):
        out[f"roc_{period}"] = roc(close, period)

    if intraday:
        out["vwap"] = vwap(out)

    return out


def latest_snapshot(df: pd.DataFrame, config: Dict) -> Dict[str, float]:
    """Flat dict of the most recent indicator values for tables/signals."""
    if df is None or df.empty:
        return {}
    last = df.iloc[-1]
    snap: Dict[str, float] = {}
    for col in df.columns:
        try:
            snap[col] = float(last[col])
        except (TypeError, ValueError):
            continue
    # Distance from rolling highs (fraction; negative = below high).
    close = df["Close"]
    for period, label in [(20, "dist_20d_high"), (50, "dist_50d_high"), (200, "dist_200d_high")]:
        roll_high = close.rolling(period, min_periods=1).max().iloc[-1]
        snap[label] = float(close.iloc[-1] / roll_high - 1.0)
    return snap


# --------------------------------------------------------------------------
# Entry signal
# --------------------------------------------------------------------------
def buy_dip_signal(df: pd.DataFrame) -> pd.Series:
    """Boolean Series flagging 'buy the dip in an uptrend' entries.

    Backtested as the best historical SOXL entry (see scripts/backtest_entry.py):
    require an uptrend (close > 200-day MA) AND a pullback to support -- either a
    tag of the lower Bollinger Band or a cross down to the 50-day MA. Causal:
    uses only closed bars.
    """
    needed = {"Close", "sma_50", "sma_200", "bb_lower"}
    if df is None or df.empty or not needed.issubset(df.columns):
        idx = df.index if df is not None else None
        return pd.Series([], dtype=bool, index=idx)
    close = df["Close"]
    uptrend = close > df["sma_200"]
    lower_tag = close <= df["bb_lower"]
    ma50_cross = (close.shift(1) > df["sma_50"].shift(1)) & (close <= df["sma_50"])
    return (uptrend & (lower_tag | ma50_cross)).fillna(False)


def hanging_man_signal(
    df: pd.DataFrame,
    body_max: float = 0.35,
    lower_min_body: float = 2.0,
    lower_min_range: float = 0.5,
    upper_max: float = 0.20,
    trend_lookback: int = 10,
) -> pd.Series:
    """Boolean Series flagging hanging-man candles.

    Shape: small real body near the TOP of the range, a long lower shadow
    (>= 2x the body and >= half the range), and little/no upper shadow, occurring
    after an advance (close above where it was ``trend_lookback`` bars ago). The
    same shape after a decline would be a bullish 'hammer'; the uptrend filter is
    what makes it a (bearish) hanging man. Causal -- only closed bars.
    """
    if df is None or df.empty:
        idx = df.index if df is not None else None
        return pd.Series([], dtype=bool, index=idx)
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    rng = (h - l)
    body = (c - o).abs()
    upper = h - c.where(c >= o, o)          # high - max(open, close)
    lower = o.where(o <= c, c) - l          # min(open, close) - low
    valid = rng > 0
    small_body = body <= body_max * rng
    long_lower = (lower >= lower_min_body * body) & (lower >= lower_min_range * rng)
    short_upper = upper <= upper_max * rng
    uptrend = c > c.shift(trend_lookback)
    return (valid & small_body & long_lower & short_upper & uptrend).fillna(False)


def latest_entry(df: pd.DataFrame) -> Dict[str, Any]:
    """Whether the most recent bar is a buy-the-dip entry, with a reason."""
    sig = buy_dip_signal(df)
    if sig.empty or not bool(sig.iloc[-1]):
        return {"active": False, "reason": ""}
    close = float(df["Close"].iloc[-1])
    reasons = ["price above 200-day MA (uptrend)"]
    if close <= float(df["bb_lower"].iloc[-1]):
        reasons.append("tagged the lower Bollinger Band")
    if close <= float(df["sma_50"].iloc[-1]):
        reasons.append("pulled back to the 50-day MA")
    return {"active": True, "reason": "; ".join(reasons)}
