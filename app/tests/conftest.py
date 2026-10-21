"""pytest config for the UnboundBot app layer.

Keeps tests credential-free and order-free: the strategy, reconciliation, and
reporting code are exercised against temp SQLite DBs and mocked broker/IO. Nothing
here ever starts the trading process or places a (even paper) order.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "app" / "scripts"
STRATEGIES = ROOT / "app" / "user_data" / "strategies"
for p in (str(SCRIPTS), str(STRATEGIES)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def tmp_ledger(monkeypatch, tmp_path):
    """Point obs_lib's ledger at a throwaway DB and ensure schema is present."""
    import obs_lib as O
    db = tmp_path / "unbound_ledger.db"
    monkeypatch.setattr(O, "LEDGER_DB", db)
    con = O.ledger_connect()
    con.close()
    yield db


TRADE_COLS = ("id,pair,is_open,open_date,close_date,open_rate,close_rate,stake_amount,"
              "amount,fee_open,fee_close,fee_open_cost,fee_close_cost,fee_open_currency,"
              "fee_close_currency,close_profit,close_profit_abs,exit_reason,enter_tag,"
              "leverage,is_short,strategy,timeframe")


@pytest.fixture
def make_ft_db(tmp_path):
    """Build a temp Freqtrade-shaped DB. Usage: make_ft_db(trades=[...], orders=[...], locks=n)."""
    def _make(trades=None, orders=None, locks=0):
        db = tmp_path / "tradesv3.sqlite"
        c = sqlite3.connect(db)
        cols = ("id INTEGER PRIMARY KEY, pair TEXT, is_open INTEGER, open_date TEXT, "
                "close_date TEXT, open_rate REAL, close_rate REAL, stake_amount REAL, "
                "amount REAL, fee_open REAL, fee_close REAL, fee_open_cost REAL, "
                "fee_close_cost REAL, fee_open_currency TEXT, fee_close_currency TEXT, "
                "close_profit REAL, close_profit_abs REAL, exit_reason TEXT, enter_tag TEXT, "
                "leverage REAL, is_short INTEGER, strategy TEXT, timeframe TEXT")
        c.execute(f"CREATE TABLE trades ({cols})")
        c.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, order_id TEXT, "
                  "ft_is_open INTEGER, ft_order_side TEXT, status TEXT)")
        c.execute("CREATE TABLE pairlocks (id INTEGER PRIMARY KEY, pair TEXT, side TEXT, "
                  "reason TEXT, lock_time TEXT, lock_end_time TEXT, active INTEGER)")
        ncol = TRADE_COLS.count(",") + 1
        for t in (trades or []):
            assert len(t) == ncol, f"trade tuple has {len(t)} values, expected {ncol}"
            c.execute(f"INSERT INTO trades ({TRADE_COLS}) VALUES "
                      "(" + ",".join("?" * ncol) + ")", t)
        for o in (orders or []):
            c.execute("INSERT INTO orders (order_id, ft_is_open, ft_order_side, status) "
                      "VALUES (?,?,?,?)", o)
        for i in range(locks):
            c.execute("INSERT INTO pairlocks (pair,side,reason,lock_time,active) "
                      "VALUES ('BTC/USD','long','MaxDrawdown','2026-10-20',1)", ())
        c.commit()
        c.close()
        return db
    return _make
