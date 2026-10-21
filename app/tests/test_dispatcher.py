"""PaperAutonomous dispatcher tests: BTC parity, alt routing, status-only gating,
and the automatic (no-manual-approval) entry veto. No orders, no network."""
from __future__ import annotations

import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from BtcZScore import BtcZScore
from PaperAutonomous import PaperAutonomous
from risk import policy


def _new():
    return PaperAutonomous.__new__(PaperAutonomous)


def _stub():
    return types.SimpleNamespace(
        zscore_period=BtcZScore.zscore_period,
        bull_threshold=BtcZScore.bull_threshold,
        exit_threshold=BtcZScore.exit_threshold,
    )


def _df(closes, volume=1.0):
    n = len(closes)
    v = volume if not np.isscalar(volume) else [volume] * n
    return pd.DataFrame({"open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": list(closes),
                         "volume": list(v)})


def _spike_series():
    closes = [float(c) for c in range(140, 60, -1)]      # declining => z negative
    idx = len(closes)
    closes = closes + [220.0, 225.0, 230.0]              # fresh bullish cross
    return closes, idx


def test_dispatcher_is_a_btczscore_subclass():
    assert issubclass(PaperAutonomous, BtcZScore)
    assert PaperAutonomous.timeframe == "1d"
    assert PaperAutonomous.can_short is False


def test_btc_branch_is_bit_identical_to_baseline():
    closes, idx = _spike_series()
    base = BtcZScore.populate_indicators(_stub(), _df(closes).copy(), {})
    base = BtcZScore.populate_entry_trend(_stub(), base, {})
    obj = _new()
    disp = obj.populate_indicators(_df(closes).copy(), {"pair": "BTC/USD"})
    disp = obj.populate_entry_trend(disp, {"pair": "BTC/USD"})
    pd.testing.assert_series_equal(base["enter_long"].fillna(0),
                                   disp["enter_long"].fillna(0), check_names=False)
    assert disp.loc[idx, "enter_long"] == 1


def test_alt_experimental_entry_fires_and_is_tagged():
    closes, idx = _spike_series()
    obj = _new()
    d = obj.populate_indicators(_df(closes).copy(), {"pair": "ETH/USD"})
    d = obj.populate_entry_trend(d, {"pair": "ETH/USD"})
    assert d.loc[idx, "enter_long"] == 1
    assert str(d.loc[idx, "enter_tag"]).startswith("EXPERIMENTAL")


@pytest.mark.parametrize("pair", ["USDT/USD", "FOO/USD"])
def test_status_only_and_unsupported_generate_no_entry(pair):
    closes, _ = _spike_series()
    obj = _new()
    d = obj.populate_indicators(_df(closes).copy(), {"pair": pair})
    d = obj.populate_entry_trend(d, {"pair": pair})
    assert int((d["enter_long"].fillna(0) == 1).sum()) == 0


@pytest.fixture
def veto(monkeypatch):
    """Neutral side effects so confirm_trade_entry is hermetic."""
    monkeypatch.setattr(policy, "log_rejection", lambda *a, **k: None)
    monkeypatch.setattr(policy, "is_blocked", lambda: {"blocked": False, "reason": ""})
    # Default: a FRESH cross-executor ledger reporting the other bot holds nothing, so
    # the exposure gate is exercised against a known state (individual tests override).
    monkeypatch.setattr(policy, "external_exposure",
                        lambda *a, **k: {"external": 0.0, "known": True})
    return monkeypatch


def _trades(monkeypatch, items):
    class _T:
        def __init__(self, pair, stake): self.pair = pair; self.stake_amount = stake
    monkeypatch.setattr("freqtrade.persistence.Trade.get_trades_proxy",
                        staticmethod(lambda *a, **k: [_T(p, s) for p, s in items]))


def test_valid_entry_auto_approved_without_manual_step(veto):
    _trades(veto, [])
    veto.setattr(policy, "get_equity", lambda *a, **k: {"equity": 100000.0})
    obj = _new()
    ok = obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                 datetime.now(timezone.utc), "tag", "long")
    assert ok is True


def test_rejects_unsupported_pair(veto):
    obj = _new()
    assert obj.confirm_trade_entry("USDT/USD", "market", 1, 1, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_rejects_when_circuit_breaker_active(veto):
    veto.setattr(policy, "is_blocked", lambda: {"blocked": True, "reason": "daily_loss"})
    obj = _new()
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_rejects_on_stale_or_unknown_equity(veto):
    veto.setattr(policy, "get_equity", lambda *a, **k: {})
    obj = _new()
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_rejects_over_per_position_cap(veto):
    veto.setattr(policy, "get_equity", lambda *a, **k: {"equity": 100000.0})
    _trades(veto, [])
    obj = _new()
    # notional 8000 > BTC cap 5000 -> rejected (amount*rate too big)
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.1, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_rejects_when_pair_already_open(veto):
    veto.setattr(policy, "get_equity", lambda *a, **k: {"equity": 100000.0})
    _trades(veto, [("BTC/USD", 4000.0)])
    obj = _new()
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_rejects_when_exposure_cap_would_breach(veto):
    veto.setattr(policy, "get_equity", lambda *a, **k: {"equity": 100000.0})
    _trades(veto, [("ETH/USD", 9000.0)])   # 9000 open + new BTC 4800 > 10000 cap
    obj = _new()
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_rejects_when_exposure_ledger_unavailable(veto):
    # Fail-closed: a missing/stale cross-executor ledger means the GLOBAL exposure
    # cannot be verified, so the entry is vetoed even with fresh equity.
    veto.setattr(policy, "get_equity", lambda *a, **k: {"equity": 100000.0})
    veto.setattr(policy, "external_exposure",
                 lambda *a, **k: {"external": 0.0, "known": False, "reason": "stale"})
    _trades(veto, [])
    obj = _new()
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False


def test_other_executor_exposure_counts_toward_global_cap(veto):
    # BTC's own DB is empty, but the FAST executor already holds 9000; adding BTC 4800
    # would breach the 10000 GLOBAL cap — the only way to see this is via the ledger.
    veto.setattr(policy, "get_equity", lambda *a, **k: {"equity": 100000.0})
    veto.setattr(policy, "external_exposure",
                 lambda *a, **k: {"external": 9000.0, "known": True})
    _trades(veto, [])
    obj = _new()
    assert obj.confirm_trade_entry("BTC/USD", "market", 0.06, 80000.0, "GTC",
                                   datetime.now(timezone.utc), "t", "long") is False
