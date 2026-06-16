"""SOXL Live Dashboard -- Streamlit entry point.

Run with:  streamlit run app.py
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from src import (
    alerts as alerts_mod,
    charts,
    data_loader,
    drawdown as dd_mod,
    indicators,
    regime as regime_mod,
    risk_metrics,
    utils,
)

st.set_page_config(page_title="SOXL Live Dashboard", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")


def _compute_period(interval: str, display_period: str) -> str:
    """Period to fetch for indicator warm-up (longer than the display window).

    Daily/weekly: use full history so MA20/50/200 are defined across the whole
    visible chart. Intraday: use the largest window yfinance allows for that
    interval (1m -> 7d, others -> 60d).
    """
    if interval.endswith("m") or interval.endswith("h"):
        return "7d" if interval == "1m" else "60d"
    return "max"


def _slice_display(df: pd.DataFrame, period: str, intraday: bool) -> pd.DataFrame:
    """Trim a warmed-up frame down to the user's selected display window."""
    if df is None or df.empty:
        return df
    end = df.index[-1]
    if period == "1d":
        return df[df.index.normalize() == end.normalize()]
    if period == "5d":
        last_days = sorted({d for d in df.index.normalize()})[-5:]
        keep = set(last_days)
        return df[df.index.normalize().isin(keep)]
    offsets = {"1mo": pd.DateOffset(months=1), "3mo": pd.DateOffset(months=3),
               "6mo": pd.DateOffset(months=6), "1y": pd.DateOffset(years=1),
               "5y": pd.DateOffset(years=5)}
    off = offsets.get(period)
    if off is None:
        return df
    return df[df.index >= end - off]


@st.cache_data(show_spinner=False, ttl=30)
def _cached_load(period: str, interval: str, intraday: bool, source: str,
                 _cfg_id: int, config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch extended history, compute indicators on it, slice to the window.

    Computing indicators on the longer ``_compute_period`` frame and then
    slicing means moving averages (incl. MA200) are warmed up and defined
    across the entire visible chart. ``_cfg_id`` busts the cache on refresh.
    """
    fetch_period = _compute_period(interval, period)
    res = data_loader.load_ohlcv(config, fetch_period, interval, source)
    full = indicators.compute_all(res.df, config, intraday)
    disp = _slice_display(full, period, intraday)
    return {
        "df": disp, "source": res.source, "is_live": res.is_live,
        "fetched_at": res.fetched_at, "note": res.note, "quote": res.quote,
    }


# CSS: shrink the metric font and let values wrap instead of being clipped
# with an ellipsis when the six header columns get narrow.
_METRIC_CSS = """
<style>
[data-testid="stMetricValue"] {
    font-size: 1.5rem;
    white-space: normal;
    overflow-wrap: anywhere;
    line-height: 1.2;
}
[data-testid="stMetricLabel"] p { font-size: 0.78rem; }
[data-testid="stMetricDelta"] { font-size: 0.85rem; }
</style>
"""


def metric_row(quote: Dict[str, Any], dd_summary: Dict[str, Any],
               regime: regime_mod.RegimeResult, res: Dict[str, Any],
               tz: str) -> None:
    st.markdown(_METRIC_CSS, unsafe_allow_html=True)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("SOXL", utils.fmt_price(quote.get("price")))
    c2.metric("Daily Change",
              utils.fmt_price(quote.get("change")),
              utils.fmt_pct(quote.get("change_pct")))
    c3.metric("DD from 52w High", utils.fmt_pct(dd_summary.get("drop_from_52w_high")))
    c4.markdown(
        f"<div style='font-size:0.78rem;color:#808495;font-weight:600'>Regime</div>"
        f"<span style='background:{regime.color};color:white;display:inline-block;"
        f"margin-top:6px;padding:4px 10px;border-radius:6px;font-weight:600;"
        f"font-size:0.95rem'>{regime.label}</span>",
        unsafe_allow_html=True,
    )
    # Source: provider name big, live/cached state as the delta line.
    c5.metric("Source", res["source"], "LIVE" if res["is_live"] else "CACHED",
              delta_color="normal" if res["is_live"] else "off")
    # Last update: time-of-day big, date underneath.
    fetched = res["fetched_at"]
    if hasattr(fetched, "strftime"):
        c6.metric("Last Update", fetched.strftime("%H:%M:%S"),
                  fetched.strftime("%Y-%m-%d"), delta_color="off")
    else:
        c6.metric("Last Update", str(fetched))


def snapshot_row(quote: Dict[str, Any]) -> None:
    """Horizontal strip of quote metrics, full width beneath the price chart."""
    items = [
        ("Previous Close", utils.fmt_price(quote.get("prev_close"))),
        ("Open", utils.fmt_price(quote.get("open"))),
        ("Day High", utils.fmt_price(quote.get("high"))),
        ("Day Low", utils.fmt_price(quote.get("low"))),
        ("Volume", utils.fmt_volume(quote.get("volume"))),
        ("Avg Volume (20d)", utils.fmt_volume(quote.get("avg_volume"))),
        ("52-Week High", utils.fmt_price(quote.get("high_52w"))),
        ("52-Week Low", utils.fmt_price(quote.get("low_52w"))),
    ]
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


# Stretch the main content to the full monitor width (Streamlit's "wide"
# layout still caps width and adds large side padding by default).
_FULLWIDTH_CSS = """
<style>
.block-container,
[data-testid="stMainBlockContainer"] {
    max-width: 100% !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    padding-top: 1.5rem !important;
}
</style>
"""


def main() -> None:
    config = utils.load_config()
    tz = config["timezone"]
    st.markdown(_FULLWIDTH_CSS, unsafe_allow_html=True)

    # ---------------- Controls (top panel, full-width) ------------------
    # Kept out of the sidebar so the dashboard spans the full page width.
    tf_labels = list(config["timeframes"].keys())
    with st.expander("⚙️ Controls", expanded=True):
        r1c1, r1c2, r1c3, r1c4 = st.columns([2, 2, 2, 1])
        tf_label = r1c1.selectbox("Timeframe / Interval", tf_labels, index=3)
        tf = config["timeframes"][tf_label]
        intraday = tf["intraday"]
        source = r1c2.selectbox(
            "Data source", ["yfinance", "alpaca", "polygon", "tradier"],
            index=0, help="Only yfinance is implemented; others are stubs.")
        refresh = r1c3.slider("Auto-refresh (seconds)", 0, 120,
                              int(config["refresh_interval_seconds"]), step=10,
                              help="0 disables auto-refresh. Paused when market is closed.")
        r1c4.write("")  # vertical spacer to align the button with the inputs
        refresh_token = 0
        if r1c4.button("🔄 Refresh", use_container_width=True):
            _cached_load.clear()
            refresh_token = 1

        st.markdown("**Indicators**")
        icols = st.columns(6)
        show_ma = [
            p for i, p in enumerate(config["moving_averages"])
            if icols[i].checkbox(f"MA {p}", value=(p != 200 or not intraday))
        ]
        show_vwap = icols[3].checkbox("VWAP (intraday)", value=intraday, disabled=not intraday)
        show_bbands = icols[4].checkbox("Bollinger Bands", value=True)
        show_rsi = icols[5].checkbox("RSI", value=True)

    if refresh and refresh > 0:
        try:
            st.autorefresh = st.experimental_rerun  # noqa
        except Exception:
            pass

    # ---------------- Load data (indicators already computed) -----------
    res = _cached_load(tf["period"], tf["interval"], intraday, source,
                       refresh_token, config)
    df = res["df"]
    quote = res["quote"]

    if res["note"]:
        st.warning(res["note"])

    if df is None or df.empty:
        st.error("No data could be loaded (live fetch failed and no cache). "
                 "Check your connection or try Manual refresh.")
        st.stop()

    # ---------------- Compute period-scoped metrics ---------------------
    # Indicators (MAs etc.) were computed on full history then sliced, so they
    # are warmed up. Drawdown/risk below are intentionally over the displayed
    # window only.
    market_open = utils.is_market_open(tz)
    snapshot = indicators.latest_snapshot(df, config)
    dd_summary = dd_mod.drawdown_summary(df, quote)
    risk = risk_metrics.compute_risk(df, quote, config)
    regime = regime_mod.classify(
        snapshot, dd_summary.get("current_drawdown", float("nan")),
        risk.get("vol_20d"), risk.get("vol_60d"))
    triggered = alerts_mod.evaluate(df, quote, risk, config)

    # ---------------- Top row -------------------------------------------
    st.title("📈 SOXL Live Dashboard")
    metric_row(quote, dd_summary, regime, res, tz)
    st.caption("⚠️ " + risk_metrics.LEVERAGE_WARNING)
    st.divider()

    # ---------------- Main chart (full width) ---------------------------
    # Price, volume, RSI and MACD live in ONE figure with a shared x-axis so
    # they pan/zoom/hover together.
    st.subheader(f"Price — {tf_label}")
    st.plotly_chart(
        charts.price_stack_chart(df, config, intraday, show_ma, show_vwap,
                                 show_bbands, show_rsi=show_rsi, show_macd=True,
                                 show_drawdown=True, market_open=market_open),
        use_container_width=True)

    # Snapshot as a horizontal metric strip beneath the charts.
    st.subheader("Snapshot")
    snapshot_row(quote)

    st.divider()

    # ---------------- Drawdown metrics (chart is in the stack above) ----
    st.subheader("📉 Drawdown from Rolling High")
    zone = dd_mod.classify_zone(dd_summary.get("current_drawdown", float("nan")),
                                config["drawdown_zones"])
    st.markdown(
        f"<span style='background:{dd_mod.ZONE_COLORS[zone]};color:white;"
        f"padding:3px 10px;border-radius:6px'>{dd_mod.ZONE_LABELS[zone]}</span>",
        unsafe_allow_html=True)
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Current Drawdown", utils.fmt_pct(dd_summary.get("current_drawdown")))
    d2.metric("Max Drawdown (period)", utils.fmt_pct(dd_summary.get("max_drawdown")))
    d3.metric("Drop from 52w High", utils.fmt_pct(dd_summary.get("drop_from_52w_high")))
    d4.metric("Drop from All-Time High", utils.fmt_pct(dd_summary.get("drop_from_ath")))
    phd = dd_summary.get("period_high_date")
    st.caption(f"Period high {utils.fmt_price(dd_summary.get('period_high'))} on "
               f"{phd.strftime('%Y-%m-%d') if phd else '—'} "
               f"({dd_summary.get('days_since_period_high', '—')} days ago)")

    st.divider()

    # ---------------- Indicator table -----------------------------------
    st.subheader("🧮 Technical Indicators")
    st.dataframe(_indicator_table(snapshot, risk), hide_index=True,
                 use_container_width=True)

    st.divider()

    # ---------------- Risk + Alerts -------------------------------------
    rcol, acol = st.columns(2)
    with rcol:
        st.subheader("🛡️ Risk Dashboard")
        st.dataframe(_risk_table(risk), hide_index=True, use_container_width=True)
    with acol:
        st.subheader("🚨 Alerts")
        if not triggered:
            st.success("No alerts triggered.")
        for a in triggered:
            icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(a.severity, "⚪")
            (st.error if a.severity == "critical" else
             st.warning if a.severity == "warning" else st.info)(f"{icon} {a.message}")

        st.subheader("Regime rationale")
        for r in regime.reasons:
            st.write("• " + r)

    # ---------------- Auto-refresh --------------------------------------
    # Only auto-refresh during regular US market hours -- there is no new data
    # to fetch when the market is closed.
    if refresh and refresh > 0:
        if market_open:
            st.caption(f"🟢 Market open — auto-refreshing every {refresh}s.")
            _auto_refresh(refresh)
        else:
            st.caption("🔴 Market closed — auto-refresh paused. "
                       "Use the Refresh button to update.")


def _indicator_table(snap: Dict[str, Any], risk: Dict[str, Any]) -> pd.DataFrame:
    def g(k):
        return snap.get(k)
    rows = [
        ("Price", utils.fmt_price(g("Close"))),
        ("MA 20 / 50 / 200", f"{utils.fmt_price(g('sma_20'))} / "
                              f"{utils.fmt_price(g('sma_50'))} / {utils.fmt_price(g('sma_200'))}"),
        ("MA20 slope", utils.fmt_pct(g("sma_20_slope"))),
        ("RSI 14", _num(g("rsi"))),
        ("MACD / Signal", f"{_num(g('macd'))} / {_num(g('macd_signal'))}"),
        ("MACD hist", _num(g("macd_hist"))),
        ("ROC 5 / 20 / 60d", f"{utils.fmt_pct(g('roc_5'))} / "
                             f"{utils.fmt_pct(g('roc_20'))} / {utils.fmt_pct(g('roc_60'))}"),
        ("ATR 14", utils.fmt_price(g("atr"))),
        ("Hist vol 20 / 60d", f"{utils.fmt_pct(g('hv_20'), signed=False)} / "
                              f"{utils.fmt_pct(g('hv_60'), signed=False)}"),
        ("BB width", utils.fmt_pct(g("bb_width"), signed=False)),
        ("Rel volume", _num(g("rel_volume"), "x")),
        ("OBV", utils.fmt_volume(g("obv"))),
        ("Dist 20 / 50 / 200d high", f"{utils.fmt_pct(g('dist_20d_high'))} / "
                                     f"{utils.fmt_pct(g('dist_50d_high'))} / "
                                     f"{utils.fmt_pct(g('dist_200d_high'))}"),
        ("Gap from prev close", utils.fmt_pct(risk.get("gap_from_prev_close"))),
    ]
    return pd.DataFrame(rows, columns=["Indicator", "Value"])


def _risk_table(risk: Dict[str, Any]) -> pd.DataFrame:
    conf = int(risk.get("var_confidence", 0.95) * 100)
    rows = [
        ("1-day move", utils.fmt_pct(risk.get("move_1d"))),
        ("5-day move", utils.fmt_pct(risk.get("move_5d"))),
        ("20-day move", utils.fmt_pct(risk.get("move_20d"))),
        ("60-day move", utils.fmt_pct(risk.get("move_60d"))),
        ("20-day volatility (annual)", utils.fmt_pct(risk.get("vol_20d"), signed=False)),
        ("60-day volatility (annual)", utils.fmt_pct(risk.get("vol_60d"), signed=False)),
        ("Current drawdown", utils.fmt_pct(risk.get("current_drawdown"))),
        ("Max drawdown (period)", utils.fmt_pct(risk.get("max_drawdown"))),
        (f"1-day {conf}% VaR (historical)", utils.fmt_pct(risk.get("var_95_1d"), signed=False)),
        ("Worst 1-day loss", utils.fmt_pct(risk.get("worst_1d"))),
        ("Worst 5-day loss", utils.fmt_pct(risk.get("worst_5d"))),
        ("Worst 20-day loss", utils.fmt_pct(risk.get("worst_20d"))),
        ("Daily realized vol (20d)", utils.fmt_pct(risk.get("daily_realized_vol"), signed=False)),
    ]
    return pd.DataFrame(rows, columns=["Risk Metric", "Value"])


def _num(v, suffix: str = "") -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.2f}{suffix}"


def _auto_refresh(seconds: int) -> None:
    """Trigger a rerun after *seconds*. Uses st.autorefresh when available."""
    fn = getattr(st, "autorefresh", None)
    if callable(fn):
        fn(interval=seconds * 1000, key="auto_refresh")
        return
    # Fallback for Streamlit builds without st.autorefresh.
    st.markdown(
        f"<meta http-equiv='refresh' content='{seconds}'>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
