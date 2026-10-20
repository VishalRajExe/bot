"""Fetch Alpaca BTC/USD OHLCV via CCXT and write Freqtrade-format feather data.

Freqtrade's live candle refresh is unreliable for the (unsupported) Alpaca
exchange, so we pre-seed the data dir. Output matches Freqtrade's feather schema:
columns [date, open, high, low, close, volume], date = datetime64[ns, UTC].

Keys come from D:\\BOT\\.env (never printed). Read-only market data; no orders.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app" / "user_data" / "data" / "alpaca" / "BTC_USD-1d.feather"


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    ex = ccxt.alpaca({
        "apiKey": os.environ["ALPACA_PAPER_API_KEY"],
        "secret": os.environ["ALPACA_PAPER_API_SECRET"],
        "enableRateLimit": True,
    })
    ex.set_sandbox_mode(True)

    all_rows: list[list] = []
    since = ex.parse8601("2020-01-01T00:00:00Z")
    now = ex.milliseconds()
    while since < now:
        batch = ex.fetch_ohlcv("BTC/USD", timeframe="1d", since=since, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 1
        time.sleep(ex.rateLimit / 1000)

    # De-dup by timestamp, keep order.
    seen: dict[int, list] = {}
    for r in all_rows:
        seen[int(r[0])] = r
    rows = [seen[k] for k in sorted(seen)]

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True).astype("datetime64[ns, UTC]")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype("float64")
    df = df[["date", "open", "high", "low", "close", "volume"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_feather(OUT)
    print(f"wrote {OUT} rows={len(df)} "
          f"range={df['date'].iloc[0]} -> {df['date'].iloc[-1]} last_close={df['close'].iloc[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
