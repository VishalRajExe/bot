"""Windows process-lifecycle tests for the Job Object containment fix (Audit §11.3).

Two layers:

* Portable unit tests (run anywhere): the supervisor's fail-closed behaviour when
  containment is impossible, Ctrl+C handler state, and the shutdown-summary drain.
* Windows integration tests (skipif non-Windows): they spawn REAL dummy processes
  (``_dummy_worker.py`` / ``_dummy_supervisor.py``) — never the production trading
  supervisor, never any order/network — and prove the OS-level guarantees:
  graceful drain, force-kill teardown of child+grandchild, descendant containment,
  unrelated-process safety, fail-closed on assignment error, idempotent shutdown,
  clean restart, and accurate early-failure health reporting.

Every integration test tracks the PIDs it creates and force-cleans them in a
finally so a failed assertion can never leak a process.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

win_only = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Job Object behaviour is OS-specific"
)

import win_job  # noqa: E402  (conftest puts app/scripts on sys.path)
import supervise as S  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "_dummy_worker.py")
SUPERVISOR = os.path.join(HERE, "_dummy_supervisor.py")

psutil = pytest.importorskip("psutil")


# ------------------------------------------------------------- helpers
def _read_pid(path: str) -> int | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read().strip()
        return int(txt) if txt else None
    except (FileNotFoundError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    if not psutil.pid_exists(pid):
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        # pid exists but we cannot open it (transient during teardown) => treat as alive.
        return True


def _wait(pred, timeout: float, interval: float = 0.1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


def _force_cleanup(pids: list[int | None]) -> None:
    for pid in pids:
        if pid is None:
            continue
        try:
            p = psutil.Process(pid)
            if p.is_running():
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


# ============================================================ portable unit tests
def test_fail_closed_when_containment_raises(monkeypatch):
    """Managed.start must NOT launch an unprotected worker: a containment error
    marks the spec failed, leaves proc None, and never retries."""
    from win_job import ContainmentError

    def _boom(*_a, **_k):
        raise ContainmentError("simulated AssignProcessToJobObject failure")

    monkeypatch.setattr(S, "spawn_managed", _boom)
    alerts: list[str] = []
    monkeypatch.setattr(S, "_alert", lambda t, d: alerts.append(t))
    monkeypatch.setattr(S, "_log", lambda *_a, **_k: None)

    m = S.Managed("executor-daily", [sys.executable, "-c", "pass"], kind="executor")
    m.start()
    assert m.proc is None
    assert m.failed is True
    assert any("COULD NOT LAUNCH" in a for a in alerts)
    # A retry tick is a no-op once failed.
    m.start()
    assert m.proc is None and m.failed is True


def test_stop_is_idempotent_and_reports_status():
    """stop() must tolerate being called repeatedly and report a status tag."""
    sent: list[int] = []

    class _FakeProc:
        pid = 4242
        def __init__(self): self._alive = True
        def poll(self): return None if self._alive else 0
        def send_signal(self, sig): sent.append(sig)
        def wait(self, timeout=None): self._alive = False; return 0
        def kill(self): self._alive = False
        def close(self): pass

    m = S.Managed("t", ["x"], kind="always")
    m.proc = _FakeProc()
    first = m.stop()
    second = m.stop()
    assert first == "graceful"
    assert second == "already"
    assert sent and sent[0] == signal.CTRL_BREAK_EVENT


def test_drain_closes_job_and_summarises(monkeypatch, capsys):
    """_drain stops every child, then terminates+ closes the job (the OS backstop)."""
    closed = {"terminate": False, "close": False}

    class _Job:
        def terminate(self, _code=0): closed["terminate"] = True
        def close(self): closed["close"] = True

    class _FakeProc:
        pid = 1
        def __init__(self): self._alive = True
        def poll(self): return None if self._alive else 0
        def send_signal(self, _sig): pass
        def wait(self, timeout=None): self._alive = False; return 0
        def kill(self): self._alive = False
        def close(self): pass

    monkeypatch.setattr(S, "_JOB", _Job())
    monkeypatch.setattr(S, "_log", lambda *_a, **_k: None)
    m = S.Managed("monitor", ["x"], kind="always")
    m.proc = _FakeProc()
    S._drain([m])
    assert closed["terminate"] and closed["close"]


def test_ctrl_c_handler_sets_stop_then_second_exit(monkeypatch):
    """The supervisor's SIGINT/SIGTERM handler flips _STOP so main() drains cleanly,
    and a second signal forces SystemExit — it does not depend on Ctrl+C propagating
    to child process groups."""
    monkeypatch.setattr(S, "_log", lambda *_a, **_k: None)
    monkeypatch.setattr(S, "_STOP", {"f": False})
    S._install_stop_handlers()
    handler = signal.getsignal(signal.SIGINT)
    # First signal: set the stop flag, do not raise.
    handler(signal.SIGINT, None)
    assert S._STOP["f"] is True
    # Second signal: hard exit.
    with pytest.raises(SystemExit):
        handler(signal.SIGINT, None)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


# ============================================================ Windows integration
@win_only
def test_A_graceful_shutdown_stops_child_and_grandchild(tmp_path):
    child_pf = str(tmp_path / "child.pid")
    gc_pf = str(tmp_path / "gc.pid")
    job = win_job.JobObject()
    proc = None
    tracked: list[int | None] = []
    try:
        proc = win_job.spawn(
            [sys.executable, WORKER, child_pf, "--grandchild", gc_pf],
            cwd=HERE, job=job,
        )
        assert _wait(lambda: _read_pid(child_pf) and _read_pid(gc_pf), 8.0), \
            "child/grandchild never started"
        cp, gp = _read_pid(child_pf), _read_pid(gc_pf)
        tracked += [cp, gp]
        assert _alive(cp) and _alive(gp), "child/grandchild not alive before drain"
        # Graceful drain: CTRL_BREAK to the child's own group, then wait.
        proc.send_signal(signal.CTRL_BREAK_EVENT)
        proc.wait(timeout=5.0)
        assert _wait(lambda: not _alive(cp), 5.0), "child survived graceful stop"
        assert _wait(lambda: not _alive(gp), 5.0), "grandchild survived graceful stop"
    finally:
        _force_cleanup(tracked)
        if proc is not None:
            proc.close()
        job.close()


@win_only
def test_B_forced_supervisor_kill_reaps_tree(tmp_path):
    """Force-killing the supervisor must make Windows kill child + grandchild."""
    child_pf = str(tmp_path / "child.pid")
    gc_pf = str(tmp_path / "gc.pid")
    sup = subprocess.Popen(
        [sys.executable, SUPERVISOR, child_pf, gc_pf],
        cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    cp = gp = None
    try:
        assert _wait(lambda: _read_pid(child_pf) and _read_pid(gc_pf), 10.0), \
            "supervisor never brought up its contained tree"
        cp, gp = _read_pid(child_pf), _read_pid(gc_pf)
        assert _alive(cp) and _alive(gp), "contained child/grandchild not running"
        # Kill ONLY the supervisor; its job handle closes => contained tree dies.
        sup.kill()
        sup.wait(timeout=10)
        assert _wait(lambda: not _alive(cp), 10.0), \
            "orphaned child survived force-killing the supervisor"
        assert _wait(lambda: not _alive(gp), 10.0), \
            "orphaned grandchild survived force-killing the supervisor"
    finally:
        _force_cleanup([cp, gp, sup.pid])
        try:
            sup.stdout.close()  # type: ignore[union-attr]
        except Exception:
            pass


@win_only
def test_C_descendant_is_contained_and_cleaned(tmp_path):
    """A grandchild we never explicitly assigned is still contained (inherited job)."""
    child_pf = str(tmp_path / "child.pid")
    gc_pf = str(tmp_path / "gc.pid")
    job = win_job.JobObject()
    proc = None
    tracked: list[int | None] = []
    try:
        proc = win_job.spawn(
            [sys.executable, WORKER, child_pf, "--grandchild", gc_pf],
            cwd=HERE, job=job,
        )
        assert _wait(lambda: _read_pid(child_pf) and _read_pid(gc_pf), 8.0)
        cp, gp = _read_pid(child_pf), _read_pid(gc_pf)
        tracked += [cp, gp]
        # Close ONLY the job — no explicit kill of anything.
        job.close()
        assert _wait(lambda: not _alive(cp), 8.0), "child escaped containment"
        assert _wait(lambda: not _alive(gp), 8.0), "grandchild escaped containment"
        job = None  # already closed
    finally:
        _force_cleanup(tracked)
        if proc is not None:
            proc.close()
        if job is not None:
            job.close()


@win_only
def test_D_unrelated_process_is_not_touched(tmp_path):
    """Stopping the managed job must NOT kill an unrelated process outside it."""
    managed_pf = str(tmp_path / "managed.pid")
    stray_pf = str(tmp_path / "stray.pid")
    job = win_job.JobObject()
    proc = None
    stray = subprocess.Popen([sys.executable, WORKER, stray_pf], cwd=HERE)
    stray_pids: list[int | None] = [stray.pid]
    managed_pids: list[int | None] = []
    try:
        assert _wait(lambda: _read_pid(stray_pf), 8.0), "stray worker never started"
        stray_pid = _read_pid(stray_pf)
        stray_pids.append(stray_pid)
        proc = win_job.spawn([sys.executable, WORKER, managed_pf], cwd=HERE, job=job)
        assert _wait(lambda: _read_pid(managed_pf), 8.0)
        mp = _read_pid(managed_pf)
        managed_pids.append(mp)
        assert _wait(lambda: _alive(mp), 5.0)
        assert _wait(lambda: _alive(stray_pid), 5.0)
        job.close()
        assert _wait(lambda: not _alive(mp), 8.0), "managed child not killed by job close"
        # The stray process must STILL be alive (we clean it explicitly below).
        assert _alive(stray_pid), "job close wrongly killed an unrelated process"
        job = None
    finally:
        _force_cleanup(stray_pids)
        _force_cleanup(managed_pids)
        if proc is not None:
            proc.close()
        if job is not None:
            job.close()
        try:
            stray.wait(timeout=5)
        except Exception:
            stray.kill()


@win_only
def test_E_spawn_into_closed_job_fails_closed(tmp_path):
    """Assigning into an unusable job raises ContainmentError and leaves NO process."""
    child_pf = str(tmp_path / "child.pid")
    job = win_job.JobObject()
    job.close()  # make the job handle unusable -> assign must fail
    with pytest.raises(win_job.ContainmentError):
        win_job.spawn([sys.executable, WORKER, child_pf], cwd=HERE, job=job)
    # No contained process was created / left running.
    assert _read_pid(child_pf) is None or not _alive(_read_pid(child_pf))


@win_only
def test_F_repeated_shutdown_is_safe(tmp_path):
    """Real contained child; supervising layer stop() called twice -> idempotent."""
    child_pf = str(tmp_path / "child.pid")
    job = win_job.JobObject()
    prev = S._JOB
    S._JOB = job
    m = S.Managed("worker", [sys.executable, WORKER, child_pf], kind="always")
    tracked: list[int | None] = []
    try:
        m.start()
        assert _wait(lambda: _read_pid(child_pf), 8.0), "contained child never started"
        cp = _read_pid(child_pf)
        tracked.append(cp)
        assert m.alive and _alive(cp)
        assert m.stop() in ("graceful", "killed")
        assert m.stop() == "already"     # second call is a safe no-op
        assert _wait(lambda: not _alive(cp), 5.0)
    finally:
        S._JOB = prev
        _force_cleanup(tracked)
        job.close()


@win_only
def test_G_restart_leaves_no_duplicate(tmp_path):
    """After a supervisor is killed and its tree reaped, a fresh one sees no leftover."""
    child_pf = str(tmp_path / "child1.pid")
    gc_pf = str(tmp_path / "gc1.pid")
    sup = subprocess.Popen(
        [sys.executable, SUPERVISOR, child_pf, gc_pf],
        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cp = gp = None
    try:
        assert _wait(lambda: _read_pid(child_pf) and _read_pid(gc_pf), 10.0)
        cp, gp = _read_pid(child_pf), _read_pid(gc_pf)
        sup.kill(); sup.wait(timeout=10)
        assert _wait(lambda: not _alive(cp) and not _alive(gp), 10.0), \
            "previous tree not fully cleaned before restart"
        # Only now bring up a replacement; assert nothing from run-1 lingers.
        child_pf2 = str(tmp_path / "child2.pid")
        gc_pf2 = str(tmp_path / "gc2.pid")
        sup2 = subprocess.Popen(
            [sys.executable, SUPERVISOR, child_pf2, gc_pf2],
            cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            assert _wait(lambda: _read_pid(child_pf2) and _read_pid(gc_pf2), 10.0)
            cp2 = _read_pid(child_pf2)
            assert not _alive(cp), "duplicate child from earlier run still present"
            assert _alive(cp2)
        finally:
            g2 = _read_pid(gc_pf2)
            sup2.kill(); sup2.wait(timeout=10)
            _force_cleanup([cp2, g2])
    finally:
        _force_cleanup([cp, gp, sup.pid])


@win_only
def test_H_early_child_failure_is_reported_accurately(tmp_path):
    """A child that dies on its own flips alive->dead and reports its exit code."""
    child_pf = str(tmp_path / "child.pid")
    job = win_job.JobObject()
    prev = S._JOB
    S._JOB = job
    m = S.Managed("worker", [sys.executable, WORKER, child_pf, "--exit-after", "0.4"],
                  kind="always")
    try:
        m.start()
        assert _wait(lambda: _read_pid(child_pf) is not None, 8.0), "child never started"
        assert _wait(lambda: not m.alive, 6.0), "early-exiting child never reported dead"
        rc = m.proc.poll()
        assert rc is not None, "returncode must be available after exit"
    finally:
        _force_cleanup([_read_pid(child_pf)])
        S._JOB = prev
        if m.proc is not None:
            m.proc.close()
        job.close()
