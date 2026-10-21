"""Backtest runner — reproducible, credential-injected (Phase 2/5/7 evidence).

Freqtrade cannot put %ENV% in its config, so paper keys are injected via
FREQTRADE__EXCHANGE__KEY/SECRET exactly like run_paper.py. This is an OFFLINE
simulation: Freqtrade loads Alpaca *market metadata* with those keys but places
NO orders and hits NO trading endpoint. It exists so the backtest commands run
during audit remediation are reproducible and documented (docs/Phases.md, P2/P5).

Usage:
  python app/scripts/run_backtest.py                       # full local range
  python app/scripts/run_backtest.py --timerange 20210101-20261020
Exit code mirrors freqtrade's.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FT = ROOT / ".venv" / "Scripts" / "freqtrade.exe"
CFG = ROOT / "app" / "configs" / "config.alpaca.paper.json"
USERDIR = ROOT / "app" / "user_data"
DEFAULT_TIMERANGE = "20210101-20261020"


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        sys.exit("missing D:\\BOT\\.env")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main(argv: list[str]) -> int:
    load_env()
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    if not key or not secret:
        sys.exit("no Alpaca paper keys in .env (needed only to load market metadata)")

    tr = DEFAULT_TIMERANGE
    if "--timerange" in argv:
        tr = argv[argv.index("--timerange") + 1]

    env = dict(os.environ)
    env["FREQTRADE__EXCHANGE__KEY"] = key
    env["FREQTRADE__EXCHANGE__SECRET"] = secret

    args = [
        str(FT), "backtesting", "-c", str(CFG), "--userdir", str(USERDIR),
        "--strategy", "BtcZScore", "--timerange", tr, "--cache", "none",
    ]
    print("running (offline simulation, NO orders):", " ".join(args[1:]))
    return subprocess.call(args, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
