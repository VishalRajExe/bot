"""Standalone 'supervisor' for the forced-termination integration test. Creates a
Job Object, launches a contained worker (which itself spawns a grandchild) inside
it, records both PIDs to marker files, prints READY, then idles until it is
force-killed. Because the job handle lives in THIS process, force-killing us must
make Windows tear down the whole contained tree — that is exactly what Test B
asserts. Harmless: no network, no orders, no trading imports.

Usage: python _dummy_supervisor.py <child_pidfile> <grandchild_pidfile>
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir, "scripts"))
import win_job  # noqa: E402

child_pidfile = sys.argv[1]
gc_pidfile = sys.argv[2]
worker = os.path.join(_HERE, "_dummy_worker.py")

job = win_job.JobObject()
proc = win_job.spawn(
    [sys.executable, worker, child_pidfile, "--grandchild", gc_pidfile],
    cwd=_HERE, job=job,
)
# The worker writes its own PID + the grandchild PID into the marker files.
print(f"READY supervisor={os.getpid()} child={proc.pid}", flush=True)

# Idle forever. We are meant to be force-killed by the test harness.
try:
    while True:
        time.sleep(0.2)
except (KeyboardInterrupt, SystemExit):
    job.close()
    raise
