import numpy as np
import pandas as pd
import pytest

from src import drawdown as dd


def test_drawdown_example_from_spec():
    # Spec: high 70, current 42 -> -40%.
    price = pd.Series([70.0, 60.0, 42.0])
    assert dd.current_drawdown(price) == pytest.approx(-0.40)


def test_drawdown_series_non_positive():
    price = pd.Series([10, 12, 11, 15, 9, 20], dtype=float)
    series = dd.drawdown_series(price)
    assert (series <= 1e-12).all()


def test_drawdown_zero_at_new_high():
    price = pd.Series([10, 11, 12, 13], dtype=float)
    assert dd.current_drawdown(price) == pytest.approx(0.0)


def test_max_drawdown():
    price = pd.Series([100, 50, 75, 25, 60], dtype=float)
    # Running max 100; lowest point 25 -> -75%.
    assert dd.max_drawdown(price) == pytest.approx(-0.75)


def test_classify_zone():
    zones = {"normal": -0.10, "correction": -0.25, "major": -0.50}
    assert dd.classify_zone(-0.05, zones) == "normal"
    assert dd.classify_zone(-0.15, zones) == "correction"
    assert dd.classify_zone(-0.40, zones) == "major"
    assert dd.classify_zone(-0.60, zones) == "crash"


def test_no_lookahead_drawdown():
    price = pd.Series(np.arange(1, 30, dtype=float))
    base = dd.drawdown_series(price)
    price2 = price.copy()
    price2.iloc[25] = 0.1  # crash in the future
    modified = dd.drawdown_series(price2)
    assert base.iloc[10] == pytest.approx(modified.iloc[10])


def test_drawdown_summary():
    idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="America/New_York")
    df = pd.DataFrame({
        "Open": [10, 12, 14, 13, 9],
        "High": [11, 13, 15, 14, 10],
        "Low": [9, 11, 13, 12, 8],
        "Close": [10, 12, 14, 13, 9],
        "Volume": [100, 100, 100, 100, 100],
    }, index=idx)
    quote = {"price": 9.0, "high_52w": 15.0}
    s = dd.drawdown_summary(df, quote)
    assert s["period_high"] == 15.0
    assert s["drop_from_52w_high"] == pytest.approx(9.0 / 15.0 - 1)
    assert s["current_drawdown"] == pytest.approx(9.0 / 14.0 - 1)
