import numpy as np
import pandas as pd
import pytest

from src import risk_metrics as rm
from src import utils


@pytest.fixture
def price():
    rng = np.random.RandomState(42)
    rets = rng.normal(0, 0.03, 300)
    return pd.Series(100 * np.cumprod(1 + rets))


def test_period_move(price):
    assert rm.period_move(price, 1) == pytest.approx(price.iloc[-1] / price.iloc[-2] - 1)


def test_period_move_insufficient():
    assert np.isnan(rm.period_move(pd.Series([1.0]), 5))


def test_annualized_vol_positive(price):
    assert rm.annualized_vol(price, 20) > 0


def test_historical_var_positive(price):
    var = rm.historical_var(price, 0.95)
    assert var > 0


def test_var_quantile_meaning():
    # With known returns, 95% VaR == -5th percentile.
    rets = pd.Series(np.linspace(-0.1, 0.1, 101))
    price = pd.Series(100 * np.cumprod(1 + rets.values))
    var = rm.historical_var(price, 0.95)
    realized = price.pct_change().dropna()
    expected = -np.quantile(realized, 0.05)
    assert var == pytest.approx(expected, abs=1e-6)


def test_worst_n_day_loss(price):
    w5 = rm.worst_n_day_loss(price, 5)
    rolling = price / price.shift(5) - 1
    assert w5 == pytest.approx(rolling.min())


def test_gap_from_prev_close():
    quote = {"prev_close": 100.0, "open": 95.0}
    assert rm.gap_from_prev_close(quote) == pytest.approx(-0.05)


def test_compute_risk_keys(price):
    idx = pd.date_range("2023-01-01", periods=len(price), freq="D", tz="America/New_York")
    df = pd.DataFrame({
        "Open": price.values, "High": price.values * 1.01,
        "Low": price.values * 0.99, "Close": price.values,
        "Volume": np.full(len(price), 1e6),
    }, index=idx)
    cfg = utils.load_config()
    quote = {"prev_close": float(price.iloc[-2]), "open": float(price.iloc[-1])}
    risk = rm.compute_risk(df, quote, cfg)
    for key in ["move_1d", "vol_20d", "var_95_1d", "worst_5d", "max_drawdown",
                "current_drawdown", "gap_from_prev_close"]:
        assert key in risk
