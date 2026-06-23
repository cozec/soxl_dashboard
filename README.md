# Semiconductor ETF Dashboard (SMH / SOXL)

A live(-ish) Python dashboard for semiconductor ETFs, with one tab per ticker:

- **SMH (1x)** — VanEck Semiconductor ETF (unleveraged underlying basket).
- **SOXL (3x)** — the 3x leveraged semiconductor ETF.

It focuses on price action, candlestick charting, drawdown from previous highs,
technical indicators, candlestick/entry signals, regime classification, and
leverage-aware risk monitoring. Both tabs share one parameterized dashboard.

> ⚠️ **SOXL is a 3x leveraged ETF.** It is designed for *daily* leveraged
> exposure and can suffer from **volatility decay** over longer holding periods.
> This dashboard is for monitoring/education only — not investment advice.

---

## Features

- **Live price header** — current price, day change ($/%), prev close, open,
  high/low of day, volume, average volume, 52-week high/low, last-update time.
- **Combined zoomable chart** — price, volume, drawdown, RSI and MACD stacked in
  **one shared-x-axis figure**, rendered through an embedded Plotly.js so it
  behaves like Yahoo Finance:
  - mouse-wheel **scroll-zoom**, **drag-pan**, double-click reset;
  - **quick-zoom buttons** (1M / 3M / 6M / 1Y / 10Y / All);
  - **y-axis auto-rescales** to the visible candles on every zoom/pan/button;
  - the chart holds the **full loaded history**, with the timeframe as the
    initial view, so zooming out reveals more history;
  - y-axis labels on the right; OHLC candles with 20/50/200 MAs, shaded
    Bollinger band, intraday VWAP, and a rolling-high step line.
- **Candlestick / entry signals on the chart:**
  - **Rolling-high stars** — a ★ on every bar that sets a new running high;
  - **Buy-the-dip entry** — green ▲ markers + a header badge + a green alert
    when, in an uptrend (>200-day MA), price tags the lower Bollinger Band or
    pulls back to the 50-day MA;
  - **Hanging-man** candles labelled with an arrowed textbox.
- **Drawdown panel** — drawdown from the rolling high with shaded severity zones
  (normal / correction / major / crash), plus all-time-high, 52-week-high, and
  period-high metrics.
- **Technical indicators** — trend (MAs + slope), momentum (RSI, MACD, ROC),
  volatility (ATR, historical vol, Bollinger width), volume (vol MA, relative
  volume, OBV), and risk distances from rolling highs.
- **Signal/regime panel** — classifies the ticker into one of six regimes with a
  color badge and a plain-English rationale.
- **Risk dashboard** — multi-horizon moves, annualized vol, historical 1-day
  95% VaR, worst 1/5/20-day losses, gap from prev close.
- **Alerts** — MA crossovers, RSI extremes, drawdown thresholds, volume spikes,
  large daily losses, and the buy-the-dip entry. Shown in-app; delivery is
  pluggable (email/SMS/Telegram).
- **Market-hours-aware auto-refresh** — refreshes only during the regular US
  session (exact NYSE calendar via `pandas_market_calendars` when installed,
  otherwise a built-in holiday list).
- **Resilient data layer** — Parquet caching with graceful fallback to last
  cached data when the live fetch fails; clear "LIVE vs CACHED" status.
- **Backtests** — event-study scripts under `scripts/` for the Bollinger-band
  tag, candidate entry signals, and a step-aside strategy.

---

## Project structure

```
SOXL_dashboard/
    README.md
    requirements.txt
    config.yaml          # all tunable parameters
    app.py               # Streamlit entry point
    data/cache/          # Parquet cache (gitignored)
    src/
        utils.py         # config, timezones, formatting
        data_loader.py   # fetch + cache + fallback + pluggable sources
        indicators.py    # MAs, RSI, MACD, ATR, VWAP, Bollinger, volume, ROC
        drawdown.py      # drawdown series + summary + zones
        risk_metrics.py  # moves, vol, VaR, worst-loss
        regime.py        # regime classification
        alerts.py        # alert engine + notifier interface
        charts.py        # Plotly figures
    scripts/
        backtest_bbands.py    # Bollinger-band tag event study
        backtest_entry.py     # candidate entry-signal event study
        backtest_strategy.py  # step-aside-after-tag strategy backtest
    tests/
        test_indicators.py
        test_drawdown.py
        test_risk_metrics.py
```

---

## Setup

```bash
# from the project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

Switch between the **SMH** and **SOXL** tabs at the top. The chart opens on the
default timeframe (3M / 1d) — use the **quick-zoom buttons** (1M…All) or
scroll/drag to explore; the y-axis re-fits automatically. Defaults (timeframe,
indicators, refresh interval, data source) live in `config.yaml`.

## Backtests

```bash
.venv/bin/python scripts/backtest_bbands.py     # upper-band tag event study
.venv/bin/python scripts/backtest_entry.py      # entry-signal event study
.venv/bin/python scripts/backtest_strategy.py   # step-aside strategy vs buy&hold
```

These are analysis-only (they never feed the live app). The *signal* is causal;
the *forward returns* they measure are, by design, look-ahead. Caveats are
printed with the results: bull-heavy samples, no transaction costs/slippage, and
no leverage-decay modelling for SOXL.

## Test

```bash
pytest -q
```

---

## Data source notes

By default the dashboard uses **yfinance** (free, no key required).

### Limitations of yfinance intraday data
- Intraday data is **delayed**, not true real-time (typically ~15 min).
- Intraday history is limited: 1-minute data is only available for roughly the
  last few days, and longer intraday intervals have their own retention caps.
  The timeframe presets in `config.yaml` stay within these limits.
- yfinance is an unofficial scraper of Yahoo Finance and can rate-limit or
  break without notice. The data layer retries, then falls back to the local
  Parquet cache and clearly flags the data as **CACHED**.

### Adding a paid real-time API later
The data layer is built around a small `DataSource` interface in
[src/data_loader.py](src/data_loader.py). Stubs already exist for **Alpaca**,
**Polygon.io**, and **Tradier**. To wire one up:

1. Implement `fetch(ticker, period, interval)` on the corresponding subclass so
   it returns a frame with `Open, High, Low, Close, Volume` columns.
2. Add your API key (use Streamlit secrets / env vars — never commit keys).
3. Set `data_source:` in `config.yaml`.

Everything downstream (indicators, drawdown, risk, charts) is source-agnostic.

---

## How the drawdown calculation works

Drawdown is the percentage drop from the **running (expanding) maximum** price:

```
drawdown_t = price_t / running_max(price)_t - 1     (always <= 0)
```

The running max uses only past + current data, so there is **no lookahead
bias**. Example from the spec: if the previous high was $70 and the current
price is $42, drawdown = 42 / 70 − 1 = **−40%**.

Severity zones (configurable in `config.yaml`):

| Zone        | Range            |
|-------------|------------------|
| Normal      | 0% to −10%       |
| Correction  | −10% to −25%     |
| Major       | −25% to −50%     |
| Crash       | below −50%       |

---

## How regime classification works

The latest indicator snapshot + current drawdown are evaluated worst-first, so
the most severe applicable regime wins:

| Regime | Key conditions |
|--------|----------------|
| **Crash / Extreme Risk** | Drawdown ≤ −50%, price < 200-day MA, (vol spiking) |
| **High Risk / Downtrend** | Price < 200-day MA, drawdown ≤ −25%, 20MA < 50MA |
| **Correction** | Price < 50-day MA, drawdown ≤ −15% |
| **Strong Uptrend** | Price > 20/50/200 MAs, 20MA > 50MA, RSI 50–75, DD shallower than −10% |
| **Uptrend but Extended** | Above major MAs, RSI > 75 or >10% above 20-day MA |
| **Neutral** | Default — no strong trend or risk signal dominates |

Each result includes the specific reasons it was selected, shown in the
dashboard's regime rationale panel.

---

## Risk warning

SOXL seeks **300%** of the *daily* performance of the ICE Semiconductor Index.
Because it resets daily, compounding and volatility decay mean multi-day and
longer returns can differ sharply from 3× the index over the same period.
Leveraged ETFs can move violently and are intended for short holding periods and
active monitoring. Always understand the product before trading it.

---

## Notes & assumptions

- "All-time high" is approximated by the maximum within the **loaded history**
  for the selected timeframe (yfinance does not provide true inception-to-date
  highs in a single intraday call). Use a longer timeframe for a wider window.
- Timezones: intraday timestamps are converted to the exchange timezone from
  `config.yaml` (`America/New_York`); daily/weekly bars are localized to it.
- All indicator and risk calculations are causal (backward-looking) to avoid
  lookahead bias; this is unit-tested in `tests/`.
