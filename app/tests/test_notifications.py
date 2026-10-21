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
