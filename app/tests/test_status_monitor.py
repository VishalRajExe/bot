"""Read-only status monitor: notify-on-change dedupe regression tests.

Guards the false-change bug (sweep key is a tuple, JSON state returns a list;
tuple != list in Python, so without normalization every sweep re-alerted).
build_asset/send/state IO are stubbed — no network, no Telegram, no orders.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crypto_status_monitor as M  # noqa: E402


def _asset(signal="HOLD", pos=None, order="no open position", status="ACTIVE_BASELINE"):
    return {"symbol": "BTC/USD", "signal": signal, "position": pos,
            "order_state": order, "status": status}


def test_sweep_alerts_once_then_dedupes(tmp_path, monkeypatch):
    state_file = tmp_path / "crypto_status.json"
    monkeypatch.setattr(M, "STATE_PATH", state_file)
    monkeypatch.setattr(M, "open_positions", lambda *_a: {})
    monkeypatch.setattr(M, "update_equity_and_breaker",
                        lambda *_a: {"blocked": False, "equity": 100000.0})
    sent: list[str] = []
    monkeypatch.setattr(M, "send", lambda _e, text: (sent.append(text), True)[1])
    monkeypatch.setattr(M, "format_asset_status", lambda a: f"{a['symbol']} {a['signal']}")
    asset = {"BTC/USD": _asset()}
    monkeypatch.setattr(M, "build_asset",
                        lambda _e, _h, pair, _p, _b: dict(asset[pair]))

    assert M.sweep({}, {}, ["BTC/USD"], notify_mode="full") == 1   # initial alert
    assert M.sweep({}, {}, ["BTC/USD"], notify_mode="changes") == 0  # unchanged -> silent
    asset["BTC/USD"] = _asset(signal="BUY")                        # real signal change
    assert M.sweep({}, {}, ["BTC/USD"], notify_mode="changes") == 1
    assert M.sweep({}, {}, ["BTC/USD"], notify_mode="changes") == 0


def test_position_appearance_is_a_change(tmp_path, monkeypatch):
    state_file = tmp_path / "crypto_status.json"
    monkeypatch.setattr(M, "STATE_PATH", state_file)
    monkeypatch.setattr(M, "open_positions", lambda *_a: {})
    monkeypatch.setattr(M, "update_equity_and_breaker",
                        lambda *_a: {"blocked": False, "equity": 100000.0})
    monkeypatch.setattr(M, "send", lambda _e, text: True)
    monkeypatch.setattr(M, "format_asset_status", lambda a: a["signal"])
    no_pos = {"BTC/USD": _asset()}
    with_pos = {"BTC/USD": _asset(pos={"qty": 0.06}, order="OPEN (confirmed filled)")}
    box = {"data": no_pos}
    monkeypatch.setattr(M, "build_asset",
                        lambda _e, _h, pair, _p, _b: dict(box["data"][pair]))
    M.sweep({}, {}, ["BTC/USD"], notify_mode="full")
    box["data"] = with_pos
    assert M.sweep({}, {}, ["BTC/USD"], notify_mode="changes") == 1
