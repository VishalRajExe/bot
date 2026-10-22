"""Hermetic tests for the shared strategy-family library (app/indicators/families.py).

Pure, synthetic, no network / no bot / no orders. Covers:
  * param resolution (defaults + registry overrides, unknown family);
  * each family adds its indicator columns and emits NaN-safe boolean masks;
  * CAUSALITY: every family is prefix-invariant (a signal at bar t is unchanged when
    future bars are removed) -> no lookahead / recursive bias;
  * functional triggers for the constructible families (momentum cross, bb squeeze
    breakout) and specificity (wrong regime -> no entry) for trend/divergence families.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from indicators import families  # noqa: E402


def _ohlc(closes, volumes=None, spread=0.5) -> pd.DataFrame:
    closes = [float(c) for c in closes]
    n = len(closes)
    vols = [100.0] * n if volumes is None else [float(v) for v in volumes]
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(closes)
    return pd.DataFrame({
        "date": idx,
        "open": close.shift(1).fillna(close.iloc[0]).to_numpy(),
        "high": (close + spread).to_numpy(),
        "low": (close - spread).to_numpy(),
        "close": close.to_numpy(),
        "volume": vols,
    }).set_index("date")


def _random_ohlc(n=320, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1.0, size=n)
    closes = 100 + np.cumsum(steps)
    closes = np.clip(closes, 5, None)
    vols = rng.uniform(50, 500, size=n)
    return _ohlc(list(closes), list(vols))


# ---- param resolution -------------------------------------------------------

def test_params_for_merges_defaults_and_overrides():
    p = families.params_for("momentum_ema_vol", {"momentum": {"ema_fast": 5}})
    assert p["ema_fast"] == 5 and p["ema_slow"] == 21 and p["vol_window"] == 20
    p2 = families.params_for("bb_squeeze", {"bb_squeeze": {"squeeze_pct": 0.1}})
    assert p2["squeeze_pct"] == 0.1 and p2["bb_period"] == 20
    assert families.params_for("nope", {}) == {}


def test_unknown_family_is_safe():
    df = _random_ohlc(40)
    assert families.add_indicators(df.copy(), "nope", {}) is not None
    assert families.entry_mask(df, "nope", {}).sum() == 0
    assert families.exit_mask(df, "nope", {}).sum() == 0
    assert families.tags("nope") == ("", "")


# ---- indicator columns ------------------------------------------------------

def test_each_family_adds_its_columns():
    df = _random_ohlc(320)
    expected = {
        "momentum_ema_vol": {"ema_fast", "ema_slow", "vol_ma"},
        "rsi_divergence": {"rsi", "price_new_low", "rsi_higher", "price_new_high", "rsi_lower"},
        "bb_squeeze": {"bb_upper", "bb_mid", "bb_lower", "bb_width", "bb_squeeze", "vol_ma"},
        "link_trend": {"ema_fast", "ema_slow", "rsi", "adx", "atr"},
    }
    for fam, cols in expected.items():
        out = families.add_indicators(df.copy(), fam, families.params_for(fam, {}))
        assert cols <= set(out.columns), fam


def test_masks_are_bool_and_nan_safe():
    df = _random_ohlc(320)
    for fam in families.FAMILIES:
        p = families.params_for(fam, {})
        ind = families.add_indicators(df.copy(), fam, p)
        e = families.entry_mask(ind, fam, p)
        x = families.exit_mask(ind, fam, p)
        assert e.dtype == bool and x.dtype == bool, fam
        assert not e.isna().any() and not x.isna().any(), fam
        assert len(e) == len(df) and len(x) == len(df), fam


# ---- causality (no lookahead) ----------------------------------------------

def _assert_prefix_invariant(fam, df, params, k=25):
    ind_full = families.add_indicators(df.copy(), fam, params)
    e_full = families.entry_mask(ind_full, fam, params)
    x_full = families.exit_mask(ind_full, fam, params)
    pre = df.iloc[:-k].copy()
    ind_pre = families.add_indicators(pre, fam, params)
    e_pre = families.entry_mask(ind_pre, fam, params)
    x_pre = families.exit_mask(ind_pre, fam, params)
    assert e_pre.tolist() == e_full.iloc[:-k].tolist(), f"{fam} entry uses future data"
    assert x_pre.tolist() == x_full.iloc[:-k].tolist(), f"{fam} exit uses future data"


def test_all_families_are_causal():
    df = _random_ohlc(360, seed=7)
    for fam in families.FAMILIES:
        _assert_prefix_invariant(fam, df, families.params_for(fam, {}))


# ---- functional triggers ----------------------------------------------------

def test_momentum_cross_up_and_down():
    down = np.linspace(100, 80, 25)
    up = np.linspace(80, 120, 30)
    down2 = np.linspace(120, 95, 25)
    closes = list(down) + list(up) + list(down2)
    vols = [100.0] * len(down) + [1000.0] * len(up) + [100.0] * len(down2)
    df = _ohlc(closes, vols)
    p = families.params_for("momentum_ema_vol", {})
    ind = families.add_indicators(df.copy(), "momentum_ema_vol", p)
    assert families.entry_mask(ind, "momentum_ema_vol", p).sum() >= 1
    assert families.exit_mask(ind, "momentum_ema_vol", p).sum() >= 1


def test_momentum_needs_volume_surge():
    down = np.linspace(100, 80, 25)
    up = np.linspace(80, 120, 30)
    closes = list(down) + list(up)
    flat_vol = [100.0] * len(closes)          # no bar exceeds its rolling mean
    df = _ohlc(closes, flat_vol)
    p = families.params_for("momentum_ema_vol", {})
    ind = families.add_indicators(df.copy(), "momentum_ema_vol", p)
    assert families.entry_mask(ind, "momentum_ema_vol", p).sum() == 0


def test_bb_squeeze_breakout_fires_and_flat_does_not():
    # 200 exactly-flat bars collapse the Bollinger bandwidth to 0 (a guaranteed squeeze),
    # then a single breakout bar closes above the upper band on a volume surge.
    flat = [100.0] * 200
    closes = flat + [106.0]
    vols = [100.0] * 200 + [5000.0]
    df = _ohlc(closes, vols)
    p = families.params_for("bb_squeeze", {"bb_squeeze": {"squeeze_lookback": 100}})
    ind = families.add_indicators(df.copy(), "bb_squeeze", p)
    assert bool(ind["bb_squeeze"].iloc[:200].any())            # a squeeze existed
    assert families.entry_mask(ind, "bb_squeeze", p).sum() >= 1  # breakout entry

    # specificity: a purely flat series with no breakout never enters
    flat_only = _ohlc(flat, [100.0] * 200)
    ind2 = families.add_indicators(flat_only.copy(), "bb_squeeze", p)
    assert families.entry_mask(ind2, "bb_squeeze", p).sum() == 0


def test_link_trend_requires_uptrend():
    # a monotonic downtrend must not produce trend-continuation entries
    dn = np.linspace(150, 60, 300)
    df = _ohlc(list(dn))
    p = families.params_for("link_trend", {})
    ind = families.add_indicators(df.copy(), "link_trend", p)
    assert families.entry_mask(ind, "link_trend", p).sum() == 0
    # in a sustained uptrend the fast EMA sits above the slow EMA (trend detected)
    up = np.linspace(60, 200, 300)
    ind2 = families.add_indicators(_ohlc(list(up)).copy(), "link_trend", p)
    tail = ind2.iloc[-50:]
    assert (tail["ema_fast"] > tail["ema_slow"]).all()


def test_rsi_divergence_no_entry_in_uptrend():
    up = np.linspace(60, 200, 300)
    df = _ohlc(list(up))
    p = families.params_for("rsi_divergence", {})
    ind = families.add_indicators(df.copy(), "rsi_divergence", p)
    # a clean uptrend is never oversold, so the bullish-divergence entry stays silent
    assert families.entry_mask(ind, "rsi_divergence", p).sum() == 0
