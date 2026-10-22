"""Durable trade journal for the UnboundBot learning layer (Phase D).

Builds the ``trade_journal`` table (defined in obs_lib.SCHEMA) from the CLOSED rows of
``paper_trades`` that the read-only reconcile step already mirrors into the ledger. It
adds the two things a closed-trade row lacks for learning:

  * the strategy ``family`` the pair was routed to (from the registry via policy), and
  * the ``R``-multiple — realized PnL measured in units of that trade's PLANNED risk
    (stake x stop distance), the scale-free currency the performance gate and sizing use.

It is READ-ONLY with respect to the broker and the order path: it only reads the ledger
and writes the journal table. The entry "feature snapshot" column is populated only when
the candle data for the entry bar is available offline (best-effort); it is left NULL
otherwise and never faked, so a missing feature never becomes a misleading 0.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from risk import policy


def r_multiple(profit_abs: float | None, stake: float | None, stop_frac: float | None) -> float | None:
    """R-multiple = realized PnL / planned risk. planned risk = stake * stop fraction.
    Returns None (fail-closed) when the risk cannot be computed — never a fake 0."""
    if profit_abs is None or stake is None or stop_frac is None:
        return None
    planned_risk = float(stake) * abs(float(stop_frac))
    if planned_risk <= 0:
        return None
    return round(float(profit_abs) / planned_risk, 4)


def _closed_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return con.execute(
        "SELECT id, pair, timeframe, stake_amount, fee_open_cost, fee_close_cost, "
        "profit_abs, open_date, close_date, exit_reason, enter_tag "
        "FROM paper_trades WHERE is_open = 0 AND close_date IS NOT NULL"
    ).fetchall()


def build_journal(con: sqlite3.Connection,
                  family_fn: Callable[[str], str | None] | None = None,
                  stop_fn: Callable[[str], float | None] | None = None,
                  feature_fn: Callable[[str, str], dict | None] | None = None) -> int:
    """Upsert one trade_journal row per closed paper_trade. Returns the number written.

    family_fn/stop_fn default to the live registry/policy lookups but are injectable so
    the builder is unit-testable without the real configs. feature_fn(pair, open_date)
    optionally returns an entry indicator snapshot; when absent it is stored as NULL.
    """
    family_fn = family_fn or (lambda p: policy.pair_entry(p).get("strategy_family"))
    stop_fn = stop_fn or policy.stoploss_fraction
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in _closed_rows(con):
        pair = r["pair"]
        stake = float(r["stake_amount"] or 0.0)
        pnl = float(r["profit_abs"]) if r["profit_abs"] is not None else None
        fees = (float(r["fee_open_cost"] or 0.0) + float(r["fee_close_cost"] or 0.0)) or None
        fam = family_fn(pair)
        r_mult = r_multiple(pnl, stake, stop_fn(pair))
        feats = None
        if feature_fn is not None:
            snap = feature_fn(pair, r["open_date"])
            feats = json.dumps(snap) if snap else None
        con.execute(
            "INSERT OR REPLACE INTO trade_journal (id, pair, family, timeframe, stake, "
            "fee_cost, r, pnl, open_date, close_date, exit_reason, enter_tag, features, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], pair, fam, r["timeframe"], stake, fees, r_mult, pnl,
             r["open_date"], r["close_date"], r["exit_reason"], r["enter_tag"], feats, now),
        )
        n += 1
    con.commit()
    return n


def closed_records(con: sqlite3.Connection) -> list[dict]:
    """Read the journal back as perf.py-compatible records (pair, family, r, pnl)."""
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT pair, family, timeframe, r, pnl FROM trade_journal"
    ).fetchall()
    return [dict(r) for r in rows]
