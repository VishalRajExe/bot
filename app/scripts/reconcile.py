"""Phase 10 — paper-trade reconciliation harness (READ-ONLY, idempotent).

Cross-checks the two authoritative sources and mirrors them into the durable
ledger WITHOUT ever touching the broker's trading state:

  1. Freqtrade paper trade DB (tradesv3.sqlite) — trades, orders (by identity),
     pair-lock (protection) events, wallet snapshot.
  2. Alpaca PAPER account via read-only GETs — /v2/account, /v2/positions,
     /v2/orders?status=open.
  3. Executor liveness — the bot's heartbeat/PID file (app/state/paper_bot.json)
     and the freshness of the latest market candle on disk.

The status is a defined model — HEALTHY / STALE / OFFLINE / BROKER_UNREACHABLE /
REVIEW / CRITICAL — and it can NEVER report HEALTHY when the executor is offline,
the heartbeat is stale, market data is stale, or the portfolio does not reconcile.
The pure decision logic lives in classify_status() so it is unit-testable without
a live bot, DB, or broker. No orders are placed and no secrets are printed.

Usage:
  python app/scripts/reconcile.py              # one snapshot
  python app/scripts/reconcile.py --watch 900  # repeat every 900s (Ctrl-C stops)
Exit codes: 0 = wrote a snapshot (any status), 2 = source unavailable.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone

_HERE = __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0]
sys.path.insert(0, _HERE)
import obs_lib as O  # noqa: E402

# --- thresholds (candidate operational limits; NOT trading risk limits) ---
QTY_TOL = 1e-6              # BTC quantity tolerance for portfolio match
# Alpaca settles crypto fees NET OF POSITION (broker qty < filled qty), so a correctly
# reconciled crypto trade drifts by up to the fee rate (observed 0.15% on a live paper
# fill). 0.35% covers taker fees on both sides with margin; a real mismatch (missing/
# duplicate/external position) is orders of magnitude larger and still CRITICALs.
FEE_DRIFT_TOL = 0.0035
HEARTBEAT_MAX_AGE_S = 600   # bot must beat within this or it is OFFLINE
CANDLE_MAX_AGE_H = 30.0     # daily candle older than this => STALE feed

HEALTHY = "HEALTHY"
STALE = "STALE"
OFFLINE = "OFFLINE"
BROKER_UNREACHABLE = "BROKER_UNREACHABLE"
REVIEW = "REVIEW"
CRITICAL = "CRITICAL"

# Each executor has its own autoincrementing trade id, so mirror them into the shared
# ledger under disjoint id ranges (daily: 1.., fast: 10_000_000+) to avoid collisions.
_EXECUTOR_ID_BASE = {"daily": 0, "fast": 10_000_000}


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _pid_alive(pid) -> bool | None:
    """Best-effort OS liveness. None when it cannot be determined (rely on heartbeat)."""
    if not pid:
        return None
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        pass
    try:  # POSIX
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def reconcile_order_identity(broker_open_ids, ft_open_ids):
    """Match broker open orders to Freqtrade open orders BY IDENTITY, not by count.

    Returns (unmatched_broker, unresolved_ft):
      unmatched_broker: broker order ids with no Freqtrade counterpart (external/manual).
      unresolved_ft:    Freqtrade open order ids the broker does not show as open
                        (possibly filled/cancelled without FT update — never assume fill).
    """
    b = {str(x) for x in broker_open_ids if x}
    f = {str(x) for x in ft_open_ids if x}
    return len(b - f), len(f - b)


def classify_status(s: dict) -> tuple[str, str]:
    """Pure status decision. `s` is a signal dict; returns (status, detail).

    Precedence: CRITICAL > OFFLINE > BROKER_UNREACHABLE > STALE > REVIEW > HEALTHY.
    A non-HEALTHY result is guaranteed whenever the executor is offline/stale or the
    portfolio does not reconcile — HEALTHY is unreachable on drift, stale heartbeat,
    stale data, or a corrupt DB.
    """
    # --- CRITICAL: portfolio truth is broken or trading on the wrong endpoint ---
    if not s.get("ft_db_ok", True):
        return CRITICAL, "Freqtrade trade DB unreadable/corrupt — cannot reconcile."
    if s.get("live_endpoint_suspected"):
        return CRITICAL, "Resolved trader endpoint is NOT Alpaca paper — stop."
    drift = _f(s.get("qty_drift", 0.0))
    # Fee-net settlement makes broker_qty slightly < ft filled qty. Tolerance scales
    # with the open amount; a genuine mismatch (missing/duplicate/external position)
    # is far larger and still trips CRITICAL.
    drift_tol = max(QTY_TOL, abs(_f(s.get("ft_open_amount", 0.0))) * FEE_DRIFT_TOL)
    if abs(drift) > drift_tol:
        return CRITICAL, (f"portfolio mismatch: broker qty {s.get('broker_position_qty')} "
                          f"vs Freqtrade open amount {s.get('ft_open_amount')} "
                          f"(drift {drift}, tol {round(drift_tol, 8)}).")

    # --- OFFLINE: the executor is not provably running ---
    hb = s.get("heartbeat_age_s")
    alive = s.get("process_alive")
    if alive is False or hb is None or (hb is not None and _f(hb) > HEARTBEAT_MAX_AGE_S):
        why = "no heartbeat file" if hb is None else f"heartbeat age {_f(hb):.0f}s > {HEARTBEAT_MAX_AGE_S}s"
        if alive is False:
            why = "recorded PID not alive"
        return OFFLINE, f"paper executor is OFFLINE ({why}); never reported healthy."

    # --- BROKER_UNREACHABLE: alive but cannot confirm against the broker ---
    if not s.get("broker_ok", False):
        return BROKER_UNREACHABLE, "executor alive but Alpaca PAPER account not reachable."

    # --- STALE: alive & broker ok but market data feed has stalled ---
    age = s.get("candle_age_h")
    if age is None or _f(age) > CANDLE_MAX_AGE_H:
        why = "no candle data" if age is None else f"last candle {_f(age):.1f}h old > {CANDLE_MAX_AGE_H:.0f}h"
        return STALE, f"market data is STALE ({why}); not healthy."

    # --- REVIEW: reconciled but non-critical items need a human look ---
    review = []
    if int(s.get("active_locks", 0) or 0) > 0:
        review.append(f"{s['active_locks']} active protection lock(s)")
    if int(s.get("unmatched_broker_orders", 0) or 0) > 0:
        review.append(f"{s['unmatched_broker_orders']} broker order(s) not owned by Freqtrade")
    if int(s.get("ft_unresolved_orders", 0) or 0) > 0:
        review.append(f"{s['ft_unresolved_orders']} Freqtrade open order(s) not shown open by broker")
    if review:
        return REVIEW, "; ".join(review) + " — needs attention."

    return HEALTHY, "Executor alive, data fresh, broker reachable, portfolio reconciled."


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def gather_signals(now: datetime | None = None) -> dict:
    """Read every liveness / portfolio signal from real sources. Never places orders."""
    now = now or datetime.now(timezone.utc)
    s: dict = {"ft_db_ok": True, "live_endpoint_suspected": False,
               "heartbeat_age_s": None, "process_alive": None, "candle_age_h": None,
               "broker_ok": False, "broker_cash": None, "broker_equity": None,
               "broker_buying_power": None, "broker_position_qty": 0.0,
               "broker_position_val": 0.0, "broker_open_orders": 0,
               "ft_open_trades": 0, "ft_open_amount": 0.0, "ft_open_orders": 0,
               "total_trades": 0, "closed_trades": 0, "realized_abs": 0.0,
               "active_locks": 0, "unmatched_broker_orders": 0, "ft_unresolved_orders": 0,
               "qty_drift": 0.0, "strategy": None}

    # strategy label + endpoint check from config (fallback when no trades yet)
    try:
        import json as _json
        cfg = _json.loads(O.PAPER_CFG.read_text(encoding="utf-8"))
        s["strategy"] = cfg.get("strategy")
        trader_url = (cfg.get("exchange", {}).get("ccxt_config", {})
                      .get("urls", {}).get("api", {}).get("trader", ""))
        s["live_endpoint_suspected"] = bool(trader_url) and "paper-api.alpaca.markets" not in trader_url
    except Exception:  # noqa: BLE001
        pass

    # --- liveness: heartbeat + PID across BOTH executors ---
    # OFFLINE if ANY executor that has a heartbeat file is dead/stale. An executor with
    # no file yet simply isn't running (not penalised); once started it must stay fresh.
    ages: list[float] = []
    any_present = False
    all_alive = True
    for ex in O.executors():
        try:
            hb = O.read_heartbeat(ex["state"])
        except TypeError:  # legacy single-DB resolver (no-arg monkeypatch in tests)
            hb = O.read_heartbeat()
        if not hb:
            continue
        any_present = True
        alive = _pid_alive(hb.get("pid"))
        if alive is False:
            all_alive = False
        try:
            last = datetime.fromisoformat(hb.get("last_heartbeat")).replace(tzinfo=timezone.utc)
            ages.append((now - last).total_seconds())
        except Exception:  # noqa: BLE001
            all_alive = False
    if any_present:
        s["heartbeat_age_s"] = max(ages) if ages else None
        s["process_alive"] = bool(all_alive and (s["heartbeat_age_s"] is not None))
    else:
        s["heartbeat_age_s"] = None
        s["process_alive"] = None

    # --- liveness: market data freshness ---
    s["candle_age_h"] = O.latest_candle_age_hours()

    # --- Freqtrade execution record (aggregated across both disjoint DBs) ---
    dbs = {}
    for ex in O.executors():
        try:
            dbs[ex["name"]] = O.ft_db_path(ex["cfg"])
        except TypeError:  # legacy single-DB resolver (no-arg monkeypatch in tests)
            dbs[ex["name"]] = O.ft_db_path()
    s["trades_rows"] = []
    s["ft_open_order_ids"] = []
    any_db_exists = False
    seen_paths: set = set()
    for name, db in dbs.items():
        if db is None or db in seen_paths:
            continue  # skip a missing DB, and never double-count a shared path
        seen_paths.add(db)
        any_db_exists = True
        try:
            c = O.ft_connect_ro(db)
            tabs = _tables(c)
            if "trades" in tabs:
                rows = c.execute(
                    "SELECT id,pair,is_open,open_date,close_date,open_rate,close_rate,"
                    "stake_amount,amount,fee_open,fee_close,fee_open_cost,fee_close_cost,"
                    "fee_open_currency,fee_close_currency,close_profit,close_profit_abs,"
                    "exit_reason,enter_tag,leverage,is_short,strategy,timeframe "
                    "FROM trades ORDER BY id").fetchall()
                base = _EXECUTOR_ID_BASE.get(name, 0)  # namespace ids across the two DBs
                for r in rows:
                    d = dict(r)
                    d["id"] = base + int(d["id"])
                    s["trades_rows"].append(d)
                s["ft_open_trades"] += sum(1 for r in rows if r["is_open"])
                s["ft_open_amount"] += sum(_f(r["amount"]) for r in rows if r["is_open"])
                s["closed_trades"] += sum(1 for r in rows if not r["is_open"])
                s["realized_abs"] += sum(_f(r["close_profit_abs"]) for r in rows if not r["is_open"])
            if "orders" in tabs:
                fo = c.execute("SELECT order_id FROM orders WHERE ft_is_open=1").fetchall()
                s["ft_open_order_ids"] += [r["order_id"] for r in fo]
            if "pairlocks" in tabs:
                s["active_locks"] += c.execute(
                    "SELECT COUNT(*) FROM pairlocks WHERE active=1").fetchone()[0]
            c.close()
        except Exception as e:  # noqa: BLE001
            s["ft_db_ok"] = False
            s["ft_db_error"] = f"{name}: {type(e).__name__}: {str(e)[:120]}"
    if not any_db_exists:
        s["ft_db_ok"] = False
    s["total_trades"] = len(s["trades_rows"])
    s["ft_open_orders"] = len(s["ft_open_order_ids"])

    # --- broker (Alpaca PAPER, read-only) ---
    st, acct = O.alpaca_get("/v2/account")
    if st == 200 and isinstance(acct, dict):
        s["broker_ok"] = True
        s["broker_cash"] = _f(acct.get("cash"))
        s["broker_equity"] = _f(acct.get("equity"))
        s["broker_buying_power"] = _f(acct.get("buying_power"))
    st, pos = O.alpaca_get("/v2/positions")
    if st == 200 and isinstance(pos, list):
        for p in pos:
            s["broker_position_qty"] += _f(p.get("qty"))
            s["broker_position_val"] += _f(p.get("market_value"))
    st, orders = O.alpaca_get("/v2/orders?status=open")
    if st == 200 and isinstance(orders, list):
        s["broker_open_orders"] = len(orders)
        s["broker_open_order_ids"] = [o.get("id") for o in orders]

    # --- portfolio + identity reconciliation ---
    s["qty_drift"] = round(s["broker_position_qty"] - s["ft_open_amount"], 8)
    if s["broker_ok"]:
        unmatched, unresolved = reconcile_order_identity(
            s.get("broker_open_order_ids", []), s.get("ft_open_order_ids", []))
        s["unmatched_broker_orders"] = unmatched
        s["ft_unresolved_orders"] = unresolved
    return s


def snapshot() -> dict:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    day = now.strftime("%Y-%m-%d")
    s = gather_signals(now)
    status, detail = classify_status(s)

    lc = O.ledger_connect()
    # mirror trades (with monetary fee costs) — idempotent by Freqtrade id
    for r in s.get("trades_rows", []):
        lc.execute(
            "INSERT OR REPLACE INTO paper_trades (id,source,pair,is_open,open_date,close_date,"
            "open_rate,close_rate,stake_amount,amount,fee_open,fee_close,fee_open_cost,"
            "fee_close_cost,fee_open_currency,fee_close_currency,profit_ratio,profit_abs,"
            "exit_reason,enter_tag,leverage,is_short,strategy,timeframe,reconciled_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], "alpaca_paper", r["pair"], 1 if r["is_open"] else 0, r["open_date"],
             r["close_date"], _opt(r["open_rate"]), _opt(r["close_rate"]),
             _f(r["stake_amount"]), _f(r["amount"]), _f(r["fee_open"]), _f(r["fee_close"]),
             _opt(r["fee_open_cost"]), _opt(r["fee_close_cost"]),
             r.get("fee_open_currency"), r.get("fee_close_currency"),
             _opt(r["close_profit"]), _opt(r["close_profit_abs"]),
             r["exit_reason"], r["enter_tag"], _f(r["leverage"], 1.0),
             1 if r["is_short"] else 0, r["strategy"], r["timeframe"], ts),
        )

    lc.execute(
        "INSERT OR REPLACE INTO reconcile_log (ts,status,detail,broker_cash,broker_equity,"
        "broker_buying_power,broker_position_qty,broker_position_val,ft_open_trades,"
        "ft_open_orders,broker_open_orders,unmatched_broker_orders,ft_unresolved_orders,"
        "active_locks,qty_drift,process_alive,heartbeat_age_s,candle_age_h,strategy,version_note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, status, detail, s.get("broker_cash"), s.get("broker_equity"),
         s.get("broker_buying_power"), s["broker_position_qty"], s["broker_position_val"],
         s["ft_open_trades"], s["ft_open_orders"], s["broker_open_orders"],
         s["unmatched_broker_orders"], s["ft_unresolved_orders"], s["active_locks"],
         s["qty_drift"], 1 if s.get("process_alive") else 0, s.get("heartbeat_age_s"),
         s.get("candle_age_h"), s.get("strategy"), "unboundbot-alpaca-paper"),
    )

    dd = 0.0
    if s["broker_ok"] and s.get("broker_equity") is not None:
        prev_peak = lc.execute("SELECT MAX(equity) FROM account_equity").fetchone()[0]
        peak = max(_f(prev_peak), s["broker_equity"])
        dd = round((s["broker_equity"] - peak) / peak, 6) if peak else 0.0
        lc.execute(
            "INSERT OR REPLACE INTO account_equity (date,cash,equity,buying_power,"
            "position_value,drawdown,source) VALUES (?,?,?,?,?,?,?)",
            (day, s.get("broker_cash"), s["broker_equity"], s.get("broker_buying_power"),
             s["broker_position_val"], dd, "alpaca_paper"),
        )
    lc.commit()
    lc.close()
    s.update({"ts": ts, "status": status, "detail": detail,
              "drawdown_pct": round(dd * 100, 3), "db": str(O.ft_db_path())})
    return s


def _opt(x):
    """Return float or None (preserve 'unknown is not zero' for fee/profit fields)."""
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def main() -> int:
    for _st in (sys.stdout, sys.stderr):
        try:
            _st.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    watch = 0
    if "--watch" in sys.argv:
        i = sys.argv.index("--watch")
        watch = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 900

    def run_once() -> int:
        s = snapshot()
        print(f"[{s['ts']}] status={s['status']} — {s['detail']}")
        print(f"    liveness: process_alive={s.get('process_alive')} "
              f"heartbeat_age_s={s.get('heartbeat_age_s')} candle_age_h={s.get('candle_age_h')} "
              f"broker_ok={s['broker_ok']} ft_db_ok={s['ft_db_ok']}")
        print(f"    portfolio: drift={s['qty_drift']} broker_qty={s['broker_position_qty']} "
              f"ft_open_amt={round(s['ft_open_amount'],6)} unmatched_broker_orders="
              f"{s['unmatched_broker_orders']} ft_unresolved={s['ft_unresolved_orders']} "
              f"locks={s['active_locks']}")
        if s.get("broker_cash") is not None:
            print(f"    account: cash={s['broker_cash']} equity={s['broker_equity']} "
                  f"dd={s['drawdown_pct']}%  (trades total={s['total_trades']})")
        return 0

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
