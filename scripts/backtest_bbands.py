"""Event study: does price crossing ABOVE the upper Bollinger Band lead to a
pull-back in SOXL?

This is an analysis script (not used by the live app). It is causal for the
*signal* (the cross uses only past/closed bars); the *forward* returns it
measures are, by definition, looking ahead -- that's the point of an event
study, and it never feeds back into any live calculation.

Run:  .venv/bin/python scripts/backtest_bbands.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import data_loader, indicators, utils  # noqa: E402

HORIZONS = [1, 3, 5, 10, 20]


def _stats(fwd: pd.Series) -> dict:
    fwd = fwd.dropna()
    return {
        "n": len(fwd),
        "mean_%": fwd.mean() * 100,
        "median_%": fwd.median() * 100,
        "win_rate_%": (fwd > 0).mean() * 100,
    }


def main() -> None:
    cfg = utils.load_config()
    res = data_loader.load_ohlcv(cfg, "max", "1d")
    df = res.df.copy()
    close = df["Close"]
    ind = cfg["indicators"]
    bb = indicators.bollinger_bands(close, ind["bb_period"], ind["bb_std"])
    upper = bb["bb_upper"]

    # Forward returns at each horizon.
    fwd = {h: close.shift(-h) / close - 1.0 for h in HORIZONS}

    # Signal A: CROSS above the upper band (was at/below, now above).
    cross_up = (close.shift(1) <= upper.shift(1)) & (close > upper)
    # Signal B: STATE of being above the upper band (any such day).
    above = close > upper

    print(f"SOXL daily bars: {len(df)}  ({df.index[0].date()} -> {df.index[-1].date()})")
    print(f"Bollinger: {ind['bb_period']}-period, {ind['bb_std']} std\n")

    def report(label: str, mask: pd.Series) -> None:
        print(f"=== {label}  (signals: {int(mask.sum())}) ===")
        print(f"{'horizon':>8} {'n':>6} {'mean%':>8} {'median%':>9} {'win%':>7}"
              f"   {'baseline mean%':>14} {'edge%':>7}")
        for h in HORIZONS:
            s = _stats(fwd[h][mask])
            b = _stats(fwd[h])  # unconditional baseline
            edge = s["mean_%"] - b["mean_%"]
            print(f"{h:>7}d {s['n']:>6} {s['mean_%']:>8.2f} {s['median_%']:>9.2f} "
                  f"{s['win_rate_%']:>6.1f}%   {b['mean_%']:>14.2f} {edge:>+7.2f}")
        print()

    report("Forward return AFTER crossing UP through upper band", cross_up)
    report("Forward return on ANY day the close is ABOVE upper band", above)

    # ---- Conditional event study: the tag ONLY when overextended ----------
    rsi = indicators.rsi(close, ind["rsi_period"])
    sma20 = indicators.sma(close, 20)
    sma200 = indicators.sma(close, 200)
    print("------------------------------------------------------------------")
    print("CONDITIONAL: upper-band cross filtered by 'overextended' context\n")
    report("Cross up + RSI > 70", cross_up & (rsi > 70))
    report("Cross up + RSI > 75", cross_up & (rsi > 75))
    report("Cross up + price >10% above 20-day MA", cross_up & (close > 1.10 * sma20))
    report("Cross up + price BELOW 200-day MA (downtrend tag)",
           cross_up & (close < sma200))

    print("Reading it: 'edge%' = signal mean minus the all-days baseline mean.")
    print("Negative edge => the setup underperforms a random day (supports the")
    print("pull-back idea). Positive edge => price tends to keep going (band-walk).")


if __name__ == "__main__":
    main()
