# Entry Signal Backtest — Summary

Backtest of the **"buy the dip in an uptrend"** entry signal used by the live
dashboard (`buy_dip_signal` in [`src/indicators.py`](src/indicators.py)).
Generated from [`scripts/backtest_entry.py`](scripts/backtest_entry.py).

- **Instrument:** SOXL (3× semiconductor ETF), daily bars
- **Sample:** 2010-03-11 → 2026-07-07 (4,105 bars)
- **Run:** `.venv/bin/python scripts/backtest_entry.py`

---

## 1. Method

This is an **event study of forward returns**, not an equity/P&L backtest. For
every historical day a candidate signal fired, we measure the realized forward
return over the next *N* trading days (N ∈ {5, 10, 20, 60}) and compare it to the
all-days **baseline** (the average forward return over the whole sample).

- **Edge** = signal mean forward return − baseline mean forward return.
  Positive edge ⇒ the signal historically bought *better-than-average* forward
  returns.
- **Win%** = share of occurrences with a positive forward return.
- **Causal:** every signal is computed from **closed bars only** (uses
  `shift(1)` for "yesterday"), so the live dashboard has no look-ahead. The
  forward returns look ahead *by construction* — that is the measurement, not a
  live calculation.

**Baseline mean forward return:**

| Horizon | Baseline mean |
|--------:|--------------:|
| 5d  | +1.43% |
| 10d | +2.79% |
| 20d | +5.63% |
| 60d | +16.84% |

---

## 2. The live signal

The dashboard fires an entry when the stock is in an uptrend **and** has pulled
back to support:

```
uptrend  AND  ( lower_band_tag  OR  ma50_cross )
```

- **uptrend** — `close > 200-day MA`
- **lower_band_tag** — `close ≤ lower Bollinger Band` (MA20 − 2σ, period 20)
- **ma50_cross** — was above the 50-day MA yesterday, closed at/below it today
  (`prev_close > prev_MA50 AND close ≤ MA50`)

### Combined signal performance (union of the two triggers)

**141 occurrences**, 2011-03-09 → 2026-07-02.

| Horizon | n | Mean | Median | Win% | **Edge vs baseline** |
|--------:|--:|-----:|-------:|-----:|---------------------:|
| 5d  | 141 | +2.52% | +2.46% | 61.4% | **+1.09** |
| 10d | 141 | +4.46% | +4.38% | 62.1% | **+1.67** |
| 20d | 141 | +10.09% | +10.45% | 70.0% | **+4.46** |
| 60d | 141 | +27.73% | +24.82% | 72.9% | **+10.89** |

The combined signal beats the baseline at every horizon, and 70–73% of
occurrences were positive over the 20- and 60-day windows.

### Component triggers

| Trigger | n | 20d mean | 20d win% | 20d edge | 60d mean | 60d edge |
|---------|--:|---------:|---------:|---------:|---------:|---------:|
| Lower Bollinger tag, in uptrend | 69 | +12.74% | 75.4% | **+7.11** | +27.41% | +10.58 |
| Pullback to 50-day MA, in uptrend | 92 | +8.10% | 67.0% | **+2.48** | +26.62% | +9.79 |

*(69 + 92 = 161 > 141 because ~20 days trigger both conditions at once.)*
The lower-band tag is the stronger, rarer trigger; the 50-MA pullback fires more
often with a smaller (still positive) edge.

---

## 3. Full candidate ranking (by 20-day edge)

All eight signals that were evaluated. ✅ marks the two adopted by the live
signal; the rest were rejected for weak or negative edge.

| Rank | Signal | n | 20d edge | 60d edge |
|-----:|--------|--:|---------:|---------:|
| 1 | Lower Bollinger tag, **in uptrend** ✅ | 69 | **+7.11** | +10.58 |
| 2 | Lower Bollinger tag (any trend) | 156 | +5.48 | +15.46 |
| 3 | Pullback to 50-MA, **in uptrend** ✅ | 92 | **+2.48** | +9.79 |
| 4 | MACD bullish cross, in uptrend | 110 | +1.38 | +4.37 |
| 5 | Correction dip −10%…−25%, >200MA | 709 | −0.12 | +1.75 |
| 6 | Reclaim 20-MA, in uptrend | 178 | −1.03 | +0.82 |
| 7 | RSI crosses back above 30 | 26 | −1.70 | +1.46 |
| — | RSI crosses above 30, in uptrend | 0 | n/a | n/a |

**Why the uptrend filter matters:** requiring `close > 200-day MA` lifts the
lower-band tag's 20-day edge from +5.48 (any trend) to **+7.11** — it screens out
"catching a falling knife" dips in downtrends.

**Zero-occurrence quirk:** "RSI crosses above 30 *in an uptrend*" never fired —
SOXL is rarely both deeply oversold (RSI < 30) and above its 200-day MA at the
same time.

---

## 4. Signal frequency by year (combined signal)

| Year | Signals | Year | Signals |
|-----:|--------:|-----:|--------:|
| 2011 | 8  | 2019 | 10 |
| 2012 | 5  | 2020 | 6  |
| 2013 | 13 | 2021 | 21 |
| 2014 | 13 | 2022 | 3  |
| 2015 | 10 | 2023 | 4  |
| 2016 | 7  | 2024 | 9  |
| 2017 | 15 | 2025 | 7  |
| 2018 | 7  | 2026 | 3  |

Roughly 6–15 signals/year, clustered in volatile pullback years (peak 21 in
2021). Quiet trending years (2022–2023) produced few.

---

## 5. Most recent occurrences (last 15) with realized 20-day forward return

| Date | Close | Fwd 20d |
|------|------:|--------:|
| 2024-04-19 | 30.79 | +47.45% |
| 2024-04-22 | 32.07 | +50.45% |
| 2024-07-17 | 51.55 | −32.01% |
| 2024-07-24 | 42.90 | −2.73% |
| 2024-07-25 | 39.78 | −5.71% |
| 2025-08-21 | 25.35 | +30.26% |
| 2025-08-29 | 26.04 | +30.65% |
| 2025-11-17 | 36.84 | +9.91% |
| 2025-11-18 | 34.35 | +4.83% |
| 2025-11-20 | 30.81 | +35.41% |
| 2025-12-12 | 41.71 | +34.43% |
| 2025-12-31 | 42.03 | +47.01% |
| 2026-03-03 | 53.42 | −10.31% |
| 2026-03-06 | 47.89 | +14.45% |
| 2026-07-02 | 181.47 | *(open — <20d elapsed)* |

Mostly strong subsequent runs, but note the losers (the 2024-07 cluster,
2026-03-03): the signal is an **edge, not a guarantee** — ~30% of occurrences
were negative over 20 days.

---

## 6. Key findings

1. The two triggers wired into the live signal are the **top causal signals with
   a meaningful positive edge**, which is why they were chosen.
2. **Longer horizons carry the edge.** The 5-day edge is small (+1.09); the real
   separation shows at 20d (+4.46) and 60d (+10.89) — this is a swing/position
   entry, not a day-trade signal.
3. The **200-day-MA uptrend filter is the single most important element** — it
   converts marginal dip-buys into higher-edge ones.
4. Mean ≈ median for the combined signal at every horizon, so the edge is broad-
   based rather than driven by a few outliers.

---

## 7. Caveats

- **Not a tradeable strategy.** This measures forward returns *after* the signal
  — no exits, position sizing, transaction costs, or compounding. It says "this
  condition preceded good returns," not "this system returned X%."
- **Modest sample sizes** (69 / 92 / 141 occurrences). Directionally solid, but
  not large; the script itself flags "small n ⇒ less reliable."
- **Fitted on SOXL only.** The same rule is applied as-is to the other dashboard
  tickers (SMH, QQQ, SPY, MU, SNDK, MRVL, TQQQ), where it was **not**
  independently validated.
- Overlapping windows mean nearby occurrences are correlated (not independent
  samples), which inflates apparent consistency.

*Related scripts not covered here:* [`scripts/backtest_bbands.py`](scripts/backtest_bbands.py)
and [`scripts/backtest_strategy.py`](scripts/backtest_strategy.py).
