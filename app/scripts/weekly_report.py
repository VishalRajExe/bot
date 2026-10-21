"""Phase 10 — weekly observation report generator (READ-ONLY).

Summarizes the paper-trading observation interval from the durable ledger
(populated by reconcile.py) plus the Freqtrade DB, and writes a Markdown report
at docs/Phase10_Observation.md. Covers the Phases.md P10 checklist: signals /
orders & fills / costs / reconciliation drift / risk triggers / exposure &
drawdown, with explicit "insufficient sample" honesty for the daily-timeframe
bot. Places no orders; touches nothing but the ledger `reports` row and the md.

Usage:
  python app/scripts/weekly_report.py            # trailing 7 days
  python app/scripts/weekly_report.py --days 14  # custom window
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
import obs_lib as O  # noqa: E402

ROOT = O.ROOT
REPORT = ROOT / "docs" / "Phase10_Observation.md"


def _rows(con, q, args=()):
    cur = con.execute(q, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def collect(days: int) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_day = start.strftime("%Y-%m-%d")
    end_day = now.strftime("%Y-%m-%d")

    lc = O.ledger_connect()
    trades_all = _rows(lc, "SELECT * FROM paper_trades ORDER BY id")
    trades_win = [t for t in trades_all
                  if (t["open_date"] or "")[:10] >= start_day]
    closed_win = [t for t in trades_all
                  if t["is_open"] == 0 and (t["close_date"] or "")[:10] >= start_day]
    open_now = [t for t in trades_all if t["is_open"] == 1]

    recs = _rows(lc, "SELECT * FROM reconcile_log WHERE substr(ts,1,10) >= ? ORDER BY ts",
                 (start_day,))
    eq = _rows(lc, "SELECT * FROM account_equity WHERE date >= ? ORDER BY date", (start_day,))
    lc.close()

    # Freqtrade-side: protection locks (risk triggers) that overlapped the window.
    locks = []
    db = O.ft_db_path()
    if db is not None:
        c = O.ft_connect_ro(db)
        try:
            tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "pairlocks" in tabs:
                locks = _rows(c,
                    "SELECT pair,side,reason,lock_time,lock_end_time,active FROM pairlocks "
                    "WHERE COALESCE(lock_end_time,lock_time) >= ? ORDER BY lock_time", (start_day,))
        finally:
            c.close()

    statuses = {}
    for r in recs:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    max_drift = max((abs(r["qty_drift"] or 0.0) for r in recs), default=0.0)
    review_runs = [r for r in recs if r["status"] == "REVIEW"]

    eq_start = eq[0]["equity"] if eq else None
    eq_end = eq[-1]["equity"] if eq else None
    peak = max((e["equity"] for e in eq), default=None)
    max_dd = min((e["drawdown"] for e in eq), default=0.0)
    last = recs[-1] if recs else None
    exposure = None
    if eq and eq[-1]["equity"]:
        exposure = round(eq[-1]["position_value"] / eq[-1]["equity"] * 100, 2)

    fees = sum((t["fee_open"] or 0) + (t["fee_close"] or 0) for t in trades_all)
    realized = sum((t["profit_abs"] or 0.0) for t in trades_all if t["is_open"] == 0)

    return {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": days, "start_day": start_day, "end_day": end_day,
        "trades_all": trades_all, "trades_opened_win": trades_win,
        "trades_closed_win": closed_win, "open_now": open_now,
        "recs": recs, "statuses": statuses, "max_drift": max_drift,
        "review_runs": review_runs, "eq": eq, "eq_start": eq_start,
        "eq_end": eq_end, "peak": peak, "max_dd": max_dd, "exposure": exposure,
        "last": last, "locks": locks, "fees": fees, "realized": realized,
        "db": str(db),
    }


def render(d: dict) -> str:
    L = []
    A = L.append
    A("# Phase 10 — Paper Observation Report")
    A("")
    A(f"- Generated (UTC): `{d['generated']}`")
    A(f"- Window: trailing **{d['days']} days** ({d['start_day']} → {d['end_day']})")
    A(f"- Mode: Alpaca **PAPER** only (`dry_run=false`, paper-api endpoint). No real money.")
    A(f"- Freqtrade trade DB: `{d['db']}`")
    A(f"- Source of truth: Freqtrade execution DB; this report is a read-only mirror.")
    A("")

    A("## 1. Signals & entries/exits")
    n_open = len(d["trades_opened_win"])
    n_close = len(d["trades_closed_win"])
    A(f"- Trades opened in window: **{n_open}**")
    A(f"- Trades closed in window: **{n_close}**")
    A(f"- Currently open positions: **{len(d['open_now'])}**")
    if d["open_now"]:
        A("")
        A("| pair | opened | entry_rate | stake | amount | enter_tag |")
        A("|---|---|---|---|---|---|")
        for t in d["open_now"]:
            A(f"| {t['pair']} | {t['open_date']} | {round(t['open_rate'] or 0,2)} "
              f"| {round(t['stake_amount'] or 0,2)} | {round(t['amount'] or 0,6)} "
              f"| {t['enter_tag'] or '-'} |")
    if n_open == 0 and n_close == 0:
        A("")
        A("> Daily-timeframe bot on a single pair (BTC/USD). Zero signals in this "
          "window is expected and is NOT evidence of a stall — it means the Z-score "
          "entry condition was not met. **Insufficient sample for statistical "
          "significance; do not extrapolate edge from this interval.**")
    A("")

    A("## 2. Orders, fills & costs")
    A(f"- Total mirrored trades (all-time in ledger): **{len(d['trades_all'])}**")
    A(f"- Cumulative fees booked in ledger: **{round(d['fees'], 4)}**")
    A(f"- Realized P&L (closed trades): **{round(d['realized'], 4)}**")
    if d["trades_all"]:
        A("")
        A("| id | pair | open | close | exit_reason | profit_ratio | profit_abs |")
        A("|---|---|---|---|---|---|---|")
        for t in d["trades_all"][-15:]:
            pr = '' if t['profit_ratio'] is None else round(t['profit_ratio'], 4)
            pa = '' if t['profit_abs'] is None else round(t['profit_abs'], 2)
            A(f"| {t['id']} | {t['pair']} | {t['open_date']} | {t['close_date'] or 'OPEN'} "
              f"| {t['exit_reason'] or '-'} | {pr} | {pa} |")
    A("")

    A("## 3. Reconciliation (Freqtrade records vs broker)")
    A(f"- Observation snapshots in window: **{len(d['recs'])}**")
    if d["recs"]:
        A(f"- Status mix: " + ", ".join(f"{k}={v}" for k, v in sorted(d["statuses"].items())))
        A(f"- Max absolute position qty drift: **{d['max_drift']}**")
        A(f"- Last snapshot: `{d['last']['ts']}` → **{d['last']['status']}** — {d['last']['detail']}")
        if d["review_runs"]:
            A("")
            A("### ⚠ Runs flagged REVIEW (needs attention)")
            for r in d["review_runs"]:
                A(f"- `{r['ts']}` — {r['detail']}")
        else:
            A("- No drift / unmatched broker activity / external orders detected. ✅")
    else:
        A("- No reconcile snapshots yet — run `python app/scripts/reconcile.py` "
          "(or `--watch`) to populate this section.")
    A("")

    A("## 4. Risk triggers (protections / pair locks)")
    if d["locks"]:
        A("| pair | side | reason | locked | until | active |")
        A("|---|---|---|---|---|---|")
        for k in d["locks"]:
            A(f"| {k['pair']} | {k['side']} | {k['reason']} | {k['lock_time']} "
              f"| {k['lock_end_time']} | {1 if k['active'] else 0} |")
    else:
        A("- No protection/pair-lock events in window.")
    A("")

    A("## 5. Account, exposure & drawdown")
    if d["eq"]:
        A(f"- Equity (start → end): **{round(d['eq_start'],2)} → {round(d['eq_end'],2)}**")
        A(f"- Peak equity in window: **{round(d['peak'],2)}**")
        A(f"- Max drawdown in window: **{round(d['max_dd']*100,3)}%**")
        A(f"- Current exposure (position/equity): **{d['exposure']}%**")
    elif d["last"] and d["last"]["broker_equity"] is not None:
        lb = d["last"]
        A(f"- Latest broker snapshot: cash={lb['broker_cash']} equity={lb['broker_equity']} "
          f"buying_power={lb['broker_buying_power']} position_value={lb['broker_position_val']}")
        A("- No equity time-series yet (needs repeated reconcile runs over days).")
    else:
        A("- Broker snapshot unavailable in window (see §3 status).")
    A("")

    A("## 6. Paper vs backtest caveats (P10-05)")
    A("- Slippage/latency in paper differ from backtest assumptions; fills are "
      "market orders against Alpaca paper quotes.")
    A("- Daily timeframe + single pair ⇒ very low trade frequency; expect long "
      "flat stretches. Sample must accumulate over weeks, not days.")
    A("- Paper equity ≠ live-money behavior (no partial fills / rejects under "
      "real liquidity stress).")
    A("")

    A("## 7. Next priorities (P10-09)")
    A("- Keep reconcile cadence (scheduled task or `--watch`) so §3/§5 gain a time series.")
    A("- Accumulate ≥ a few weeks of signals before any edge/regime judgment.")
    A("- Review HMM activation only when there is a statistically meaningful sample "
      "(see docs/Phase8_HMM_Report.md — currently DEFERRED).")
    A("- Do NOT promote to real money without explicit owner approval + a clean "
      "multi-week reconciliation with zero unresolved drift.")
    A("")
    A("_Generated read-only by app/scripts/weekly_report.py. No orders placed._")
    return "\n".join(L) + "\n"


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    days = 7
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        days = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 7

    d = collect(days)
    md = render(d)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding="utf-8")

    # Record the report in the ledger history (idempotent per second).
    lc = O.ledger_connect()
    ts = d["generated"]
    summary = (f"{len(d['recs'])} snapshots; {len(d['trades_opened_win'])} opened / "
               f"{len(d['trades_closed_win'])} closed in window; "
               f"max_drift={d['max_drift']}; status_mix={d['statuses']}")
    lc.execute("INSERT OR REPLACE INTO reports (ts,window_start,window_end,path,summary) "
               "VALUES (?,?,?,?,?)", (ts, d["start_day"], d["end_day"],
                                      str(REPORT.relative_to(ROOT)).replace("\\", "/"), summary))
    lc.commit()
    lc.close()

    print(f"Wrote {REPORT}  (window {d['start_day']}→{d['end_day']}, {days}d)")
    print(f"  {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
