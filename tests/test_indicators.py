import numpy as np
import pandas as pd
import pytest

from src import indicators as ind


@pytest.fixture
def price():
    # Deterministic, gently trending series.
    return pd.Series(np.linspace(10, 20, 100) + np.sin(np.arange(100)) * 0.5)


@pytest.fixture
def ohlcv():
    n = 120
    close = pd.Series(np.linspace(10, 20, n) + np.sin(np.arange(n)) * 0.5)
    high = close + 0.5
    low = close - 0.5
    open_ = close.shift(1).fillna(close.iloc[0])
    vol = pd.Series(np.random.RandomState(0).randint(1e5, 1e6, n).astype(float))
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="America/New_York")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                         "Close": close, "Volume": vol}, index=idx)


def test_sma_matches_manual(price):
    result = ind.sma(price, 5)
    assert np.isnan(result.iloc[3])           # not enough data yet
    assert result.iloc[4] == pytest.approx(price.iloc[:5].mean())


def test_rsi_bounds(price):
    rsi = ind.rsi(price, 14).dropna()
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_rsi_all_up_is_100():
    s = pd.Series(np.arange(1, 50, dtype=float))  # strictly increasing
    rsi = ind.rsi(s, 14).dropna()
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_all_down_is_0():
    s = pd.Series(np.arange(50, 1, -1, dtype=float))
    rsi = ind.rsi(s, 14).dropna()
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_macd_hist_is_macd_minus_signal(price):
    m = ind.macd(price)
    assert (m["hist"] - (m["macd"] - m["signal"])).abs().max() < 1e-9


def test_atr_positive(ohlcv):
    atr = ind.atr(ohlcv, 14).dropna()
    assert (atr > 0).all()


def test_roc(price):
    r = ind.roc(price, 1)
    expected = price.iloc[1] / price.iloc[0] - 1
    assert r.iloc[1] == pytest.approx(expected)


def test_bollinger_band_ordering(price):
    bb = ind.bollinger_bands(price, 20, 2.0).dropna()
    assert (bb["bb_upper"] >= bb["bb_mid"]).all()
    assert (bb["bb_mid"] >= bb["bb_lower"]).all()


def test_vwap_resets_per_day():
    idx = pd.date_range("2024-01-01 09:30", periods=4, freq="1h", tz="America/New_York")
    idx = idx.append(pd.date_range("2024-01-02 09:30", periods=2, freq="1h", tz="America/New_York"))
    df = pd.DataFrame({
        "High": [10, 11, 12, 13, 20, 21],
        "Low": [9, 10, 11, 12, 19, 20],
        "Close": [9.5, 10.5, 11.5, 12.5, 19.5, 20.5],
        "Volume": [100, 100, 100, 100, 100, 100],
    }, index=idx)
    vwap = ind.vwap(df)
    # First bar of each day equals that bar's typical price.
    assert vwap.iloc[0] == pytest.approx((10 + 9 + 9.5) / 3)
    assert vwap.iloc[4] == pytest.approx((20 + 19 + 19.5) / 3)


def test_relative_volume(ohlcv):
    rv = ind.relative_volume(ohlcv["Volume"], 20).dropna()
    assert (rv > 0).all()


def test_no_lookahead_sma():
    # Changing a future value must not alter a past SMA value.
    s = pd.Series(np.arange(50, dtype=float))
    base = ind.sma(s, 10)
    s2 = s.copy()
    s2.iloc[40] = 999
    modified = ind.sma(s2, 10)
    assert base.iloc[30] == pytest.approx(modified.iloc[30])


def test_compute_all_columns(ohlcv):
    from src import utils
    cfg = utils.load_config()
    out = ind.compute_all(ohlcv, cfg, intraday=False)
    for col in ["sma_20", "rsi", "macd", "atr", "bb_width", "rel_volume", "obv", "roc_20"]:
        assert col in out.columns
