"""Phase 10 observation harness — shared read-only helpers.

Used by app/scripts/reconcile.py and app/scripts/weekly_report.py. Everything
here is READ-ONLY against the two authoritative sources (the Freqtrade paper
trade DB and the Alpaca PAPER account) and idempotent against our durable
ledger. It never places orders and never prints secrets.

Ledger design note: backtest/research rows already live in `trades`/`equity`
(written by build_ledger.py). Live/paper observation is stored in SEPARATE
tables so it never overwrites research and so the Freqtrade DB remains the
execution source of truth (docs/Rules.md, Phases.md P7-01/P10).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
PAPER_CFG = ROOT / "app" / "configs" / "config.alpaca.paper.json"
LEDGER_DB = ROOT / "app" / "ledger" / "unbound.db"
# Heartbeat/PID file maintained by run_paper.py while the paper bot lives.
STATE_FILE = ROOT / "app" / "state" / "paper_bot.json"
ALPACA_FEATHER = ROOT / "app" / "user_data" / "data" / "alpaca" / "BTC_USD-1d.feather"

# Alpaca PAPER trader host (read-only GETs). Overridable via .env.
ALPACA_BASE = "https://paper-api.alpaca.markets"

# Live observation tables (created only if missing; research tables untouched).
SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY, source TEXT, pair TEXT, is_open INTEGER,
    open_date TEXT, close_date TEXT, open_rate REAL, close_rate REAL,
    stake_amount REAL, amount REAL, fee_open REAL, fee_close REAL,
    fee_open_cost REAL, fee_close_cost REAL, fee_open_currency TEXT,
    fee_close_currency TEXT,
    profit_ratio REAL, profit_abs REAL, exit_reason TEXT, enter_tag TEXT,
    leverage REAL, is_short INTEGER, strategy TEXT, timeframe TEXT,
    reconciled_at TEXT
);
CREATE TABLE IF NOT EXISTS reconcile_log (
    ts TEXT PRIMARY KEY, status TEXT, detail TEXT,
    broker_cash REAL, broker_equity REAL, broker_buying_power REAL,
    broker_position_qty REAL, broker_position_val REAL,
    ft_open_trades INTEGER, ft_open_orders INTEGER,
    broker_open_orders INTEGER, unmatched_broker_orders INTEGER,
    ft_unresolved_orders INTEGER, active_locks INTEGER,
    qty_drift REAL, process_alive INTEGER, heartbeat_age_s REAL,
    candle_age_h REAL, strategy TEXT, version_note TEXT
);
CREATE TABLE IF NOT EXISTS account_equity (
    date TEXT PRIMARY KEY, cash REAL, equity REAL, buying_power REAL,
    position_value REAL, drawdown REAL, source TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    ts TEXT PRIMARY KEY, window_start TEXT, window_end TEXT,
    path TEXT, summary TEXT
);
"""


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def ft_db_path() -> Path | None:
    """Resolve the Freqtrade paper trade DB from config db_url, else common spots."""
    candidates: list[Path] = []
    try:
        cfg = json.loads(PAPER_CFG.read_text(encoding="utf-8"))
        db = cfg.get("db_url", "")
        if db.startswith("sqlite:///"):
            candidates.append(Path(db.replace("sqlite:///", "")))
    except Exception:  # noqa: BLE001
        pass
    candidates += [ROOT / "tradesv3.sqlite", ROOT / "app" / "user_data" / "tradesv3.sqlite"]
    for c in candidates:
        if c.exists():
            return c
    return None


def ft_connect_ro(db: Path) -> sqlite3.Connection:
    """Open the Freqtrade DB read-only; concurrent reads don't block the bot."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def ledger_connect() -> sqlite3.Connection:
    LEDGER_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LEDGER_DB)
    con.executescript(SCHEMA)
    _ensure_columns(con)
    con.commit()
    return con


# (table, column, type) added idempotently so pre-existing dev DBs upgrade in place.
_MIGRATIONS = [
    ("paper_trades", "fee_open_cost", "REAL"),
    ("paper_trades", "fee_close_cost", "REAL"),
    ("paper_trades", "fee_open_currency", "TEXT"),
    ("paper_trades", "fee_close_currency", "TEXT"),
    ("reconcile_log", "ft_unresolved_orders", "INTEGER"),
    ("reconcile_log", "active_locks", "INTEGER"),
    ("reconcile_log", "process_alive", "INTEGER"),
    ("reconcile_log", "heartbeat_age_s", "REAL"),
    ("reconcile_log", "candle_age_h", "REAL"),
]


def _ensure_columns(con: sqlite3.Connection) -> None:
    for table, col, typ in _MIGRATIONS:
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def read_heartbeat() -> dict | None:
    """Return the paper bot's heartbeat state file, or None if absent/unreadable.
    Expected keys written by run_paper.py: bot_name, pid, started, last_heartbeat
    (ISO-8601 UTC)."""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return None


def latest_candle_age_hours(feather_path: Path | None = None, now=None) -> float | None:
    """Hours since the most recent completed daily candle on disk. None if no data."""
    p = feather_path or ALPACA_FEATHER
    try:
        import pandas as pd
        from datetime import datetime, timezone as _tz
        df = pd.read_feather(p)
        last = pd.to_datetime(df["date"], utc=True).max()
        ref = now or pd.Timestamp.now(tz="UTC")
        return float((ref - last).total_seconds() / 3600.0)
    except Exception:  # noqa: BLE001
        return None



def alpaca_get(path: str, timeout: int = 15):
    """Authenticated read-only GET against Alpaca PAPER. Returns (status, json|None)."""
    load_env()
    key = os.environ.get("ALPACA_PAPER_API_KEY", "")
    secret = os.environ.get("ALPACA_PAPER_API_SECRET", "")
    if not key or not secret:
        return 0, None
    try:
        r = requests.get(
            f"{ALPACA_BASE}{path}",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        return -1, {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    if r.status_code == 200:
        try:
            return 200, r.json()
        except ValueError:
            return 200, None
    # 404 on /v2/positions means "no positions" for Alpaca.
    return r.status_code, (r.text[:200] if r.text else None)
