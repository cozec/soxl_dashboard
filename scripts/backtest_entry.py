"""Which technical signals make good ENTRIES for SOXL?

Event study of forward returns after several candidate *buy* signals, compared
to the all-days baseline. A signal with a positive 'edge' (signal mean minus
baseline mean) bought historically better-than-average forward returns.

All signals are causal (computed from closed bars only). Forward returns look
ahead by construction -- that's the measurement, not a live calculation.

Run:  .venv/bin/python scripts/backtest_entry.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import data_loader, indicators, utils  # noqa: E402

HORIZONS = [5, 10, 20, 60]


def _row(fwd: pd.Series, base: dict, h: int) -> str:
    s = fwd.dropna()
    mean = s.mean() * 100
    win = (s > 0).mean() * 100
    edge = mean - base[h]
    return f"{h:>6}d {len(s):>6} {mean:>8.2f} {win:>6.1f}%  {edge:>+7.2f}"


def main() -> None:
    cfg = utils.load_config()
    df = data_loader.load_ohlcv(cfg, "max", "1d").df.copy()
    close = df["Close"]
    ind = cfg["indicators"]

    fwd = {h: close.shift(-h) / close - 1.0 for h in HORIZONS}
    base = {h: fwd[h].mean() * 100 for h in HORIZONS}

    rsi = indicators.rsi(close, ind["rsi_period"])
    sma20 = indicators.sma(close, 20)
    sma50 = indicators.sma(close, 50)
    sma200 = indicators.sma(close, 200)
    lower = indicators.bollinger_bands(close, ind["bb_period"], ind["bb_std"])["bb_lower"]
    macd = indicators.macd(close, ind["macd_fast"], ind["macd_slow"], ind["macd_signal"])
    dd = close / close.cummax() - 1.0

    uptrend = close > sma200
    signals = {
        "RSI crosses back above 30 (oversold bounce)":
            (rsi.shift(1) < 30) & (rsi >= 30),
        "RSI crosses above 30, IN uptrend (>200MA)":
            (rsi.shift(1) < 30) & (rsi >= 30) & uptrend,
        "Close tags lower Bollinger Band":
            close < lower,
        "Close tags lower band, IN uptrend":
            (close < lower) & uptrend,
        "Reclaim 20-MA in uptrend (cross up 20MA, >200MA)":
            (close.shift(1) <= sma20.shift(1)) & (close > sma20) & uptrend,
        "Pullback to 50-MA in uptrend (cross down to/below 50MA, >200MA)":
            (close.shift(1) > sma50.shift(1)) & (close <= sma50) & uptrend,
        "MACD bullish cross, IN uptrend":
            (macd["macd"].shift(1) <= macd["signal"].shift(1))
            & (macd["macd"] > macd["signal"]) & uptrend,
        "Correction dip: drawdown -10%..-25% while >200MA":
            (dd <= -0.10) & (dd > -0.25) & uptrend,
    }

    print(f"SOXL daily {df.index[0].date()} -> {df.index[-1].date()}  ({len(df)} bars)")
    print("Baseline mean fwd return: " +
          ", ".join(f"{h}d {base[h]:.2f}%" for h in HORIZONS) + "\n")

    ranked = []
    for name, mask in signals.items():
        mask = mask.fillna(False)
        edge20 = (fwd[20][mask].mean() * 100) - base[20]
        ranked.append((edge20, name, mask))
    ranked.sort(reverse=True)

    for edge20, name, mask in ranked:
        print(f"=== {name}  (signals: {int(mask.sum())}) ===")
        print(f"{'horizon':>7} {'n':>6} {'mean%':>8} {'win%':>7}  {'edge%':>7}")
        for h in HORIZONS:
            print(_row(fwd[h][mask], base, h))
        print()

    print("Ranked by 20-day edge (top = best historical entry). Positive edge =")
    print("bought better-than-average forward returns; small n => less reliable.")


if __name__ == "__main__":
    main()
