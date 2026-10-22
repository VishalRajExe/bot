"""Supervisor (Phase F) structural tests. Never spawns a subprocess — verifies the
watchdog's decision logic (kill-switch refusal, backoff ladder, spec assembly)."""
from __future__ import annotations

import time

import pytest

from risk import policy
import supervise as S


def test_default_specs_always_includes_monitor_and_learner():
    specs = S.default_specs(include=["daily"], with_learner=True)
    names = [m.name for m in specs]
    assert "monitor" in names
    assert "learner" in names
    assert "executor-daily" in names
    # fast + swing must NOT be spawned unless explicitly requested (staged rollout).
    assert "executor-fast" not in names
    assert "executor-swing" not in names


def test_default_specs_all_include_three_executors():
    specs = S.default_specs(include=["daily", "fast", "swing"], with_learner=True)
    names = {m.name for m in specs}
    assert {"executor-daily", "executor-fast", "executor-swing"} <= names


def test_default_specs_no_learner_flag():
    specs = S.default_specs(include=["daily"], with_learner=False)
    assert all(m.name != "learner" for m in specs)


def test_executors_are_kind_executor_and_observers_are_kind_always():
    """The kill-switch rule applies ONLY to order executors; the monitor and learner
    must keep running even when the breaker is tripped so the operator still sees
    state and can recover."""
    specs = S.default_specs(include=["daily", "fast", "swing"], with_learner=True)
    kinds = {m.name: m.kind for m in specs}
    assert kinds["monitor"] == "always"
    assert kinds["learner"] == "always"
    for n in ("executor-daily", "executor-fast", "executor-swing"):
        assert kinds[n] == "executor"


def test_backoff_ladder_caps_and_resets_after_stable_run():
    m = S.Managed("t", ["true"], kind="always")
    # Ladder progresses: 5, 10, 30, 60, then stays at 60 (capped).
    assert m.next_sleep() == 5
    assert m.next_sleep() == 10
    assert m.next_sleep() == 30
    assert m.next_sleep() == 60
    assert m.next_sleep() == 60
    # Simulate a stable run -> reset the counter so a fresh crash restarts fast.
    m.started_at = time.time() - (S.STABLE_RESET_S + 1)
    m.note_stable()
    assert m.backoff_i == 0
    assert m.next_sleep() == 5


def test_kill_switch_refuses_relaunch_of_executors(tmp_path, monkeypatch):
    """Core Phase F rule: NEVER relaunch an order executor while the circuit breaker
    is active. Alerts instead. The monitor + learner still tick."""
    monkeypatch.setattr(policy, "kill_switch_path", lambda: tmp_path / "ks.json")
    policy.reload_all()
    policy.set_kill_switch(True, "unit test breaker")

    specs = S.default_specs(include=["daily"], with_learner=False)
    daily = next(s for s in specs if s.name == "executor-daily")
    assert daily.proc is None

    sent: list[str] = []
    monkeypatch.setattr(S, "_send_telegram", lambda text: sent.append(text) or True)
    monkeypatch.setattr(S, "_log", lambda *_a, **_k: None)

    # First tick on a never-started executor: it must NOT spawn while the breaker is
    # tripped, and it must have emitted exactly one Telegram alert.
    S._tick(specs)
    assert daily.proc is None, "executor must remain unspawned while kill-switch active"
    assert any("REFUSED RELAUNCH" in m for m in sent), sent
    # Second tick within the throttle window -> no duplicate alert.
    n_before = len(sent)
    S._tick(specs)
    assert len(sent) == n_before, "refusal alert must be throttled, not spammed"


def test_kill_switch_does_not_stop_monitor_or_learner(tmp_path, monkeypatch):
    """"always"-kind processes are never blocked by the kill-switch; the operator
    still needs state visibility during an incident."""
    monkeypatch.setattr(policy, "kill_switch_path", lambda: tmp_path / "ks.json")
    policy.reload_all()
    policy.set_kill_switch(True, "unit test breaker")

    launched: list[str] = []

    class _FakeProc:
        def __init__(self, name): self.name = name
        def poll(self): return None
        def send_signal(self, *_a): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass
        pid = 4242

    def _fake_start(self):
        launched.append(self.name)
        self.proc = _FakeProc(self.name)
        self.started_at = time.time()

    monkeypatch.setattr(S.Managed, "start", _fake_start)
    monkeypatch.setattr(S, "_log", lambda *_a, **_k: None)
    monkeypatch.setattr(S, "_send_telegram", lambda *_a, **_k: False)

    specs = S.default_specs(include=["daily"], with_learner=True)
    S._tick(specs)

    assert "monitor" in launched
    assert "learner" in launched
    assert "executor-daily" not in launched


def test_alert_helper_uses_telegram_and_logs(tmp_path, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(S, "_send_telegram", lambda text: sent.append(text) or True)
    logged: list[str] = []
    monkeypatch.setattr(S, "_log", lambda msg: logged.append(msg))
    S._alert("X", "detail")
    assert sent and "SUPERVISOR" in sent[0] and "X" in sent[0]
    assert logged and "SUPERVISOR" in logged[0]
