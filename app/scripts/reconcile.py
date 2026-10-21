"""Phase 10 — paper-trade reconciliation harness (READ-ONLY, idempotent).

Cross-checks the two authoritative sources and mirrors them into the durable
ledger WITHOUT ever touching the broker's trading state:

  1. Freqtrade paper trade DB (D:/BOT/tradesv3.sqlite) — trades, open orders,
     pair-lock (protection) events, and Freqtrade's own wallet snapshot.
  2. Alpaca PAPER account via read-only GETs — /v2/account, /v2/positions,
     /v2/orders?status=open.

Writes: paper_trades (mirror of Freqtrade trades), reconcile_log (one snapshot
per run with a drift/discrepancy status), account_equity (daily equity + running
drawdown from broker equity). No orders are placed and no secrets are printed.

Usage:
  python app/scripts/reconcile.py            # one snapshot
  python app/scripts/reconcile.py --watch 900  # repeat every 900s (Ctrl-C to stop)
Exit codes: 0 = wrote a snapshot (any status), 2 = source unavailable.
"""
from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
import obs_lib as O  # noqa: E402

QTY_TOL = 1e-6


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def snapshot() -> dict:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    day = now.strftime("%Y-%m-%d")

    # ---- Freqtrade side (authoritative execution record) ----
    ft = {"open_trades": 0, "open_amount": 0.0, "open_orders": 0,
          "total_trades": 0, "closed_trades": 0, "realized_abs": 0.0,
          "active_locks": 0, "strategy": None}
    try:
        import json as _json
        ft["strategy"] = _json.loads(O.PAPER_CFG.read_text(encoding="utf-8")).get("strategy")
    except Exception:  # noqa: BLE001
        pass
    trades_rows: list[dict] = []
    db = O.ft_db_path()
    if db is not None:
        c = O.ft_connect_ro(db)
        tabs = _tables(c)
        if "trades" in tabs:
            rows = c.execute(
                "SELECT id,pair,is_open,open_date,close_date,open_rate,close_rate,"
                "stake_amount,amount,fee_open,fee_close,close_profit,close_profit_abs,"
                "exit_reason,enter_tag,leverage,is_short,strategy,timeframe "
                "FROM trades ORDER BY id"
            ).fetchall()
            trades_rows = [dict(r) for r in rows]
            ft["total_trades"] = len(trades_rows)
            ft["open_trades"] = sum(1 for r in trades_rows if r["is_open"])
            ft["open_amount"] = sum(_f(r["amount"]) for r in trades_rows if r["is_open"])
            ft["closed_trades"] = sum(1 for r in trades_rows if not r["is_open"])
            ft["realized_abs"] = sum(_f(r["close_profit_abs"]) for r in trades_rows if not r["is_open"])
            if trades_rows and trades_rows[0]["strategy"]:
                ft["strategy"] = trades_rows[0]["strategy"]
        if "orders" in tabs:
            ft["open_orders"] = c.execute(
                "SELECT COUNT(*) FROM orders WHERE ft_is_open=1").fetchone()[0]
        if "pairlocks" in tabs:
            ft["active_locks"] = c.execute(
                "SELECT COUNT(*) FROM pairlocks WHERE active=1").fetchone()[0]
        c.close()

    # ---- Broker side (Alpaca PAPER, read-only) ----
    broker = {"reachable": False, "cash": None, "equity": None, "buying_power": None,
              "position_qty": 0.0, "position_val": 0.0, "open_orders": 0}
    st, acct = O.alpaca_get("/v2/account")
    if st == 200 and isinstance(acct, dict):
        broker.update(reachable=True, cash=_f(acct.get("cash")),
                      equity=_f(acct.get("equity")), buying_power=_f(acct.get("buying_power")))
    st, pos = O.alpaca_get("/v2/positions")
    if st == 200 and isinstance(pos, list):
        for p in pos:
            broker["position_qty"] += _f(p.get("qty"))
            broker["position_val"] += _f(p.get("market_value"))
    # 404 = no positions (fine). st in (-1,0,...) may mean unreachable below.
    st, orders = O.alpaca_get("/v2/orders?status=open")
    if st == 200 and isinstance(orders, list):
        broker["open_orders"] = len(orders)

    # ---- Reconciliation ----
    qty_drift = round(broker["position_qty"] - ft["open_amount"], 8)
    unmatched = 0
    if broker["reachable"] and broker["open_orders"] > ft["open_orders"]:
        unmatched = broker["open_orders"] - ft["open_orders"]

    if not broker["reachable"]:
        status = "BROKER_UNREACHABLE"
        detail = "Alpaca PAPER /v2/account not reachable; Freqtrade-side snapshot only."
    elif abs(qty_drift) > QTY_TOL or unmatched or ft["active_locks"]:
        bits = []
        if abs(qty_drift) > QTY_TOL:
            bits.append(f"position qty drift {qty_drift}")
        if unmatched:
            bits.append(f"{unmatched} broker open order(s) beyond Freqtrade")
        if ft["active_locks"]:
            bits.append(f"{ft['active_locks']} active protection lock(s)")
        status = "REVIEW"
        detail = "; ".join(bits)
    else:
        status = "OK"
        detail = "Freqtrade records reconcile with broker (no external/manual activity)."

    # ---- Persist to ledger ----
    lc = O.ledger_connect()
    for r in trades_rows:
        lc.execute(
            "INSERT OR REPLACE INTO paper_trades (id,source,pair,is_open,open_date,close_date,"
            "open_rate,close_rate,stake_amount,amount,fee_open,fee_close,profit_ratio,profit_abs,"
            "exit_reason,enter_tag,leverage,is_short,strategy,timeframe,reconciled_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "alpaca_paper", r["pair"], 1 if r["is_open"] else 0, r["open_date"],
             r["close_date"], _f(r["open_rate"], None) if r["open_rate"] is not None else None,
             _f(r["close_rate"], None) if r["close_rate"] is not None else None,
             _f(r["stake_amount"]), _f(r["amount"]), _f(r["fee_open"]), _f(r["fee_close"]),
             _f(r["close_profit"], None) if r["close_profit"] is not None else None,
             _f(r["close_profit_abs"], None) if r["close_profit_abs"] is not None else None,
             r["exit_reason"], r["enter_tag"], _f(r["leverage"], 1.0),
             1 if r["is_short"] else 0, r["strategy"], r["timeframe"], ts),
        )

    lc.execute(
        "INSERT OR REPLACE INTO reconcile_log (ts,status,detail,broker_cash,broker_equity,"
        "broker_buying_power,broker_position_qty,broker_position_val,ft_open_trades,"
        "ft_open_orders,broker_open_orders,unmatched_broker_orders,qty_drift,strategy,version_note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, status, detail, broker["cash"], broker["equity"], broker["buying_power"],
         broker["position_qty"], broker["position_val"], ft["open_trades"], ft["open_orders"],
         broker["open_orders"], unmatched, qty_drift, ft["strategy"], "unboundbot-alpaca-paper"),
    )

    # Daily equity snapshot with running drawdown (only when broker reachable).
    dd = 0.0
    if broker["reachable"] and broker["equity"] is not None:
        prev_peak = lc.execute(
            "SELECT MAX(equity) FROM account_equity").fetchone()[0]
        peak = max(_f(prev_peak), broker["equity"])
        dd = round((broker["equity"] - peak) / peak, 6) if peak else 0.0
        lc.execute(
            "INSERT OR REPLACE INTO account_equity (date,cash,equity,buying_power,"
            "position_value,drawdown,source) VALUES (?,?,?,?,?,?,?)",
            (day, broker["cash"], broker["equity"], broker["buying_power"],
             broker["position_val"], dd, "alpaca_paper"),
        )
    lc.commit()
    lc.close()

    return {"ts": ts, "status": status, "detail": detail, "ft": ft,
            "broker": broker, "qty_drift": qty_drift, "unmatched": unmatched,
            "drawdown_pct": round(dd * 100, 3), "db": str(db)}


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    watch = 0
    if "--watch" in sys.argv:
        i = sys.argv.index("--watch")
        watch = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 900

    def run_once() -> int:
        s = snapshot()
        print(f"[{s['ts']}] status={s['status']} — {s['detail']}")
        print(f"    ft: trades={s['ft']['total_trades']} open={s['ft']['open_trades']} "
              f"closed={s['ft']['closed_trades']} realized={round(s['ft']['realized_abs'],2)} "
              f"open_orders={s['ft']['open_orders']} locks={s['ft']['active_locks']}")
        b = s["broker"]
        if b["reachable"]:
            print(f"    broker: cash={b['cash']} equity={b['equity']} "
                  f"pos_qty={b['position_qty']} open_orders={b['open_orders']} "
                  f"drift={s['qty_drift']} dd={s['drawdown_pct']}%")
        else:
            print("    broker: UNREACHABLE (recorded ft-side only)")
        print(f"    ft_db={s['db']}")
        return 0 if b["reachable"] or s["ft"]["total_trades"] >= 0 else 2

    code = run_once()
    if watch <= 0:
        return code

    stop = {"f": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(f=True))
    print(f"watching every {watch}s (Ctrl-C to stop)...")
    while not stop["f"]:
        time.sleep(watch)
        if stop["f"]:
            break
        run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
