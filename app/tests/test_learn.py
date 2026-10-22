"""Phase D learning-layer tests — pure perf/journal + policy hooks + veto integration.

Nothing here opens a broker connection or places an order. State files (perf.json,
strategy_gate.json) and the ledger DB are always pointed at tmp_path so tests are
hermetic and never touch real learning artifacts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from learn import journal, perf
from risk import policy


# ------------------------------------------------------------------ perf (pure)
def test_summarize_empty_is_all_none_fail_closed():
    s = perf.summarize([])
    assert s["n"] == 0
    for k in ("win_rate", "avg_R", "expectancy_R", "profit_factor",
              "gross_win", "gross_loss", "realized_pnl"):
        assert s[k] is None, f"{k} must be None when n=0, got {s[k]!r}"


def test_summarize_basic_win_loss_split():
    recs = [
        {"r": 1.5, "pnl": 15.0},
        {"r": -0.5, "pnl": -5.0},
        {"r": 2.0, "pnl": 20.0},
        {"r": None, "pnl": None},   # ignored (fail-closed)
    ]
    s = perf.summarize(recs)
    assert s["n"] == 3
    assert s["win_rate"] == round(2 / 3, 4)
    assert s["avg_R"] == round((1.5 - 0.5 + 2.0) / 3, 4)
    assert s["expectancy_R"] == s["avg_R"]
    assert s["gross_win"] == 3.5
    assert s["gross_loss"] == 0.5
    assert s["profit_factor"] == 7.0
    assert s["realized_pnl"] == 30.0


def test_by_pair_family_groups_keyed_correctly():
    recs = [
        {"pair": "BTC/USD", "family": "daily_zscore", "r": 1.0, "pnl": 10.0},
        {"pair": "BTC/USD", "family": "daily_zscore", "r": -0.5, "pnl": -5.0},
        {"pair": "ETH/USD", "family": "momentum_ema_vol", "r": 0.7, "pnl": 7.0},
    ]
    g = perf.by_pair_family(recs)
    assert set(g) == {"BTC/USD|daily_zscore", "ETH/USD|momentum_ema_vol"}
    assert g["BTC/USD|daily_zscore"]["n"] == 2
    assert g["ETH/USD|momentum_ema_vol"]["n"] == 1


def test_should_demote_boundaries():
    # Not enough data -> never demote (young strategies are not punished).
    assert perf.should_demote({"n": 19, "expectancy_R": -0.5}) is False
    # Enough data + negative or zero expectancy -> demote.
    assert perf.should_demote({"n": 20, "expectancy_R": -0.5}) is True
    assert perf.should_demote({"n": 20, "expectancy_R": 0.0}) is True
    # Enough data + positive expectancy -> keep.
    assert perf.should_demote({"n": 20, "expectancy_R": 0.1}) is False
    # Missing expectancy (all-None summarize) -> do not demote.
    assert perf.should_demote({"n": 30, "expectancy_R": None}) is False


def test_size_multiplier_inert_below_n_min_and_clamped_above():
    # Young account -> exactly 1.0 (no scaling).
    assert perf.size_multiplier({"n": 19, "avg_R": 5.0}) == 1.0
    # Enough evidence + strong edge -> clamped to SCALE_MAX (2.0).
    assert perf.size_multiplier({"n": 20, "avg_R": 10.0}) == perf.SCALE_MAX
    # Enough evidence + moderate edge -> linear scale (1 + 0.5*avg_R).
    assert perf.size_multiplier({"n": 20, "avg_R": 1.0}) == 1.5
    # Losing edge (avg_R negative) still keeps m at 1.0 (never shrinks sizing here;
    # the strategy GATE handles losers by demoting).
    assert perf.size_multiplier({"n": 25, "avg_R": -0.4}) == 1.0


# ------------------------------------------------------------------ journal (pure)
def test_r_multiple_fail_closed_when_input_missing():
    assert journal.r_multiple(None, 10.0, 0.05) is None
    assert journal.r_multiple(1.0, None, 0.05) is None
    assert journal.r_multiple(1.0, 10.0, None) is None
    assert journal.r_multiple(1.0, 0.0, 0.05) is None   # planned_risk = 0
    # Happy path: profit 1.5 on stake 10 * 5% stop = 0.5 risk -> 3R.
    assert journal.r_multiple(1.5, 10.0, 0.05) == 3.0


def test_build_journal_writes_rows_with_family_and_R(tmp_path):
    db = tmp_path / "ledger.db"
    con = sqlite3.connect(db)
    # Reuse the real SCHEMA (paper_trades + trade_journal).
    import obs_lib as O
    con.executescript(O.SCHEMA)
    con.execute(
        "INSERT INTO paper_trades (id, pair, is_open, open_date, close_date, "
        "stake_amount, fee_open_cost, fee_close_cost, profit_abs, exit_reason, "
        "enter_tag, timeframe) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, "BTC/USD", 0, "2026-10-01", "2026-10-05", 15.0, 0.05, 0.05, 4.5,
         "exit_signal", "z_cross_up", "1d"),
    )
    con.execute(
        "INSERT INTO paper_trades (id, pair, is_open, open_date, close_date, "
        "stake_amount, fee_open_cost, fee_close_cost, profit_abs, exit_reason, "
        "enter_tag, timeframe) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (2, "ETH/USD", 1, "2026-10-10", None, 10.0, None, None, None,
         None, None, "5m"),   # still open -> ignored
    )
    con.commit()

    n = journal.build_journal(con,
        family_fn=lambda p: {"BTC/USD": "daily_zscore", "ETH/USD": "momentum_ema_vol"}[p],
        stop_fn=lambda p: {"BTC/USD": 0.15, "ETH/USD": 0.03}[p])
    assert n == 1
    rows = journal.closed_records(con)
    assert len(rows) == 1
    btc = rows[0]
    assert btc["pair"] == "BTC/USD" and btc["family"] == "daily_zscore"
    # planned risk = 15 * 0.15 = 2.25 -> R = 4.5 / 2.25 = 2.0
    assert btc["r"] == 2.0
    assert btc["pnl"] == 4.5
    con.close()


# ------------------------------------------------------------------ policy hooks
def _write_state(tmp_path, name: str, payload: dict):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_evidence_multiplier_inert_when_no_perf_file(monkeypatch, tmp_path):
    monkeypatch.setattr(policy, "perf_path", lambda: tmp_path / "perf.json")
    policy.reload_all()
    assert policy.evidence_multiplier("BTC/USD") == 1.0
    # And stake_for_pair is byte-for-byte the base cap on a young account.
    assert policy.stake_for_pair("BTC/USD", 5000) == 15.0
    assert policy.stake_for_pair("ETH/USD", 5000) == 10.0


def test_evidence_multiplier_and_stake_scale_with_perf(tmp_path, monkeypatch):
    perf_file = _write_state(tmp_path, "perf.json", {"by_pair_family": {
        "BTC/USD|daily_zscore": {"n": 25, "avg_R": 3.0},   # m would be 2.5 -> clamp 2.0
        "ETH/USD|momentum_ema_vol": {"n": 22, "avg_R": 0.4},  # m = 1.2
    }})
    monkeypatch.setattr(policy, "perf_path", lambda: perf_file)
    policy.reload_all()
    assert policy.evidence_multiplier("BTC/USD") == 2.0     # clamped to MAX_EVIDENCE_SCALE
    assert policy.evidence_multiplier("ETH/USD") == 1.2
    # stake scales: BTC base 15 -> 30 (bounded by cap * MAX_EVIDENCE_SCALE = 30).
    assert policy.stake_for_pair("BTC/USD", 5000) == 30.0
    assert policy.stake_for_pair("ETH/USD", 5000) == 12.0
    # A pair with no entry in perf.json stays at m=1.0 (never blindly scaled up).
    assert policy.evidence_multiplier("DOT/USD") == 1.0


def test_is_demoted_flips_is_tradeable(tmp_path, monkeypatch):
    gate = _write_state(tmp_path, "strategy_gate.json", {
        "demoted": [{"pair": "ETH/USD", "family": "momentum_ema_vol", "since": "t"}],
    })
    monkeypatch.setattr(policy, "strategy_gate_path", lambda: gate)
    policy.reload_all()
    assert policy.is_demoted("ETH/USD") is True
    assert policy.is_demoted("BTC/USD") is False
    # The tradeable lookup respects the gate.
    assert policy.is_tradeable("ETH/USD") is False
    assert policy.is_tradeable("BTC/USD") is True
    assert "ETH/USD" not in policy.tradeable_pairs()


def test_is_demoted_defaults_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "strategy_gate_path", lambda: tmp_path / "nope.json")
    policy.reload_all()
    assert policy.is_demoted("BTC/USD") is False
    assert policy.is_tradeable("BTC/USD") is True


# ------------------------------------------------------------------ veto integration
def test_per_position_pct_equity_guard_blocks_oversized_entry(monkeypatch, tmp_path):
    """Plan §3 hard ceiling: no single position may exceed 20% of equity, regardless
    of the per-pair cap or evidence scaling. Simulate a grown account where base cap
    (15) is much smaller than 20% of equity, then an entry that scales past 20% via
    evidence multiplier — the new step 6b must reject it."""
    # Fresh tmp state files (isolate from any real repo perf/gate).
    monkeypatch.setattr(policy, "perf_path", lambda: tmp_path / "perf.json")
    monkeypatch.setattr(policy, "strategy_gate_path", lambda: tmp_path / "gate.json")
    monkeypatch.setattr(policy, "kill_switch_path", lambda: tmp_path / "ks.json")
    monkeypatch.setattr(policy, "equity_path", lambda: tmp_path / "eq.json")
    monkeypatch.setattr(policy, "rejections_path", lambda: tmp_path / "rej.json")
    monkeypatch.setattr(policy, "open_exposure_path", lambda: tmp_path / "exp.json")
    policy.reload_all()

    # Equity is grown so per-position cap (15 * 2 = 30) is under 20% of equity.
    policy.write_json(policy.equity_path(),
                      {"equity": 100.0, "asof": datetime.now(timezone.utc).isoformat()})
    policy.write_json(policy.open_exposure_path(),
                      {"asof": datetime.now(timezone.utc).isoformat(),
                       "executors": {"daily": 0.0, "fast": 0.0, "swing": 0.0}})

    import PaperAutonomous as PA
    obj = PA.PaperAutonomous.__new__(PA.PaperAutonomous)

    # Notional $25 vs $100 equity -> 25% > 20% -> REJECTED at step 6b.
    class _NoTrades:
        @staticmethod
        def get_trades_proxy(*_a, **_k):
            return []
    import freqtrade.persistence
    monkeypatch.setattr(freqtrade.persistence.Trade, "get_trades_proxy",
                        staticmethod(lambda *a, **k: []))
    ok = obj.confirm_trade_entry("BTC/USD", "market", 25.0 / 80000.0, 80000.0,
                                 "GTC", datetime.now(timezone.utc), "tag", "long")
    assert ok is False
    items = policy.read_json(policy.rejections_path()).get("items", [])
    assert items and items[-1]["code"] == "PER_POSITION_PCT_EQUITY"

    # Notional $8 -> under 20% equity ($20) and under 15 base cap -> ACCEPTED.
    ok = obj.confirm_trade_entry("BTC/USD", "market", 8.0 / 80000.0, 80000.0,
                                 "GTC", datetime.now(timezone.utc), "tag", "long")
    assert ok is True


def test_per_position_cap_allows_evidence_scaled_stake_under_20pct_equity(monkeypatch, tmp_path):
    """The 15 base cap on BTC becomes 30 after MAX_EVIDENCE_SCALE=2. On a $1000
    account 20% = $200, so a $25 stake (m=1.67) fits under both. Sanity-check the
    veto lets it through, which proves step 5 was correctly relaxed."""
    for name in ("perf", "strategy_gate", "kill_switch", "equity",
                 "risk_rejections", "open_exposure"):
        monkeypatch.setattr(policy, f"{name}_path" if name != "risk_rejections" else "rejections_path",
                            lambda n=name: tmp_path / f"{n}.json")
    # Simpler: point each explicitly.
    monkeypatch.setattr(policy, "perf_path", lambda: tmp_path / "perf.json")
    monkeypatch.setattr(policy, "strategy_gate_path", lambda: tmp_path / "gate.json")
    monkeypatch.setattr(policy, "kill_switch_path", lambda: tmp_path / "ks.json")
    monkeypatch.setattr(policy, "equity_path", lambda: tmp_path / "eq.json")
    monkeypatch.setattr(policy, "rejections_path", lambda: tmp_path / "rej.json")
    monkeypatch.setattr(policy, "open_exposure_path", lambda: tmp_path / "exp.json")
    policy.reload_all()

    # Inject a perf so BTC earns m = 1 + 0.5 * 1.5 = 1.75 -> stake = 15 * 1.75 = 26.25
    _write_state(tmp_path, "perf.json", {"by_pair_family": {
        "BTC/USD|daily_zscore": {"n": 22, "avg_R": 1.5},
    }})
    policy.write_json(policy.equity_path(),
                      {"equity": 1000.0, "asof": datetime.now(timezone.utc).isoformat()})
    policy.write_json(policy.open_exposure_path(),
                      {"asof": datetime.now(timezone.utc).isoformat(),
                       "executors": {"daily": 0.0, "fast": 0.0, "swing": 0.0}})

    # Notional $26.25 -> under 2x cap ($30) AND under 20% of $1000 ($200) -> accept.
    import PaperAutonomous as PA
    import freqtrade.persistence
    monkeypatch.setattr(freqtrade.persistence.Trade, "get_trades_proxy",
                        staticmethod(lambda *a, **k: []))
    obj = PA.PaperAutonomous.__new__(PA.PaperAutonomous)
    ok = obj.confirm_trade_entry("BTC/USD", "market", 26.25 / 80000.0, 80000.0,
                                 "GTC", datetime.now(timezone.utc), "tag", "long")
    assert ok is True


# ------------------------------------------------------------------ learn.py runner
def test_learn_run_once_emits_perf_and_gate(tmp_path, monkeypatch):
    """End-to-end: seed the ledger with 20+ losing closed BTC trades so should_demote
    trips, run the learner, verify perf.json + strategy_gate.json were written and
    that the pair is now demoted via policy.is_demoted (auto-demote path)."""
    import obs_lib as O
    db = tmp_path / "unbound_ledger.db"
    monkeypatch.setattr(O, "LEDGER_DB", db)
    con = O.ledger_connect()
    con.close()
    # Reopen to seed rows before running.
    con = sqlite3.connect(db)
    for i in range(1, 26):
        con.execute(
            "INSERT INTO paper_trades (id, pair, is_open, open_date, close_date, "
            "stake_amount, fee_open_cost, fee_close_cost, profit_abs, exit_reason, "
            "enter_tag, timeframe) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, "BTC/USD", 0, "2026-09-01", "2026-09-02", 15.0, 0.02, 0.02, -1.0,
             "exit_signal", "z_cross_up", "1d"),
        )
    con.commit()
    con.close()

    # Point state files at tmp_path so we never touch the real app/state/.
    monkeypatch.setattr(policy, "perf_path", lambda: tmp_path / "perf.json")
    monkeypatch.setattr(policy, "strategy_gate_path", lambda: tmp_path / "gate.json")
    policy.reload_all()

    import learner as L
    rc = L.run_once()
    assert rc == 0

    perf_payload = json.loads((tmp_path / "perf.json").read_text(encoding="utf-8"))
    stats = perf_payload["by_pair_family"]["BTC/USD|daily_zscore"]
    assert stats["n"] == 25
    assert stats["expectancy_R"] < 0   # all losses

    gate_payload = json.loads((tmp_path / "gate.json").read_text(encoding="utf-8"))
    assert any(d["pair"] == "BTC/USD" for d in gate_payload["demoted"])
    assert policy.is_demoted("BTC/USD") is True


def test_learn_gate_is_append_only_no_auto_promote(tmp_path, monkeypatch):
    """A pair that was demoted in a prior run stays demoted even if the newest stats
    look better: promotion requires owner edit, never an automatic overwrite."""
    existing = {"demoted": [
        {"pair": "ETH/USD", "family": "momentum_ema_vol",
         "since": "2026-10-01T00:00:00Z", "reason": "prior evidence"}]}
    gate_file = tmp_path / "gate.json"
    gate_file.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(policy, "strategy_gate_path", lambda: gate_file)
    monkeypatch.setattr(policy, "perf_path", lambda: tmp_path / "perf.json")

    # No new demotions (empty stats) -> the old demotion must survive verbatim.
    import learner as L
    merged = L._merge_gate(existing, [])
    assert len(merged["demoted"]) == 1
    assert merged["demoted"][0]["since"] == "2026-10-01T00:00:00Z"
    assert merged["demoted"][0]["reason"] == "prior evidence"
