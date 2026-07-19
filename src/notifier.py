"""Email notifier -- near-close signal alerts and a daily digest.

Reuses the EXACT signal functions the dashboard/backtest use (buy_dip_signal,
overbought_signal from src/indicators.py) so alert logic can never drift from
the backtested rules. See the design doc for the full rationale.

Run (scheduled via launchd, or manually):
    .venv/bin/python -m src.notifier --check    # near close: email ONLY if a signal fired
    .venv/bin/python -m src.notifier --digest   # after close: always email the summary
    .venv/bin/python -m src.notifier --digest --dry-run   # render to stdout, don't send

Guards (all causal, all logged):
  * trading-day gate  -- calendar-only check; exits silently on weekends/holidays.
  * replay-window gate -- launchd replays missed jobs on wake; --check refuses
    to email after ``notifier.check_deadline_et`` so a 9pm wake-up never sends
    a stale "near-close" alert. The digest may send late (final bars stay true).
  * freshness gate    -- load_ohlcv silently falls back to cache on fetch
    failure; a ticker whose data is not live *and dated today* is skipped,
    never alerted on.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import pandas as pd

from . import alerts as alerts_mod
from . import data_loader, indicators, risk_metrics, utils

ET = "America/New_York"
FWD_BARS = 20                       # scorecard forward-return horizon (sessions)

log = logging.getLogger("notifier")


# --------------------------------------------------------------------------
# Secrets / state / logging plumbing
# --------------------------------------------------------------------------
def load_secrets(path: str) -> Dict[str, str]:
    """Parse a KEY=VALUE env-style file (comments and blanks ignored)."""
    secrets: Dict[str, str] = {}
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return secrets
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            secrets[key.strip()] = value.strip()
    return secrets


def _abs_path(rel: str) -> str:
    if os.path.isabs(rel) or rel.startswith("~"):
        return os.path.expanduser(rel)
    return os.path.join(utils.PROJECT_ROOT, rel)


def _load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {"sent": []}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state["sent"] = state.get("sent", [])[-500:]     # keep the file bounded
    with open(path, "w") as fh:
        json.dump(state, fh, indent=1)


def _setup_logging(log_file: str) -> None:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stderr)],
    )


# --------------------------------------------------------------------------
# Per-ticker evaluation (the dashboard's own code path, headless)
# --------------------------------------------------------------------------
def evaluate_ticker(config: Dict[str, Any], ticker: str,
                    today: "pd.Timestamp") -> Dict[str, Any]:
    """Load 2y of daily bars and evaluate signals for one ticker.

    Returns a dict with either ``stale=True`` (skip: could not get live data
    dated today) or the evaluated payload. 2y (not 1y) so sma_200 is warm
    across the whole scorecard window.
    """
    cfg = dict(config)
    cfg["ticker"] = ticker
    res = data_loader.load_ohlcv(cfg, "2y", "1d")
    df = res.df
    if df is None or df.empty:
        return {"ticker": ticker, "stale": True, "note": res.note or "no data"}
    last_bar_day = df.index[-1].date()
    if not res.is_live or last_bar_day != today.date():
        return {"ticker": ticker, "stale": True,
                "note": f"is_live={res.is_live}, last_bar={last_bar_day} "
                        f"(today={today.date()}); {res.note}"}

    full = indicators.compute_all(df, cfg, intraday=False)
    buy_dip = bool(indicators.buy_dip_signal(full).iloc[-1])
    overbought = bool(indicators.overbought_signal(full).iloc[-1])
    entry = indicators.latest_entry(full)
    quote = res.quote or {}
    risk = risk_metrics.compute_risk(full, quote, cfg)
    triggered = alerts_mod.evaluate(full, quote, risk, cfg)

    close = float(full["Close"].iloc[-1])
    prev = float(full["Close"].iloc[-2]) if len(full) >= 2 else close
    return {
        "ticker": ticker,
        "stale": False,
        "buy_dip": buy_dip,
        "overbought": overbought,
        "entry_reason": entry.get("reason", ""),
        "close": close,
        "change_pct": close / prev - 1.0,
        "drawdown": risk.get("current_drawdown"),
        "rsi": float(full["rsi"].iloc[-1]) if "rsi" in full else float("nan"),
        "alerts": [a.message for a in triggered],
        "scorecard": build_scorecard(full["Close"],
                                     indicators.buy_dip_signal(full),
                                     config["notifier"]["scorecard_sessions"]),
    }


OVERBOUGHT_REASON = ("crossed above upper Bollinger Band with RSI > 75 — "
                     "trim/caution, not a hard sell")


def build_scorecard(close: pd.Series, signal: pd.Series,
                    sessions: int) -> List[Dict[str, Any]]:
    """Replay *signal* over the trailing *sessions* bars.

    For each signal date: close at signal and the +20-session forward return,
    or ``None`` (rendered as "open") when fewer than 20 bars have elapsed.
    Uses the same building blocks as scripts/backtest_entry.py.
    """
    out: List[Dict[str, Any]] = []
    if signal is None or signal.empty:
        return out
    window = signal.iloc[-sessions:]
    for ts in window.index[window.values]:
        i = signal.index.get_loc(ts)
        entry_close = float(close.iloc[i])
        fwd = None
        if i + FWD_BARS < len(close):
            fwd = float(close.iloc[i + FWD_BARS] / entry_close - 1.0)
        out.append({"date": ts.date().isoformat(), "close": entry_close,
                    "fwd20": fwd,
                    "open_days": None if fwd is not None else len(close) - 1 - i})
    return out


# --------------------------------------------------------------------------
# Email rendering
# --------------------------------------------------------------------------
_STYLE = ("font-family:-apple-system,Helvetica,Arial,sans-serif;"
          "font-size:14px;color:#222")
_TH = ("text-align:left;padding:4px 10px;border-bottom:2px solid #444;"
       "font-size:12px;color:#666")
_TD = "padding:4px 10px;border-bottom:1px solid #ddd"


def _fmt_fwd(sc: Dict[str, Any]) -> str:
    if sc["fwd20"] is None:
        return f"open ({sc['open_days']}d)"
    return utils.fmt_pct(sc["fwd20"])


def render_check_email(fired: List[Dict[str, Any]],
                       today: "pd.Timestamp") -> (str, str):
    """Subject + HTML body for the near-close signal alert."""
    dips = [f["ticker"] for f in fired if f["kind"] == "buy_dip"]
    obs = [f["ticker"] for f in fired if f["kind"] == "overbought"]
    parts = []
    if dips:
        parts.append(f"🟢 BUY DIP: {', '.join(dips)}")
    if obs:
        parts.append(f"🔴 OVERBOUGHT: {', '.join(obs)}")
    subject = " · ".join(parts) + f" — {today.date().isoformat()}"

    rows = "".join(
        f"<li><b>{f['ticker']}</b> — "
        f"{'🟢 Buy dip' if f['kind'] == 'buy_dip' else '🔴 Overbought'}: "
        f"{f['reason']} (close {utils.fmt_price(f['close'])})</li>"
        for f in fired)
    html = (f"<div style='{_STYLE}'>"
            f"<p>Signal(s) on the nearly-final daily bar "
            f"({today.strftime('%Y-%m-%d %H:%M %Z')}). Bars are ~99% formed; "
            f"the after-close digest reports the final truth.</p>"
            f"<ul>{rows}</ul>"
            f"<p style='color:#666'>Rules are the exact backtested functions in "
            f"src/indicators.py (see summary.md for the event study).</p></div>")
    return subject, html


def render_digest_email(results: List[Dict[str, Any]], today: "pd.Timestamp",
                        early_close: bool) -> (str, str):
    """Subject + HTML body for the always-sent daily digest."""
    live = [r for r in results if not r["stale"]]
    stale = [r for r in results if r["stale"]]
    n_signals = sum(1 for r in live if r["buy_dip"] or r["overbought"])
    lead = ""
    if live:
        worst = min(live, key=lambda r: r["change_pct"])
        lead = f", {worst['ticker']} {utils.fmt_pct(worst['change_pct'])}"
    subject = (f"📊 Daily close: {n_signals} signal"
               f"{'' if n_signals == 1 else 's'}{lead} — {today.date().isoformat()}")

    rows = ""
    for r in live:
        sig = []
        if r["buy_dip"]:
            sig.append("🟢 BUY DIP")
        if r["overbought"]:
            sig.append("🔴 OVERBOUGHT")
        rows += (f"<tr><td style='{_TD}'><b>{r['ticker']}</b></td>"
                 f"<td style='{_TD}'>{utils.fmt_price(r['close'])}</td>"
                 f"<td style='{_TD}'>{utils.fmt_pct(r['change_pct'])}</td>"
                 f"<td style='{_TD}'>{utils.fmt_pct(r['drawdown'])}</td>"
                 f"<td style='{_TD}'>{r['rsi']:.0f}</td>"
                 f"<td style='{_TD}'>{' '.join(sig) or '—'}</td></tr>")

    sc_rows = ""
    for r in live:
        for sc in r["scorecard"]:
            sc_rows += (f"<tr><td style='{_TD}'>{sc['date']}</td>"
                        f"<td style='{_TD}'>{r['ticker']}</td>"
                        f"<td style='{_TD}'>{utils.fmt_price(sc['close'])}</td>"
                        f"<td style='{_TD}'>{_fmt_fwd(sc)}</td></tr>")
    scorecard_html = ("<p>No buy-dip signals in the trailing window.</p>"
                      if not sc_rows else
                      f"<table style='border-collapse:collapse'>"
                      f"<tr><th style='{_TH}'>Signal date</th>"
                      f"<th style='{_TH}'>Ticker</th><th style='{_TH}'>Close</th>"
                      f"<th style='{_TH}'>Fwd 20d</th></tr>{sc_rows}</table>")

    stale_html = ""
    if stale:
        items = "".join(f"<li>{r['ticker']}: {r['note']}</li>" for r in stale)
        stale_html = (f"<p style='color:#b00'>⚠️ Skipped (no live data today):"
                      f"</p><ul style='color:#b00'>{items}</ul>")

    alert_lines = []
    for r in live:
        for msg in r["alerts"]:
            alert_lines.append(f"<li><b>{r['ticker']}</b>: {msg}</li>")
    alerts_html = (f"<h3>Alerts</h3><ul>{''.join(alert_lines)}</ul>"
                   if alert_lines else "")

    early = ("<p><i>Early close today (holiday half-day).</i></p>"
             if early_close else "")
    html = (f"<div style='{_STYLE}'>{early}"
            f"<table style='border-collapse:collapse'>"
            f"<tr><th style='{_TH}'>Ticker</th><th style='{_TH}'>Close</th>"
            f"<th style='{_TH}'>Change</th><th style='{_TH}'>Drawdown</th>"
            f"<th style='{_TH}'>RSI</th><th style='{_TH}'>Signals</th></tr>"
            f"{rows}</table>"
            f"{alerts_html}"
            f"<h3>Buy-dip scorecard (trailing window)</h3>"
            f"{scorecard_html}{stale_html}"
            f"<p style='color:#666'>Generated by src/notifier.py at "
            f"{today.strftime('%Y-%m-%d %H:%M %Z')}.</p></div>")
    return subject, html


def send_email(subject: str, html: str, config: Dict[str, Any],
               dry_run: bool = False) -> bool:
    """Send via Gmail SMTP (SSL). Returns True if sent (or dry-run printed)."""
    if dry_run:
        print(f"=== DRY RUN — email NOT sent ===\nSubject: {subject}\n\n{html}")
        return True
    ncfg = config["notifier"]
    secrets = load_secrets(ncfg["secrets_file"])
    sender = secrets.get("GMAIL_ADDRESS")
    password = secrets.get("GMAIL_APP_PASSWORD", "")
    if not sender or not password or "paste" in password:
        log.error("No usable Gmail credentials in %s — email not sent.",
                  ncfg["secrets_file"])
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ncfg["recipient"] or sender
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    log.info("Sent: %s", subject)
    return True


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------
def _parse_deadline(now: "pd.Timestamp", hhmm: str) -> "pd.Timestamp":
    hour, minute = (int(x) for x in hhmm.split(":"))
    return now.normalize() + pd.Timedelta(hours=hour, minutes=minute)


def run_check(config: Dict[str, Any], now: Optional[pd.Timestamp] = None,
              dry_run: bool = False) -> str:
    """Near-close signal check. Emails ONLY if a fresh signal fired."""
    now = now if now is not None else pd.Timestamp.now(tz=ET)
    session = utils.trading_session(ET, at=now)
    if session is None:
        log.info("check: not a trading day — exit.")
        return "not_trading_day"
    deadline = _parse_deadline(now, config["notifier"]["check_deadline_et"])
    if now > deadline:
        log.info("check: past deadline %s (launchd replay?) — exit.", deadline)
        return "past_deadline"

    ncfg = config["notifier"]
    state_path = _abs_path(ncfg["state_file"])
    state = _load_state(state_path)
    fired: List[Dict[str, Any]] = []
    for _, ticker in config["tabs"]:
        r = evaluate_ticker(config, ticker, now)
        if r["stale"]:
            log.warning("check: %s skipped — %s", ticker, r["note"])
            continue
        for kind, active, reason in [
            ("buy_dip", r["buy_dip"], r["entry_reason"]),
            ("overbought", r["overbought"], OVERBOUGHT_REASON),
        ]:
            if kind not in ncfg["signals"] or not active:
                continue
            key = f"{ticker}:{kind}:{now.date().isoformat()}"
            if key in state.get("sent", []):
                log.info("check: %s already alerted today — dedup.", key)
                continue
            fired.append({"ticker": ticker, "kind": kind, "reason": reason,
                          "close": r["close"], "key": key})

    if not fired:
        log.info("check: no new signals — no email.")
        return "no_signals"
    subject, html = render_check_email(fired, now)
    if send_email(subject, html, config, dry_run) and not dry_run:
        state.setdefault("sent", []).extend(f["key"] for f in fired)
        _save_state(state_path, state)
    return "sent"


def run_digest(config: Dict[str, Any], now: Optional[pd.Timestamp] = None,
               dry_run: bool = False) -> str:
    """After-close digest. Always emails on trading days (heartbeat)."""
    now = now if now is not None else pd.Timestamp.now(tz=ET)
    session = utils.trading_session(ET, at=now)
    if session is None:
        log.info("digest: not a trading day — exit.")
        return "not_trading_day"
    results = [evaluate_ticker(config, t, now) for _, t in config["tabs"]]
    subject, html = render_digest_email(results, now, session["early_close"])
    send_email(subject, html, config, dry_run)
    return "sent"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="near-close: email only if a signal fired")
    mode.add_argument("--digest", action="store_true",
                      help="after close: always email the daily summary")
    parser.add_argument("--dry-run", action="store_true",
                        help="render the email to stdout instead of sending")
    args = parser.parse_args(argv)

    config = utils.load_config()
    _setup_logging(_abs_path(config["notifier"]["log_file"]))
    try:
        outcome = (run_check if args.check else run_digest)(
            config, dry_run=args.dry_run)
        log.info("outcome: %s", outcome)
        return 0
    except Exception:
        log.exception("notifier failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
