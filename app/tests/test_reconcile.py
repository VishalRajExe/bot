"""Reconciliation safety tests — the false-OK guarantee.

Covers the pure status model (classify_status) exhaustively and the snapshot()
end-to-end path against a temp Freqtrade DB with the broker/heartbeat/data reads
mocked. Nothing here opens a network socket, places an order, or starts the bot.

Core guarantee under test: an OFFLINE executor, a STALE heartbeat, stale market
data, an unreadable DB, or portfolio drift can NEVER produce HEALTHY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import obs_lib as O
import reconcile as R


def _sig(**over) -> dict:
    """A fully HEALTHY baseline signal; override individual keys to force states."""
    s = {
        "ft_db_ok": True, "live_endpoint_suspected": False,
        "qty_drift": 0.0, "broker_position_qty": 0.0, "ft_open_amount": 0.0,
        "heartbeat_age_s": 10.0, "process_alive": True,
        "broker_ok": True, "candle_age_h": 5.0,
        "active_locks": 0, "unmatched_broker_orders": 0, "ft_unresolved_orders": 0,
    }
    s.update(over)
    return s


# ---------- classify_status: precedence & the never-healthy-on-fault rules ----

def test_all_clear_is_healthy():
    status, _ = R.classify_status(_sig())
    assert status == R.HEALTHY


def test_offline_process_is_never_healthy():
    status, detail = R.classify_status(_sig(process_alive=False))
    assert status == R.OFFLINE
    assert "OFFLINE" in detail


def test_missing_heartbeat_is_offline():
    status, _ = R.classify_status(_sig(heartbeat_age_s=None))
    assert status == R.OFFLINE


def test_stale_heartbeat_is_offline_not_healthy():
    status, _ = R.classify_status(_sig(heartbeat_age_s=R.HEARTBEAT_MAX_AGE_S + 1))
    assert status == R.OFFLINE


def test_stale_market_data_is_stale():
    status, _ = R.classify_status(_sig(candle_age_h=R.CANDLE_MAX_AGE_H + 5))
    assert status == R.STALE


def test_missing_candle_data_is_stale():
    status, _ = R.classify_status(_sig(candle_age_h=None))
    assert status == R.STALE


def test_broker_unreachable_when_alive():
    status, _ = R.classify_status(_sig(broker_ok=False))
    assert status == R.BROKER_UNREACHABLE


def test_portfolio_drift_is_critical():
    status, _ = R.classify_status(_sig(qty_drift=0.5, broker_position_qty=0.5))
    assert status == R.CRITICAL


def test_corrupt_db_is_critical():
    status, _ = R.classify_status(_sig(ft_db_ok=False))
    assert status == R.CRITICAL


def test_live_endpoint_is_critical():
    status, _ = R.classify_status(_sig(live_endpoint_suspected=True))
    assert status == R.CRITICAL


def test_external_orders_are_review():
    status, detail = R.classify_status(_sig(unmatched_broker_orders=1))
    assert status == R.REVIEW
    assert "not owned by Freqtrade" in detail


def test_active_locks_are_review():
    status, _ = R.classify_status(_sig(active_locks=2))
    assert status == R.REVIEW


def test_unresolved_ft_orders_are_review():
    status, _ = R.classify_status(_sig(ft_unresolved_orders=1))
    assert status == R.REVIEW


def test_critical_beats_offline_and_review():
    # Precedence: even when also offline/review, a portfolio break is CRITICAL.
    status, _ = R.classify_status(_sig(process_alive=False, qty_drift=1.0))
    assert status == R.CRITICAL


def test_offline_beats_stale_and_review():
    # Offline executor wins over stale data / review items (never just REVIEW).
    status, _ = R.classify_status(
        _sig(process_alive=False, candle_age_h=99, active_locks=1))
    assert status == R.OFFLINE


# ---------- identity reconciliation -------------------------------------------

def test_identity_matches_by_id_not_count():
    unmatched, unresolved = R.reconcile_order_identity(["a", "b"], ["a", "b"])
    assert (unmatched, unresolved) == (0, 0)


def test_identity_external_broker_order():
    unmatched, unresolved = R.reconcile_order_identity(["a", "ext"], ["a"])
    assert (unmatched, unresolved) == (1, 0)


def test_identity_unresolved_ft_order():
    # FT thinks an order is open but the broker doesn't show it — never assume fill.
    unmatched, unresolved = R.reconcile_order_identity(["a"], ["a", "ft1"])
    assert (unmatched, unresolved) == (0, 1)


def test_same_count_different_ids_still_flags():
    # Equal counts but different identity sets must NOT reconcile to zero.
    unmatched, unresolved = R.reconcile_order_identity(["x"], ["y"])
    assert (unmatched, unresolved) == (1, 1)


# ---------- snapshot() end-to-end against mocked sources ---------------------

def _patch_sources(monkeypatch, ft_db, *, heartbeat, alive, candle_age,
                   broker_positions=None, broker_orders=None, ft_orders=None):
    monkeypatch.setattr(O, "read_heartbeat", lambda: heartbeat)
    monkeypatch.setattr(R, "_pid_alive", lambda pid: alive)
    monkeypatch.setattr(O, "latest_candle_age_hours", lambda *a, **k: candle_age)
    monkeypatch.setattr(O, "ft_db_path", lambda: ft_db)

    # A hermetic config pointing at the paper host.
    cfg = tmp_paper_cfg(monkeypatch)

    def fake_get(path, timeout=15):
        if path == "/v2/account":
            return 200, {"cash": 100000.0, "equity": 100000.0, "buying_power": 100000.0}
        if path.startswith("/v2/positions"):
            return 200, broker_positions or []
        if path.startswith("/v2/orders"):
            return 200, broker_orders or []
        return 200, None

    monkeypatch.setattr(O, "alpaca_get", fake_get)
    return cfg


def tmp_paper_cfg(monkeypatch, tmp_path=None):
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    p = d / "cfg.json"
    p.write_text(json.dumps({
        "strategy": "BtcZScore",
        "exchange": {"ccxt_config": {"urls": {"api": {
            "trader": "https://paper-api.alpaca.markets"}}}},
    }), encoding="utf-8")
    monkeypatch.setattr(O, "PAPER_CFG", p)
    return p


def test_snapshot_offline_when_no_heartbeat(tmp_ledger, make_ft_db, monkeypatch):
    db = make_ft_db()
    _patch_sources(monkeypatch, db, heartbeat=None, alive=None, candle_age=5.0)
    s = R.snapshot()
    assert s["status"] == R.OFFLINE
    # and it was actually persisted as OFFLINE, not OK
    con = O.ledger_connect()
    try:
        row = con.execute(
            "SELECT status FROM reconcile_log ORDER BY ts DESC LIMIT 1").fetchone()
    finally:
        con.close()
    assert row[0] == R.OFFLINE


def test_snapshot_stale_heartbeat_offline(tmp_ledger, make_ft_db, monkeypatch):
    db = make_ft_db()
    now = datetime.now(timezone.utc)
    hb = {"pid": 4242, "last_heartbeat": now.isoformat()}
    _patch_sources(monkeypatch, db, heartbeat=hb, alive=True, candle_age=5.0)
    # Force the heartbeat to be old by patching age computation via a past stamp
    hb_old = {"pid": 4242,
              "last_heartbeat": now.replace(year=now.year - 1).isoformat()}
    monkeypatch.setattr(O, "read_heartbeat", lambda: hb_old)
    s = R.snapshot()
    assert s["status"] == R.OFFLINE


def test_snapshot_healthy_when_all_fresh(tmp_ledger, make_ft_db, monkeypatch):
    db = make_ft_db()
    now = datetime.now(timezone.utc)
    hb = {"pid": 4242, "last_heartbeat": now.isoformat()}
    _patch_sources(monkeypatch, db, heartbeat=hb, alive=True, candle_age=5.0)
    s = R.snapshot()
    assert s["status"] == R.HEALTHY, s.get("detail")


def test_snapshot_corrupt_db_is_critical(tmp_ledger, monkeypatch):
    from pathlib import Path
    now = datetime.now(timezone.utc)
    hb = {"pid": 4242, "last_heartbeat": now.isoformat()}
    # ft_db_path points at a non-SQLite garbage file -> ft_connect_ro raises
    import tempfile
    bad = Path(tempfile.mkdtemp()) / "tradesv3.sqlite"
    bad.write_text("not a database", encoding="utf-8")
    _patch_sources(monkeypatch, bad, heartbeat=hb, alive=True, candle_age=5.0)
    s = R.snapshot()
    assert s["status"] == R.CRITICAL


def test_snapshot_position_drift_is_critical(tmp_ledger, make_ft_db, monkeypatch):
    db = make_ft_db(trades=[
        (1, "BTC/USD", 1, "2026-10-20", None, 60000.0, None, 1000.0,
         0.0166, 0.001, 0.001, 0.166, None, "USD", None,
         None, None, None, "zscore", 1.0, 0, "BtcZScore", "1d"),
    ])
    now = datetime.now(timezone.utc)
    hb = {"pid": 4242, "last_heartbeat": now.isoformat()}
    # Broker shows 0 qty but Freqtrade has an open 0.0166 BTC position -> drift.
    _patch_sources(monkeypatch, db, heartbeat=hb, alive=True, candle_age=5.0,
                   broker_positions=[])
    s = R.snapshot()
    assert s["status"] == R.CRITICAL


def test_snapshot_external_order_is_review(tmp_ledger, make_ft_db, monkeypatch):
    db = make_ft_db()
    now = datetime.now(timezone.utc)
    hb = {"pid": 4242, "last_heartbeat": now.isoformat()}
    _patch_sources(monkeypatch, db, heartbeat=hb, alive=True, candle_age=5.0,
                   broker_orders=[{"id": "external-1"}])
    s = R.snapshot()
    assert s["status"] == R.REVIEW
