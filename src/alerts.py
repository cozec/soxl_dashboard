"""Alert engine.

Evaluates a list of conditions against the latest data and returns triggered
``Alert`` objects. Notification *delivery* is abstracted behind ``Notifier`` so
email / SMS / Telegram can be added later by implementing a subclass and
registering it -- the evaluation logic does not change.

Crossover alerts compare the last two bars to detect the bar where a level was
crossed (causal: uses only the two most recent closed observations).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from . import indicators

SEVERITY_ORDER = {"success": 0, "info": 0, "warning": 1, "critical": 2}


@dataclass
class Alert:
    key: str
    message: str
    severity: str  # "info" | "warning" | "critical"


# --------------------------------------------------------------------------
# Notifier interface (delivery channels are pluggable / added later)
# --------------------------------------------------------------------------
class Notifier:
    name = "base"

    def send(self, alert: Alert) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InAppNotifier(Notifier):
    """Default channel: collects alerts so the dashboard can render them."""

    name = "in_app"

    def __init__(self) -> None:
        self.collected: List[Alert] = []

    def send(self, alert: Alert) -> None:
        self.collected.append(alert)


# Example stubs for future channels -- left unimplemented on purpose.
class EmailNotifier(Notifier):
    name = "email"

    def send(self, alert: Alert) -> None:  # pragma: no cover
        raise NotImplementedError("Wire up SMTP / SES here.")


class TelegramNotifier(Notifier):
    name = "telegram"

    def send(self, alert: Alert) -> None:  # pragma: no cover
        raise NotImplementedError("Call the Telegram bot API here.")


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------
def _crossed_up(series: pd.Series, level: pd.Series) -> bool:
    if len(series) < 2 or len(level) < 2:
        return False
    return series.iloc[-2] <= level.iloc[-2] and series.iloc[-1] > level.iloc[-1]


def _crossed_down(series: pd.Series, level: pd.Series) -> bool:
    if len(series) < 2 or len(level) < 2:
        return False
    return series.iloc[-2] >= level.iloc[-2] and series.iloc[-1] < level.iloc[-1]


def evaluate(
    df: pd.DataFrame,
    quote: Dict[str, Any],
    risk: Dict[str, Any],
    config: Dict[str, Any],
) -> List[Alert]:
    """Return all currently-triggered alerts (most severe first)."""
    alerts: List[Alert] = []
    if df is None or df.empty:
        return alerts

    acfg = config["alerts"]
    close = df["Close"]

    # --- MA crossovers ---------------------------------------------------
    for period, sev in [(20, "info"), (50, "warning"), (200, "critical")]:
        col = f"sma_{period}"
        if col in df.columns and df[col].notna().sum() >= 2:
            ma = df[col]
            if _crossed_up(close, ma):
                alerts.append(Alert(f"cross_up_{period}",
                                    f"Price crossed ABOVE the {period}-day MA.",
                                    "info"))
            if _crossed_down(close, ma):
                alerts.append(Alert(f"cross_down_{period}",
                                    f"Price crossed BELOW the {period}-day MA.",
                                    sev))

    # --- RSI extremes ----------------------------------------------------
    if "rsi" in df.columns and df["rsi"].notna().any():
        rsi = float(df["rsi"].iloc[-1])
        if rsi > acfg["rsi_overbought"]:
            alerts.append(Alert("rsi_high", f"RSI {rsi:.0f} > {acfg['rsi_overbought']} (overbought).", "warning"))
        if rsi < acfg["rsi_oversold"]:
            alerts.append(Alert("rsi_low", f"RSI {rsi:.0f} < {acfg['rsi_oversold']} (oversold).", "warning"))

    # --- Drawdown thresholds --------------------------------------------
    dd = risk.get("current_drawdown")
    if dd is not None and dd == dd:
        for level in sorted(acfg["drawdown_levels"]):  # most negative first
            if dd <= level:
                sev = "critical" if level <= -0.25 else "warning"
                alerts.append(Alert(f"dd_{abs(int(level*100))}",
                                    f"Drawdown {dd*100:.1f}% breached the {level*100:.0f}% level.",
                                    sev))
                break  # report the worst breached level only

    # --- Volume spike ----------------------------------------------------
    if "rel_volume" in df.columns and df["rel_volume"].notna().any():
        rv = float(df["rel_volume"].iloc[-1])
        if rv >= acfg["relative_volume_spike"]:
            alerts.append(Alert("vol_spike", f"Volume is {rv:.1f}x its average.", "info"))

    # --- Daily loss ------------------------------------------------------
    move_1d = risk.get("move_1d")
    if move_1d is not None and move_1d == move_1d and move_1d <= acfg["daily_loss_threshold"]:
        alerts.append(Alert("daily_loss", f"Daily move {move_1d*100:.1f}% (loss exceeds {acfg['daily_loss_threshold']*100:.0f}%).", "critical"))

    # --- Buy-the-dip entry signal (backtested; see scripts/backtest_entry.py)
    entry = indicators.latest_entry(df)
    if entry["active"]:
        alerts.append(Alert("entry_buy_dip",
                            f"Entry signal — buy the dip: {entry['reason']}.",
                            "success"))

    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a.severity, 0), reverse=True)
    return alerts


def dispatch(alerts: List[Alert], notifiers: List[Notifier]) -> None:
    """Send each alert through every registered notifier (best-effort)."""
    for alert in alerts:
        for notifier in notifiers:
            try:
                notifier.send(alert)
            except NotImplementedError:
                continue
