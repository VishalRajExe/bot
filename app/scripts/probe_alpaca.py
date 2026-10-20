"""Phase 0/2 feasibility probe for Alpaca via CCXT.

Reads PAPER keys from D:\\BOT\\.env (never prints them), then verifies:
  - markets resolve BTC/USD
  - historical daily OHLCV coverage (earliest date, count, last close)
  - paper account equity endpoint is reachable
No orders are placed. No secrets are printed.
"""
import os
import sys
import time
from pathlib import Path

import ccxt


def load_env(path: Path) -> None:
    if not path.exists():
        print(f"missing env file: {path}")
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env(Path(__file__).resolve().parents[2] / ".env")
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    print(f"key_loaded={bool(key)} secret_loaded={bool(secret)}")

    ex = ccxt.alpaca({"apiKey": key, "secret": secret, "enableRateLimit": True})
    ex.set_sandbox_mode(True)  # paper environment
    print("sandbox/paper:", ex.urls.get("api"))

    ex.load_markets()
    sym = "BTC/USD"
    print("BTC/USD in markets:", sym in ex.markets)
    m = ex.markets.get(sym)
    if m:
        print("  active:", m.get("active"), "type:", m.get("type"),
              "precision.price:", m.get("precision", {}).get("price"))

    # Historical daily coverage
    since = ex.parse8601("2015-01-01T00:00:00Z")
    try:
        ohlcv = ex.fetch_ohlcv(sym, timeframe="1d", since=since, limit=1000)
        if ohlcv:
            first = time.strftime("%Y-%m-%d", time.gmtime(ohlcv[0][0] / 1000))
            last = time.strftime("%Y-%m-%d", time.gmtime(ohlcv[-1][0] / 1000))
            print(f"OHLCV daily: count={len(ohlcv)} first={first} last={last} "
                  f"last_close={ohlcv[-1][4]}")
        else:
            print("OHLCV daily: EMPTY")
    except Exception as e:  # noqa: BLE001
        print("OHLCV error:", type(e).__name__, str(e)[:200])

    # Paper account equity (read-only)
    try:
        bal = ex.fetch_balance()
        usd = bal.get("total", {}).get("USD")
        print("paper_balance_USD_total:", usd)
    except Exception as e:  # noqa: BLE001
        print("balance error:", type(e).__name__, str(e)[:200])

    return 0


if __name__ == "__main__":
    sys.exit(main())
