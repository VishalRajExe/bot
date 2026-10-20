"""Alpaca paper readiness checker (Phase 6 gate).

Read-only: verifies authentication, resolves the paper endpoint, checks BTC/USD
market + data coverage, and reports paper cash. Places NO orders and prints NO
secrets. Run this before ever starting the Alpaca paper bot.

Exit codes: 0 = AUTH OK (ready), 2 = AUTH BLOCKED, 3 = other error.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import ccxt
import requests

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    print(f"keys_present={bool(key) and bool(secret)} (values not shown)")

    # 1) Direct auth check (unambiguous 401 detection).
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/account",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=20,
        )
    except Exception as e:  # noqa: BLE001
        print("network error:", type(e).__name__, str(e)[:120])
        return 3

    if r.status_code != 200:
        print(f"AUTH BLOCKED: /v2/account -> {r.status_code} {r.text[:120]}")
        print("Fix: supply valid PAPER keys in D:\\BOT\\.env (rotate the exposed ones).")
        return 2

    acct = r.json()
    print("AUTH OK: paper account reachable")
    print(f"  cash={acct.get('cash')}  equity={acct.get('equity')}  "
          f"buying_power={acct.get('buying_power')}  crypto_status={acct.get('crypto_status')}")

    # 2) CCXT market + data coverage (still no orders).
    ex = ccxt.alpaca({"apiKey": key, "secret": secret, "enableRateLimit": True})
    ex.set_sandbox_mode(True)
    print("  resolved trader endpoint:", ex.urls["api"].get("trader"))
    ex.load_markets()
    print("  BTC/USD tradable:", ex.markets.get("BTC/USD", {}).get("active"))
    since = ex.parse8601("2017-01-01T00:00:00Z")
    o = ex.fetch_ohlcv("BTC/USD", "1d", since=since, limit=1000)
    if o:
        first = time.strftime("%Y-%m-%d", time.gmtime(o[0][0] / 1000))
        last = time.strftime("%Y-%m-%d", time.gmtime(o[-1][0] / 1000))
        print(f"  data daily: count={len(o)} first={first} last={last} close={o[-1][4]}")
    print("READY: Alpaca paper execution may proceed after owner approval.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
