"""Reporting tests — monetary fee math and incomplete-data honesty.

The audit finding (C2) was that the report treated fee_open/fee_close (RATES,
e.g. 0.001) as if they were money. These tests pin the corrected behavior:
summarize_fees() sums fee_open_cost + fee_close_cost, and any missing/null cost
is counted (lower bound), never silently folded into zero.
"""
from __future__ import annotations

import weekly_report as W


def test_fees_are_monetary_not_rates():
    trades = [
        {"fee_open": 0.001, "fee_close": 0.001,
         "fee_open_cost": 0.10, "fee_close_cost": 0.20},
        {"fee_open": 0.001, "fee_close": 0.001,
         "fee_open_cost": 0.05, "fee_close_cost": 0.05},
    ]
    out = W.summarize_fees(trades)
    # 0.10+0.20+0.05+0.05 = 0.40 (money), NOT 0.004 (four rate values summed).
    assert out["total_cost"] == 0.40
    assert out["missing_count"] == 0
    assert out["trades_count"] == 2
    # Regression guard: total must not equal the naive sum of the rate columns.
    naive_rates = sum(t["fee_open"] + t["fee_close"] for t in trades)
    assert abs(out["total_cost"] - naive_rates) > 0.01


def test_missing_fee_cost_is_counted_not_zeroed():
    trades = [
        {"fee_open_cost": 0.10, "fee_close_cost": None},   # half-record
        {"fee_open_cost": None, "fee_close_cost": None},   # fully unknown
    ]
    out = W.summarize_fees(trades)
    assert out["missing_count"] == 2
    assert out["total_cost"] == 0.10  # known part only, flagged as a lower bound


def test_empty_history_is_zero_not_error():
    out = W.summarize_fees([])
    assert out == {"total_cost": 0.0, "missing_count": 0, "trades_count": 0}


def test_partial_records_incomplete_data():
    trades = [
        {"fee_open_cost": 1.0, "fee_close_cost": 1.0},     # complete
        {"fee_open_cost": 0.5},                            # close missing (KeyError-safe)
    ]
    out = W.summarize_fees(trades)
    assert out["total_cost"] == 2.5   # 1.0+1.0 (complete) + 0.5+unknown
    assert out["missing_count"] == 1


def test_fee_missing_surfaces_as_warning_in_render():
    d = _base_render_data()
    d["fee_summary"] = {"total_cost": 0.10, "missing_count": 3, "trades_count": 5}
    md = W.render(d)
    assert "lower bound" in md
    assert "3 trade record(s) have missing/null fee cost" in md


def test_offline_status_is_unverified_not_benign_in_render():
    d = _base_render_data()
    d["last"] = {"status": "OFFLINE", "ts": "2026-10-21T00:00:00Z",
                 "detail": "executor offline"}
    d["recs"] = [d["last"]]
    d["statuses"] = {"OFFLINE": 1}
    md = W.render(d)
    assert "UNVERIFIED" in md


def _base_render_data():
    # Minimal dict satisfying render()'s required keys for the tested sections.
    return {
        "generated": "2026-10-21T00:00:00Z", "days": 7,
        "start_day": "2026-10-14", "end_day": "2026-10-21",
        "trades_all": [], "trades_opened_win": [], "trades_closed_win": [],
        "open_now": [], "recs": [], "statuses": {}, "max_drift": 0.0,
        "review_runs": [], "eq": [], "eq_start": None, "eq_end": None,
        "peak": None, "max_dd": 0.0, "exposure": None, "last": None,
        "locks": [], "fee_summary": {"total_cost": 0.0, "missing_count": 0,
                                      "trades_count": 0}, "realized": 0.0,
        "db": "x",
    }
