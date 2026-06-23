"""Plotly chart builders.

Each function returns a ``plotly.graph_objects.Figure`` the Streamlit app can
render with ``st.plotly_chart``. Charts degrade gracefully on empty/short data.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import drawdown as dd_mod
from . import indicators as ind_mod

_MA_COLORS = {20: "#1f77b4", 50: "#ff7f0e", 200: "#9467bd"}


def _rangebreaks(df: pd.DataFrame, intraday: bool) -> List[dict]:
    """Rangebreaks that hide non-trading gaps (weekends, holidays, overnight).

    Weekends and holidays are derived from the data itself: any calendar day in
    the visible span with no bars is removed. Intraday charts additionally hide
    the overnight period outside the regular 09:30-16:00 session.
    """
    if df is None or df.empty:
        return []
    present = {ts.strftime("%Y-%m-%d") for ts in df.index}
    full_days = pd.date_range(df.index[0].normalize(), df.index[-1].normalize(), freq="D")
    missing = [d.strftime("%Y-%m-%d") for d in full_days
               if d.strftime("%Y-%m-%d") not in present]
    breaks: List[dict] = []
    if intraday:
        breaks.append(dict(bounds=[16, 9.5], pattern="hour"))  # overnight
    if missing:
        breaks.append(dict(values=missing))  # weekends + holidays (whole days)
    return breaks


def candlestick_chart(
    df: pd.DataFrame,
    config: Dict[str, Any],
    intraday: bool,
    show_ma: List[int],
    show_vwap: bool,
    show_bbands: bool,
    market_open: bool = False,
) -> go.Figure:
    """Price candles + volume subplot + optional MA/VWAP/Bollinger overlays.

    Also annotates the current rolling high and the latest close (labelled as
    the live price while the market is open).
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.78, 0.22], vertical_spacing=0.03,
        specs=[[{"type": "candlestick"}], [{"type": "bar"}]],
    )
    if df is None or df.empty:
        fig.update_layout(title="No data available")
        return fig

    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name="OHLC",
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    for period in show_ma:
        col = f"sma_{period}"
        if col in df.columns and df[col].notna().any():
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], name=f"MA{period}",
                           line=dict(width=1.3, color=_MA_COLORS.get(period))),
                row=1, col=1,
            )

    if show_vwap and intraday and "vwap" in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["vwap"], name="VWAP",
                       line=dict(width=1.3, color="#00bcd4", dash="dot")),
            row=1, col=1,
        )

    if show_bbands and "bb_upper" in df.columns:
        for col, dash in [("bb_upper", "dot"), ("bb_lower", "dot")]:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], name=col.replace("bb_", "BB "),
                           line=dict(width=1, color="rgba(150,150,150,0.7)", dash=dash),
                           showlegend=False),
                row=1, col=1,
            )

    vol_colors = [
        "#26a69a" if c >= o else "#ef5350"
        for o, c in zip(df["Open"], df["Close"])
    ]
    fig.add_trace(
        go.Bar(x=df.index, y=df["Volume"], name="Volume",
               marker_color=vol_colors, opacity=0.6),
        row=2, col=1,
    )

    # --- Annotations: rolling high + latest close -----------------------
    # Rolling (running) high = peak of the High series over the visible window.
    high_pos = df["High"].idxmax()
    high_val = float(df["High"].loc[high_pos])
    fig.add_annotation(
        x=high_pos, y=high_val, row=1, col=1,
        text=f"Rolling High ${high_val:,.2f}", showarrow=True, arrowhead=2,
        arrowcolor="#26a69a", ax=0, ay=-32, font=dict(color="#1b8a78", size=11),
        bgcolor="rgba(255,255,255,0.7)",
    )
    # Latest close (= current price while the market is open).
    last_pos = df.index[-1]
    last_close = float(df["Close"].iloc[-1])
    close_label = "Current" if market_open else "Close"
    fig.add_annotation(
        x=last_pos, y=last_close, row=1, col=1,
        text=f"{close_label} ${last_close:,.2f}", showarrow=True, arrowhead=2,
        arrowcolor="#ef5350", ax=38, ay=0, font=dict(color="#c0392b", size=11),
        bgcolor="rgba(255,255,255,0.7)",
    )

    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        hovermode="x unified",
    )
    # Hide non-trading gaps (weekends, holidays, overnight).
    fig.update_xaxes(rangebreaks=_rangebreaks(df, intraday))
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    return fig


def price_stack_chart(
    df: pd.DataFrame,
    config: Dict[str, Any],
    intraday: bool,
    show_ma: List[int],
    show_vwap: bool,
    show_bbands: bool,
    show_rsi: bool = True,
    show_macd: bool = True,
    show_drawdown: bool = True,
    show_entries: bool = True,
    market_open: bool = False,
    initial_xrange=None,
) -> go.Figure:
    """Price + volume + (optional) drawdown + RSI + MACD in ONE figure.

    All panels share a single x-axis, so panning/zooming, hover, and the
    non-trading-gap rangebreaks stay aligned across every subplot.
    """
    # Build the row layout dynamically based on which panels are enabled.
    rows = [("price", 0.46), ("vol", 0.12)]
    if show_drawdown:
        rows.append(("dd", 0.16))
    if show_rsi:
        rows.append(("rsi", 0.15))
    if show_macd:
        rows.append(("macd", 0.16))
    # Normalise heights to sum to 1.
    total = sum(h for _, h in rows)
    heights = [h / total for _, h in rows]
    row_of = {name: i + 1 for i, (name, _) in enumerate(rows)}

    fig = make_subplots(rows=len(rows), cols=1, shared_xaxes=True,
                        vertical_spacing=0.025, row_heights=heights)
    if df is None or df.empty:
        fig.update_layout(title="No data available")
        return fig

    r = row_of["price"]
    fig.add_trace(
        go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                       low=df["Low"], close=df["Close"], name="OHLC",
                       increasing_line_color="#26a69a", decreasing_line_color="#ef5350"),
        row=r, col=1)
    for period in show_ma:
        col = f"sma_{period}"
        if col in df.columns and df[col].notna().any():
            fig.add_trace(go.Scatter(x=df.index, y=df[col], name=f"MA{period}",
                                     line=dict(width=1.3, color=_MA_COLORS.get(period))),
                          row=r, col=1)
    if show_vwap and intraday and "vwap" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["vwap"], name="VWAP",
                                 line=dict(width=1.3, color="#00bcd4", dash="dot")),
                      row=r, col=1)
    if show_bbands and "bb_upper" in df.columns and "bb_lower" in df.columns:
        # Upper band (no fill), then lower band filling up to it -> shaded band.
        fig.add_trace(go.Scatter(x=df.index, y=df["bb_upper"], name="BB upper",
                                 line=dict(width=0.8, color="rgba(150,150,150,0.45)"),
                                 showlegend=False, hoverinfo="skip"),
                      row=r, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["bb_lower"], name="Bollinger Bands",
                                 line=dict(width=0.8, color="rgba(150,150,150,0.45)"),
                                 fill="tonexty", fillcolor="rgba(160,160,160,0.18)",
                                 showlegend=True, hoverinfo="skip"),
                      row=r, col=1)

    # Running (expanding) high = the exact reference the drawdown panel uses:
    # at each date it is max(Close) up to and including that date. Drawn as a
    # step line so the drawdown reference is visible for every date.
    run_high = df["Close"].cummax()
    fig.add_trace(go.Scatter(x=df.index, y=run_high, name="Running High",
                             line=dict(width=1.1, color="#f2a900", dash="dash"),
                             line_shape="hv", showlegend=True),
                  row=r, col=1)
    # Star every bar that SETS a new rolling high (where the step line steps up).
    new_high = run_high.gt(run_high.shift(1))
    if len(new_high) > 0:
        new_high.iloc[0] = True  # the first bar establishes the initial high
    if new_high.any():
        fig.add_trace(go.Scatter(
            x=df.index[new_high.values], y=run_high[new_high.values],
            mode="markers", name="New High",
            marker=dict(symbol="star", size=11, color="#f2a900",
                        line=dict(width=0.6, color="#8a6d00"))),
            row=r, col=1)

    # Annotations on the price row. The marker sits at the latest value of the
    # running high (= the window peak, since the peak is already in the past).
    high_pos = df["Close"].idxmax()
    high_val = float(run_high.iloc[-1])
    fig.add_annotation(x=high_pos, y=high_val, row=r, col=1,
                       text=f"Rolling High ${high_val:,.2f}", showarrow=True, arrowhead=2,
                       arrowcolor="#26a69a", ax=0, ay=-32, font=dict(color="#1b8a78", size=11),
                       bgcolor="rgba(255,255,255,0.7)")
    last_close = float(df["Close"].iloc[-1])
    dd_now = last_close / high_val - 1.0  # drawdown from the running high
    # Close / drawdown shown as a static label in the empty top-right corner so
    # it never overlaps the candles.
    # Anchored to today's close with an arrow; text hangs down-LEFT into the
    # empty area so it stays inside the plot (the last candle is at the right
    # edge, so offsetting right would clip the box).
    fig.add_annotation(
        x=df.index[-1], y=last_close, row=r, col=1,
        text=(f"{'Current' if market_open else 'Close'} ${last_close:,.2f}"
              f"<br>DD from Rolling High {dd_now * 100:.1f}%"),
        showarrow=True, arrowhead=2, arrowcolor="#c0392b", arrowwidth=1.3,
        ax=-22, ay=55, xanchor="right", yanchor="top", align="right",
        font=dict(color="#c0392b", size=11), bgcolor="rgba(255,255,255,0.75)")

    # Buy-the-dip entry markers (green triangles just below the bar's low).
    if show_entries:
        entries = ind_mod.buy_dip_signal(df)
        if not entries.empty and entries.any():
            ex = df.index[entries.values]
            ey = df["Low"][entries.values] * 0.985
            fig.add_trace(go.Scatter(x=ex, y=ey, mode="markers", name="Entry (buy dip)",
                                     marker=dict(symbol="triangle-up", size=11,
                                                 color="#2e7d32",
                                                 line=dict(width=0.5, color="white"))),
                          row=r, col=1)

    # Hanging-man candles: a small textbox with an arrow pointing down at each.
    hm = ind_mod.hanging_man_signal(df)
    if not hm.empty and hm.any():
        hx = df.index[hm.values]
        hy = df["High"][hm.values]
        for x_, y_ in zip(hx, hy):
            fig.add_annotation(
                x=x_, y=float(y_), row=r, col=1, text="Hanging Man",
                showarrow=True, arrowhead=2, arrowcolor="#e67e22", arrowwidth=1.2,
                ax=-30, ay=-24, font=dict(color="#b35e10", size=9),
                bgcolor="rgba(255,255,255,0.8)", bordercolor="#e67e22",
                borderwidth=0.6, borderpad=1)

    # Volume.
    rv = row_of["vol"]
    vol_colors = ["#26a69a" if c >= o else "#ef5350"
                  for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                         marker_color=vol_colors, opacity=0.6, showlegend=False),
                  row=rv, col=1)

    # Drawdown from rolling high, with shaded severity zones.
    if show_drawdown:
        rd = row_of["dd"]
        dd = dd_mod.drawdown_series(df["Close"]) * 100.0
        fig.add_trace(go.Scatter(x=dd.index, y=dd, name="Drawdown %",
                                 fill="tozeroy", line=dict(color="#ef5350", width=1),
                                 showlegend=False),
                      row=rd, col=1)
        zones = config["drawdown_zones"]
        floor = min(float(dd.min()), zones["major"] * 100) - 5
        for y0, y1, color in [
            (zones["normal"] * 100, 0, "rgba(46,204,113,0.10)"),
            (zones["correction"] * 100, zones["normal"] * 100, "rgba(241,196,15,0.12)"),
            (zones["major"] * 100, zones["correction"] * 100, "rgba(230,126,34,0.12)"),
            (floor, zones["major"] * 100, "rgba(231,76,60,0.12)"),
        ]:
            fig.add_hrect(y0=y0, y1=y1, fillcolor=color, line_width=0,
                          layer="below", row=rd, col=1)

    # RSI.
    if show_rsi and "rsi" in df.columns:
        rr = row_of["rsi"]
        fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI",
                                 line=dict(color="#7e57c2", width=1.2), showlegend=False),
                      row=rr, col=1)
        fig.add_hline(y=70, line=dict(color="#ef5350", width=1, dash="dash"), row=rr, col=1)
        fig.add_hline(y=30, line=dict(color="#26a69a", width=1, dash="dash"), row=rr, col=1)
        fig.update_yaxes(range=[0, 100], row=rr, col=1)

    # MACD.
    if show_macd and "macd" in df.columns:
        rm = row_of["macd"]
        hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["macd_hist"].fillna(0)]
        fig.add_trace(go.Bar(x=df.index, y=df["macd_hist"], name="Hist",
                             marker_color=hist_colors, opacity=0.6, showlegend=False),
                      row=rm, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["macd"], name="MACD",
                                 line=dict(color="#1f77b4", width=1.2), showlegend=False),
                      row=rm, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["macd_signal"], name="Signal",
                                 line=dict(color="#ff7f0e", width=1.2), showlegend=False),
                      row=rm, col=1)

    # Panel labels in the top-left corner of each subplot (replaces the y-axis
    # titles, which ate horizontal space on the left).
    panel_labels = {"price": "Price", "vol": "Vol", "dd": "DD %",
                    "rsi": "RSI", "macd": "MACD"}
    for name, rnum in row_of.items():
        fig.add_annotation(
            text=f"<b>{panel_labels[name]}</b>", row=rnum, col=1,
            xref="x domain", yref="y domain", x=0.004, y=0.97,
            xanchor="left", yanchor="top", showarrow=False,
            font=dict(size=11, color="#666"), bgcolor="rgba(255,255,255,0.55)")

    fig.update_layout(
        # 2x taller panels: doubled the base + per-row heights.
        height=640 + 300 * (len(rows) - 1),
        # Y labels live on the right now, so keep the left margin tight.
        # Extra top room for the quick-zoom buttons + legend.
        margin=dict(l=8, r=52, t=52, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        hovermode="x unified",
        bargap=0,
        # Yahoo-style interaction: drag to pan, mouse-wheel to zoom
        # (scrollZoom is enabled in the Streamlit render config).
        dragmode="pan",
    )
    # Y-axis tick labels on the RIGHT side (Yahoo-style); automargin reserves
    # room so they aren't clipped.
    fig.update_yaxes(side="right", automargin=True)
    # Single shared x-axis: apply gap rangebreaks to every panel.
    fig.update_xaxes(rangebreaks=_rangebreaks(df, intraday))
    # Quick-zoom buttons above the price panel (client-side; they trigger the
    # y-axis auto-rescale just like a manual zoom).
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=1, label="1M", step="month", stepmode="backward"),
                dict(count=3, label="3M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=10, label="10Y", step="year", stepmode="backward"),
                dict(step="all", label="All"),
            ],
            x=1, xanchor="right", y=1.0, yanchor="bottom",
            bgcolor="rgba(245,245,245,0.95)", activecolor="#d0d0d0",
            bordercolor="#cccccc", borderwidth=1, font=dict(size=10),
        ),
        row=1, col=1,
    )
    # Initial visible window. If a range is supplied (the selected timeframe),
    # use it -- zooming/panning out then reveals the rest of the loaded history.
    # Pad the right edge by ~0.6 of a bar so the latest candle isn't clipped.
    bar = (df.index[-1] - df.index[-2]) if len(df.index) >= 2 else None
    if initial_xrange is not None:
        start, end = initial_xrange
        # Fit every panel's y-axis to the initially-visible window so the chart
        # opens tight (like Yahoo) instead of auto-ranging over all history.
        _set_initial_yranges(fig, df, row_of, start, end, show_ma, show_bbands,
                             show_drawdown, show_macd)
        if bar is not None and end is not None:
            end = end + bar * 0.6
        fig.update_xaxes(range=[start, end])
    elif bar is not None:
        fig.update_xaxes(range=[df.index[0], df.index[-1] + bar * 0.6])
    return fig


def _set_initial_yranges(fig, df, row_of, start, end, show_ma, show_bbands,
                         show_drawdown, show_macd) -> None:
    """Set each panel's y-range from the data visible in [start, end]."""
    vis = df[(df.index >= start) & (df.index <= end)]
    if vis.empty:
        return

    def _pad(lo, hi):
        p = (hi - lo) * 0.06 or abs(hi) * 0.06 or 1.0
        return lo - p, hi + p

    # Price panel: candles + shown MAs + Bollinger band + running high.
    cols = ["High", "Low"]
    cols += [f"sma_{p}" for p in show_ma if f"sma_{p}" in vis.columns]
    if show_bbands:
        cols += [c for c in ("bb_upper", "bb_lower") if c in vis.columns]
    pv = vis[cols]
    lo, hi = float(pv.min().min()), float(pv.max().max())
    rh_vis = df["Close"].cummax()[(df.index >= start) & (df.index <= end)]
    if not rh_vis.empty:
        hi = max(hi, float(rh_vis.max()))
    lo, hi = _pad(lo, hi)
    fig.update_yaxes(range=[lo, hi], row=row_of["price"], col=1)

    # Volume: 0-based.
    fig.update_yaxes(range=[0, float(vis["Volume"].max()) * 1.06],
                     row=row_of["vol"], col=1)

    # Drawdown: visible minimum up to ~0.
    if show_drawdown and "dd" in row_of:
        dd_vis = (df["Close"] / df["Close"].cummax() - 1.0) * 100.0
        dd_vis = dd_vis[(df.index >= start) & (df.index <= end)]
        if not dd_vis.empty:
            ddlo = float(dd_vis.min())
            fig.update_yaxes(range=[ddlo - (abs(ddlo) * 0.06 or 1.0), 1.0],
                             row=row_of["dd"], col=1)

    # MACD.
    if show_macd and "macd" in row_of and "macd" in vis.columns:
        mc = [c for c in ("macd", "macd_signal", "macd_hist") if c in vis.columns]
        mv = vis[mc]
        mlo, mhi = _pad(float(mv.min().min()), float(mv.max().max()))
        fig.update_yaxes(range=[mlo, mhi], row=row_of["macd"], col=1)


def drawdown_chart(df: pd.DataFrame, config: Dict[str, Any]) -> go.Figure:
    """Drawdown-from-rolling-high with shaded severity zones."""
    fig = go.Figure()
    if df is None or df.empty:
        fig.update_layout(title="No data available")
        return fig

    dd = dd_mod.drawdown_series(df["Close"])
    fig.add_trace(
        go.Scatter(x=dd.index, y=dd * 100.0, name="Drawdown %",
                   fill="tozeroy", line=dict(color="#ef5350", width=1))
    )

    zones = config["drawdown_zones"]
    bands = [
        (0, zones["normal"] * 100, "rgba(46,204,113,0.10)"),
        (zones["normal"] * 100, zones["correction"] * 100, "rgba(241,196,15,0.12)"),
        (zones["correction"] * 100, zones["major"] * 100, "rgba(230,126,34,0.12)"),
        (zones["major"] * 100, min(dd.min() * 100, zones["major"] * 100) - 5, "rgba(231,76,60,0.12)"),
    ]
    for y1, y0, color in bands:
        fig.add_hrect(y0=y0, y1=y1, fillcolor=color, line_width=0, layer="below")

    fig.update_layout(
        height=260, margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="Drawdown %", hovermode="x unified", showlegend=False,
    )
    return fig


def rsi_chart(df: pd.DataFrame, config: Dict[str, Any]) -> go.Figure:
    fig = go.Figure()
    if df is None or df.empty or "rsi" not in df.columns:
        fig.update_layout(title="RSI: no data")
        return fig
    fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI",
                             line=dict(color="#7e57c2", width=1.2)))
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,83,80,0.08)", line_width=0, layer="below")
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(38,166,154,0.08)", line_width=0, layer="below")
    fig.add_hline(y=70, line=dict(color="#ef5350", width=1, dash="dash"))
    fig.add_hline(y=30, line=dict(color="#26a69a", width=1, dash="dash"))
    fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis=dict(range=[0, 100], title="RSI"),
                      hovermode="x unified", showlegend=False)
    return fig


def macd_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df is None or df.empty or "macd" not in df.columns:
        fig.update_layout(title="MACD: no data")
        return fig
    hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["macd_hist"].fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=df["macd_hist"], name="Hist",
                         marker_color=hist_colors, opacity=0.6))
    fig.add_trace(go.Scatter(x=df.index, y=df["macd"], name="MACD",
                             line=dict(color="#1f77b4", width=1.2)))
    fig.add_trace(go.Scatter(x=df.index, y=df["macd_signal"], name="Signal",
                             line=dict(color="#ff7f0e", width=1.2)))
    fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="MACD", hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0))
    return fig
