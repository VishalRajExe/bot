"""Research backtest for the FVG/OB core on real Alpaca candles (read-only).

This is NOT a second trading engine. It imports the *same* deterministic core
(``app.strategies_core.fvg_ob``) that ships with its unit tests and replays it
over real Alpaca crypto candles for the intended venue, then resolves each
setup's outcome by first-touch of TP vs stop on subsequent 5M bars. It places
no orders and mutates nothing in the live path.

Honesty rules baked in:
  * entry is assumed filled at the retest-bar CLOSE (the core's own rule);
  * intra-bar TP/stop order is unknown -> if a bar could touch BOTH we assume the
    STOP fired first (pessimistic);
  * Alpaca free-tier crypto history depth is limited -> we print the ACTUAL span;
  * round-trip fee ~2 x 0.25% taker is applied to the fee-adjusted column;
  * small samples are explicitly flagged as not statistically significant.

Usage:
  python app/scripts/research_fvg_backtest.py --pair ETH/USD --days5 12
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import ccxt  # noqa: E402
from app.strategies_core import fvg_ob as F  # noqa: E402

SUMMARY_OUT = ROOT / "app" / "user_data" / "fvg_ob_backtest_summary.json"
FEE_RT = 0.0050  # ~2 x 0.25% taker round trip (approx; Alpaca crypto fee schedule)


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def fetch(ex: ccxt.alpaca, symbol: str, tf: str, days: int) -> pd.DataFrame:
    since = ex.parse8601((datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    rows: list[list] = []
    now = ex.milliseconds()
    while since < now:
        batch = ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1][0]
        if last <= since:
            break
        since = last + 1
        if len(rows) > 5000:  # hard cap to bound runtime on deep 5M windows
            break
        time.sleep(ex.rateLimit / 1000)
    seen: dict[int, list] = {int(r[0]): r for r in rows}
    ordered = [seen[k] for k in sorted(seen)]
    df = pd.DataFrame(ordered, columns=["date", "open", "high", "low", "close", "volume"])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True).astype("datetime64[ns, UTC]")
    return df


def resolve_outcome(entry: dict, df5: pd.DataFrame, horizon: int) -> dict:
    """First-touch of stop vs TP on bars AFTER the entry, pessimistic on ties."""
    after = df5[df5["date"] > pd.Timestamp(entry["entry_ts"])].head(horizon)
    stop, tp = float(entry["stop"]), float(entry["take_profit"])
    res = {"result": "timeout", "r": 0.0}
    for _, bar in after.iterrows():
        hit_stop = bar["low"] <= stop
        hit_tp = bar["high"] >= tp
        if hit_stop and hit_tp:
            res = {"result": "loss", "r": -1.0}   # pessimistic tie-break
            break
        if hit_stop:
            res = {"result": "loss", "r": -1.0}
            break
        if hit_tp:
            res = {"result": "win", "r": 2.0}
            break
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="ETH/USD")
    ap.add_argument("--days1h", type=int, default=40)
    ap.add_argument("--days5", type=int, default=12)
    ap.add_argument("--horizon", type=int, default=288, help="max 5M bars to hold (288=24h)")
    ap.add_argument("--no-overlap", action="store_true",
                    help="sensitivity: drop the 1H FVG/OB confluence requirement "
                         "(keeps bias->zone->tap->5M FVG->retest). Shipped default keeps it.")
    args = ap.parse_args()

    load_env()
    ex = ccxt.alpaca({
        "apiKey": os.environ.get("ALPACA_PAPER_API_KEY", ""),
        "secret": os.environ.get("ALPACA_PAPER_API_SECRET", ""),
        "enableRateLimit": True,
    })
    ex.set_sandbox_mode(True)
    ex.load_markets()
    if args.pair not in ex.markets:
        print(f"pair {args.pair} not on Alpaca")
        return 2

    print(f"fetching {args.pair} 1h ({args.days1h}d) + 5m ({args.days5}d) from Alpaca ...")
    df1 = fetch(ex, args.pair, "1h", args.days1h)
    df5 = fetch(ex, args.pair, "5m", args.days5)
    if df1.empty or df5.empty:
        print("insufficient data (free-tier crypto history depth); nothing to backtest")
        return 3
    span1 = f"{df1['date'].iloc[0]} -> {df1['date'].iloc[-1]}"
    span5 = f"{df5['date'].iloc[0]} -> {df5['date'].iloc[-1]}"
    print(f"1h bars={len(df1)} span={span1}")
    print(f"5m bars={len(df5)} span={span5}")

    cfg = F.FvgCfg()  # shipped defaults (require_overlap=True, rr=2.0)
    if args.no_overlap:
        cfg.require_overlap = False
    entries, _ = F.evaluate_ohlcv(df1, df5, cfg, pair=args.pair)

    outcomes = [resolve_outcome(e, df5, args.horizon) for e in entries]
    wins = sum(1 for o in outcomes if o["result"] == "win")
    losses = sum(1 for o in outcomes if o["result"] == "loss")
    timeouts = sum(1 for o in outcomes if o["result"] == "timeout")
    gross_r = sum(o["r"] for o in outcomes)
    # fee drag expressed in R: fees are % of notional; convert with avg risk per unit
    fee_r = 0.0
    if entries:
        avg_risk = sum(float(e["risk_per_unit"]) for e in entries) / len(entries)
        avg_px = sum(float(e["entry_price"]) for e in entries) / len(entries)
        fee_per_trade_r = (FEE_RT * avg_px) / avg_risk if avg_risk else 0.0
        fee_r = fee_per_trade_r * (wins + losses)
    net_r = gross_r - fee_r
    decided = wins + losses
    win_rate = (wins / decided) if decided else None
    breakeven_wr = 1 / 3  # 1:2 RR needs >33.3% to be net positive pre-fee

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "venue": "Alpaca PAPER (ccxt fetch_ohlcv)",
        "pair": args.pair,
        "config": {k: getattr(cfg, k) for k in ("bias_ema", "atr_n", "swing_k", "require_overlap",
                                                "rr", "stop_atr_mult", "zone_ttl_bars")},
        "data": {"bars_1h": len(df1), "span_1h": span1, "bars_5m": len(df5), "span_5m": span5},
        "setups": len(entries),
        "wins": wins, "losses": losses, "timeouts": timeouts,
        "win_rate_of_decided": win_rate,
        "gross_r": round(gross_r, 2), "fee_r": round(fee_r, 2), "net_r": round(net_r, 2),
        "breakeven_win_rate_1to2": round(breakeven_wr, 4),
        "assumptions": [
            "entry filled at retest-bar close (core rule)",
            "intra-bar TP/stop order unknown -> ties counted as STOP (pessimistic)",
            f"round-trip fee {FEE_RT*100:.2f}% applied to decided trades",
            "not the live Freqtrade engine; research replay of the pure core only",
        ],
        "statistically_significant": decided >= 30,
    }

    print("\n===== FVG/OB research backtest =====")
    print(f"pair={args.pair} setups={len(entries)} (wins={wins} losses={losses} timeouts={timeouts})")
    if win_rate is not None:
        print(f"win_rate(decided)={win_rate:.1%}  breakeven@1:2={breakeven_wr:.1%}")
    print(f"gross_R={gross_r:+.2f}  fee_R={-fee_r:+.2f}  net_R={net_r:+.2f}")
    if decided < 30:
        print(f"CAVEAT: only {decided} decided trades -> NOT statistically significant.")
    print("CAVEAT: research replay of the deterministic core on real Alpaca candles; "
          "does NOT replace a Freqtrade backtest and enables nothing.")

    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"wrote {SUMMARY_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
