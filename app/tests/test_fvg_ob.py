"""Deterministic unit tests for the FVG/OB core (app/strategies_core/fvg_ob.py).

Synthetic completed candles only. No exchange, no Freqtrade, no orders, no network.
Covers owner decision #2 ("every step needs a timestamp and a test") and the §13 list.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.strategies_core import fvg_ob as F  # noqa: E402
from app.strategies_core import state_store as SS  # noqa: E402


def ts(n, start="2026-01-01 00:00"):
    return pd.date_range(start, periods=n, freq="1h", tz="UTC")


# ---------------------------------------------------------------- FVG detection
def test_bullish_fvg_detection():
    # candles: a=[h=100], b=[mid], c=[l=110] -> low(c) 110 > high(a) 100 => bull gap (100..110)
    high = np.array([100, 105, 112, 115])
    low = np.array([95, 100, 110, 112])
    fvgs = F.find_fvg(high, low, pd.Series(ts(4)))
    bull = [g for g in fvgs if g.direction == 1]
    assert bull and bull[0].bottom == 100 and bull[0].top == 110
    assert bull[0].creation_ts == pd.Timestamp("2026-01-01 02:00", tz="UTC")  # 3rd bar


def test_bearish_fvg_detection():
    # high(c) < low(a): a=[l=110], c=[h=100] => bear gap (100..110)
    high = np.array([115, 108, 100, 98])
    low = np.array([110, 104, 95, 90])
    fvgs = F.find_fvg(high, low, pd.Series(ts(4)))
    bear = [g for g in fvgs if g.direction == -1]
    assert bear and bear[0].bottom == 100 and bear[0].top == 110


def test_no_fvg_when_overlapping():
    high = np.array([100, 101, 100.5])
    low = np.array([99, 100, 99.5])  # low(c)=99.5 not > high(a)=100 -> no bull; high(c) not< low(a)
    assert F.find_fvg(high, low, pd.Series(ts(3))) == []


# ---------------------------------------------------------------- bias + swings
def test_bias_series_directions():
    close = np.arange(100, 130, dtype=float)          # rising -> bull
    high = close + 1
    low = close - 1
    b = F.bias_series(close, high, low, F.FvgCfg(bias_ema=5))
    assert b[-1] == 1
    bd = F.bias_series(close[::-1], high[::-1], low[::-1], F.FvgCfg(bias_ema=5))
    assert bd[-1] == -1


def test_swing_confirmation_is_forward_lagged():
    # a single spike at index 3 with k=2 is only confirmed once indices 4,5 exist
    high = np.array([10, 11, 12, 20, 12, 11, 10], dtype=float)
    low = high - 1
    hi_idx, _ = F.swing_points(high, low, k=2)
    assert 3 in hi_idx  # detected, but caller may only USE it from bar index 3+2=5


# ---------------------------------------------------------------- tracker happy path
def _drive_to_tapped(cfg=None):
    tr = F.SetupTracker("BTC/USD", cfg or F.FvgCfg())
    a = ts(4)
    tr.step("1h", a[1], 100, 101, 99, 100, atr_val=2.0, bias=1, bar_index=1)  # ->BIAS
    zone = F.FVG(+1, bottom=100.0, top=110.0, creation_ts=a[2], i=2)
    assert tr.open_zone(zone, ob_bottom=102.0, ob_top=108.0, atr_val=2.0, bar_index=2)
    assert tr.state == "HTF_CONFLUENCE_ZONE_IDENTIFIED"
    # tap: a bar whose range touches (102..108)
    tr.step("1h", a[3], 110, 111, 103, 106, atr_val=2.0, bias=1, bar_index=3)
    assert tr.state == "HTF_ZONE_TAPPED"
    return tr, a


def test_full_sequence_emits_entry_with_1to2_rr():
    tr, a = _drive_to_tapped()
    # new bullish 5M FVG overlapping the HTF zone, created AFTER the tap
    f5 = F.FVG(+1, bottom=103.0, top=106.0, creation_ts=pd.Timestamp("2026-01-01 04:00", tz="UTC"), i=0)
    assert tr.ltf_fvg(f5) is True
    assert tr.state == "LTF_FVG_CONFIRMED"
    # first retest bar dips into the 5M FVG; entry at its close
    entry = tr.ltf_retest(pd.Timestamp("2026-01-01 04:30", tz="UTC"),
                          o=105, h=106, l=103, c=104.0, atr_val=2.0)
    assert entry is not None and tr.state == "ENTRY_TRIGGERED"
    stop = entry["stop"]
    assert entry["risk_per_unit"] == pytest.approx(entry["entry_price"] - stop)
    assert entry["take_profit"] == pytest.approx(entry["entry_price"] + 2.0 * entry["risk_per_unit"])
    # stop sits below the HTF zone bottom (buffer applied)
    assert stop < 102.0
    # every step timestamped
    for k in ("htf_creation_ts", "htf_tap_ts", "ltf_creation_ts", "entry_ts"):
        assert entry[k]


def test_entry_before_tap_is_never_accepted():
    tr = F.SetupTracker("X/USD", F.FvgCfg())
    f5 = F.FVG(+1, 103.0, 106.0, pd.Timestamp("2026-01-01 04:00", tz="UTC"), 0)
    assert tr.ltf_fvg(f5) is False               # IDLE, no tap -> rejected
    assert tr.state == "IDLE"


def test_ltf_fvg_before_htf_tap_ts_rejected():
    tr, a = _drive_to_tapped()
    # 5M FVG that formed BEFORE the tap time must not count
    early = F.FVG(+1, 103.0, 106.0, pd.Timestamp("2025-12-31 00:00", tz="UTC"), 0)
    assert tr.ltf_fvg(early) is False


def test_ltf_fvg_must_overlap_htf_zone():
    tr, a = _drive_to_tapped()
    far = F.FVG(+1, 200.0, 210.0, pd.Timestamp("2026-01-01 05:00", tz="UTC"), 0)
    assert tr.ltf_fvg(far) is False   # no overlap with 102..108 zone


def test_second_retest_does_not_duplicate_entry():
    tr, a = _drive_to_tapped()
    f5 = F.FVG(+1, 103.0, 106.0, pd.Timestamp("2026-01-01 04:00", tz="UTC"), 0)
    tr.ltf_fvg(f5)
    first = tr.ltf_retest(pd.Timestamp("2026-01-01 04:30", tz="UTC"), 105, 106, 103, 104.0, 2.0)
    assert first is not None
    tr.confirm_position()
    second = tr.ltf_retest(pd.Timestamp("2026-01-01 05:00", tz="UTC"), 105, 106, 103, 104.0, 2.0)
    assert second is None   # POSITION_OPEN: no re-entry until reset()


def test_stop_wrong_side_is_rejected_no_entry():
    cfg = F.FvgCfg(stop_atr_mult=0.5)  # HTF zone 102..108 -> stop = 102 - 1.0 = 101
    tr, a = _drive_to_tapped(cfg)
    # 5M FVG overlaps the zone, but the retest bar CLOSES below the stop -> risk<=0
    f5 = F.FVG(+1, 103.0, 106.0, pd.Timestamp("2026-01-01 04:00", tz="UTC"), 0)
    assert tr.ltf_fvg(f5) is True
    entry = tr.ltf_retest(pd.Timestamp("2026-01-01 04:30", tz="UTC"),
                          o=104.0, h=105.0, l=100.4, c=100.5, atr_val=2.0)
    assert entry is None
    assert tr.state == "INVALIDATED"
    assert "risk_non_positive" in tr.st.invalid_reason


def test_zone_expires_if_not_tapped():
    tr = F.SetupTracker("BTC/USD", F.FvgCfg(zone_ttl_bars=2))
    t = ts(6)
    tr.step("1h", t[1], 100, 101, 99, 100, atr_val=2.0, bias=1, bar_index=1)   # -> BIAS
    zone = F.FVG(+1, 100.0, 110.0, t[2], 2)
    assert tr.open_zone(zone, None, None, 2.0, bar_index=2)                    # expiry_index = 4
    # a 1H bar past expiry, price never touching the zone -> invalidated
    tr.step("1h", t[3], 120, 121, 118, 120, atr_val=2.0, bias=1, bar_index=5)
    assert tr.state == "INVALIDATED"
    assert "zone_expired" in tr.st.invalid_reason


def test_retest_window_expiry():
    cfg = F.FvgCfg(retest_window_5m=2)
    tr, a = _drive_to_tapped(cfg)
    f5 = F.FVG(+1, 103.0, 106.0, pd.Timestamp("2026-01-01 04:00", tz="UTC"), 0)
    tr.ltf_fvg(f5)
    # three non-retesting 5M bars blow the window (high stays above zone, no dip)
    for i in range(3):
        e = tr.ltf_retest(pd.Timestamp("2026-01-01 04:%02d" % (5 + i), tz="UTC"),
                          107, 108, 106.5, 107.5, 2.0)
    assert e is None and tr.state == "INVALIDATED"


def test_spot_only_bearish_never_long_entry():
    tr = F.SetupTracker("BTC/USD", F.FvgCfg())
    bear = F.FVG(-1, 103.0, 106.0, pd.Timestamp("2026-01-01 04:00", tz="UTC"), 0)
    assert tr.open_zone(bear, None, None, 2.0, 2) is False  # bear FVG never opens a LONG zone


# ---------------------------------------------------------------- no-lookahead
def test_no_lookahead_append_invariance():
    high = np.array([100, 105, 112, 115], dtype=float)
    low = np.array([95, 100, 110, 112], dtype=float)
    t = ts(4)
    base = F.find_fvg(high, low, pd.Series(t))
    # append a violent crash candle; previously-detected gaps must not change
    high2 = np.append(high, 90)
    low2 = np.append(low, 80)
    after = F.find_fvg(high2, low2, pd.Series(ts(5)))
    assert base == after[:len(base)]   # prefix identical -> earlier signals don't use the future bar


def test_bias_does_not_use_future():
    close = np.arange(100, 120, dtype=float)
    high, low = close + 1, close - 1
    t = F.FvgCfg(bias_ema=5)
    full = F.bias_series(close, high, low, t)
    prefix = F.bias_series(close[:-3], high[:-3], low[:-3], t)
    assert (full[:len(prefix)] == prefix).all()


# ---------------------------------------------------------------- persistence / restart
def test_restart_recovery_no_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(SS, "STATE_DIR", tmp_path)
    tr, a = _drive_to_tapped()
    f5 = F.FVG(+1, 103.0, 106.0, pd.Timestamp("2026-01-01 04:00", tz="UTC"), 0)
    tr.ltf_fvg(f5)
    snap = tr.snapshot()
    SS.save("BTC/USD", snap)
    # simulate restart: rebuild from persisted state, then a retest arrives once
    tr2 = F.SetupTracker("BTC/USD", F.FvgCfg(), state=SS.load("BTC/USD"))
    assert tr2.state == "LTF_FVG_CONFIRMED"
    entry = tr2.ltf_retest(pd.Timestamp("2026-01-01 04:30", tz="UTC"), 105, 106, 103, 104.0, 2.0)
    assert entry is not None
    # after entry, re-loading the ENTRY_TRIGGERED snapshot must not re-fire
    SS.save("BTC/USD", tr2.snapshot())
    tr3 = F.SetupTracker("BTC/USD", F.FvgCfg(), state=SS.load("BTC/USD"))
    tr3.confirm_position()
    assert tr3.ltf_retest(pd.Timestamp("2026-01-01 05:00", tz="UTC"), 105, 106, 103, 104.0, 2.0) is None


def test_tracker_rearms_after_invalidation():
    # Regression for the replay wedge: evaluate() supersedes a dead (INVALIDATED) or
    # stale pre-entry setup so one dud can never permanently block later ones. This
    # pins the primitive it relies on: reset() from a terminal state re-opens cleanly.
    tr = F.SetupTracker("BTC/USD", F.FvgCfg(zone_ttl_bars=2))
    t = ts(6)
    tr.step("1h", t[1], 100, 101, 99, 100, atr_val=2.0, bias=1, bar_index=1)
    zone = F.FVG(+1, 100.0, 110.0, t[2], 2)
    assert tr.open_zone(zone, None, None, 2.0, bar_index=2)          # expiry_index = 4
    tr.step("1h", t[3], 120, 121, 118, 120, atr_val=2.0, bias=1, bar_index=9)  # past expiry
    assert tr.state == "INVALIDATED"
    # a dead setup is superseded: reset then a brand-new bullish zone opens
    tr.reset()
    assert tr.state == "IDLE"
    zone2 = F.FVG(+1, 200.0, 210.0, t[4], 4)
    assert tr.open_zone(zone2, None, None, 2.0, bar_index=4) is True
    assert tr.state == "HTF_CONFLUENCE_ZONE_IDENTIFIED"


# ---------------------------------------------------------------- integration (scan)
def mkdf(rows, start, freq):
    d = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    d.insert(0, "date", pd.date_range(start, periods=len(d), freq=freq, tz="UTC"))
    d["volume"] = 1.0
    return d


CFG = F.FvgCfg(bias_ema=3, atr_n=2, swing_k=1, require_overlap=False, zone_ttl_bars=24)

# 1H: rising -> bull FVG (101..108) at bar i2 -> tap at bar i3
DF1H = mkdf([
    [99, 101, 98, 100],
    [100, 105, 100, 104],
    [105, 110, 108, 109],   # low 108 > high(i0) 101 => bull FVG (101..108)
    [109, 110, 102, 103],   # tap: low 102 <= 108, high 110 >= 101 (after creation)
], "2026-01-01 00:00", "1h")

# 5M (after the 04:00 tap close-time): bull FVG overlapping zone, then first retest
DF5M = mkdf([
    [104.0, 105.0, 103.0, 104.5],
    [104.5, 106.0, 104.0, 105.8],
    [106.0, 108.0, 106.5, 107.5],   # low 106.5 > high(j0) 105 => bull 5M FVG (105..106.5)
    [107.0, 107.0, 105.2, 105.5],   # first retest dips into 5M FVG -> entry @close 105.5
], "2026-01-01 04:00", "5min")


def test_evaluate_emits_single_entry_with_1to2_rr():
    entries, tr = F.evaluate_ohlcv(DF1H, DF5M, CFG, pair="ETH/USD")
    assert len(entries) == 1
    e = entries[0]
    assert e["direction"] == "long"
    assert e["risk_per_unit"] > 0 and e["stop"] < 101.0            # stop below HTF zone bottom
    assert e["take_profit"] == pytest.approx(e["entry_price"] + 2.0 * e["risk_per_unit"])
    # every step carries a timestamp
    assert all(e[k] for k in ("htf_creation_ts", "htf_tap_ts", "ltf_creation_ts", "entry_ts"))


def test_evaluate_no_entry_until_sequence_complete():
    # drop the retest bar -> sequence never completes -> no entry
    entries, _ = F.evaluate_ohlcv(DF1H, DF5M.iloc[:-1], CFG, pair="ETH/USD")
    assert entries == []


def test_evaluate_no_lookahead_prefix_invariance():
    e1, _ = F.evaluate_ohlcv(DF1H, DF5M, CFG, "ETH/USD")
    # extend BOTH frames far into the future; the already-emitted entry must not change
    df1h_ext = pd.concat([DF1H, mkdf([[110, 112, 108, 109], [109, 111, 107, 108]],
                                     "2026-01-01 04:00", "1h")], ignore_index=True)
    df5m_ext = pd.concat([DF5M, mkdf([[105, 106, 104, 104.5], [104.5, 105, 103, 103.5]],
                                     "2026-01-01 04:20", "5min")], ignore_index=True)
    e2, _ = F.evaluate_ohlcv(df1h_ext, df5m_ext, CFG, "ETH/USD")
    assert e2[:len(e1)] == e1


def test_order_block_detector_finds_bull_ob():
    # a down bar then a big bull displacement that clears a prior swing high
    open_ = np.array([100, 101, 99, 100, 110, 130], dtype=float)
    high = np.array([101, 102, 100, 110, 128, 140], dtype=float)
    low = np.array([99, 100, 97, 99, 109, 128], dtype=float)
    close = np.array([100, 101, 98, 110, 127, 139], dtype=float)
    atr_arr = np.array([5, 5, 5, 5, 5, 5], dtype=float)
    t = pd.Series(ts(6))
    hi_idx, lo_idx = F.swing_points(high, low, k=1)
    obs = F.find_order_blocks(high, low, open_, close, atr_arr, t, F.FvgCfg(disp_atr_mult=1.0, swing_k=1),
                              hi_idx, lo_idx)
    assert any(o.direction == 1 for o in obs)   # a bullish OB (last down bar before displacement)
