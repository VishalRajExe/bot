"""Independent paper-risk policy tests — pure calculation + fail-closed, no orders, no net."""
from __future__ import annotations

from risk import policy


def setup_function(_):
    policy.reload_all()


def test_btc_stake_preserved_and_alt_bounded():
    assert policy.max_stake_usd("BTC/USD") == 5000.0
    assert policy.max_planned_loss_usd("BTC/USD") is None          # baseline never loss-capped down
    assert policy.stake_for_pair("BTC/USD", 5000) == 5000.0
    assert policy.stake_for_pair("BTC/USD", 99999) == 5000.0        # capped at 5000
    assert policy.stake_for_pair("ETH/USD", 5000) == 1000.0         # alt stake cap


def test_tradeable_vs_status_only_sets():
    tp = policy.tradeable_pairs()
    assert "BTC/USD" in tp and "ETH/USD" in tp
    assert "USDT/USD" in policy.status_only_pairs()
    assert not policy.is_tradeable("USDT/USD")


def test_exposure_cap_is_lower_of_fixed_and_pct_equity():
    assert policy.exposure_cap_usd(100000) == 10000.0              # fixed cap binds
    assert policy.exposure_cap_usd(50000) == 5000.0                # 10% binds
    assert policy.exposure_cap_usd(30000) == 3000.0


def test_exposure_cap_fail_closed_when_equity_unknown():
    # equity unknown -> caller must treat as unable to size; would_breach returns True
    assert policy.would_breach_exposure(0, 1000, None) is True


def test_would_breach_exposure_math():
    assert policy.would_breach_exposure(9000, 1500, 100000) is True   # 10500 > 10000
    assert policy.would_breach_exposure(9000, 500, 100000) is False


def test_breaker_daily_loss_and_drawdown():
    br = policy.breaker_status(equity=98000, sod_equity=100000, peak_equity=100000)
    assert br["triggered"] is True
    assert any("daily_equity_loss" in r for r in br["reasons"])
    br2 = policy.breaker_status(equity=94000, sod_equity=98000, peak_equity=100000)
    assert br2["triggered"] is True
    assert any("peak_to_trough_drawdown" in r for r in br2["reasons"])
    br3 = policy.breaker_status(equity=99500, sod_equity=100000, peak_equity=100000)
    assert br3["triggered"] is False


def test_kill_switch_roundtrip(tmp_path, monkeypatch):
    ks = tmp_path / "kill_switch.json"
    monkeypatch.setattr(policy, "kill_switch_path", lambda: ks)
    assert policy.is_blocked()["blocked"] is False
    policy.set_kill_switch(True, "daily_equity_loss")
    assert policy.is_blocked()["blocked"] is True
    policy.set_kill_switch(False, "manual recovery")
    assert policy.is_blocked()["blocked"] is False


def test_rejection_log_roundtrip(tmp_path, monkeypatch):
    rp = tmp_path / "risk_rejections.json"
    monkeypatch.setattr(policy, "rejections_path", lambda: rp)
    policy.log_rejection("ETH/USD", "EXPOSURE_CAP", "would exceed cap", {"x": 1})
    items = policy.read_json(rp)["items"]
    assert items[-1]["pair"] == "ETH/USD" and items[-1]["code"] == "EXPOSURE_CAP"


def test_real_config_validates_clean():
    import json
    from pathlib import Path
    cfg = json.loads((Path(__file__).resolve().parents[1] / "configs" /
                      "config.alpaca.paper.json").read_text(encoding="utf-8"))
    assert policy.validate_policy(policy.policy()) == []
    assert policy.validate_registry(policy.registry()) == []
    assert policy.validate_config(cfg) == []
