"""Alpaca crypto asset discovery + eligibility ranking (decision #3, read-only).

Owner rule: *Alpaca's current asset list* decides what is AVAILABLE, while
liquidity, data quality, transaction cost, and backtesting decide what is
ENABLED. This script does the discovery + ranking and writes a proposed
shortlist to `app/configs/asset_universe.json`. It NEVER enables a pair and
NEVER places orders — turning a candidate into a live pair is a separate,
owner-approved step that requires a backtest first.

Pipeline (all read-only market-data calls, no secrets printed):
  1. GET /v2/assets?asset_class=crypto              -> availability (tradable list)
  2. GET /v1beta3/crypto/us/bars (30d, batched)     -> liquidity + data quality
  3. GET /v1beta3/crypto/us/quotes (top-N only)     -> spread as a cost proxy
  4. Rank by 30d median daily notional (USD); apply gates.

BTC/USD is always reported but flagged as the existing baseline (kept separate
from the FVG/OB strategy per decision #1).

Exit codes: 0 = report written, 2 = AUTH BLOCKED, 3 = other error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "app" / "configs" / "asset_universe.json"

TRADER_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"

# --- thresholds (documented proposal; owner may tighten/loosen) --------------
BARS_LIMIT = 30            # daily bars for the liquidity window
MIN_BARS = 25              # data quality: need >=25 of 30 daily bars
BATCH_SYMBOLS = 50         # crypto bars symbols per request
LIQUIDITY_PERCENTILE = 0.75   # "liquid" = top quartile of traded notional (relative)
MAX_SPREAD_PCT = 0.50      # top-N cost gate: bid/ask spread % of mid
TOP_N_QUOTES = 20          # only fetch quotes for the most liquid N
ALPACA_CRYPTO_TAKER_FEE = 0.0025  # 0.25% flat taker fee (known constant)


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _headers(key: str, secret: str) -> dict:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch_available_crypto(hdrs: dict) -> tuple[list[dict], str]:
    """Return (tradable crypto assets, status_note). Availability = Alpaca's list."""
    r = requests.get(
        f"{TRADER_BASE}/v2/assets", headers=hdrs,
        params={"asset_class": "crypto", "limit": 1000}, timeout=25,
    )
    if r.status_code == 401:
        return [], "AUTH_BLOCKED"
    r.raise_for_status()
    body = r.json()
    data = body.get("data") if isinstance(body, dict) else body  # v2 returns a plain list
    assets: list[dict] = []
    for a in data or []:
        # tradable crypto are flagged status='active' with tradable=True
        if a.get("tradable") and a.get("status") in ("active", "tradable"):
            assets.append({
                "symbol": a.get("symbol"),
                "name": a.get("name"),
                "min_order_size": a.get("min_order_size"),
                "fractionable": a.get("fractionable"),
            })
    return assets, "OK"


def _parse_bars_into(out: dict[str, dict], bars_map: dict) -> None:
    """Fold one /bars response into ``out`` (shared by the batch + retry passes)."""
    for sym, bars in (bars_map or {}).items():
        bars = bars[-BARS_LIMIT:] if bars else bars
        if not bars:
            out.setdefault(sym, {"bars": 0, "median_notional": 0.0, "last_close": None})
            continue
        # traded value per bar = vwap * base volume (falls back to close * volume)
        notionals = sorted(
            float(b.get("vw") or b.get("c", 0)) * float(b.get("v", 0)) for b in bars
        )
        mid = notionals[len(notionals) // 2] if notionals else 0.0
        out[sym] = {
            "bars": len(bars),
            "median_notional": round(mid, 2),
            "last_close": bars[-1].get("c"),
        }


def fetch_bars_notional(hdrs: dict, symbols: list[str]) -> dict[str, dict]:
    """Batched 30d daily bars -> {symbol: {bars, median_notional, last_close}}.

    Alpaca's free crypto feed intermittently OMITS symbols from a batched /bars
    response, which previously dropped actively-traded pairs (e.g. XRP/USD) from
    the report entirely. After the batched pass we retry every still-missing (or
    zero-bar) symbol individually so the artifact is complete and stable.
    """
    out: dict[str, dict] = {}
    start = (datetime.now(timezone.utc) - timedelta(days=BARS_LIMIT + 3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(0, len(symbols), BATCH_SYMBOLS):
        chunk = symbols[i:i + BATCH_SYMBOLS]
        r = requests.get(
            f"{DATA_BASE}/v1beta3/crypto/us/bars",
            headers=hdrs,
            params={"symbols": ",".join(chunk), "timeframe": "1D", "start": start},
            timeout=30,
        )
        r.raise_for_status()
        _parse_bars_into(out, r.json().get("bars", {}))
        time.sleep(0.2)  # be polite to the free data tier

    # --- retry pass: individually fetch symbols the batch omitted ---------------
    for attempt in range(3):
        missing = [s for s in symbols if out.get(s, {}).get("bars", 0) == 0]
        if not missing:
            break
        for sym in missing:
            try:
                r = requests.get(
                    f"{DATA_BASE}/v1beta3/crypto/us/bars",
                    headers=hdrs,
                    params={"symbols": sym, "timeframe": "1D", "start": start},
                    timeout=20,
                )
                if r.status_code == 200:
                    _parse_bars_into(out, r.json().get("bars", {}))
            except Exception:  # noqa: BLE001 - best-effort completeness retry
                pass
            time.sleep(0.1)
    return out


def fetch_spreads(hdrs: dict, symbols: list[str]) -> dict[str, float]:
    """Latest quote spread as % of mid for the shortlist only (cost proxy).

    Uses the per-call ``/latest/quotes`` endpoint; the historical multi-symbol
    ``/quotes`` endpoint intermittently omits symbols, so we query the small
    shortlist one at a time for reliable bid/ask coverage.
    """
    spreads: dict[str, float] = {}
    for sym in symbols:
        try:
            r = requests.get(
                f"{DATA_BASE}/v1beta3/crypto/us/latest/quotes",
                headers=hdrs,
                params={"symbols": sym},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            q = (r.json().get("quotes", {}) or {}).get(sym)
            if isinstance(q, list) and q:
                q = q[-1]
            if not isinstance(q, dict):
                continue
            bp, ap = q.get("bp"), q.get("ap")
            if bp and ap and (bp + ap) > 0:
                mid = (bp + ap) / 2.0
                spreads[sym] = round((ap - bp) / mid * 100.0, 4)
        except Exception:  # noqa: BLE001 - cost proxy is best-effort
            continue
        time.sleep(0.1)
    return spreads


def build_report(top: int) -> dict:
    load_env()
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    if not key or not secret:
        raise RuntimeError("missing ALPACA_PAPER_API_KEY/SECRET in .env")
    hdrs = _headers(key, secret)

    assets, status = fetch_available_crypto(hdrs)
    if status == "AUTH_BLOCKED":
        raise PermissionError("AUTH_BLOCKED")
    symbols = [a["symbol"] for a in assets if a.get("symbol")]
    by_symbol = {a["symbol"]: a for a in assets}

    metrics = fetch_bars_notional(hdrs, symbols)
    ranked = sorted(
        (s for s in symbols if s in metrics),
        key=lambda s: metrics[s]["median_notional"],
        reverse=True,
    )
    spreads = fetch_spreads(hdrs, ranked[:TOP_N_QUOTES])

    # Alpaca's own crypto volume feed is thin (BTC shows ~1e5 USD/day notional,
    # not the billions seen on aggregate venues), so an absolute USD floor is
    # misleading. Rank *relatively*: a pair is "liquid" if it sits in the top
    # LIQUIDITY_PERCENTILE of traded-notional among Alpaca's tradable crypto.
    positive = sorted(m["median_notional"] for m in metrics.values() if m["median_notional"] > 0)
    if len(positive) >= 4:
        cutoff = positive[min(len(positive) - 1, int(len(positive) * LIQUIDITY_PERCENTILE))]
    else:
        cutoff = 0.0

    rows = []
    for sym in ranked:
        m = metrics[sym]
        spread = spreads.get(sym)
        liquid = m["median_notional"] >= cutoff and m["median_notional"] > 0
        quality = m["bars"] >= MIN_BARS
        # cost gate only bites when a live quote was obtained; missing => unverified
        cost_verified = spread is not None
        cheap = (not cost_verified) or (spread <= MAX_SPREAD_PCT)
        eligible = liquid and quality and cheap
        rows.append({
            "symbol": sym,
            "name": by_symbol[sym].get("name"),
            "available": True,          # it came from Alpaca's tradable list
            "bars_30d": m["bars"],
            "median_notional_usd": m["median_notional"],
            "spread_pct": spread,
            "cost_verified": cost_verified,
            "taker_fee_pct": ALPACA_CRYPTO_TAKER_FEE * 100,
            "gates": {"liquid": liquid, "data_quality": quality, "cost": cheap},
            "eligible": eligible,
            "proposed_candidate": eligible and sym != "BTC/USD",
            "enabled": False,           # NEVER auto-enabled by this script
            "baseline": sym == "BTC/USD",
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Alpaca /v2/assets?asset_class=crypto + crypto bars/quotes (PAPER)",
        "policy": {
            "availability": "Alpaca tradable crypto asset list",
            "eligibility": f">= {MIN_BARS}/{BARS_LIMIT} daily bars AND top-"
                           f"{int((1 - LIQUIDITY_PERCENTILE) * 100)}% notional "
                           f"(cutoff ~${cutoff:,.0f} median daily, relative because "
                           f"Alpaca's crypto volume feed is thin)"
                           + (f" AND verified spread <= {MAX_SPREAD_PCT}%" if spreads else ""),
            "enabling": "requires backtest + owner approval; script never enables",
            "btc": "baseline strategy (kept separate from FVG/OB)",
        },
        "counts": {
            "available": len(symbols),
            "eligible": sum(r["eligible"] for r in rows),
            "proposed_candidates": sum(r["proposed_candidate"] for r in rows),
            "enabled": 0,
        },
        "assets": rows[: max(top, 1)],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Alpaca crypto asset discovery (read-only)")
    ap.add_argument("--top", type=int, default=40, help="report the N most liquid assets")
    ap.add_argument("--write", action="store_true", help="write asset_universe.json")
    args = ap.parse_args()

    try:
        report = build_report(args.top)
    except PermissionError:
        print("AUTH BLOCKED: /v2/assets -> 401. Fix paper keys in D:\\BOT\\.env.")
        return 2
    except Exception as e:  # noqa: BLE001
        print("error:", type(e).__name__, str(e)[:160])
        return 3

    print(f"available={report['counts']['available']} "
          f"eligible={report['counts']['eligible']} "
          f"proposed={report['counts']['proposed_candidates']} enabled=0 (never auto-enabled)")
    print(f"{'SYMBOL':<12}{'bars':>5}{'medNotional$':>16}{'spread%':>9}  gates")
    for r in report["assets"]:
        g = r["gates"]
        flags = "".join([
            "L" if g["liquid"] else "-",
            "Q" if g["data_quality"] else "-",
            "C" if g["cost"] else "-",
        ])
        tag = " [BASELINE]" if r["baseline"] else (" [CANDIDATE]" if r["proposed_candidate"] else "")
        print(f"{r['symbol']:<12}{r['bars_30d']:>5}{r['median_notional_usd']:>16,.0f}"
              f"{(r['spread_pct'] if r['spread_pct'] is not None else -1):>9.3f}  {flags}{tag}")

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"wrote {OUT}")
    print("NOTE: availability from Alpaca; eligibility is a PROPOSAL pending backtest; "
          "nothing here enables trading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
