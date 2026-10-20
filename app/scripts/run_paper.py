"""Alpaca PAPER bot launcher (Phase 6).

Loads PAPER keys from D:\\BOT\\.env (never printed, never committed) and injects
them via Freqtrade's env-var mechanism (FREQTRADE__EXCHANGE__KEY/SECRET), then
starts `freqtrade trade` against the paper endpoint. Freqtrade does NOT support
%ENV% substitution in config, so keys must come from these env vars.

Usage:
  python app/scripts/run_paper.py            # start (respects config initial_state)
  python app/scripts/run_paper.py --check    # connect + load markets only, then exit
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


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        sys.exit("missing D:\\BOT\\.env")
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    if not key or not secret:
        sys.exit("no Alpaca paper keys found in .env")
    print("keys loaded from .env (values not shown)")

    env = dict(os.environ)
    env["FREQTRADE__EXCHANGE__KEY"] = key
    env["FREQTRADE__EXCHANGE__SECRET"] = secret

    if "--check" in sys.argv:
        # Validate markets/data without trading: use show-trades? simplest: list-markets.
        args = [str(FT), "list-markets", "-c", str(CFG), "--userdir", str(USERDIR)]
        print("connectivity check: loading alpaca paper markets ...")
        return subprocess.call(args, env=env)

    args = [
        str(FT), "trade", "-c", str(CFG), "--userdir", str(USERDIR),
        "--strategy", "BtcZScore", "--logfile", str(ROOT / ".ft_alpaca.log"),
    ]
    print("launching Alpaca PAPER bot ...")
    return subprocess.call(args, env=env)


if __name__ == "__main__":
    sys.exit(main())
