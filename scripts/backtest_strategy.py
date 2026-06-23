"""Strategy backtest: 'step aside after an overextended upper-band tag'.

Rule (long / flat, no shorting -- shorting a 3x uptrending ETF is a fast way to
go broke):
  * Default position is LONG SOXL (buy & hold).
  * When the close crosses UP through the upper Bollinger Band *and* RSI > 75
    (overextended), go to CASH for the next H trading days, then resume LONG.

Everything is causal: the position for day t+1 is decided from data known at the
close of day t (close, band, RSI). Transaction costs are charged on every change
in position. We compare the strategy to plain buy & hold across several H.

Run:  .venv/bin/python scripts/backtest_strategy.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import data_loader, indicators, utils  # noqa: E402

TRADING_DAYS = 252
COST_BPS = 5.0          # per side, in basis points (0.05%)
HOLD_DAYS = [3, 5, 10]  # days to stay flat after an overextended tag


def metrics(daily_ret: pd.Series) -> dict:
    """CAGR, vol, Sharpe, max drawdown, total return from a daily-return series."""
    daily_ret = daily_ret.dropna()
    equity = (1.0 + daily_ret).cumprod()
    n = len(daily_ret)
    total = equity.iloc[-1] - 1.0
    cagr = equity.iloc[-1] ** (TRADING_DAYS / n) - 1.0
    vol = daily_ret.std() * np.sqrt(TRADING_DAYS)
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(TRADING_DAYS)
              if daily_ret.std() > 0 else float("nan"))
    max_dd = (equity / equity.cummax() - 1.0).min()
    return {"total_%": total * 100, "cagr_%": cagr * 100, "vol_%": vol * 100,
            "sharpe": sharpe, "max_dd_%": max_dd * 100, "equity_end": equity.iloc[-1]}


def run() -> None:
    cfg = utils.load_config()
    res = data_loader.load_ohlcv(cfg, "max", "1d")
    df = res.df.copy()
    close = df["Close"]
    ind = cfg["indicators"]

    asset_ret = close.pct_change().fillna(0.0)
    upper = indicators.bollinger_bands(close, ind["bb_period"], ind["bb_std"])["bb_upper"]
    rsi = indicators.rsi(close, ind["rsi_period"])
    signal = (close.shift(1) <= upper.shift(1)) & (close > upper) & (rsi > 75)
    sig_idx = np.where(signal.fillna(False).values)[0]

    n = len(df)
    cost = COST_BPS / 10000.0

    print(f"SOXL daily {df.index[0].date()} -> {df.index[-1].date()}  "
          f"({n} bars), cost {COST_BPS:.0f} bps/side\n")

    # Buy & hold baseline.
    bh = metrics(asset_ret)

    print(f"{'strategy':<28} {'total%':>10} {'CAGR%':>8} {'vol%':>7} "
          f"{'Sharpe':>7} {'maxDD%':>8} {'expo%':>7} {'trades':>7}")
    print("-" * 88)
    print(f"{'Buy & Hold':<28} {bh['total_%']:>10.0f} {bh['cagr_%']:>8.2f} "
          f"{bh['vol_%']:>7.1f} {bh['sharpe']:>7.2f} {bh['max_dd_%']:>8.1f} "
          f"{100.0:>7.1f} {0:>7}")

    for h in HOLD_DAYS:
        pos = np.ones(n)
        for i in sig_idx:
            pos[i + 1: i + 1 + h] = 0.0   # flat for h days starting next bar
        pos = pd.Series(pos, index=df.index)
        turnover = pos.diff().abs().fillna(0.0)
        strat_ret = pos * asset_ret - turnover * cost
        m = metrics(strat_ret)
        trades = int((turnover > 0).sum())
        expo = pos.mean() * 100
        print(f"{'Step-aside H=' + str(h) + 'd':<28} {m['total_%']:>10.0f} "
              f"{m['cagr_%']:>8.2f} {m['vol_%']:>7.1f} {m['sharpe']:>7.2f} "
              f"{m['max_dd_%']:>8.1f} {expo:>7.1f} {trades:>7}")

    print("\nNotes:")
    print(" - 'expo%' = share of days actually invested; 'trades' = position changes.")
    print(" - Long/flat only (no shorting). Costs charged on every position change.")
    print(" - Caveats: one secular semis bull market, no slippage/borrow, no")
    print("   leverage-decay modelling, signal count is small -> treat as indicative.")


if __name__ == "__main__":
    run()
