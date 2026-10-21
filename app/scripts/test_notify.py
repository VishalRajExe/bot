"""Verify Telegram notification *delivery* with real formatted detail payloads.

Sends a sample baseline-signal report and a sample FVG/OB setup report (built by
running the deterministic core) to the owner's chat so we can confirm the message
format arrives intact. This places NO orders and prints NO secrets — it only calls
Telegram's sendMessage endpoint with the token from D:\\BOT\\.env.

Usage:
  python app/scripts/test_notify.py            # send sample notifications
  python app/scripts/test_notify.py --dry      # print formatted text, send nothing
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.notifications import format as NF  # noqa: E402
from app.strategies_core import fvg_ob as F  # noqa: E402


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _sample_fvg_ob_entry() -> dict:
    """Drive the real state machine to produce a genuine completed setup."""
    tr = F.SetupTracker("ETH/USD", F.FvgCfg())
    a = pd.date_range("2026-01-01 00:00", periods=4, freq="1h", tz="UTC")
    tr.step("1h", a[1], 100, 101, 99, 100, atr_val=2.0, bias=1, bar_index=1)
    zone = F.FVG(+1, bottom=100.0, top=110.0, creation_ts=a[2], i=2)
    tr.open_zone(zone, ob_bottom=102.0, ob_top=108.0, atr_val=2.0, bar_index=2)
    tr.step("1h", a[3], 110, 111, 103, 106, atr_val=2.0, bias=1, bar_index=3)
    f5 = F.FVG(+1, bottom=103.0, top=106.0,
               creation_ts=pd.Timestamp("2026-01-01 04:00", tz="UTC"), i=0)
    tr.ltf_fvg(f5)
    entry = tr.ltf_retest(pd.Timestamp("2026-01-01 04:30", tz="UTC"),
                          o=105, h=106, l=103, c=104.0, atr_val=2.0)
    if entry is None:
        raise RuntimeError("sample setup failed to emit an entry")
    return entry


def send(token: str, chat_id: str, text: str) -> bool:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text,
              "disable_web_page_preview": True},
        timeout=20,
    )
    body = r.json()
    ok = bool(body.get("ok"))
    print(f"  sendMessage -> http={r.status_code} ok={ok}"
          + ("" if ok else f" desc={body.get('description')}"))
    return ok


def main() -> int:
    load_env()
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    dry = "--dry" in sys.argv

    signal_msg = NF.format_signal_report(
        pair="BTC/USD", timeframe="1d", now=datetime.now(timezone.utc),
        decision="NO_ENTRY", reason="daily close z-score has not crossed the bull threshold",
        indicators={"zscore": 0.77, "bull_threshold": 0.5, "ema65": 79000.0, "close": 83114.0},
        risk={"stake_amount": 5000.0, "max_open_trades": 1, "stoploss": -0.35},
    )
    setup_msg = NF.format_fvg_ob_setup(_sample_fvg_ob_entry())
    header = NF.format_status(bot_name="unboundbot-alpaca-paper", state="NOTIFICATION TEST",
                              detail="sample detail payloads (paper, no orders)")

    print(header, "\n\n", signal_msg, "\n\n", setup_msg, "\n")

    if dry:
        print("(--dry) nothing sent.")
        return 0
    if not token or not chat_id:
        print("TELEGRAM not configured (token/chat_id missing in .env); use --dry to preview.")
        return 3

    ok_all = True
    for text in (header, signal_msg, setup_msg):
        ok_all &= send(token, chat_id, text)
    print("DELIVERY:", "OK — check your Telegram chat" if ok_all else "FAILED")
    return 0 if ok_all else 4


if __name__ == "__main__":
    sys.exit(main())
