"""UnboundBot supervisor (Phase F) — Windows-friendly watchdog.

Keeps the read-only observer (``crypto_status_monitor.py``) and the learner
(``learner.py``) plus the three PAPER order executors (daily / fast / swing) alive.
Every managed process is launched in its OWN subprocess; when one dies the
supervisor restarts it after a small backoff — UNLESS the persisted circuit-breaker
kill-switch is active, in which case it STAYS DOWN and a Telegram alert is sent
instead. Restarting into a tripped breaker would defeat the whole safety layer, so
the "no-relaunch on kill-switch" rule is non-negotiable.

What this file does NOT do:
  * It never places or cancels an order. It shells out to the same scripts the
    operator would run manually (``run_paper.py --fast`` etc.), and to the read-only
    monitor + learner.
  * It does not touch the risk policy, kill-switch state, or ledger directly. It
    reads ``policy.is_blocked()`` for the same fail-closed signal every entry uses.
  * It does not attempt to run live trading. PAPER ONLY.

Design notes:
  * Subprocesses are spawned detached-with-own-console on Windows (via CREATE_NEW_-
    PROCESS_GROUP) so Ctrl-C on the supervisor does not orphan the children; a
    clean shutdown terminates each known child.
  * On Windows every child is ALSO bound to a kernel Job Object configured with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (see ``win_job.py``). That is the primary
    no-orphan guarantee: if the supervisor dies for ANY reason -- including a hard
    force-kill that skips the ``finally`` drain -- the OS tears down the whole
    contained tree (including the ``freqtrade.exe`` grandchild that ``run_paper.py``
    spawns) the instant the supervisor's job handle closes. The graceful signal path
    below is a second layer, not a substitute.
  * The supervisor owns the SAME state files the executor writes
    (``app/state/paper_bot*.json``). Heartbeats are still produced by the bot
    itself — the supervisor does NOT fake a heartbeat.
  * Backoff: 5s -> 10s -> 30s -> 60s (capped). A stable 5-minute run resets the
    backoff. This is a real operational concern: a crash-looping strategy that
    keeps dying would otherwise hammer the broker / log disk.
  * Every restart / refusal is Telegram-alerted through the monitor's own ``send``
    helper so we do not duplicate credential parsing here.

Usage:
  python app/scripts/supervise.py                # start everything configured
  python app/scripts/supervise.py --only daily   # only the daily executor (+observer)
  python app/scripts/supervise.py --no-learner   # skip the learner subprocess
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess  # noqa: S405 - intentional, we spawn our own scripts
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]          # D:\BOT\app
_ROOT = _APP.parent                                  # D:\BOT
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))
if str(_APP / "scripts") not in sys.path:
    sys.path.insert(0, str(_APP / "scripts"))

from risk import policy  # noqa: E402

# win_job is Windows-only (ctypes). Import defensively so the module still loads
# on POSIX, where we fall back to plain subprocess.Popen + process groups.
try:
    import win_job  # noqa: E402
except Exception:  # noqa: BLE001 - not on Windows / import failed
    win_job = None

PY = sys.executable
MONITOR = _APP / "scripts" / "crypto_status_monitor.py"
LEARNER = _APP / "scripts" / "learner.py"
RUN_PAPER = _APP / "scripts" / "run_paper.py"

# Backoff ladder (seconds) — a stable run for STABLE_RESET_S resets the index.
BACKOFF_LADDER = [5, 10, 30, 60]
STABLE_RESET_S = 300
POLL_S = 2.0
# Graceful drain budget per child on shutdown; survivors are force-terminated
# after it (and, on Windows, the job-close backstop kills anything left anyway).
GRACEFUL_TIMEOUT = 15.0

_STOP = {"f": False}
# The single Job Object every Windows child is bound to; created once in main().
_JOB = None


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z [supervise] {msg}", flush=True)


def _new_proc_group_kwargs() -> dict:
    # Detach children into their own process group so Ctrl-C on the supervisor does
    # not immediately kill every child; the supervisor terminates them explicitly.
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


def _init_job():
    """Create the containment Job Object once at startup (Windows). Returns the
    job, or None on POSIX. Raises ``win_job.ContainmentError`` if containment
    cannot be established on Windows -- callers MUST fail closed on that."""
    if os.name != "nt":
        return None
    if win_job is None or not win_job.supported():
        raise RuntimeError("Windows supervisor requires win_job containment support")
    return win_job.JobObject(name="UnboundBot-supervisor-job")


def spawn_managed(argv: list[str], cwd: str):
    """Launch one child. On Windows it is atomically suspended -> bound to the
    shared job -> resumed (``win_job.spawn``), so it can never escape containment
    even during the start window. On POSIX it uses a fresh process group. Any
    Windows containment problem raises ``ContainmentError`` (fail closed)."""
    if os.name == "nt" and _JOB is not None:
        return win_job.spawn(argv, cwd=cwd, job=_JOB)
    return subprocess.Popen(argv, cwd=cwd, **_new_proc_group_kwargs())


def _managed_cmdline_tokens() -> dict[str, list[str]]:
    """Read-only scan for already-running UnboundBot workers (by their specific
    script path in the command line, never by a bare ``python.exe`` name). Used
    at startup to detect orphans from a previous supervisor so we do not silently
    double-launch a second executor / monitor / learner. Returns name -> [pid,...]."""
    markers = {
        "monitor": [str(MONITOR)],
        "learner": [str(LEARNER)],
        "executor-daily": [str(RUN_PAPER)],
        "executor-fast": [str(RUN_PAPER), "--fast"],
        "executor-swing": [str(RUN_PAPER), "--swing"],
    }
    found: dict[str, list[int]] = {}
    try:
        import psutil  # noqa: PLC0415 - optional, only for best-effort detection
    except Exception:  # noqa: BLE001
        return found
    me = os.getpid()
    procs = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.pid == me:
                continue
            cl = p.info.get("cmdline") or []
            procs.append((p.pid, " ".join(cl)))
        except Exception:  # noqa: BLE001 - process vanished mid-scan
            continue
    for name, toks in markers.items():
        if name.startswith("executor-"):
            flag = "--" + name.split("-", 1)[1]  # --daily has no flag (base profile)
            for pid, cmd in procs:
                if str(RUN_PAPER) in cmd and flag in cmd:
                    found.setdefault(name, []).append(pid)
        else:
            for pid, cmd in procs:
                if toks[0] in cmd:
                    found.setdefault(name, []).append(pid)
    return found


# ---------------------------------------------------------------- telegram
def _send_telegram(text: str) -> bool:
    """Reuse the monitor's send(env, text) so we do not duplicate .env parsing. A
    no-op when Telegram is unconfigured (returns False, logs only)."""
    try:
        import crypto_status_monitor as M  # noqa: PLC0415
        env = M.load_env()
        return M.send(env, text)
    except Exception as e:  # noqa: BLE001
        _log(f"telegram send failed: {type(e).__name__}: {e}")
        return False


def _alert(title: str, detail: str) -> None:
    body = f"🛡️ SUPERVISOR — {title}\n{detail}\n⏱️ {_now()}"
    _log(body.replace("\n", " | "))
    _send_telegram(body)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- spec
class Managed:
    """One supervised subprocess (identified by a stable name) and its restart policy."""

    def __init__(self, name: str, argv: list[str], kind: str):
        self.name = name
        self.argv = argv                # list-form (no shell), so no quoting pitfalls
        self.kind = kind                # "executor" (blocked by kill-switch) | "always"
        self.proc: subprocess.Popen | None = None
        self.backoff_i = 0
        self.started_at: float = 0.0
        self.last_refusal_log_at: float = 0.0
        self.failed: bool = False       # containment failed -> never retry, stay down

    # ---- state ----
    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def _close_handle(proc) -> None:
        """Release the OS process handle if the child wrapper owns one. Idempotent
        and a no-op for plain ``subprocess.Popen`` (which manages its own handle)."""
        closer = getattr(proc, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass

    def start(self) -> None:
        if self.failed:
            return
        cwd = str(_ROOT)
        _log(f"launch {self.name}: {' '.join(self.argv)}")
        try:
            self.proc = spawn_managed(self.argv, cwd=cwd)
        except Exception as e:  # noqa: BLE001 - ContainmentError / OSError
            # Fail closed: an uncontained worker breaks the no-orphan contract, so
            # we refuse to launch it at all rather than risk an orphaned executor.
            self.failed = True
            self.proc = None
            _alert(
                f"COULD NOT LAUNCH {self.name}",
                f"process creation / containment failed: {type(e).__name__}: {e}.\n"
                "Refusing to start this worker unprotected (no-orphan safety contract).",
            )
            return
        self.started_at = time.time()

    def stop(self, timeout: float = GRACEFUL_TIMEOUT) -> str:
        """Graceful-then-forced shutdown of this child. Idempotent: safe to call
        repeatedly. Returns a status tag for the final shutdown summary:
        'graceful' | 'killed' | 'already' | 'none'."""
        proc = self.proc
        if proc is None:
            return "none"
        if proc.poll() is not None:
            self._close_handle(proc)
            return "already"
        pid = getattr(proc, "pid", None)
        _log(f"terminating {self.name} (pid={pid})")
        try:
            if os.name == "nt":
                # CTRL_BREAK_EVENT asks Python's default handler to raise
                # KeyboardInterrupt inside the child so it can shut down cleanly.
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=timeout)
            self._close_handle(proc)
            return "graceful"
        except subprocess.TimeoutExpired:
            _log(f"force-killing {self.name} (pid={pid})")
            try:
                proc.kill()
            finally:
                self._close_handle(proc)
            return "killed"

    def note_stable(self) -> None:
        if self.started_at and time.time() - self.started_at >= STABLE_RESET_S:
            self.backoff_i = 0
            self.started_at = time.time()   # so we don't reset every tick

    def next_sleep(self) -> float:
        idx = min(self.backoff_i, len(BACKOFF_LADDER) - 1)
        s = BACKOFF_LADDER[idx]
        self.backoff_i = min(self.backoff_i + 1, len(BACKOFF_LADDER))
        return s


def default_specs(include: list[str], with_learner: bool) -> list[Managed]:
    """Build the process list to supervise. The daily executor is what the operator
    runs first on the $100 preset; fast + swing are added when their names appear in
    ``include`` (matching the plan's staged-rollout stance — they exist as configs but
    ``running=false`` in paper_risk_policy.json.executors until verified)."""
    specs: list[Managed] = [
        Managed("monitor", [PY, str(MONITOR)], kind="always"),
    ]
    if with_learner:
        specs.append(Managed("learner", [PY, str(LEARNER), "--watch", "900"], kind="always"))
    if "daily" in include:
        specs.append(Managed("executor-daily", [PY, str(RUN_PAPER)], kind="executor"))
    if "fast" in include:
        specs.append(Managed("executor-fast", [PY, str(RUN_PAPER), "--fast"], kind="executor"))
    if "swing" in include:
        specs.append(Managed("executor-swing", [PY, str(RUN_PAPER), "--swing"], kind="executor"))
    return specs


# ---------------------------------------------------------------- loop
def _tick(specs: list[Managed]) -> None:
    """One supervisor tick: bring up anything missing, honour the kill-switch rule."""
    blocked = policy.is_blocked()
    for m in specs:
        if m.alive:
            m.note_stable()
            continue
        # A process just exited (or hasn't been started). Decide whether to relaunch.
        if m.kind == "executor" and blocked["blocked"]:
            now = time.time()
            # Throttle the refusal alert so a crash-loop cannot spam Telegram.
            if now - m.last_refusal_log_at > 300:
                m.last_refusal_log_at = now
                _alert(
                    "REFUSED RELAUNCH (kill-switch)",
                    f"executor {m.name} is stopped and will stay stopped because the "
                    f"circuit breaker is active: {blocked['reason']}\nManual recovery "
                    "required (crypto_status_monitor.py --recover-kill-switch).",
                )
            continue
        if m.proc is None:
            # First start — no backoff.
            m.start()
            continue
        # It died. Restart with the backoff ladder.
        rc = m.proc.poll()
        sleep_s = m.next_sleep()
        _log(f"{m.name} exited rc={rc}; will relaunch in {sleep_s}s")
        time.sleep(sleep_s)
        if m.kind == "executor" and policy.is_blocked()["blocked"]:
            continue   # recheck: kill-switch may have tripped during the sleep
        m.start()
        _alert(f"{m.name} restarted", "the supervised process came back after a crash.")


def _install_stop_handlers() -> None:
    def _halt(signum, _frame):  # noqa: ANN001
        # On Ctrl-C / SIGTERM we do NOT want to orphan children. Set the flag so
        # main() drains them cleanly; a second Ctrl-C force-exits.
        if _STOP["f"]:
            raise SystemExit(130)
        _STOP["f"] = True
        _log(f"stop requested (signal {signum}); draining children ...")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _halt)
        except (ValueError, OSError):
            pass


def _drain(specs: list[Managed]) -> None:
    """Graceful shutdown: stop scheduling (caller already set _STOP), ask each
    child to exit, force-kill survivors, then close the job so the OS reaps any
    contained process we lost track of (including grandchildren). Idempotent and
    ordered; never touches processes outside our own tree."""
    summary: dict[str, str] = {}
    for m in specs:
        summary[m.name] = m.stop()
    # Reap any that reported 'killed' again defensively (double shutdown call safe).
    for m in specs:
        if summary.get(m.name) == "killed" and m.alive:
            summary[m.name] = m.stop()
    _log("shutdown summary: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    # Backstop: closing the job handle makes Windows kill everything still in it.
    if _JOB is not None:
        try:
            _JOB.terminate(0)
        except Exception:  # noqa: BLE001
            pass
        _JOB.close()


def main(argv=None) -> int:
    global _JOB
    for _st in (sys.stdout, sys.stderr):
        try:
            _st.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="UnboundBot 24/7 PAPER supervisor (Phase F)")
    ap.add_argument("--only", default="daily",
                    help="comma list of executors to supervise: daily,fast,swing (or 'all')")
    ap.add_argument("--no-learner", action="store_true",
                    help="skip spawning the learner subprocess")
    ap.add_argument("--tick", type=float, default=POLL_S, help="poll seconds (default 2)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    include = [x.strip() for x in args.only.split(",") if x.strip()]
    if "all" in include:
        include = ["daily", "fast", "swing"]

    # Establish containment BEFORE launching anything. On Windows a failure here
    # means we cannot honour the no-orphan contract, so we refuse to run.
    try:
        _JOB = _init_job()
    except Exception as e:  # noqa: BLE001 - ContainmentError / RuntimeError
        _log(f"FATAL: process containment unavailable: {type(e).__name__}: {e}")
        _alert("SUPERVISOR REFUSED TO START", "Windows Job Object containment could "
               "not be established; refusing to launch unprotected workers.")
        return 4

    # Warn about (but do not blindly kill) leftovers from a previous supervisor.
    preexisting = _managed_cmdline_tokens()
    for name, pids in preexisting.items():
        _log(f"WARNING: found pre-existing {name} process(es) {pids} not owned by "
             "this supervisor; they are OUTSIDE this job and must be cleaned up "
             "manually before a duplicate is safe.")
        _alert(f"PRE-EXISTING {name} DETECTED",
               f"PIDs {pids} are already running for {name}. They were NOT started by "
               "this supervisor and are not job-contained. Verify and stop the old "
               "ones before allowing a second instance.")

    specs = default_specs(include=include, with_learner=not args.no_learner)
    _log(f"supervising: {', '.join(m.name for m in specs)}")
    _install_stop_handlers()

    # Initial bring-up.
    for m in specs:
        if m.proc is None and not m.alive:
            if m.kind == "executor" and policy.is_blocked()["blocked"]:
                _alert("REFUSED START (kill-switch)",
                       f"{m.name} not started because circuit breaker is active")
                continue
            if m.name in preexisting:
                _log(f"skipping start of {m.name}: a pre-existing instance is running")
                continue
            m.start()

    try:
        while not _STOP["f"]:
            time.sleep(args.tick)
            _tick(specs)
    finally:
        _drain(specs)
    _log("supervisor shut down cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
