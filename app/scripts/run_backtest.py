"""Backtest runner — reproducible, credential-injected, multi-asset research harness.

Two modes:

  1. SINGLE run (default): backtest one strategy over one config/timerange, exactly the
     way the earlier audit runs did. Offline simulation — NO orders, NO trading endpoint.

  2. MATRIX run (--matrix): Phase C of the owner-approved plan — for every (pair,
     candidate family) run the pure family signal math on the public Binance USDT proxy
     (config.research.binance.json), download the candles, and emit a per-pair
     best-by-expectancy report to docs/Backtest_Results_<date>.csv + a markdown table.

WHY THE BINANCE PROXY: Freqtrade 2026.9 cannot load Alpaca's private market-metadata
endpoint during a backtest (alpaca is not Freqtrade-native), and the production veto
fail-closes offline (needs a fresh broker equity snapshot + cross-executor exposure
ledger only the running monitor writes). So research measures SIGNAL QUALITY via
ResearchFamily (the same app/indicators/families.py the live dispatcher routes to), with
a realistic taker fee (--fee) and price_side="other" (touch-to-touch) spread proxy.
This is a RESEARCH PROXY, NOT Alpaca execution parity (docs/Phase0_Audit.md sec.5).

Credentials are NOT needed for the Binance proxy (public data, dry_run), so no secrets
are read or injected here.

Usage:
  python app/scripts/run_backtest.py                                  # BTC baseline, 1d, full range
  python app/scripts/run_backtest.py --timerange 20210101-20261020
  python app/scripts/run_backtest.py --matrix --timerange 20240101-20261020
Exit code mirrors freqtrade's (single mode) or 0 after a matrix report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FT = ROOT / ".venv" / "Scripts" / "freqtrade.exe"
USERDIR = ROOT / "app" / "user_data"
RESEARCH_CFG = ROOT / "app" / "configs" / "config.research.binance.json"
ALPACA_CFG = ROOT / "app" / "configs" / "config.alpaca.paper.json"
DEFAULT_TIMERANGE = "20210101-20261020"
DOCS = ROOT / "docs"

# Taker fee per side for the after-cost expectancy (0.25%/side ≈ the Alpaca crypto
# taker cost; spread is additionally approximated by the proxy's price_side="other").
RESEARCH_FEE = "0.0025"

# Alpaca USD pair -> Binance USDT research proxy pair (Phase A universe).
PROXY_PAIRS = {
    "BTC/USD": "BTC/USDT", "ETH/USD": "ETH/USDT", "XRP/USD": "XRP/USDT",
    "DOT/USD": "DOT/USDT", "LINK/USD": "LINK/USDT", "SOL/USD": "SOL/USDT",
    "UNI/USD": "UNI/USDT", "LTC/USD": "LTC/USDT", "AVAX/USD": "AVAX/USDT",
    "DOGE/USD": "DOGE/USDT",
}

# Candidate families per timeframe (which signal families are worth ranking).
FAMILIES_BY_TF = {
    "1d": ["momentum_ema_vol", "rsi_divergence", "bb_squeeze", "link_trend"],
    "1h": ["momentum_ema_vol", "rsi_divergence", "bb_squeeze", "link_trend"],
    "5m": ["momentum_ema_vol", "link_trend"],
}
# Cost-aware stop per timeframe used for the research sim (fraction).
STOP_BY_TF = {"1d": "0.15", "1h": "0.06", "5m": "0.03"}


def _flag(argv: list[str], name: str, default: str | None = None) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def run_single(argv: list[str]) -> int:
    """Legacy single backtest (BTC baseline by default) against a chosen config."""
    cfg = Path(_flag(argv, "--config", str(ALPACA_CFG)))
    strategy = _flag(argv, "--strategy", "BtcZScore")
    tr = _flag(argv, "--timerange", DEFAULT_TIMERANGE)
    pairs = _flag(argv, "--pairs")
    env_over = []
    if pairs:
        env_over = ["--pairs", *[p.strip() for p in pairs.split(",") if p.strip()]]
    args = [str(FT), "backtesting", "-c", str(cfg), "--userdir", str(USERDIR),
            "--strategy", strategy, "--timerange", tr, "--cache", "none", *env_over]
    print("running (offline simulation, NO orders):", " ".join(args[1:]))
    return subprocess.call(args)


def _download(pairs: list[str], timeframe: str, timerange: str) -> int:
    args = [str(FT), "download-data", "-c", str(RESEARCH_CFG), "--userdir", str(USERDIR),
            "--timeframe", timeframe, "--timerange", timerange,
            "--pairs", *pairs]
    print(f"  download-data {timeframe} for {pairs} ...")
    return subprocess.call(args)


def _parse_result() -> dict:
    """Read the newest freqtrade backtest artifact and return the single strategy block's
    summary metrics.

    Freqtrade 2026.9 writes ``backtest_results/.last_result.json`` whose ``latest_backtest``
    points to either ``backtest-result-<ts>.zip`` (``--export trades``) or a ``.json``.
    The zip contains the result json (no separate plain .json is written). We follow the
    pointer, unzip if needed, and take the ONE strategy block (one strategy per run).
    Returns {} if nothing parseable — the caller records a FAILED row, never a silent 0.
    """
    results_dir = USERDIR / "backtest_results"
    lr = results_dir / ".last_result.json"
    if not lr.exists():
        return {}
    try:
        name = json.loads(lr.read_text(encoding="utf-8")).get("latest_backtest")
        if not name:
            return {}
        base = results_dir / name
        if name.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(base) as zf:
                inner = [n for n in zf.namelist() if n.endswith(".json") and "meta" not in n]
                if not inner:
                    return {}
                data = json.loads(zf.read(inner[0]).decode("utf-8"))
        else:
            data = json.loads(base.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    strat = data.get("strategy", {})
    block = next(iter(strat.values()), None) if isinstance(strat, dict) else None
    if not isinstance(block, dict):
        return {}
    def _pct(key):
        v = block.get(key)
        return round(float(v) * 100, 3) if isinstance(v, (int, float)) else None
    def _num(key):
        v = block.get(key)
        return round(float(v), 4) if isinstance(v, (int, float)) else None
    return {
        "trades": block.get("total_trades"),
        "win_%": _pct("winrate"),
        "profit_total_%": _pct("profit_total"),
        "profit_factor": _num("profit_factor"),
        "expectancy": _num("expectancy"),
        "max_drawdown_%": _pct("max_drawdown_account"),
        "sharpe": _num("sharpe"),
        "cagr_%": _pct("cagr"),
    }


def _run_family(pairs: list[str], timeframe: str, family: str, timerange: str) -> dict:
    import os
    env = dict(os.environ)
    env["UNBOUND_RESEARCH_FAMILY"] = family
    env["UNBOUND_RESEARCH_TF"] = timeframe
    env["UNBOUND_RESEARCH_STOP"] = STOP_BY_TF.get(timeframe, "0.10")
    args = [str(FT), "backtesting", "-c", str(RESEARCH_CFG), "--userdir", str(USERDIR),
            "--strategy", "ResearchFamily", "--strategy-path", str(USERDIR / "strategies"),
            "--timerange", timerange, "--cache", "none", "--fee", RESEARCH_FEE,
            "--export", "trades", "--pairs", *pairs]
    rc = subprocess.call(args, env=env)
    metrics = dict(_parse_result())
    metrics["family"] = family
    metrics["timeframe"] = timeframe
    metrics["pairs"] = " ".join(pairs)
    metrics["rc"] = rc
    return metrics


def run_matrix(argv: list[str]) -> int:
    import csv
    tr = _flag(argv, "--timerange", "20240101-20261020")
    # which pairs to rank: explicit --pairs (USD), else the whole proxy universe
    want = _flag(argv, "--pairs")
    usd_pairs = ([p.strip() for p in want.split(",")] if want else list(PROXY_PAIRS))
    usd_pairs = [p for p in usd_pairs if p in PROXY_PAIRS]
    timeframe = _flag(argv, "--timeframe", "1d")
    families = FAMILIES_BY_TF.get(timeframe, FAMILIES_BY_TF["1d"])
    proxy = [PROXY_PAIRS[p] for p in usd_pairs]

    print(f"Matrix backtest: {len(usd_pairs)} pairs x {len(families)} families on TF {timeframe}, "
          f"range {tr}, fee {RESEARCH_FEE}/side (Binance USDT proxy)")
    dl = _download(proxy, timeframe, tr)
    if dl != 0:
        print(f"WARNING: download-data exited {dl} (network/data gap). Running on whatever "
              f"candles are present; failed rows will be recorded, never silently zeroed.")

    rows: list[dict] = []
    # per-pair, per-family detail — the matrix that picks best-by-expectancy per pair.
    for usd in usd_pairs:
        bp = PROXY_PAIRS[usd]
        for fam in families:
            m = _run_family([bp], timeframe, fam, tr)
            rows.append({"pair": usd, **m})

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = DOCS / f"Backtest_Results_{date}.csv"
    fields = ["pair", "timeframe", "family", "trades", "win_%", "profit_total_%",
              "profit_factor", "expectancy", "max_drawdown_%", "sharpe",
              "cagr_%", "rc"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    best = {}
    for r in rows:
        if r.get("pair") == "(all-proxy)":
            continue
        e = r.get("expectancy")
        t = r.get("trades") or 0
        if e is None or t < 5:
            continue
        cur = best.get(r["pair"])
        if cur is None or e > (cur.get("expectancy") or -1e9):
            best[r["pair"]] = r
    md = _markdown(rows, best, timeframe, tr, date)
    md_path = DOCS / f"Backtest_Results_{date}.md"
    md_path.write_text(md, encoding="utf-8")

    print(f"\nWrote {csv_path.relative_to(ROOT)} and {md_path.relative_to(ROOT)}")
    print("Best-by-expectancy family per pair:")
    for p, r in sorted(best.items()):
        print(f"  {p:10} -> {r['family']:16} (trades={r.get('trades')}, expectancy={r.get('expectancy')})")
    return 0


def _markdown(rows, best, timeframe, tr, date) -> str:
    lines = [
        f"# Backtest Results — {date} (RESEARCH PROXY)",
        "",
        f"- Source: **public Binance USDT candles** via `config.research.binance.json`.",
        f"- Strategy: `ResearchFamily` (binds `app/indicators/families.py` — the SAME causal "
        f"signal math the live dispatcher routes to, WITHOUT the order-safety veto).",
        f"- Timeframe: `{timeframe}`   Range: `{tr}`   Fee: **{RESEARCH_FEE}/side** taker; "
        f"`entry_pricing.price_side=other` approximates the touch-to-touch spread.",
        "",
        "> **NOT Alpaca execution parity.** This ranks *signal quality / after-cost expectancy* "
        "on a price proxy. It does not prove profit, and it does not authorize live trading. "
        "The live veto (stake caps, exposure, kill-switch) is exercised only in PAPER, never here.",
        "",
        "## Best-by-expectancy family per pair (min 5 trades)",
        "",
        "| Pair | Family | Trades | Win% | Profit% | Exp expectancy | Profit factor | Max DD% |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p, r in sorted(best.items()):
        lines.append(
            f"| {p} | {r['family']} | {r.get('trades')} | {r.get('win_%')} | "
            f"{r.get('profit_total_%')} | {r.get('expectancy')} | {r.get('profit_factor')} | "
            f"{r.get('max_drawdown_%')} |")
    if not best:
        lines.append("| _(no pair reached the 5-trade threshold in this window)_ | | | | | | | |")
    lines += ["", "## All rows", "",
              "| Pair | TF | Family | Trades | Win% | Profit% | Expectancy | PF | MaxDD% | rc |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r.get('pair')} | {r.get('timeframe')} | {r.get('family')} | {r.get('trades')} | "
            f"{r.get('win_%')} | {r.get('profit_total_%')} | {r.get('expectancy')} | "
            f"{r.get('profit_factor')} | {r.get('max_drawdown_%')} | {r.get('rc')} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    if "--matrix" in argv:
        return run_matrix(argv)
    return run_single(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
