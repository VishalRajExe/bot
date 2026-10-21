"""Strategy correctness tests (BtcZScore) — no broker, no orders, deterministic."""
from __future__ import annotations

import types

import numpy as np
import pandas as pd
import pytest

from BtcZScore import BtcZScore


def _stub():
    return types.SimpleNamespace(
        zscore_period=BtcZScore.zscore_period,
        bull_threshold=BtcZScore.bull_threshold,
        exit_threshold=BtcZScore.exit_threshold,
    )


def _df(closes, volume=1.0):
    n = len(closes)
    v = volume if not np.isscalar(volume) else [volume] * n
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": list(closes),
        "volume": list(v),
    })


def _signals(df):
    s = _stub()
    d = BtcZScore.populate_indicators(s, df.copy(), {})
    d = BtcZScore.populate_entry_trend(s, d, {})
    d = BtcZScore.populate_exit_trend(s, d, {})
    return d


def test_startup_candle_count_is_converged():
    assert BtcZScore.startup_candle_count == 400
    assert BtcZScore.startup_candle_count > BtcZScore.zscore_period


def test_ema_std_warmup_produces_nan_early():
    closes = [100 + (i % 3) for i in range(300)]  # deterministic varying series
    ind = BtcZScore.populate_indicators(_stub(), _df(closes), {})
    # rolling(65) leaves the first zscore_period-1 std values undefined
    assert ind["zscore"].isna().head(BtcZScore.zscore_period - 1).all()
    assert not ind["zscore"].iloc[BtcZScore.zscore_period:].isna().all()


def test_zero_variance_yields_no_signal():
    closes = [100.0] * 200  # std == 0 everywhere
    d = _signals(_df(closes))
    assert int((d["enter_long"] == 1).sum()) == 0
    assert int((d["exit_long"] == 1).sum()) == 0


def test_deterministic_repeat():
    closes = [100 + (i % 4) for i in range(250)]
    a = _signals(_df(closes))
    b = _signals(_df(closes))
    pd.testing.assert_series_equal(a["enter_long"].fillna(0), b["enter_long"].fillna(0))
    pd.testing.assert_series_equal(a["exit_long"].fillna(0), b["exit_long"].fillna(0))


def test_bullish_cross_creates_entry():
    # Declining baseline keeps zscore negative, so the first spike bar is a clean
    # cross_up above bull_threshold — the entry must land exactly on that bar.
    closes = [float(c) for c in range(140, 60, -1)]   # 80 steadily-declining bars
    spike_idx = len(closes)
    closes = closes + [220.0, 225.0, 230.0]          # sharp sustained jump
    d = _signals(_df(closes))
    assert d.loc[spike_idx, "z_cross_up"] == 1
    assert d.loc[spike_idx, "enter_long"] == 1


def test_bearish_cross_creates_exit_from_real_data():
    # Rising baseline (zscore high) then a collapse -> a fresh cross_dn <= exit_threshold.
    closes = [float(c) for c in range(60, 140)]      # 80 steadily-rising bars
    dip_idx = len(closes)
    closes = closes + [20.0, 18.0, 15.0]             # sharp sustained drop
    d = _signals(_df(closes))
    assert d.loc[dip_idx, "z_cross_dn"] == 1
    assert d.loc[dip_idx, "exit_long"] == 1


def test_entry_requires_volume():
    # entry rule is a pure function of z_cross_up & volume — test the wiring directly
    s = _stub()
    df = pd.DataFrame({"z_cross_up": [1, 1, 0], "volume": [0.0, 5.0, 3.0]})
    out = BtcZScore.populate_entry_trend(s, df.copy(), {})
    assert out.loc[0, "enter_long"] != 1        # cross but zero volume
    assert out.loc[1, "enter_long"] == 1        # cross with volume
    assert out.loc[2, "enter_long"] != 1


def test_bearish_cross_creates_exit():
    s = _stub()
    df = pd.DataFrame({"z_cross_dn": [0, 1, 0]})
    out = BtcZScore.populate_exit_trend(s, df.copy(), {})
    assert out.loc[1, "exit_long"] == 1
    assert out.loc[0, "exit_long"] != 1


def test_no_lookahead_append_invariance():
    """Signals on a prefix must be identical whether or not future candles exist."""
    rng = np.random.RandomState(7)
    closes = list(100 + rng.randn(200).cumsum() * 0.1)
    n = 150
    base = _signals(_df(closes[:n]))
    full = _signals(_df(closes))
    # z-score and entry/exit for the shared prefix are unchanged by appended future rows
    pd.testing.assert_series_equal(
        base["zscore"].reset_index(drop=True),
        full["zscore"].iloc[:n].reset_index(drop=True), check_names=False)
    pd.testing.assert_series_equal(
        base["enter_long"].fillna(0).reset_index(drop=True),
        full["enter_long"].fillna(0).iloc[:n].reset_index(drop=True), check_names=False)


def test_invalid_input_nan_close_no_raise():
    closes = [100 + (i % 3) for i in range(120)]
    df = _df(closes)
    df.loc[80, "close"] = np.nan
    d = _signals(df)  # must not raise
    assert d.loc[80, "enter_long"] != 1
