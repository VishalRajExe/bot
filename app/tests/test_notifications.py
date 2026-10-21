"""Pure tests for notification formatting (no network, no telegram)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.notifications import format as NF  # noqa: E402


def test_signal_report_shows_inputs_and_risk():
    msg = NF.format_signal_report(
        pair="BTC/USD",
        timeframe="1d",
        now=datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc),
        decision="ENTRY",
        reason="z crossed up through bull threshold",
        indicators={"zscore": 0.52, "bull_threshold": 0.5, "ema65": 80000.0, "close": 83114.0},
        risk={"stake_amount": 5000.0, "max_open_trades": 1, "stoploss": -0.35},
    )
    assert "BTC/USD 1d" in msg
    assert "decision: ENTRY" in msg
    assert "zscore: 0.5200" in msg
    assert "bounded risk:" in msg
    assert "stake_amount: 5,000.0000" in msg


def test_fvg_ob_setup_renders_all_steps_and_rr():
    entry = {
        "pair": "ETH/USD", "direction": "long",
        "htf_creation_ts": "2026-01-01 02:00:00+00:00", "htf_tap_ts": "2026-01-01 03:00:00+00:00",
        "ltf_creation_ts": "2026-01-01 04:10:00+00:00", "entry_ts": "2026-01-01 04:30:00+00:00",
        "entry_price": 105.5, "stop": 100.0, "take_profit": 116.5, "risk_per_unit": 5.5, "rr": 2.0,
        "htf_zone": (101.0, 108.0), "strategy_version": "fvg-ob-0.1",
    }
    msg = NF.format_fvg_ob_setup(entry)
    assert "ETH/USD LONG" in msg
    assert "1H zone tapped" in msg
    assert "5M FVG confirmed" in msg
    assert "RR 1:2.00" in msg
    assert "take-profit 116.5000" in msg
    # every step timestamped
    assert msg.count("2026-01-01") == 4


def test_missing_fields_do_not_crash():
    msg = NF.format_fvg_ob_setup({"pair": "X/USD"})
    assert "X/USD" in msg and "n/a" in msg


def test_asset_status_is_per_asset_and_distinguishes_fill_from_signal():
    asset = {
        "symbol": "BTC/USD", "status": "ACTIVE_BASELINE", "status_label": "ACTIVE (baseline)",
        "strategy": "BtcZScore", "version": "btc-1d-z65", "signal": "BUY", "signal_ts": "2026-10-21",
        "candle_ts": "2026-10-20", "price": 83360.0,
        "indicators": {"zscore": 0.52, "bull_threshold": 0.5},
        "position": {"qty": 0.06, "entry": 80000.0, "stop": 62000.0, "tp": None, "upnl": 200.0},
        "risk": {"decision": "AUTO-APPROVED", "reason": "within bounded paper policy"},
        "order_state": "OPEN (confirmed filled)",
    }
    msg = NF.format_asset_status(asset)
    assert "BTC/USD" in msg
    assert "[BUY]" in msg
    assert "ACTIVE (baseline)" in msg
    assert "BtcZScore" in msg
    assert "confirmed filled" in msg          # fill is stated as fill
    assert "AUTO-APPROVED" in msg
    assert "unrealized P&L" in msg


def test_asset_status_signal_not_reported_as_fill():
    asset = {"symbol": "ETH/USD", "status_label": "EXPERIMENTAL (paper)", "signal": "BUY",
             "strategy": "DailyZScoreAlt", "version": "alt-1d-z65", "price": 2500.0,
             "indicators": {"zscore": 0.61}, "position": None,
             "risk": {"decision": "REJECTED EXPOSURE_CAP", "reason": "would exceed cap"},
             "order_state": "no open position"}
    msg = NF.format_asset_status(asset)
    # a signal with a risk rejection must NOT read as a fill
    assert "no open position" in msg
    assert "REJECTED" in msg
    assert "filled" not in msg.lower()


def test_status_only_asset_shows_monitor_and_not_traded():
    asset = {"symbol": "USDT/USD", "status_label": "STATUS-ONLY (not traded)",
             "strategy": None, "version": "n/a", "signal": "MONITOR",
             "note": "stablecoin; not enabled", "position": None,
             "risk": {"decision": "NOT TRADED", "reason": "status-only"},
             "order_state": "no open position"}
    msg = NF.format_asset_status(asset)
    assert "USDT/USD" in msg
    assert "STATUS-ONLY" in msg
    assert "NOT TRADED" in msg
