"""Tests for src/notifier.py — gates, dedup, scorecard math, email rendering.

Network and SMTP are always mocked; fixture frames are synthetic.
"""
import json

import numpy as np
import pandas as pd
import pytest

from src import notifier
from src import utils


ET = "America/New_York"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def config():
    cfg = utils.load_config()
    cfg["tabs"] = [["SOXL (3x)", "SOXL"]]        # one ticker keeps tests fast
    cfg["notifier"] = dict(cfg["notifier"])
    return cfg


def _result(ticker="SOXL", stale=False, buy_dip=False, overbought=False):
    return {
        "ticker": ticker, "stale": stale, "note": "stale note" if stale else "",
        "buy_dip": buy_dip, "overbought": overbought,
        "entry_reason": "price above 200-day MA (uptrend); pulled back to the 50-day MA",
        "close": 100.0, "change_pct": -0.012, "drawdown": -0.08, "rsi": 44.0,
        "alerts": [], "scorecard": [],
    }


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture send_email calls instead of hitting SMTP."""
    calls = []

    def fake_send(subject, html, config, dry_run=False):
        calls.append({"subject": subject, "html": html, "dry_run": dry_run})
        return True

    monkeypatch.setattr(notifier, "send_email", fake_send)
    return calls


@pytest.fixture
def trading_day(monkeypatch):
    monkeypatch.setattr(utils, "trading_session",
                        lambda tz=ET, at=None: {"close": None, "early_close": False})


# A Friday well inside the check window (1pm ET).
NOW = pd.Timestamp("2026-07-17 13:00", tz=ET)


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------
def test_check_exits_on_non_trading_day(config, sent_emails, monkeypatch):
    monkeypatch.setattr(utils, "trading_session", lambda tz=ET, at=None: None)
    assert notifier.run_check(config, now=NOW) == "not_trading_day"
    assert sent_emails == []


def test_digest_exits_on_non_trading_day(config, sent_emails, monkeypatch):
    monkeypatch.setattr(utils, "trading_session", lambda tz=ET, at=None: None)
    assert notifier.run_digest(config, now=NOW) == "not_trading_day"
    assert sent_emails == []


def test_check_replay_window_guard(config, sent_emails, trading_day):
    """launchd replays missed jobs on wake — a 9pm run must NOT email."""
    late = pd.Timestamp("2026-07-17 21:00", tz=ET)
    assert notifier.run_check(config, now=late) == "past_deadline"
    assert sent_emails == []


def test_digest_allowed_after_deadline(config, sent_emails, trading_day, monkeypatch):
    """The digest reports final closed bars — sending late is fine."""
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t))
    late = pd.Timestamp("2026-07-17 21:00", tz=ET)
    assert notifier.run_digest(config, now=late) == "sent"
    assert len(sent_emails) == 1


def test_check_skips_stale_ticker(config, sent_emails, trading_day, monkeypatch):
    """Cached/stale data must never produce an alert (silent-fallback guard)."""
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t, stale=True, buy_dip=True))
    assert notifier.run_check(config, now=NOW) == "no_signals"
    assert sent_emails == []


def test_check_no_signals_no_email(config, sent_emails, trading_day, monkeypatch):
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t))
    assert notifier.run_check(config, now=NOW) == "no_signals"
    assert sent_emails == []


# --------------------------------------------------------------------------
# Signal -> email mapping + dedup
# --------------------------------------------------------------------------
def _with_state(config, tmp_path):
    config["notifier"]["state_file"] = str(tmp_path / "alert_state.json")
    return config


def test_check_emails_on_buy_dip(config, sent_emails, trading_day,
                                 monkeypatch, tmp_path):
    config = _with_state(config, tmp_path)
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t, buy_dip=True))
    assert notifier.run_check(config, now=NOW) == "sent"
    assert len(sent_emails) == 1
    assert "🟢 BUY DIP: SOXL" in sent_emails[0]["subject"]
    assert "2026-07-17" in sent_emails[0]["subject"]
    assert "pulled back to the 50-day MA" in sent_emails[0]["html"]


def test_check_emails_on_overbought(config, sent_emails, trading_day,
                                    monkeypatch, tmp_path):
    config = _with_state(config, tmp_path)
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t, overbought=True))
    assert notifier.run_check(config, now=NOW) == "sent"
    assert "🔴 OVERBOUGHT: SOXL" in sent_emails[0]["subject"]
    assert "trim/caution" in sent_emails[0]["html"]


def test_check_combined_subject(config, sent_emails, trading_day,
                                monkeypatch, tmp_path):
    config = _with_state(config, tmp_path)
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t, buy_dip=True, overbought=True))
    notifier.run_check(config, now=NOW)
    subject = sent_emails[0]["subject"]
    assert "🟢 BUY DIP: SOXL" in subject and "🔴 OVERBOUGHT: SOXL" in subject


def test_check_dedup_same_day(config, sent_emails, trading_day,
                              monkeypatch, tmp_path):
    """A second run the same day must not re-email the same signal."""
    config = _with_state(config, tmp_path)
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t, buy_dip=True))
    assert notifier.run_check(config, now=NOW) == "sent"
    assert notifier.run_check(config, now=NOW) == "no_signals"
    assert len(sent_emails) == 1
    state = json.loads((tmp_path / "alert_state.json").read_text())
    assert "SOXL:buy_dip:2026-07-17" in state["sent"]


def test_check_dry_run_does_not_record_state(config, sent_emails, trading_day,
                                             monkeypatch, tmp_path):
    config = _with_state(config, tmp_path)
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t, buy_dip=True))
    assert notifier.run_check(config, now=NOW, dry_run=True) == "sent"
    assert not (tmp_path / "alert_state.json").exists()


# --------------------------------------------------------------------------
# Digest rendering
# --------------------------------------------------------------------------
def test_digest_renders_table_and_stale_section(config, sent_emails,
                                                trading_day, monkeypatch):
    results = {"SOXL": _result("SOXL", buy_dip=True),
               "SMH": _result("SMH", stale=True)}
    config["tabs"] = [["SOXL (3x)", "SOXL"], ["SMH (1x)", "SMH"]]
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: results[t])
    assert notifier.run_digest(config, now=NOW) == "sent"
    html = sent_emails[0]["html"]
    subject = sent_emails[0]["subject"]
    assert subject.startswith("📊 Daily close: 1 signal")
    assert "🟢 BUY DIP" in html
    assert "Skipped (no live data today)" in html and "SMH" in html


def test_digest_early_close_note(config, sent_emails, monkeypatch):
    monkeypatch.setattr(utils, "trading_session",
                        lambda tz=ET, at=None: {"close": None, "early_close": True})
    monkeypatch.setattr(notifier, "evaluate_ticker",
                        lambda cfg, t, now: _result(t))
    notifier.run_digest(config, now=NOW)
    assert "Early close today" in sent_emails[0]["html"]


# --------------------------------------------------------------------------
# Scorecard math
# --------------------------------------------------------------------------
def test_scorecard_forward_returns():
    idx = pd.date_range("2026-01-01", periods=60, freq="B", tz=ET)
    close = pd.Series(np.linspace(100.0, 159.0, 60), index=idx)
    signal = pd.Series(False, index=idx)
    signal.iloc[10] = True     # 20+ bars of future -> resolved fwd20
    signal.iloc[50] = True     # only 9 bars of future -> open
    sc = notifier.build_scorecard(close, signal, sessions=60)
    assert len(sc) == 2
    resolved, open_sig = sc[0], sc[1]
    expected = close.iloc[30] / close.iloc[10] - 1.0
    assert resolved["fwd20"] == pytest.approx(expected)
    assert open_sig["fwd20"] is None
    assert open_sig["open_days"] == 9


def test_scorecard_window_excludes_old_signals():
    idx = pd.date_range("2026-01-01", periods=100, freq="B", tz=ET)
    close = pd.Series(np.full(100, 50.0), index=idx)
    signal = pd.Series(False, index=idx)
    signal.iloc[5] = True      # outside the trailing-30 window
    signal.iloc[95] = True     # inside
    sc = notifier.build_scorecard(close, signal, sessions=30)
    assert len(sc) == 1
    assert sc[0]["date"] == idx[95].date().isoformat()


# --------------------------------------------------------------------------
# Secrets / SMTP plumbing
# --------------------------------------------------------------------------
def test_load_secrets_parses_env_file(tmp_path):
    p = tmp_path / "secrets.env"
    p.write_text("# comment\nGMAIL_ADDRESS=a@b.com\nGMAIL_APP_PASSWORD = xyz \n\n")
    secrets = notifier.load_secrets(str(p))
    assert secrets == {"GMAIL_ADDRESS": "a@b.com", "GMAIL_APP_PASSWORD": "xyz"}


def test_send_email_refuses_placeholder_password(config, tmp_path, monkeypatch):
    p = tmp_path / "secrets.env"
    p.write_text("GMAIL_ADDRESS=a@b.com\n"
                 "GMAIL_APP_PASSWORD=paste-16-char-app-password-here\n")
    config["notifier"]["secrets_file"] = str(p)
    smtp_used = []
    monkeypatch.setattr(notifier.smtplib, "SMTP_SSL",
                        lambda *a, **k: smtp_used.append(1))
    assert notifier.send_email("s", "<p>x</p>", config) is False
    assert smtp_used == []


def test_send_email_uses_smtp(config, tmp_path, monkeypatch):
    p = tmp_path / "secrets.env"
    p.write_text("GMAIL_ADDRESS=a@b.com\nGMAIL_APP_PASSWORD=abcdabcdabcdabcd\n")
    config["notifier"]["secrets_file"] = str(p)
    config["notifier"]["recipient"] = "a@b.com"

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["subject"] = msg["Subject"]
            sent["to"] = msg["To"]

    monkeypatch.setattr(notifier.smtplib, "SMTP_SSL", FakeSMTP)
    assert notifier.send_email("hello", "<p>x</p>", config) is True
    assert sent["login"] == ("a@b.com", "abcdabcdabcdabcd")
    assert sent["subject"] == "hello" and sent["to"] == "a@b.com"
