"""Emoji trade-alert pipeline tests: formatters + monitor event diffing.

Hermetic — synthetic sqlite DB with the REAL Freqtrade 2026.9 trades schema
(no take_profit/profit_abs columns), stubbed send, tmp state files.
No network, no Telegram, no orders.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import crypto_status_monitor as M  # noqa: E402
from notifications import format as NF  # noqa: E402
from risk import policy  # noqa: E402

# 2026.9 schema subset the monitor actually reads (note: NO take_profit,
# NO profit_abs — those were the silent-query-kill bug).
DDL = """
CREATE TABLE trades (
  id INTEGER PRIMARY KEY, exchange TEXT, pair TEXT, is_open INTEGER,
  fee_open REAL, fee_open_cost REAL, fee_close REAL, fee_close_cost REAL,
  open_rate REAL, open_rate_requested REAL, open_trade_value REAL,
  close_rate REAL, close_rate_requested REAL, realized_profit REAL,
  close_profit REAL, close_profit_abs REAL, stake_amount REAL, amount REAL,
  amount_requested REAL, open_date TEXT, close_date TEXT, stop_loss REAL,
  stop_loss_pct REAL, exit_reason TEXT, exit_order_status TEXT,
  strategy TEXT, enter_tag TEXT, timeframe TEXT
)
"""


def _db(tmp_path: Path) -> Path:
    p = tmp_path / "tradesv3.sqlite"
    con = sqlite3.connect(p)
    con.executescript(DDL)
    con.commit()
    con.close()
    return p


def _insert(db: Path, **kw) -> int:
    base = dict(pair="ETH/USD", is_open=1, open_date="2026-10-21 00:05:00",
                open_rate=100.0, stake_amount=1000.0, amount=10.0,
                open_trade_value=1000.5, fee_open_cost=0.5, stop_loss=90.0,
                strategy="PaperAutonomous", enter_tag="EXPERIMENTAL alt z_cross_up",
                timeframe="1d", close_profit=None, close_profit_abs=None,
                close_rate=None, close_date=None, exit_reason=None,
                exit_order_status=None, fee_close_cost=None, realized_profit=None)
    base.update(kw)
    cols = ", ".join(base)
    ph = ", ".join("?" * len(base))
    con = sqlite3.connect(db)
    con.execute(f"INSERT INTO trades ({cols}) VALUES ({ph})", tuple(base.values()))
    con.commit()
    tid = con.execute("SELECT id FROM trades ORDER BY id DESC LIMIT 1").fetchone()[0]
    con.close()
    return tid


def _close(db: Path, tid: int, ratio=0.05, abs_=50.0) -> None:
    con = sqlite3.connect(db)
    con.execute("UPDATE trades SET is_open=0, close_profit=?, close_profit_abs=?, "
                "close_rate=105, close_date='2026-10-25 00:10:00', "
                "exit_reason='exit signal', exit_order_status='closed' WHERE id=?",
                (ratio, abs_, tid))
    con.commit()
    con.close()


def _harness(tmp_path, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(M, "TRADE_EVENTS_PATH", tmp_path / "trade_events.json")
    monkeypatch.setattr(M, "send", lambda _e, text: (sent.append(text), True)[1])
    monkeypatch.setattr(policy, "rejections_path",
                        lambda: tmp_path / "risk_rejections.json")
    return sent


# ---------------- formatters ----------------

def test_entry_and_fill_alerts_are_distinct_and_emoji_rich():
    t = {"pair": "ETH/USD", "open_date": "2026-10-21 00:05", "strategy": "PaperAutonomous",
         "timeframe": "1d", "enter_tag": "EXPERIMENTAL alt z_cross_up", "stake_amount": 1000.0,
         "open_rate": 100.0, "amount": 10.0}
    e = NF.format_trade_entry(t)
    f = NF.format_trade_filled({**t, "open_trade_value": 1000.5, "fee_open_cost": 0.5, "stop_loss": 90.0})
    assert e.startswith("🟢") and "SUBMITTED" in e and "AUTO-APPROVED" in e
    assert "why: EXPERIMENTAL" in e
    assert f.startswith("✅") and "FILLED" in f and "🛑 stop: 90" in f
    assert "SUBMITTED" not in f


def test_outcome_profit_loss_break_even_selection():
    base = {"pair": "BTC/USD", "close_date": "x", "open_rate": 1.0, "close_rate": 2.0,
            "exit_reason": "exit signal"}
    assert "💰 PROFIT" in NF.format_trade_outcome({**base, "close_profit": 0.05, "close_profit_abs": 50})
    assert "💸 LOSS" in NF.format_trade_outcome({**base, "close_profit": -0.05, "close_profit_abs": -50})
    assert "⚖️ BREAK-EVEN" in NF.format_trade_outcome({**base, "close_profit": 0.0})
    assert "+5.00%" in NF.format_trade_outcome({**base, "close_profit": 0.05, "close_profit_abs": 50})


def test_missing_fields_do_not_crash_event_formats():
    for fn in (NF.format_trade_entry, NF.format_trade_filled,
               NF.format_trade_exit, NF.format_trade_outcome):
        assert "?" in fn({}) or "n/a" in fn({})
    assert "NO TRADE" in NF.format_risk_rejection({"pair": "X/USD", "code": "EXPOSURE_CAP",
                                                   "message": "over cap", "ts": "2026-10-21"})


# ---------------- monitor open_positions (schema-robust) ----------------

def test_open_positions_works_on_2026_9_schema(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _insert(db)
    pos = M.open_positions(db)
    assert "ETH/USD" in pos and pos["ETH/USD"]["order_state"] == "OPEN (confirmed filled)"
    assert pos["ETH/USD"]["qty"] == 10.0          # would be {} with the old profit_abs query


# ---------------- event diffing state machine ----------------

def test_first_run_never_replays_history(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _insert(db)                                   # pre-existing open trade
    sent = _harness(tmp_path, monkeypatch)
    assert M.notify_trade_events({}, db) == 0     # baseline adopted silently
    assert sent == []


def test_new_open_alerts_buy_then_filled(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sent = _harness(tmp_path, monkeypatch)
    M.notify_trade_events({}, db)                 # init baseline
    _insert(db)                                   # executor opened a trade
    assert M.notify_trade_events({}, db) == 2
    assert sent[0].startswith("🟢") and sent[1].startswith("✅")
    assert M.notify_trade_events({}, db) == 0     # no re-spam


def test_close_alerts_exit_then_outcome(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sent = _harness(tmp_path, monkeypatch)
    M.notify_trade_events({}, db)
    tid = _insert(db)
    M.notify_trade_events({}, db)
    _close(db, tid)
    assert M.notify_trade_events({}, db) == 2
    assert any(s.startswith("🔴") for s in sent)
    assert any("💰 PROFIT" in s for s in sent)
    assert M.notify_trade_events({}, db) == 0


def test_open_and_close_between_polls_reports_outcome_once(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sent = _harness(tmp_path, monkeypatch)
    M.notify_trade_events({}, db)
    tid = _insert(db)
    _close(db, tid, ratio=-0.02, abs_=-20.0)      # full round trip inside one interval
    assert M.notify_trade_events({}, db) == 1
    assert sent[0].startswith("💸 LOSS")
    assert M.notify_trade_events({}, db) == 0


def test_new_rejections_alert_with_why(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sent = _harness(tmp_path, monkeypatch)
    M.notify_trade_events({}, db)
    policy.log_rejection("XRP/USD", "EXPOSURE_CAP", "would exceed 10k cap", {})
    assert M.notify_trade_events({}, db) == 1
    assert sent[0].startswith("⚠️") and "EXPOSURE_CAP" in sent[0]
    assert M.notify_trade_events({}, db) == 0
