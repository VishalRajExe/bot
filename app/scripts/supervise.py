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

PY = sys.executable
MONITOR = _APP / "scripts" / "crypto_status_monitor.py"
LEARNER = _APP / "scripts" / "learner.py"
RUN_PAPER = _APP / "scripts" / "run_paper.py"

# Backoff ladder (seconds) — a stable run for STABLE_RESET_S resets the index.
BACKOFF_LADDER = [5, 10, 30, 60]
STABLE_RESET_S = 300
POLL_S = 2.0

_STOP = {"f": False}


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z [supervise] {msg}", flush=True)


def _new_proc_group_kwargs() -> dict:
    # Detach children into their own process group so Ctrl-C on the supervisor does
    # not immediately kill every child; the supervisor terminates them explicitly.
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


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

    # ---- state ----
    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        cwd = str(_ROOT)
        _log(f"launch {self.name}: {' '.join(self.argv)}")
        self.proc = subprocess.Popen(  # noqa: S603 - we control argv
            self.argv, cwd=cwd, **_new_proc_group_kwargs(),
        )
        self.started_at = time.time()

    def stop(self, timeout: float = 15.0) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        _log(f"terminating {self.name} (pid={self.proc.pid})")
        try:
            if os.name == "nt":
                # CTRL_BREAK_EVENT asks Python's default handler to raise
                # KeyboardInterrupt inside the child so it can shut down cleanly.
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _log(f"force-killing {self.name}")
            self.proc.kill()

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


def main(argv=None) -> int:
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
            m.start()

    try:
        while not _STOP["f"]:
            time.sleep(args.tick)
            _tick(specs)
    finally:
        for m in specs:
            m.stop()
    _log("supervisor shut down cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
