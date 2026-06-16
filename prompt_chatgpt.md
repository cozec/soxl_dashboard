I want to build a live Python dashboard for the ETF ticker SOXL.

SOXL is a 3x leveraged semiconductor ETF, so the dashboard should focus on:
1. live / near-real-time price movement,
2. candlestick charting,
3. current drawdown from previous high,
4. technical indicators,
5. risk monitoring.

Build the project using Python.

Preferred stack:
- Streamlit for dashboard UI
- Plotly for interactive candlestick charts
- pandas / numpy for calculations
- yfinance for historical and delayed intraday data
- Optional: Alpaca, Polygon.io, Interactive Brokers, or Tradier API support for real-time data
- SQLite or Parquet for local caching

Main requirements:

1. Live price dashboard

Create a main dashboard for SOXL with:
- Current price
- Daily change in dollars
- Daily change in percentage
- Previous close
- Open
- High of day
- Low of day
- Volume
- Average volume
- 52-week high
- 52-week low

Refresh automatically every 30–60 seconds.

Allow user to choose timeframe:
- 1 day, 1-minute candles
- 5 days, 5-minute candles
- 1 month, 30-minute candles
- 3 months, daily candles
- 6 months, daily candles
- 1 year, daily candles
- 5 years, weekly candles

2. Main candle chart

Create a large main price window using candlestick style.

The candlestick chart should include:
- OHLC candles
- Volume bars under price chart
- Moving averages:
  - 20-period moving average
  - 50-period moving average
  - 200-period moving average for daily data
- VWAP for intraday data
- Optional Bollinger Bands

The user should be able to toggle indicators on and off.

3. Drawdown from previous max

Calculate and display current drop from previous maximum price.

Show:
- Previous all-time high
- Previous 52-week high
- Current price
- Drop from all-time high
- Drop from 52-week high
- Current drawdown percentage
- Maximum drawdown over selected period
- Date of previous high
- Number of days since previous high

Formula:

current_drawdown = current_price / previous_max_price - 1

Display drawdown as a negative percentage.

Example:
If SOXL previous high was $70 and current price is $42:
drawdown = 42 / 70 - 1 = -40%

Create a drawdown chart below the main candle chart:
- X-axis: date
- Y-axis: drawdown percentage from rolling previous high
- Highlight severe drawdown zones:
  - 0% to -10%: normal pullback
  - -10% to -25%: correction
  - -25% to -50%: major drawdown
  - below -50%: crash zone

4. Technical indicators

Include technical indicators that make sense for a leveraged ETF:

Trend indicators:
- 20-day moving average
- 50-day moving average
- 200-day moving average
- Price above or below moving averages
- Moving average slope

Momentum indicators:
- RSI 14
- MACD
- MACD signal line
- MACD histogram
- Rate of change:
  - 5-day return
  - 20-day return
  - 60-day return

Volatility indicators:
- ATR 14
- Historical volatility:
  - 20-day annualized volatility
  - 60-day annualized volatility
- Bollinger Band width

Volume indicators:
- Volume moving average
- Relative volume
- On-balance volume

Risk indicators:
- Current drawdown
- Max drawdown
- Distance from 20-day high
- Distance from 50-day high
- Distance from 200-day high
- Daily realized volatility
- Gap from previous close

5. Signal panel

Create a simple signal panel.

The dashboard should classify SOXL into one of these regimes:

Strong Uptrend:
- Price above 20-day, 50-day, and 200-day moving averages
- 20-day MA above 50-day MA
- RSI between 50 and 75
- Drawdown less than 10%

Uptrend but Extended:
- Price above major moving averages
- RSI above 75
- Price far above 20-day MA

Neutral:
- Price between 50-day and 200-day moving averages
- RSI between 40 and 60

Correction:
- Price below 50-day MA
- Drawdown greater than 15%

High Risk / Downtrend:
- Price below 200-day MA
- Drawdown greater than 25%
- 20-day MA below 50-day MA

Crash / Extreme Risk:
- Drawdown greater than 50%
- Price below 200-day MA
- Volatility sharply elevated

Show the regime with:
- Text label
- Color-coded badge
- Explanation of why the regime was selected

6. Risk dashboard

Because SOXL is 3x leveraged, add a dedicated risk section.

Display:
- 1-day move
- 5-day move
- 20-day move
- 60-day move
- 20-day volatility
- 60-day volatility
- Max drawdown
- Current drawdown
- Estimated 1-day 95% VaR using historical returns
- Worst single-day loss in selected period
- Worst 5-day loss in selected period
- Worst 20-day loss in selected period

Also include a warning:
“SOXL is a 3x leveraged ETF. It is designed for daily leveraged exposure and can suffer from volatility decay over longer holding periods.”

7. Alerts

Add alert conditions:
- Price crosses above 20-day MA
- Price crosses below 20-day MA
- Price crosses below 50-day MA
- Price crosses below 200-day MA
- RSI above 75
- RSI below 30
- Drawdown exceeds 10%
- Drawdown exceeds 25%
- Drawdown exceeds 50%
- Volume exceeds 2x average volume
- Daily loss exceeds 10%

For now, display alerts inside the dashboard.
Design the code so email, SMS, or Telegram alerts can be added later.

8. Data handling

Create a data module that:
- Downloads SOXL OHLCV data
- Supports intraday and daily data
- Caches data locally
- Handles API failures gracefully
- Falls back to last cached data if live data fails
- Clearly shows the last data update timestamp

Avoid lookahead bias in any calculation.

9. Dashboard layout

Use this Streamlit layout:

Top row:
- Ticker: SOXL
- Current price
- Daily change %
- Current drawdown from 52-week high
- Current regime
- Last update time

Main section:
- Interactive candlestick chart
- Volume bars
- Moving average overlays
- VWAP for intraday

Second section:
- Drawdown chart
- Current drawdown metrics

Third section:
- Technical indicator table
- RSI chart
- MACD chart

Fourth section:
- Risk dashboard
- Alert panel

Sidebar:
- Timeframe selector
- Candle interval selector
- Indicator toggles
- Refresh interval
- Data source selector
- Manual refresh button

10. Project structure

Create the project with this structure:

soxl_live_dashboard/
    README.md
    requirements.txt
    config.yaml
    app.py
    data/
        cache/
    src/
        data_loader.py
        indicators.py
        drawdown.py
        risk_metrics.py
        regime.py
        alerts.py
        charts.py
        utils.py
    tests/
        test_indicators.py
        test_drawdown.py
        test_risk_metrics.py

11. Implementation details

Write clean, modular, production-style Python code.

Use:
- streamlit
- pandas
- numpy
- yfinance
- plotly
- ta or pandas_ta if useful
- pyyaml

Make sure:
- All indicator calculations are unit-tested
- Missing data is handled safely
- Timezones are handled correctly
- Dashboard does not crash if API data is unavailable
- User can run it with one command:

streamlit run app.py

12. README

Create a README that includes:
- Project description
- Setup instructions
- How to run
- Data source notes
- Limitations of yfinance intraday data
- How to add a paid real-time API later
- Explanation of drawdown calculation
- Explanation of regime classification
- Warning about leveraged ETF risk

13. Output

Generate the complete working codebase.

The dashboard should be useful for monitoring SOXL live price action, current drawdown from previous maximum, technical trend condition, volatility risk, and major warning signals.