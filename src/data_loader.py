"""Data access layer.

Responsibilities:
  * Download OHLCV data for a ticker (intraday or daily).
  * Cache every successful fetch to local Parquet.
  * Fall back to the last good cache if the live fetch fails.
  * Expose a small "quote" summary (price, day change, 52w range...).
  * Provide a pluggable ``DataSource`` interface so a paid real-time API
    (Alpaca / Polygon / Tradier / IBKR) can be added later without touching
    the rest of the app.

The returned OHLCV frame always has columns: Open, High, Low, Close, Volume
and a tz-aware DatetimeIndex (display timezone from config).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from . import utils

OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


@dataclass
class LoadResult:
    """Wraps a data fetch so the UI can report freshness / fallbacks."""

    df: pd.DataFrame
    source: str                       # "yfinance", "cache", ...
    is_live: bool                     # True if freshly fetched, False if cache
    fetched_at: datetime              # when this data was obtained
    note: str = ""                    # human-readable status / error detail
    quote: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------
def _cache_path(cache_dir: str, ticker: str, period: str, interval: str) -> str:
    safe = f"{ticker}_{period}_{interval}".replace("/", "-")
    return os.path.join(cache_dir, f"{safe}.parquet")


def _abs_cache_dir(cache_dir: str) -> str:
    if os.path.isabs(cache_dir):
        return cache_dir
    return os.path.join(utils.PROJECT_ROOT, cache_dir)


def _write_cache(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        df.to_parquet(path)
    except Exception:
        # Parquet engine missing or write error -> fall back to pickle so the
        # app still benefits from caching.
        df.to_pickle(path + ".pkl")


def _read_cache(path: str) -> Optional[pd.DataFrame]:
    for candidate in (path, path + ".pkl"):
        if os.path.exists(candidate):
            try:
                if candidate.endswith(".pkl"):
                    return pd.read_pickle(candidate)
                return pd.read_parquet(candidate)
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------
# Data sources
# --------------------------------------------------------------------------
class DataSource:
    """Interface for an OHLCV provider. Subclass and implement ``fetch``."""

    name = "base"

    def fetch(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        raise NotImplementedError


class YFinanceSource(DataSource):
    name = "yfinance"

    def fetch(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        import yfinance as yf

        df = yf.download(
            tickers=ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        return _normalize_yf(df)


def _normalize_yf(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a yfinance frame into the canonical OHLCV layout."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLS)
    df = df.copy()
    # yfinance may return a MultiIndex column frame (when multiple tickers, or
    # in some versions even for a single ticker). Flatten to the price level.
    if isinstance(df.columns, pd.MultiIndex):
        # Prefer the level that contains 'Close'.
        lvl0 = df.columns.get_level_values(0)
        if "Close" in set(lvl0):
            df.columns = lvl0
        else:
            df.columns = df.columns.get_level_values(-1)
    df = df.rename(columns={c: c.title() for c in df.columns})
    keep = [c for c in OHLCV_COLS if c in df.columns]
    df = df[keep]
    df = df.dropna(how="all")
    return df


# Stubs for paid real-time providers. They raise a clear error until wired up.
class _NotImplementedSource(DataSource):
    def fetch(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        raise NotImplementedError(
            f"Data source '{self.name}' is not implemented yet. "
            f"Add credentials and implement fetch() in src/data_loader.py."
        )


class AlpacaSource(_NotImplementedSource):
    name = "alpaca"


class PolygonSource(_NotImplementedSource):
    name = "polygon"


class TradierSource(_NotImplementedSource):
    name = "tradier"


_SOURCES = {
    "yfinance": YFinanceSource,
    "alpaca": AlpacaSource,
    "polygon": PolygonSource,
    "tradier": TradierSource,
}


def get_source(name: str) -> DataSource:
    cls = _SOURCES.get(name, YFinanceSource)
    return cls()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def load_ohlcv(
    config: Dict[str, Any],
    period: str,
    interval: str,
    source_name: Optional[str] = None,
    max_retries: int = 2,
) -> LoadResult:
    """Fetch OHLCV with caching + graceful fallback.

    Never raises on network/data errors: returns cached data (or an empty
    frame) with an explanatory ``note`` instead, so the dashboard stays up.
    """
    ticker = config["ticker"]
    tz = config["timezone"]
    cache_dir = _abs_cache_dir(config["cache_dir"])
    source_name = source_name or config.get("data_source", "yfinance")
    path = _cache_path(cache_dir, ticker, period, interval)
    source = get_source(source_name)

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            df = source.fetch(ticker, period, interval)
            if df is not None and not df.empty:
                df = utils.ensure_tz(df, tz)
                _write_cache(df, path)
                return LoadResult(
                    df=df,
                    source=source.name,
                    is_live=True,
                    fetched_at=utils.now_in_tz(tz),
                    note="",
                    quote=build_quote(config, df),
                )
            last_err = ValueError("empty response")
        except Exception as exc:  # network, rate limit, parsing, etc.
            last_err = exc
        time.sleep(0.5 * (attempt + 1))

    # Live fetch failed -> fall back to cache.
    cached = _read_cache(path)
    if cached is not None and not cached.empty:
        cached = utils.ensure_tz(cached, tz)
        mtime = datetime.fromtimestamp(
            os.path.getmtime(path if os.path.exists(path) else path + ".pkl")
        )
        return LoadResult(
            df=cached,
            source="cache",
            is_live=False,
            fetched_at=mtime,
            note=f"Live fetch failed ({last_err}); showing cached data.",
            quote=build_quote(config, cached),
        )

    return LoadResult(
        df=pd.DataFrame(columns=OHLCV_COLS),
        source=source_name,
        is_live=False,
        fetched_at=utils.now_in_tz(tz),
        note=f"No data available: {last_err}",
        quote={},
    )


def build_quote(config: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """Compute a price summary from the OHLCV frame.

    Uses a separate daily download for previous-close / 52-week range so the
    numbers are correct even when *df* is an intraday frame. Falls back to the
    in-frame values if that secondary fetch fails.
    """
    if df is None or df.empty:
        return {}

    last = df.iloc[-1]
    today = df[df.index.date == df.index[-1].date()]

    quote: Dict[str, Any] = {
        "price": float(last["Close"]),
        "open": float(today["Open"].iloc[0]) if not today.empty else float(last["Open"]),
        "high": float(today["High"].max()) if not today.empty else float(last["High"]),
        "low": float(today["Low"].min()) if not today.empty else float(last["Low"]),
        "volume": float(today["Volume"].sum()) if not today.empty else float(last["Volume"]),
        "as_of": df.index[-1].to_pydatetime(),
    }

    daily = _safe_daily(config)
    if daily is not None and not daily.empty:
        closes = daily["Close"].dropna()
        if len(closes) >= 2:
            quote["prev_close"] = float(closes.iloc[-2])
        elif len(closes) == 1:
            quote["prev_close"] = float(closes.iloc[-1])
        window = daily.tail(252)
        quote["high_52w"] = float(window["High"].max())
        quote["low_52w"] = float(window["Low"].min())
        quote["avg_volume"] = float(daily["Volume"].tail(20).mean())
    else:
        # Derive what we can from the supplied frame.
        closes = df["Close"].dropna()
        quote["prev_close"] = float(closes.iloc[-2]) if len(closes) >= 2 else float(last["Close"])
        quote["high_52w"] = float(df["High"].max())
        quote["low_52w"] = float(df["Low"].min())
        quote["avg_volume"] = float(df["Volume"].tail(20).mean())

    prev_close = quote.get("prev_close")
    if prev_close:
        quote["change"] = quote["price"] - prev_close
        quote["change_pct"] = quote["price"] / prev_close - 1.0
    return quote


def _safe_daily(config: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """One-year daily frame for quote stats; cached and failure-tolerant."""
    try:
        ticker = config["ticker"]
        tz = config["timezone"]
        cache_dir = _abs_cache_dir(config["cache_dir"])
        path = _cache_path(cache_dir, ticker, "1y", "1d")
        source = get_source(config.get("data_source", "yfinance"))
        df = source.fetch(ticker, "1y", "1d")
        if df is not None and not df.empty:
            df = utils.ensure_tz(df, tz)
            _write_cache(df, path)
            return df
    except Exception:
        pass
    # Fall back to cached daily if available.
    try:
        cache_dir = _abs_cache_dir(config["cache_dir"])
        path = _cache_path(cache_dir, config["ticker"], "1y", "1d")
        cached = _read_cache(path)
        if cached is not None and not cached.empty:
            return utils.ensure_tz(cached, config["timezone"])
    except Exception:
        pass
    return None
