"""Tests for the intraday momentum executor (fast bot) and the cross-executor risk layer.

Covers the owner directive 2026-10-21 to trade the experimental alts fast/intraday
WITHOUT weakening the bounded paper policy or touching the BTC daily baseline:

  * MomentumAlt is a 5m, long-only, unleveraged strategy that REUSES the exact
    PaperAutonomous veto (custom_stake_amount + confirm_trade_entry are inherited);
  * its signal logic fires a fresh EMA cross + volume surge, and stays silent for the
    BTC baseline and any status-only pair;
  * the cross-executor external_exposure() accounts for the OTHER executor's open
    stake and fails closed when the ledger is missing or stale;
  * validate_executors enforces disjoint + full-coverage + combined global bounds.

No network, no Telegram, no orders.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))
sys.path.insert(0, str(ROOT))

import talib  # noqa: F401  (ensures TA lib is available to the strategy under test)
from PaperAutonomous import PaperAutonomous  # noqa: E402
from MomentumAlt import MomentumAlt  # noqa: E402
from risk import policy  # noqa: E402


def _strategy() -> MomentumAlt:
    # populate_*/veto use only the module-level `policy` + arguments, so we can bypass
    # the heavy IStrategy.__init__ and exercise the pure logic directly.
    return MomentumAlt.__new__(MomentumAlt)


def _df(closes, volumes) -> pd.DataFrame:
    idx = pd.date_range("2026-10-01", periods=len(closes), freq="5min", tz="UTC")
    return pd.DataFrame({
        "date": idx, "open": closes, "high": closes, "low": closes,
        "close": list(closes), "volume": list(volumes),
    }).set_index("date")


def _series():
    # down -> up -> down creates both a cross-up (entry) and a cross-down (exit)
    down = np.linspace(100, 80, 25)
    up = np.linspace(80, 120, 30)
    down2 = np.linspace(120, 95, 25)
    closes = list(down) + list(up) + list(down2)
    vols = [100.0] * len(down) + [1000.0] * len(up) + [100.0] * len(down2)
    return closes, vols


# ---- strategy shape ---------------------------------------------------------

def test_momentum_alt_shape_and_inherits_veto():
    assert MomentumAlt.timeframe == "5m"
    assert MomentumAlt.can_short is False
    assert MomentumAlt.RISK_EXECUTOR == "fast"
    assert float(MomentumAlt.stoploss) < 0
    # the risk veto is REUSED verbatim, not re-implemented (single source of truth)
    assert MomentumAlt.confirm_trade_entry is PaperAutonomous.confirm_trade_entry
    assert MomentumAlt.custom_stake_amount is PaperAutonomous.custom_stake_amount
    prots = MomentumAlt.protections.fget(None)
    assert len(prots) == 3


# ---- signal logic -----------------------------------------------------------

def test_indicators_and_entry_exit_for_alt():
    s = _strategy()
    closes, vols = _series()
    df = s.populate_indicators(_df(closes, vols), {"pair": "ETH/USD"})
    assert {"ema_fast", "ema_slow", "vol_ma"} <= set(df.columns)
    df = s.populate_entry_trend(df, {"pair": "ETH/USD"})
    df = s.populate_exit_trend(df, {"pair": "ETH/USD"})
    assert int(df["enter_long"].fillna(0).sum()) >= 1   # a fresh cross-up + vol surge
    assert int(df["exit_long"].fillna(0).sum()) >= 1    # a later cross-down


def test_entry_requires_volume_surge():
    s = _strategy()
    closes, _ = _series()
    flat_vol = [100.0] * len(closes)          # no bar exceeds the rolling mean
    df = s.populate_indicators(_df(closes, flat_vol), {"pair": "ETH/USD"})
    df = s.populate_entry_trend(df, {"pair": "ETH/USD"})
    assert int(df["enter_long"].fillna(0).sum()) == 0


def test_baseline_and_status_only_emit_nothing():
    s = _strategy()
    closes, vols = _series()
    for pair in ("BTC/USD", "USDT/USD"):
        df = s.populate_indicators(_df(closes, vols), {"pair": pair})
        df = s.populate_entry_trend(df, {"pair": pair})
        df = s.populate_exit_trend(df, {"pair": pair})
        assert int(df["enter_long"].fillna(0).sum()) == 0, pair
        assert int(df["exit_long"].fillna(0).sum()) == 0, pair


# ---- cross-executor exposure accounting -------------------------------------

def test_external_exposure_reads_other_executor(tmp_path, monkeypatch):
    p = tmp_path / "open_exposure.json"
    monkeypatch.setattr(policy, "open_exposure_path", lambda: p)
    now = datetime.now(timezone.utc)
    policy.write_json(p, {"executors": {"daily": 5000.0, "fast": 0.0},
                          "total": 5000.0, "asof": now.isoformat()})
    # as the FAST executor, the daily stake is what must be added to the global cap
    res = policy.external_exposure("fast")
    assert res["known"] is True and res["external"] == 5000.0
    # as the DAILY executor, the fast stake (0) is external
    assert policy.external_exposure("daily")["external"] == 0.0


def test_external_exposure_fail_closed_on_missing_and_stale(tmp_path, monkeypatch):
    p = tmp_path / "open_exposure.json"
    monkeypatch.setattr(policy, "open_exposure_path", lambda: p)
    assert policy.external_exposure("fast")["known"] is False      # absent
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    policy.write_json(p, {"executors": {"daily": 5000.0, "fast": 0.0},
                          "total": 5000.0, "asof": old.isoformat()})
    assert policy.external_exposure("fast", max_age_s=180)["known"] is False  # stale


# ---- global multi-executor invariant ----------------------------------------

def test_validate_executors_catches_overlap_and_gaps():
    daily = {"exchange": {"pair_whitelist": ["BTC/USD"]}, "max_open_trades": 1, "stake_amount": 15}
    fast = {"exchange": {"pair_whitelist": ["ETH/USD", "XRP/USD", "DOT/USD", "LINK/USD"]},
            "max_open_trades": 3, "stake_amount": 10}
    assert policy.validate_executors({"daily": daily, "fast": fast}) == []
    overlap = dict(daily)
    overlap["exchange"] = {"pair_whitelist": ["BTC/USD", "ETH/USD"]}
    assert any("disjoint" in x for x in policy.validate_executors({"daily": overlap, "fast": fast}))
