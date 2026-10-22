"""Dummy worker for Windows process-lifecycle tests. Harmless: no network, no
orders, no trading imports. Writes its own PID to ``argv[1]``, optionally spawns a
grandchild (whose PID is written to the path after ``--grandchild``), then idles in
short ticks so a CTRL_BREAK (KeyboardInterrupt) makes it exit promptly.

Flags:
  argv[1]                pidfile to write our PID into
  --grandchild <path>    spawn ``python _dummy_worker.py <path>`` as a child and
                         write that child's PID into <path>
  --ignore-signals       install no SIGINT/SIGTERM handler (tests forced kill)
  --exit-after <secs>    exit cleanly after N seconds instead of idling forever
"""
import os
import signal
import subprocess
import sys
import time

pidfile = sys.argv[1]
with open(pidfile, "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))

ignore_signals = "--ignore-signals" in sys.argv
if ignore_signals:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

if "--grandchild" in sys.argv:
    gc_path = sys.argv[sys.argv.index("--grandchild") + 1]
    g = subprocess.Popen([sys.executable, os.path.abspath(__file__), gc_path])
    with open(gc_path, "w", encoding="utf-8") as fh:
        fh.write(str(g.pid))

exit_after = None
if "--exit-after" in sys.argv:
    exit_after = float(sys.argv[sys.argv.index("--exit-after") + 1])

_deadline = (time.time() + exit_after) if exit_after is not None else None
try:
    while True:
        time.sleep(0.1)
        if _deadline is not None and time.time() >= _deadline:
            break
except (KeyboardInterrupt, SystemExit):
    pass
sys.exit(0)
