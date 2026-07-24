"""Shared helpers: config loading, timezone handling, formatting.

All functions here are pure / side-effect free except ``load_config`` (reads a
file) so they are easy to unit test.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the YAML config. Falls back to sensible defaults if missing."""
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return _default_config()
    with open(path, "r") as fh:
        cfg = yaml.safe_load(fh) or {}
    # Merge over defaults so missing keys never crash the app.
    merged = _default_config()
    _deep_update(merged, cfg)
    return merged


def _deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _default_config() -> Dict[str, Any]:
    return {
        "ticker": "SOXL",
        "data_source": "yfinance",
        "timezone": "America/New_York",
        "refresh_interval_seconds": 60,
        "cache_dir": "data/cache",
        "timeframes": {
            "1D / 1m": {"period": "1d", "interval": "1m", "intraday": True},
            "5D / 5m": {"period": "5d", "interval": "5m", "intraday": True},
            "1M / 30m": {"period": "1mo", "interval": "30m", "intraday": True},
            "3M / 1d": {"period": "3mo", "interval": "1d", "intraday": False},
            "6M / 1d": {"period": "6mo", "interval": "1d", "intraday": False},
            "1Y / 1d": {"period": "1y", "interval": "1d", "intraday": False},
            "5Y / 1wk": {"period": "5y", "interval": "1wk", "intraday": False},
        },
        "moving_averages": [20, 50, 100, 200],
        "indicators": {
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "atr_period": 14,
            "bb_period": 20,
            "bb_std": 2.0,
            "vol_ma_period": 20,
            "hist_vol_windows": [20, 60],
        },
        "drawdown_zones": {"normal": -0.10, "correction": -0.25, "major": -0.50},
        "risk": {"var_confidence": 0.95, "trading_days_per_year": 252},
        "alerts": {
            "rsi_overbought": 75,
            "rsi_oversold": 30,
            "drawdown_levels": [-0.10, -0.25, -0.50],
            "relative_volume_spike": 2.0,
            "daily_loss_threshold": -0.10,
        },
        "tabs": [
            ["SMH (1x)", "SMH"], ["SOXL (3x)", "SOXL"], ["S&P500", "SPY"],
            ["QQQ", "QQQ"], ["TQQQ (3x)", "TQQQ"], ["MU", "MU"],
            ["SNDK", "SNDK"], ["MRVL", "MRVL"], ["INTC", "INTC"],
            ["NFLX", "NFLX"],
        ],
        "notifier": {
            "recipient": "",
            "secrets_file": "~/.config/soxl_dashboard/secrets.env",
            "signals": ["buy_dip", "overbought"],
            "scorecard_sessions": 30,
            "state_file": "data/alert_state.json",
            "log_file": "logs/notifier.log",
            "check_deadline_et": "16:30",
        },
    }


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def fmt_price(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"${value:,.2f}"


def fmt_pct(value: Optional[float], signed: bool = True) -> str:
    """Format a *fraction* (0.05 -> 5.00%)."""
    if value is None or pd.isna(value):
        return "—"
    sign = "+" if (signed and value > 0) else ""
    return f"{sign}{value * 100:,.2f}%"


def fmt_int(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{int(value):,}"


def fmt_volume(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "—"
    value = float(value)
    for unit in ["", "K", "M", "B"]:
        if abs(value) < 1000:
            return f"{value:,.1f}{unit}".replace(".0", "")
        value /= 1000.0
    return f"{value:,.1f}T"


# --------------------------------------------------------------------------
# Timezone helpers
# --------------------------------------------------------------------------
def ensure_tz(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Return *df* with a tz-aware DatetimeIndex in *tz*.

    yfinance returns tz-aware intraday data (usually UTC/exchange tz) and
    tz-naive daily data. We normalise both to *tz* for consistent display.
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx)
    if idx.tz is None:
        # Daily/weekly bars: treat the date as exchange-local midnight.
        idx = idx.tz_localize(tz)
    else:
        idx = idx.tz_convert(tz)
    df.index = idx
    return df


def now_in_tz(tz: str) -> datetime:
    return pd.Timestamp.now(tz=tz).to_pydatetime()


# US market holidays (NYSE/Arca) for the current few years. SOXL trades on
# NYSE Arca which follows the standard US equity calendar. This list keeps the
# market-open check simple and dependency-free; extend it as years roll over.
_US_MARKET_HOLIDAYS = {
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}


def is_market_open(tz: str = "America/New_York", at: Optional[datetime] = None) -> bool:
    """Return True if the US equity market is in regular trading hours.

    Uses the exact NYSE calendar via ``pandas_market_calendars`` when it is
    installed (handles holidays AND early-close days automatically). Falls back
    to a built-in weekday + holiday-list check otherwise.
    """
    now = pd.Timestamp(at).tz_convert(tz) if at is not None else pd.Timestamp.now(tz=tz)
    exact = _is_market_open_mcal(now)
    if exact is not None:
        return exact
    return _is_market_open_fallback(now)


def _is_market_open_mcal(now: "pd.Timestamp") -> Optional[bool]:
    """Exact NYSE check via pandas_market_calendars; None if unavailable."""
    try:
        import pandas_market_calendars as mcal
    except Exception:
        return None
    try:
        cal = mcal.get_calendar("NYSE")
        day = now.strftime("%Y-%m-%d")
        sched = cal.schedule(start_date=day, end_date=day)
        if sched.empty:                       # weekend or holiday
            return False
        open_ts = sched.iloc[0]["market_open"].tz_convert(now.tz)
        close_ts = sched.iloc[0]["market_close"].tz_convert(now.tz)
        return bool(open_ts <= now < close_ts)
    except Exception:
        return None


def _is_market_open_fallback(now: "pd.Timestamp") -> bool:
    """Weekday + static-holiday-list check (no early-close awareness)."""
    if now.weekday() >= 5:  # Sat/Sun
        return False
    if now.strftime("%Y-%m-%d") in _US_MARKET_HOLIDAYS:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def trading_session(tz: str = "America/New_York",
                    at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Calendar-only session info for the given date (ignores time of day).

    Unlike ``is_market_open`` this answers "is *today* a trading day?" -- it
    stays True after the close, so an after-close digest job is not suppressed.
    Returns ``None`` on weekends/holidays, else a dict with:
      * ``close``: the session close as a tz-aware Timestamp (16:00 regular);
      * ``early_close``: True on half days (1pm ET closes) -- only detectable
        via pandas_market_calendars; the fallback always reports False.
    """
    now = pd.Timestamp(at).tz_convert(tz) if at is not None else pd.Timestamp.now(tz=tz)
    try:
        import pandas_market_calendars as mcal
        cal = mcal.get_calendar("NYSE")
        day = now.strftime("%Y-%m-%d")
        sched = cal.schedule(start_date=day, end_date=day)
        if sched.empty:                       # weekend or holiday
            return None
        close_ts = sched.iloc[0]["market_close"].tz_convert(tz)
        return {"close": close_ts, "early_close": bool(close_ts.hour < 16)}
    except Exception:
        pass
    # Fallback: weekday + static holiday list, fixed 16:00 close.
    if now.weekday() >= 5 or now.strftime("%Y-%m-%d") in _US_MARKET_HOLIDAYS:
        return None
    close_ts = now.normalize() + pd.Timedelta(hours=16)
    return {"close": close_ts, "early_close": False}


def is_trading_day(tz: str = "America/New_York", at: Optional[datetime] = None) -> bool:
    """True if the date (in *tz*) is a NYSE trading day, regardless of hour."""
    return trading_session(tz, at) is not None
