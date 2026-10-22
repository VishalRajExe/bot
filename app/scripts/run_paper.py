"""Alpaca PAPER bot launcher (Phase 6).

Loads PAPER keys from D:\\BOT\\.env (never printed, never committed) and injects
them via Freqtrade's env-var mechanism (FREQTRADE__EXCHANGE__KEY/SECRET), then
starts `freqtrade trade` against the paper endpoint. Freqtrade does NOT support
%ENV% substitution in config, so keys must come from these env vars.

Usage:
  python app/scripts/run_paper.py            # DAILY executor: BTC baseline only (1d)
  python app/scripts/run_paper.py --fast     # FAST executor: live-strict alts (5m dispatcher)
  python app/scripts/run_paper.py --swing    # SWING executor: relaxed wide-spread alts (1h dispatcher)
  python app/scripts/run_paper.py --check    # connect + load markets only, then exit
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FT = ROOT / ".venv" / "Scripts" / "freqtrade.exe"
CFG = ROOT / "app" / "configs" / "config.alpaca.paper.json"
FAST_CFG = ROOT / "app" / "configs" / "config.alpaca.paper.fast.json"
SWING_CFG = ROOT / "app" / "configs" / "config.alpaca.paper.swing.json"
USERDIR = ROOT / "app" / "user_data"
STATE_FILE = ROOT / "app" / "state" / "paper_bot.json"
HEARTBEAT_SECS = 20


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        sys.exit("missing D:\\BOT\\.env")
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _write_state(payload: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _heartbeat_loop(proc: subprocess.Popen, base: dict) -> None:
    """Touch last_heartbeat while the child lives so reconcile can prove liveness."""
    while proc.poll() is None:
        _write_state({**base, "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                      "pid": proc.pid, "alive": True})
        time.sleep(HEARTBEAT_SECS)
    _write_state({**base, "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                  "pid": proc.pid, "alive": False, "returncode": proc.returncode})


def main() -> int:
    global CFG, STATE_FILE
    fast = "--fast" in sys.argv
    swing = "--swing" in sys.argv
    if fast:
        CFG = FAST_CFG
        STATE_FILE = ROOT / "app" / "state" / "paper_bot_fast.json"
        strategy, bot_name = "MomentumAlt", "unboundbot-alpaca-paper-fast"
    elif swing:
        CFG = SWING_CFG
        STATE_FILE = ROOT / "app" / "state" / "paper_bot_swing.json"
        strategy, bot_name = "SwingAlt", "unboundbot-alpaca-paper-swing"
    else:
        strategy, bot_name = "PaperAutonomous", "unboundbot-alpaca-paper"
    profile = "FAST (5m alts)" if fast else ("SWING (1h relaxed alts)" if swing else "DAILY (BTC baseline)")
    print(f"profile={profile}  strategy={strategy}")

    load_env()
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    if not key or not secret:
        sys.exit("no Alpaca paper keys found in .env")
    print("keys loaded from .env (values not shown)")

    env = dict(os.environ)
    env["FREQTRADE__EXCHANGE__KEY"] = key
    env["FREQTRADE__EXCHANGE__SECRET"] = secret

    # Telegram (optional): inject from .env via Freqtrade's generic env override.
    # Config keeps telegram.token/chat_id empty; these env vars fill them at launch.
    tg_token = os.environ.get("TELEGRAM_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if tg_token:
        env["FREQTRADE__TELEGRAM__TOKEN"] = tg_token
        print("telegram token loaded from .env (value not shown)")
    if tg_chat:
        env["FREQTRADE__TELEGRAM__CHAT_ID"] = tg_chat
        print("telegram chat_id loaded from .env")

    logfile = ROOT / (".ft_alpaca_fast.log" if fast else (".ft_alpaca_swing.log" if swing else ".ft_alpaca.log"))
    if "--check" in sys.argv:
        # Validate markets/data without trading: use show-trades? simplest: list-markets.
        args = [str(FT), "list-markets", "-c", str(CFG), "--userdir", str(USERDIR)]
        print("connectivity check: loading alpaca paper markets ...")
        return subprocess.call(args, env=env)

    args = [
        str(FT), "trade", "-c", str(CFG), "--userdir", str(USERDIR),
        "--strategy", strategy, "--logfile", str(logfile),
    ]
    print("launching Alpaca PAPER bot ...")
    proc = subprocess.Popen(args, env=env)
    base = {"bot_name": bot_name, "started": datetime.now(timezone.utc).isoformat()}
    t = threading.Thread(target=_heartbeat_loop, args=(proc, base), daemon=True)
    t.start()
    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        rc = proc.wait()
    _write_state({**base, "pid": proc.pid, "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                  "alive": False, "returncode": rc})
    return rc



if __name__ == "__main__":
    sys.exit(main())
