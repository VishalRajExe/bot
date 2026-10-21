"""Execution-safety tests — fail-closed config gates and 'submit != filled'.

Our app layer never places orders; Freqtrade does. So "execution safety" here is
about the guarantees that keep trading DISABLED and the observation honest:

  * preflight.audit_config fails closed (BLOCK) on any unsafe/missing config, and
    is only 'ready' when an owner risk-approval record actually exists — we never
    invent one.
  * reconciliation never assumes a submitted order filled: an order Freqtrade
    still lists as open but the broker does not show as open is surfaced as an
    unresolved item (REVIEW), never silently HEALTHY.
  * ledger mirroring is idempotent, so a replayed observation cannot create
    duplicate trade/order rows.

No credentials, no network, no orders.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import obs_lib as O
import preflight as P
import reconcile as R


def _safe_cfg(**over):
    cfg = {
        "dry_run": False,
        "trading_mode": "spot",
        "margin_mode": "",
        "max_open_trades": 1,
        "stake_amount": 1000,
        "exchange": {"key": "", "secret": "",
                     "ccxt_config": {"urls": {"api": {
                         "trader": "https://paper-api.alpaca.markets"}}}},
    }
    cfg.update(over)
    return cfg


def _safe_meta(**over):
    meta = {"can_short": False, "leverage": 1.0, "stoploss": -0.35,
            "protections_count": 3, "bull_threshold": 0.5,
            "exit_threshold": 0.0}
    meta.update(over)
    return meta


def _codes(findings):
    return {x["code"] for x in findings}


# ---- fail-closed config gates ------------------------------------------------

def test_live_endpoint_is_blocked():
    cfg = _safe_cfg()
    cfg["exchange"]["ccxt_config"]["urls"]["api"]["trader"] = "https://api.alpaca.markets"
    ready, f = P.audit_config(cfg, _safe_meta())
    assert ready is False
    assert "LIVE_ENDPOINT" in _codes(f)
    assert any(x["level"] == "BLOCK" for x in f if x["code"] == "LIVE_ENDPOINT")


def test_missing_endpoint_blocked():
    cfg = _safe_cfg()
    cfg["exchange"]["ccxt_config"]["urls"]["api"]["trader"] = ""
    ready, f = P.audit_config(cfg, _safe_meta())
    assert "ENDPOINT_MISSING" in _codes(f)


def test_inline_secrets_blocked():
    cfg = _safe_cfg()
    cfg["exchange"]["key"] = "AKIA_fake"
    ready, f = P.audit_config(cfg, _safe_meta())
    assert "INLINE_SECRETS" in _codes(f)


def test_short_enabled_blocked():
    ready, f = P.audit_config(_safe_cfg(), _safe_meta(can_short=True))
    assert "SHORT_ENABLED" in _codes(f)


def test_leverage_blocked():
    ready, f = P.audit_config(_safe_cfg(), _safe_meta(leverage=3.0))
    assert "LEVERAGE_ON" in _codes(f)


def test_missing_protections_blocked():
    ready, f = P.audit_config(_safe_cfg(), _safe_meta(protections_count=0))
    assert "NO_PROTECTIONS" in _codes(f)


def test_no_stoploss_blocked():
    ready, f = P.audit_config(_safe_cfg(), _safe_meta(stoploss=None))
    assert "NO_STOPLOSS" in _codes(f)


def test_unset_threshold_blocked():
    ready, f = P.audit_config(_safe_cfg(), _safe_meta(bull_threshold=None))
    assert "THRESHOLD_UNSET" in _codes(f)


def test_missing_approval_keeps_trading_disabled(monkeypatch):
    # Even a perfectly safe config is NOT ready without an owner approval record.
    # Hermetic: force the approval-missing state regardless of the real repo file.
    monkeypatch.setattr(P, "approval_exists", lambda: False)
    ready, f = P.audit_config(_safe_cfg(), _safe_meta())
    assert ready is False
    assert "RISK_APPROVAL_MISSING" in _codes(f)


def test_unlimited_stake_warns(monkeypatch):
    monkeypatch.setattr(P, "approval_exists", lambda: True)
    ready, f = P.audit_config(_safe_cfg(stake_amount="unlimited"), _safe_meta())
    assert "UNLIMITED_STAKE" in _codes(f)   # WARN, not silent


def test_safe_config_with_approval_is_ready(monkeypatch):
    monkeypatch.setattr(P, "approval_exists", lambda: True)
    ready, f = P.audit_config(_safe_cfg(), _safe_meta())
    assert ready is True, _codes(f)
    assert not any(x["level"] == "BLOCK" for x in f)


# ---- "submitting an order does not mean it filled" ---------------------------

def test_ft_order_not_open_at_broker_is_never_healthy():
    sig = {
        "ft_db_ok": True, "live_endpoint_suspected": False, "qty_drift": 0.0,
        "broker_position_qty": 0.0, "ft_open_amount": 0.0,
        "heartbeat_age_s": 5.0, "process_alive": True, "broker_ok": True,
        "candle_age_h": 3.0, "active_locks": 0, "unmatched_broker_orders": 0,
        "ft_unresolved_orders": 1,   # FT still open, broker doesn't list it
    }
    status, _ = R.classify_status(sig)
    assert status == R.REVIEW           # flagged, never HEALTHY
    assert status != R.HEALTHY


def test_order_identity_flags_both_directions():
    unmatched, unresolved = R.reconcile_order_identity(
        broker_open_ids=["b1", "b2"], ft_open_ids=["b1", "f9"])
    assert unmatched == 1   # b2 is external (not owned by FT)
    assert unresolved == 1  # f9 is FT-open but not confirmed open at the broker


# ---- idempotent mirroring (no duplicate rows on replay) ----------------------

def _patched_sources(monkeypatch, ft_db):
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    cfgp = d / "cfg.json"
    cfgp.write_text(json.dumps({"strategy": "BtcZScore", "exchange": {
        "ccxt_config": {"urls": {"api": {"trader": "https://paper-api.alpaca.markets"}}}}}),
        encoding="utf-8")
    monkeypatch.setattr(O, "PAPER_CFG", cfgp)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(O, "read_heartbeat",
                        lambda: {"pid": 1, "last_heartbeat": now.isoformat()})
    monkeypatch.setattr(R, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(O, "latest_candle_age_hours", lambda *a, **k: 3.0)
    monkeypatch.setattr(O, "ft_db_path", lambda: ft_db)

    def fake_get(path, timeout=15):
        if path == "/v2/account":
            return 200, {"cash": 1.0, "equity": 1.0, "buying_power": 1.0}
        return 200, []
    monkeypatch.setattr(O, "alpaca_get", fake_get)


def test_snapshot_replay_is_idempotent(tmp_ledger, make_ft_db, monkeypatch):
    db = make_ft_db(trades=[
        (7, "BTC/USD", 0, "2026-10-01", "2026-10-10", 50000.0, 55000.0, 1000.0,
         0.02, 0.001, 0.001, 0.05, 0.055, "USD", "USD",
         0.1, 100.0, "exit_signal", "zscore", 1.0, 0, "BtcZScore", "1d"),
    ])
    _patched_sources(monkeypatch, db)
    R.snapshot()
    R.snapshot()
    R.snapshot()
    con = O.ledger_connect()
    try:
        n = con.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
    finally:
        con.close()
    assert n == 1   # mirrored by Freqtrade id, never duplicated across replays
