"""Phase 7 — durable trade ledger + evidence-based review notes.

Backfills a SQLite ledger from the latest Freqtrade backtest result. The same
schema is intended to receive live/paper trades later (source column). This step
only READS backtest output; it never places orders.

AI notes here are descriptive: they separate OBSERVED FACTS from HYPOTHESES and
never modify strategy/risk rules or trigger trades (see docs/Rules.md).
"""
from __future__ import annotations

import glob
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "app" / "user_data" / "backtest_results"
LEDGER_DIR = ROOT / "app" / "ledger"
LEDGER_DB = LEDGER_DIR / "unbound.db"


def latest_result_json() -> dict:
    zips = sorted(glob.glob(str(RESULTS_DIR / "*.zip")))
    if not zips:
        raise SystemExit("No backtest result zip found. Run backtesting first.")
    z = zips[-1]
    with zipfile.ZipFile(z) as f:
        jf = [n for n in f.namelist() if n.endswith(".json") and "config" not in n][0]
        data = json.loads(f.read(jf))
    data["_source_zip"] = z
    return data


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DROP TABLE IF EXISTS trades;
        DROP TABLE IF EXISTS metrics;
        DROP TABLE IF EXISTS equity;
        DROP TABLE IF EXISTS ai_notes;
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, source TEXT, pair TEXT,
            open_date TEXT, close_date TEXT, open_rate REAL, close_rate REAL,
            stake_amount REAL, amount REAL, profit_ratio REAL, profit_abs REAL,
            fee_open REAL, fee_close REAL, exit_reason TEXT, enter_tag TEXT,
            leverage REAL, is_short INTEGER, duration_min INTEGER
        );
        CREATE TABLE metrics (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE equity (date TEXT PRIMARY KEY, balance REAL, drawdown REAL);
        CREATE TABLE ai_notes (
            id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, text TEXT
        );
        """
    )


def load(data: dict, con: sqlite3.Connection) -> None:
    strat = data["strategy"]
    name = list(strat.keys())[0]
    s = strat[name]

    for t in s["trades"]:
        con.execute(
            "INSERT INTO trades (source,pair,open_date,close_date,open_rate,close_rate,"
            "stake_amount,amount,profit_ratio,profit_abs,fee_open,fee_close,exit_reason,"
            "enter_tag,leverage,is_short,duration_min) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "backtest", t.get("pair"), t.get("open_date"), t.get("close_date"),
                t.get("open_rate"), t.get("close_rate"), t.get("stake_amount"),
                t.get("amount"), t.get("profit_ratio"), t.get("profit_abs"),
                t.get("fee_open"), t.get("fee_close"), t.get("exit_reason"),
                t.get("enter_tag"), t.get("leverage"), 1 if t.get("is_short") else 0,
                t.get("trade_duration"),
            ),
        )

    keep = [
        "strategy_name", "total_trades", "wins", "losses", "winrate", "profit_total",
        "profit_total_abs", "final_balance", "starting_balance", "cagr", "sharpe",
        "sortino", "calmar", "expectancy", "profit_factor", "max_drawdown_account",
        "max_drawdown_abs", "market_change", "timeframe", "stake_currency",
        "backtest_start", "backtest_end",
    ]
    for k in keep:
        con.execute("INSERT OR REPLACE INTO metrics VALUES (?,?)", (k, json.dumps(s.get(k))))
    con.execute("INSERT OR REPLACE INTO metrics VALUES (?,?)", ("_source_zip", json.dumps(data.get("_source_zip"))))

    # Equity curve from daily profit, with running peak/drawdown.
    daily = s.get("daily_profit") or {}
    if isinstance(daily, dict):
        pairs = [(d, v) for d, v in daily.items()]
    else:  # list of [date, profit]
        pairs = [(row[0], row[1]) for row in daily]
    pairs.sort(key=lambda x: str(x[0]))
    start = float(s.get("starting_balance") or 10000)
    bal = start
    peak = bal
    for d, v in pairs:
        bal += float(v)
        peak = max(peak, bal)
        dd = (bal - peak) / peak if peak else 0.0
        con.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?)", (str(d), bal, dd))

    con.commit()


def write_notes(s: dict, con: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    trades = s["trades"]
    wins = [t for t in trades if (t.get("profit_abs") or 0) > 0]
    losses = [t for t in trades if (t.get("profit_abs") or 0) <= 0]
    stop_hits = [t for t in trades if t.get("exit_reason") == "stop_loss"]
    avg_win = sum(t["profit_abs"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["profit_abs"] for t in losses) / len(losses) if losses else 0

    notes = [
        ("FACT", f"Backtest {s.get('backtest_start')} -> {s.get('backtest_end')}: "
                 f"{s.get('total_trades')} trades, winrate {round((s.get('winrate') or 0)*100,1)}%, "
                 f"total {round((s.get('profit_total') or 0)*100,1)}%, CAGR {round((s.get('cagr') or 0)*100,2)}%, "
                 f"maxDD {round((s.get('max_drawdown_account') or 0)*100,2)}%."),
        ("FACT", f"Buy-and-hold over the same window changed {round((s.get('market_change') or 0)*100,1)}%; "
                 f"strategy total was {round((s.get('profit_total') or 0)*100,1)}%."),
        ("FACT", f"Exit reasons: stop_loss={len(stop_hits)} of {len(trades)} trades. "
                 f"Avg winner {round(avg_win,2)} vs avg loser {round(avg_loss,2)}."),
        ("HYPOTHESIS", "With candidate thresholds the strategy did not clearly beat buy-and-hold; "
                       "the true (unknown) source thresholds may behave differently. Needs a "
                       "parameter sweep + walk-forward before any conclusion."),
        ("HYPOTHESIS", f"{len(stop_hits)}/{len(trades)} stop_loss exits suggests the -35% stop may be "
                       "mismatched to daily volatility. Experiment (do NOT auto-apply): test tighter "
                       "stop and signal-only exit."),
        ("GUARDRAIL", "These notes are descriptive only. No strategy/risk rule was changed and no "
                      "order was placed. Owner approval required for any parameter change."),
    ]
    for kind, text in notes:
        con.execute("INSERT INTO ai_notes (created_at,kind,text) VALUES (?,?,?)", (now, kind, text))
    con.commit()


def main() -> None:
    data = latest_result_json()
    strat = data["strategy"]
    name = list(strat.keys())[0]
    s = strat[name]
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LEDGER_DB)
    init_db(con)
    load(data, con)
    write_notes(s, con)
    n = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    e = con.execute("SELECT COUNT(*) FROM equity").fetchone()[0]
    nn = con.execute("SELECT COUNT(*) FROM ai_notes").fetchone()[0]
    con.close()
    print(f"ledger written: {LEDGER_DB}")
    print(f"trades={n} equity_points={e} ai_notes={nn} strategy={name}")


if __name__ == "__main__":
    main()
